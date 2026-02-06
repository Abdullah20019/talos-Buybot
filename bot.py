import os
import asyncio
import json
import time
import aiohttp

from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler
from web3 import Web3, HTTPProvider

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
ARB_RPC_URL = os.getenv("ARB_RPC_URL")

TOKEN_ADDRESS = os.getenv("TOKEN_ADDRESS")
WETH_ADDRESS = os.getenv("WETH_ADDRESS")

if not (BOT_TOKEN and CHAT_ID and ARB_RPC_URL and TOKEN_ADDRESS and WETH_ADDRESS):
    raise RuntimeError("Missing one or more required env vars")

# Clean RPC URL
ARB_RPC_URL = ARB_RPC_URL.strip()

print(f"Using RPC endpoint: {ARB_RPC_URL}")

TOKEN_ADDRESS = Web3.to_checksum_address(TOKEN_ADDRESS)
WETH_ADDRESS = Web3.to_checksum_address(WETH_ADDRESS)

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
except Exception:
    TALOS_DECIMALS = 18  # safe fallback

TALOS_FACTOR = 10 ** TALOS_DECIMALS

DEXSCREENER_URL = (
    "https://api.dexscreener.com/latest/dex/tokens/" + os.getenv("TOKEN_ADDRESS")
)

# Common Arbitrum routers / aggregators
ROUTERS = {
    Web3.to_checksum_address("0xc873fEcbd354f5A56E00E710B90EF4201db2448d"),  # Camelot
    Web3.to_checksum_address("0xE592427A0AEce92De3Edee1F18E0157C05861564"),  # Uniswap v3
    Web3.to_checksum_address("0x19cEeAd7105607Cd444F5ad10dd51356436095a1"),  # Odos
    Web3.to_checksum_address("0x1111111254EEB25477B68fb85Ed929f73A960582"),  # 1inch
    Web3.to_checksum_address("0x7Ed9d62C8C4D45E9249f327F57e06adF4Adad5FA")   # OpenOcean
}

def is_router(addr: str) -> bool:
    return Web3.to_checksum_address(addr) in ROUTERS

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

        from_is_router = is_router(from_addr)
        to_is_router = is_router(to_addr)

        if from_is_router and not to_is_router:
            swap_type = "🟢 BUY"
            trader = to_addr
        elif to_is_router and not from_is_router:
            swap_type = "🔴 SELL"
            trader = from_addr
        else:
            return

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

        price_usd, fdv, dex_name = await get_live_stats()
        if price_usd:
            usd_value = talos_amount * price_usd
            value_line = f"💵 Value: ${usd_value:,.2f}"
            price_line = f"💲 Price: ${price_usd:.6f}"
        else:
            usd_value = 0.0
            value_line = "💵 Value: N/A"
            price_line = "💲 Price: N/A"

        if fdv:
            fdv_line = f"🏦 FDV: ${fdv:,.1f}"
        else:
            fdv_line = "🏦 FDV: N/A"

        robots_row = robots_for_usd(usd_value)

        msg = (
            f"$TALOS {swap_type}! 🛒\n"
            f"{dex_name or 'DEX'} Swap\n"
            f"{robots_row}\n\n"
            f"💰 TALOS: {talos_amount:,.2f}\n"
            f"💎 WETH: {weth_amount:.4f}\n"
            f"{value_line}\n"
            f"{price_line}\n"
            f"{fdv_line}\n"
            f"👤 Trader: {trader[:6]}...{trader[-4:]}\n"
            f"🔗 Txn: https://arbiscan.io/tx/{tx_hash}"
        )

        print(msg.replace("\n", " | "))
        await application.bot.send_message(chat_id=CHAT_ID, text=msg)

    except Exception as e:
        print(f"Error handling transfer event: {e}")

async def watch_talos_transfers(application: Application):
    print("✅ Watching TALOS Transfer events (routers/aggregators on Arbitrum)…")

    try:
        last_block = w3.eth.block_number
    except Exception as e:
        print(f"Error getting initial block number: {e}")
        return

    while True:
        try:
            current_block = w3.eth.block_number
            if current_block > last_block:
                from_block = last_block + 1
                to_block = current_block

                events = talos_contract.events.Transfer().get_logs(
                    fromBlock=from_block,
                    toBlock=to_block
                )
                for ev in events:
                    await handle_transfer_event(ev, application)

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
