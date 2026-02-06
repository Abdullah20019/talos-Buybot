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

# Load pool ABI
with open("abi/pool.json", "r") as f:
    pool_abi = json.load(f)

bot = Bot(token=BOT_TOKEN)

# Filled at runtime from DexScreener
POOLS: dict[str, str] = {}

DEXSCREENER_URL = (
    "https://api.dexscreener.com/latest/dex/tokens/"
    + os.getenv("TOKEN_ADDRESS")
)


async def fetch_dexscreener_pairs():
    """
    Load all TALOS pairs from DexScreener and fill POOLS.
    Only Arbitrum pairs where one side is TALOS.
    """
    global POOLS
    POOLS = {}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(DEXSCREENER_URL, timeout=10) as resp:
                data = await resp.json()

        pairs = data.get("pairs", [])
        idx = 0
        for p in pairs:
            if p.get("chainId") != "arbitrum":
                continue

            pair_address = p.get("pairAddress")
            if not pair_address:
                continue

            base = p.get("baseToken", {})
            quote = p.get("quoteToken", {})
            base_addr = (base.get("address") or "").lower()
            quote_addr = (quote.get("address") or "").lower()

            if TOKEN_ADDRESS.lower() not in (base_addr, quote_addr):
                continue

            dex_id = (p.get("dexId") or "DEX").upper()
            name = f"{dex_id} ({idx})"
            POOLS[name] = Web3.to_checksum_address(pair_address)
            idx += 1

        print("Loaded pools from DexScreener:")
        for k, v in POOLS.items():
            print(f" - {k}: {v}")

    except Exception as e:
        print(f"Error loading DexScreener pools: {e}")


async def get_live_stats():
    """
    Returns (talos_price_usd, market_cap, dex_name) from DexScreener.
    Uses the first (top-liquidity) pair.
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


async def handle_swap_event(event, pool_name):
    try:
        pool_addr = event["address"]
        contract = w3.eth.contract(address=pool_addr, abi=pool_abi)

        # Identify which token is TALOS and which is WETH
        token0 = contract.functions.token0().call()
        token1 = contract.functions.token1().call()

        amount0 = event["args"]["amount0"]
        amount1 = event["args"]["amount1"]
        recipient = event["args"]["recipient"]

        talos_delta = 0
        weth_delta = 0

        if token0.lower() == TOKEN_ADDRESS.lower():
            talos_delta = amount0
            if token1.lower() == WETH_ADDRESS.lower():
                weth_delta = amount1
        elif token1.lower() == TOKEN_ADDRESS.lower():
            talos_delta = amount1
            if token0.lower() == WETH_ADDRESS.lower():
                weth_delta = amount0
        else:
            # Pool does not contain TALOS
            return

        talos_amount = abs(talos_delta) / 1e18
        weth_amount = abs(weth_delta) / 1e18

        if talos_amount == 0:
            return

        if talos_delta > 0:
            swap_type = "🔴 SELL"
        elif talos_delta < 0:
            swap_type = "🟢 BUY"
        else:
            swap_type = "⚪️ SWAP"

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

        tx_hash = event["transactionHash"].hex()
        title_name = dex_name or pool_name

        msg = (
            f"$TALOS {swap_type}! 🛒\n"
            f"{title_name} Swap\n"
            f"{robots_row}\n\n"
            f"💰 TALOS: {talos_amount:,.2f}\n"
            f"💎 WETH: {weth_amount:.4f}\n"
            f"{value_line}\n"
            f"{price_line}\n"
            f"{mcap_line}\n"
            f"👤 Trader: {recipient[:6]}...{recipient[-4:]}\n"
            f"🔗 Txn: https://arbiscan.io/tx/{tx_hash}"
        )

        print(msg.replace("\n", " | "))

        await bot.send_message(chat_id=CHAT_ID, text=msg)

    except Exception as e:
        print(f"Error handling swap on {pool_name}: {e}")


async def watch_pool(pool_address, pool_name):
    pool_address = Web3.to_checksum_address(pool_address)
    contract = w3.eth.contract(address=pool_address, abi=pool_abi)

    print(f"✅ Watching {pool_name} at {pool_address}")

    event_filter = None
    retry_count = 0

    while True:
        try:
            if event_filter is None:
                # FIXED: correct filter syntax for Web3
                event_filter = contract.events.Swap().create_filter(
                    fromBlock="latest"
                )

            if retry_count > 0:
                print(f"✅ Reconnected to {pool_name}")
                retry_count = 0

            for event in event_filter.get_new_entries():
                await handle_swap_event(event, pool_name)

            await asyncio.sleep(2)

        except Exception as e:
            retry_count += 1
            print(f"❌ Error watching {pool_name}: {str(e)[:120]}")
            print(f"⏳ Retry #{retry_count} in 10 seconds...")
            event_filter = None
            await asyncio.sleep(10)


async def main():
    print("🚀 Starting TALOS Buy Bot...\n")

    await fetch_dexscreener_pairs()
    if not POOLS:
        print("No TALOS pools loaded from DexScreener. Exiting.")
        return

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("ping", ping))

    await application.initialize()
    await application.start()

    tasks = []
    for name, addr in POOLS.items():
        tasks.append(asyncio.create_task(watch_pool(addr, name)))

    try:
        await asyncio.gather(*tasks)
    finally:
        await application.stop()
        await application.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
