import os
import asyncio
import json
import time
import aiohttp

from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler
from telegram.constants import ParseMode
from web3 import Web3, HTTPProvider

# Load env vars if a .env file exists (safe to call even if not present)
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
ARB_RPC_URL = os.getenv("ARB_RPC_URL")

TOKEN_ADDRESS = os.getenv("TOKEN_ADDRESS")  # 0x30a538eFFD91ACeFb1b12CE9Bc0074eD18c9dFc9
WETH_ADDRESS = os.getenv("WETH_ADDRESS")

UNISWAP_LP = os.getenv("UNISWAP_LP_ADDRESS")   # TALOS-WETH on Uniswap
CAMELOT_LP = os.getenv("CAMELOT_LP_ADDRESS")   # TALOS-WETH on Camelot

if not (BOT_TOKEN and CHAT_ID and ARB_RPC_URL and TOKEN_ADDRESS and WETH_ADDRESS and UNISWAP_LP and CAMELOT_LP):
    raise RuntimeError(
        "Missing required env vars. Need BOT_TOKEN, CHAT_ID, ARB_RPC_URL, "
        "TOKEN_ADDRESS, WETH_ADDRESS, UNISWAP_LP_ADDRESS, CAMELOT_LP_ADDRESS"
    )

ARB_RPC_URL = ARB_RPC_URL.strip()
print(f"Using RPC endpoint: {ARB_RPC_URL}")

TOKEN_ADDRESS = Web3.to_checksum_address(TOKEN_ADDRESS)
WETH_ADDRESS = Web3.to_checksum_address(WETH_ADDRESS)
UNISWAP_LP = Web3.to_checksum_address(UNISWAP_LP)
CAMELOT_LP = Web3.to_checksum_address(CAMELOT_LP)

LP_ADDRESSES = {UNISWAP_LP, CAMELOT_LP}

DEX_NAME_BY_LP = {
    UNISWAP_LP: "Uniswap",
    CAMELOT_LP: "Camelot",
}

print(f"TOKEN_ADDRESS  = {TOKEN_ADDRESS}")
print(f"WETH_ADDRESS   = {WETH_ADDRESS}")
print("LP_ADDRESSES:")
for lp in LP_ADDRESSES:
    print(" -", lp)

w3 = Web3(HTTPProvider(ARB_RPC_URL))

# Connectivity test
try:
    chain_id = w3.eth.chain_id
    print(f"Connected to chain id: {chain_id}")
except Exception as e:
    raise RuntimeError(f"Failed to connect to RPC: {e}")

# --- Minimal ERC20 ABI (Transfer + decimals) ---
ERC20_ABI = json.loads("""
[
  {
    "anonymous": false,
    "inputs": [
      {"indexed": true, "name": "from", "type": "address"},
      {"indexed": true, "name": "to", "type": "address"},
      {"indexed": false, "name": "value", "type": "uint256"}
    ],
    "name": "Transfer",
    "type": "event"
  },
  {
    "constant": true,
    "inputs": [],
    "name": "decimals",
    "outputs": [{"name": "", "type": "uint8"}],
    "stateMutability": "view",
    "type": "function"
  }
]
""")

talos_contract = w3.eth.contract(address=TOKEN_ADDRESS, abi=ERC20_ABI)
weth_contract = w3.eth.contract(address=WETH_ADDRESS, abi=ERC20_ABI)

# Read decimals once
try:
    TALOS_DECIMALS = talos_contract.functions.decimals().call()
    print(f"TALOS_DECIMALS = {TALOS_DECIMALS}")
except Exception as e:
    print(f"Error reading decimals, defaulting to 18: {e}")
    TALOS_DECIMALS = 18

TALOS_FACTOR = 10 ** TALOS_DECIMALS

DEXSCREENER_URL = (
    "https://api.dexscreener.com/latest/dex/tokens/" + os.getenv("TOKEN_ADDRESS")
)

# DexScreener cache (15s)
_price_cache_ts = 0.0
_price_cache = None  # (price_usd, fdv, dex_name)

async def get_live_stats():
    global _price_cache_ts, _price_cache

    now = time.time()
    if _price_cache and (now - _price_cache_ts) < 15:
        return _price_cache

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(DEXSCREENER_URL, timeout=10) as resp:
                data = await resp.json()

        pairs = data.get("pairs", [])
        if not pairs:
            print("DexScreener: no pairs found for token")
            return None, None, None

        p = pairs[0]
        price_usd = float(p.get("priceUsd", 0) or 0.0)
        fdv = float(p.get("fdv", 0) or 0.0)
        dex_name = (p.get("dexId") or "DEX").upper()

        if price_usd <= 0:
            result = (None, fdv, dex_name)
        else:
            result = (price_usd, fdv, dex_name)

        _price_cache = result
        _price_cache_ts = now
        return result

    except Exception as e:
        print(f"DexScreener error: {e}")
        return None, None, None

def robots_for_usd(usd: float) -> str:
    if usd < 200:
        n = 5
    elif usd < 300:
        n = 10
    elif usd < 500:
        n = 13
    elif usd < 1000:
        n = 20
    elif usd < 2000:
        n = 24
    else:
        n = 30
    return "🤖" * min(n, 30)

async def ping(update, context):
    await update.message.reply_text("Bot is alive ✅")

# ---------- Media config ----------
IMAGE_PATH = "newimage.jpeg"

BUY_100_VIDEO_PATH = "100$Buy.mp4"
SELL_100_VIDEO_PATH = "100$sell.mp4"
BUYORSELL_500_VIDEO_PATH = "500$BuyorSell.mp4"

MIN_ALERT_USD = 50     # minimum trade size to alert
MINI_WHALE_USD = 100   # ≥100 USD trades -> 100$ videos
MEGA_WHALE_USD = 500   # ≥500 USD trades -> 500$ video
# -------------------------------

async def handle_transfer_event(ev, application: Application):
    try:
        args = ev["args"]
        from_addr = args["from"]
        to_addr = args["to"]
        raw_value = args["value"]

        talos_amount = raw_value / TALOS_FACTOR
        if talos_amount == 0:
            return

        tx_hash = ev["transactionHash"].hex()

        from_is_lp = from_addr.lower() in {a.lower() for a in LP_ADDRESSES}
        to_is_lp = to_addr.lower() in {a.lower() for a in LP_ADDRESSES}

        # Which LP (and thus which DEX) was used
        lp_used = None
        if from_is_lp:
            lp_used = next(a for a in LP_ADDRESSES if a.lower() == from_addr.lower())
        elif to_is_lp:
            lp_used = next(a for a in LP_ADDRESSES if a.lower() == to_addr.lower())

        dex_name_local = DEX_NAME_BY_LP.get(lp_used, "DEX")

        print(
            f"Transfer event: from={from_addr} (lp={from_is_lp}) "
            f"to={to_addr} (lp={to_is_lp}) amount={talos_amount} dex={dex_name_local}"
        )

        # BUY: LP -> user
        if from_is_lp and not to_is_lp:
            swap_type = "🟢 BUY"
            trader = to_addr
        # SELL: user -> LP
        elif to_is_lp and not from_is_lp:
            swap_type = "🔴 SELL"
            trader = from_addr
        else:
            # wallet↔wallet, LP↔LP, etc. -> ignore
            return

        # Try to get WETH amount from receipt
        try:
            receipt = w3.eth.get_transaction_receipt(tx_hash)
        except Exception as e:
            print(f"Receipt error for {tx_hash}: {e}")
            receipt = None

        weth_amount = 0.0
        if receipt is not None:
            for log in receipt.logs:
                if log["address"].lower() != WETH_ADDRESS.lower():
                    continue
                try:
                    we = weth_contract.events.Transfer().process_log(log)
                    f = we["args"]["from"]
                    t = we["args"]["to"]
                    if f.lower() == trader.lower() or t.lower() == trader.lower():
                        weth_amount = we["args"]["value"] / 1e18
                        break
                except Exception:
                    continue

        # Price + FDV
        price_usd, fdv, _dex_from_api = await get_live_stats()
        if price_usd:
            usd_value = talos_amount * price_usd
            value_line = f"💵 Value: ${usd_value:,.2f}"
            price_line = f"💲 Price: ${price_usd:.6f}"
        else:
            usd_value = 0.0
            value_line = "💵 Value: N/A"
            price_line = "💲 Price: N/A"

        # Minimum alert filter
        if usd_value < MIN_ALERT_USD:
            print(f"Skip trade below min alert size: ${usd_value:.2f}")
            return

        if fdv:
            fdv_line = f"🏦 FDV: ${fdv:,.1f}"
        else:
            fdv_line = "🏦 FDV: N/A"

        robots_row = robots_for_usd(usd_value)

        # Clickable links (Markdown)
        tx_url = f"https://arbiscan.io/tx/{tx_hash}"
        trader_url = f"https://arbiscan.io/address/{trader}"

        trader_short = f"{trader[:6]}...{trader[-4:]}"
        trader_md = f"[{trader_short}]({trader_url})"
        tx_md = f"[Txn]({tx_url})"

        msg = (
            f"$TALOS {swap_type}! 🛒\n"
            f"{dex_name_local} Swap\n"
            f"{robots_row}\n\n"
            f"💰 TALOS: {talos_amount:,.2f}\n"
            f"💎 WETH: {weth_amount:.4f}\n"
            f"{value_line}\n"
            f"{price_line}\n"
            f"{fdv_line}\n"
            f"👤 Trader: {trader_md}\n"
            f"🔗 {tx_md}"
        )

        print("Preparing Telegram media send. USD value:", usd_value)

        # ---------- Media rules ----------
        # 1) Mega whale (>= 500 USD): use 500$BuyorSell video for both buys & sells
        if usd_value >= MEGA_WHALE_USD and os.path.exists(BUYORSELL_500_VIDEO_PATH):
            print("Sending 500$BuyorSell mega-whale video")
            with open(BUYORSELL_500_VIDEO_PATH, "rb") as f:
                await application.bot.send_video(
                    chat_id=CHAT_ID,
                    video=f,
                    caption=msg,
                    parse_mode=ParseMode.MARKDOWN
                )

        # 2) 100–499 USD BUY: use 100$Buy video
        elif usd_value >= MINI_WHALE_USD and swap_type == "🟢 BUY" and os.path.exists(BUY_100_VIDEO_PATH):
            print("Sending 100$Buy mini-whale BUY video")
            with open(BUY_100_VIDEO_PATH, "rb") as f:
                await application.bot.send_video(
                    chat_id=CHAT_ID,
                    video=f,
                    caption=msg,
                    parse_mode=ParseMode.MARKDOWN
                )

        # 3) 100–499 USD SELL: use 100$sell video
        elif usd_value >= MINI_WHALE_USD and swap_type == "🔴 SELL" and os.path.exists(SELL_100_VIDEO_PATH):
            print("Sending 100$sell mini-whale SELL video")
            with open(SELL_100_VIDEO_PATH, "rb") as f:
                await application.bot.send_video(
                    chat_id=CHAT_ID,
                    video=f,
                    caption=msg,
                    parse_mode=ParseMode.MARKDOWN
                )

        # 4) Smaller trades (but ≥ 50 USD): send static image
        elif os.path.exists(IMAGE_PATH):
            print("Sending image alert")
            with open(IMAGE_PATH, "rb") as f:
                await application.bot.send_photo(
                    chat_id=CHAT_ID,
                    photo=f,
                    caption=msg,
                    parse_mode=ParseMode.MARKDOWN
                )

        # 5) Fallback: text only
        else:
            print("Media files not found, sending text only")
            await application.bot.send_message(
                chat_id=CHAT_ID,
                text=msg,
                parse_mode=ParseMode.MARKDOWN
            )

    except Exception as e:
        print(f"Error handling transfer event: {e}")

async def watch_talos_transfers(application: Application):
    print("✅ Watching TALOS LP-based buys/sells on Arbitrum…")

    try:
        last_block = w3.eth.block_number
        print(f"Starting from block: {last_block}")
    except Exception as e:
        print(f"Error getting initial block number: {e}")
        return

    # Small range to avoid QuickNode 413 Request Entity Too Large
    MAX_RANGE = 5

    # topic0 = keccak of Transfer(address,address,uint256)
    TRANSFER_EVENT_TOPIC = Web3.keccak(
        text="Transfer(address,address,uint256)"
    ).hex()
    transfer_topic = TRANSFER_EVENT_TOPIC
    print("Using Transfer topic:", transfer_topic)

    while True:
        try:
            current_block = w3.eth.block_number
            if current_block > last_block:
                from_block = last_block + 1
                to_block = current_block

                while from_block <= to_block:
                    upper = min(from_block + MAX_RANGE - 1, to_block)
                    print(f"Querying logs from {from_block} to {upper}...")

                    try:
                        raw_logs = w3.eth.get_logs({
                            "fromBlock": from_block,
                            "toBlock": upper,
                            "address": TOKEN_ADDRESS,
                            "topics": [transfer_topic]
                        })
                        print(f"Found {len(raw_logs)} raw logs in range {from_block}-{upper}")
                        events = [
                            talos_contract.events.Transfer().process_log(log)
                            for log in raw_logs
                        ]
                    except Exception as e:
                        print(
                            f"get_logs error for range {from_block}-{upper}: {e}"
                        )
                        break

                    for ev in events:
                        await handle_transfer_event(ev, application)

                    from_block = upper + 1

                last_block = current_block

            await asyncio.sleep(3)

        except Exception as e:
            print(f"❌ Error in transfer loop: {str(e)[:160]}")
            await asyncio.sleep(10)

async def main():
    print("🚀 Starting TALOS Transfer Bot...\n")

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("ping", ping))

    await application.initialize()
    await application.start()

    try:
        await watch_talos_transfers(application)
    finally:
        await application.stop()
        await application.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
