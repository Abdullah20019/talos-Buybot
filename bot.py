import os
import asyncio
import json
import aiohttp

from dotenv import load_dotenv
from telegram import Bot
from telegram.ext import Application, CommandHandler
from web3 import Web3

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
ARB_RPC_URL = os.getenv("ARB_RPC_URL")

TOKEN_ADDRESS = Web3.to_checksum_address(os.getenv("TOKEN_ADDRESS"))
WETH_ADDRESS = Web3.to_checksum_address(os.getenv("WETH_ADDRESS"))

w3 = Web3(Web3.HTTPProvider(ARB_RPC_URL))

# --- ERC20 ABI with Transfer event only ---
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
  }
]
""")

talos_contract = w3.eth.contract(address=TOKEN_ADDRESS, abi=ERC20_ABI)

bot = Bot(token=BOT_TOKEN)

DEXSCREENER_URL = (
    "https://api.dexscreener.com/latest/dex/tokens/"
    + os.getenv("TOKEN_ADDRESS")
)

# Common Arbitrum router / aggregator addresses (can extend over time)
ROUTERS = {
    # Camelot v3 router
    Web3.to_checksum_address("0xc873fEcbd354f5A56E00E710B90EF4201db2448d"),
    # Uniswap v3 router
    Web3.to_checksum_address("0xE592427A0AEce92De3Edee1F18E0157C05861564"),
    # Odos router
    Web3.to_checksum_address("0x19cEeAd7105607Cd444F5ad10dd51356436095a1"),
    # 1inch router
    Web3.to_checksum_address("0x1111111254EEB25477B68fb85Ed929f73A960582"),
    # OpenOcean
    Web3.to_checksum_address("0x7Ed9d62C8C4D45E9249f327F57e06adF4Adad5FA")
    # add more if needed
}


def is_router(addr: str) -> bool:
    return Web3.to_checksum_address(addr) in ROUTERS


async def get_live_stats():
    """
    Returns (talos_price_usd, market_cap, dex_name) from DexScreener.
    Uses the first (top-liquidity) pair. [web:219]
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(DEXSCREENER_URL, timeout=10) as resp:
                data = await resp.json()

        pairs = data.get("pairs", [])
        if not pairs:
            return None, None, None

        p = pairs[0]
        price_usd = float(p.get("priceUsd", 0) or 0)
        fdv = float(p.get("fdv", 0) or 0)
        dex_name = (p.get("dexId") or "DEX").upper()

        if price_usd <= 0:
            return None, None, dex_name

        return price_usd, fdv, dex_name

    except Exception as e:
        print(f"DexScreener error: {e}")
        return None, None, None


def robots_for_usd(usd):
    """
    Decide how many 🤖 to show based on USD value.
    Max 30 robots.
    """
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


async def handle_transfer_event(event):
    try:
        args = event["args"]
        from_addr = args["from"]
        to_addr = args["to"]
        value = args["value"]

        # Filter out mint/burn dust etc.
        talos_amount = value / 1e18
        if talos_amount == 0:
            return

        tx_hash = event["transactionHash"].hex()
        receipt = w3.eth.get_transaction_receipt(tx_hash)

        # Classify buy / sell using router addresses.
        # router -> user : BUY ; user -> router : SELL
        from_is_router = is_router(from_addr)
        to_is_router = is_router(to_addr)

        if from_is_router and not to_is_router:
            swap_type = "🟢 BUY"
            trader = to_addr
        elif to_is_router and not from_is_router:
            swap_type = "🔴 SELL"
            trader = from_addr
        else:
            # transfer between wallets, airdrop, lp, etc. – ignore
            return

        # Try to find WETH amount in logs (optional; if not found, only USD from TALOS)
        weth_amount = 0.0
        for log in receipt.logs:
            if log["address"].lower() == WETH_ADDRESS.lower():
                try:
                    # Decode as ERC20 Transfer
                    weth_evt = talos_contract.events.Transfer().process_log(log)
                    weth_amount = weth_evt["args"]["value"] / 1e18
                    break
                except Exception:
                    continue

        price_usd, mcap, dex_name = await get_live_stats()

        if price_usd:
            usd_value = talos_amount * price_usd
            value_line = f"💵 Value: ${usd_value:,.2f}"
            price_line = f"💲 Price: ${price_usd:.6f}"
        else:
            usd_value = 0
            value_line = "💵 Value: N/A"
            price_line = "💲 Price: N/A"

        if mcap:
            mcap_line = f"📊 Market Cap: ${mcap:,.1f}"
        else:
            mcap_line = "📊 Market Cap: N/A"

        robots_row = robots_for_usd(usd_value)

        msg = (
            f"$TALOS {swap_type}! 🛒\n"
            f"{dex_name or 'DEX'} Swap\n"
            f"{robots_row}\n\n"
            f"💰 TALOS: {talos_amount:,.2f}\n"
            f"💎 WETH: {weth_amount:.4f}\n"
            f"{value_line}\n"
            f"{price_line}\n"
            f"{mcap_line}\n"
            f"👤 Trader: {trader[:6]}...{trader[-4:]}\n"
            f"🔗 Txn: https://arbiscan.io/tx/{tx_hash}"
        )

        print(msg.replace("\n", " | "))

        await bot.send_message(chat_id=CHAT_ID, text=msg)

    except Exception as e:
        print(f"Error handling transfer event: {e}")


async def watch_talos_transfers():
    print("✅ Watching TALOS Transfer events (all DEXes/aggregators)…")

    event_filter = None
    retry_count = 0

    while True:
        try:
            if event_filter is None:
                event_filter = talos_contract.events.Transfer().create_filter(
                    fromBlock="latest"
                )
                if retry_count > 0:
                    print("✅ Reconnected transfer filter")
                    retry_count = 0

            for event in event_filter.get_new_entries():
                await handle_transfer_event(event)

            await asyncio.sleep(2)

        except Exception as e:
            retry_count += 1
            print(f"❌ Error watching transfers: {str(e)[:120]}")
            print(f"⏳ Retry #{retry_count} in 10 seconds...")
            event_filter = None
            await asyncio.sleep(10)


async def main():
    print("🚀 Starting TALOS Transfer Bot...\n")

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("ping", ping))

    await application.initialize()
    await application.start()

    try:
        await watch_talos_transfers()
    finally:
        await application.stop()
        await application.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
