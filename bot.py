import os
import asyncio
import json
import aiohttp

from dotenv import load_dotenv
from telegram import Bot
from telegram.ext import Application, CommandHandler
from web3 import Web3

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
ARB_RPC_URL = os.getenv('ARB_RPC_URL')

TOKEN_ADDRESS = Web3.to_checksum_address(os.getenv('TOKEN_ADDRESS'))
WETH_ADDRESS = Web3.to_checksum_address(os.getenv('WETH_ADDRESS'))

w3 = Web3(Web3.HTTPProvider(ARB_RPC_URL))

# Load pool ABI
with open('abi/pool.json', 'r') as f:
    pool_abi = json.load(f)

# Bot instance
bot = Bot(token=BOT_TOKEN)

# All known TALOS pools
POOLS = {
    'Camelot V3': '0xd971ff5a7530919ae67e06695710b262a72e8f2f',
    'Uniswap V3': '0xdaae914e4bae2aae4f536006c353117b90fb37e3',
}

DEXSCREENER_URL = (
    "https://api.dexscreener.com/latest/dex/tokens/"
    + os.getenv('TOKEN_ADDRESS')
)

async def get_prices():
    """
    Get TALOS price in USD and WETH price in USD from DexScreener.
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(DEXSCREENER_URL, timeout=10) as resp:
                data = await resp.json()
        pairs = data.get("pairs", [])
        if not pairs:
            return None, None

        # Take first pair
        p = pairs[0]
        talos_price_usd = float(p.get("priceUsd", 0))

        # Try to extract WETH price from the same pair if available
        base_token = p.get("baseToken", {})
        quote_token = p.get("quoteToken", {})
        if base_token.get("address", "").lower() == WETH_ADDRESS.lower():
            weth_price_usd = talos_price_usd
        elif quote_token.get("address", "").lower() == WETH_ADDRESS.lower():
            weth_price_usd = float(p.get("priceNative", 0)) * talos_price_usd
        else:
            # Fallback: approximate WETH as 1 / priceNative (if priceNative is TALOS in ETH)
            price_native = float(p.get("priceNative", 0)) or 0
            weth_price_usd = talos_price_usd / price_native if price_native > 0 else 0

        if talos_price_usd <= 0 or weth_price_usd <= 0:
            return None, None

        return talos_price_usd, weth_price_usd

    except Exception as e:
        print(f"Price fetch error: {e}")
        return None, None

async def ping(update, context):
    await update.message.reply_text('Bot is alive ✅')

async def handle_swap_event(event, pool_name):
    try:
        sender = event['args']['sender']
        recipient = event['args']['recipient']
        amount0 = event['args']['amount0']
        amount1 = event['args']['amount1']

        # Determine if it's a buy or sell
        if amount0 < 0 and amount1 > 0:
            swap_type = "🟢 BUY"
            talos_amount = abs(amount0) / 1e18
        elif amount0 > 0 and amount1 < 0:
            swap_type = "🔴 SELL"
            talos_amount = amount0 / 1e18
        else:
            swap_type = "⚪️ SWAP"
            talos_amount = abs(amount0) / 1e18

        # --- NEW: Compute WETH & USD from price instead of raw pool amounts ---
        talos_price_usd, weth_price_usd = await get_prices()

        if talos_price_usd and weth_price_usd:
            usd_value = talos_amount * talos_price_usd
            weth_amount = usd_value / weth_price_usd
        else:
            # Fallback to raw pool side (old behaviour, but only as backup)
            if amount0 < 0 and amount1 > 0:
                weth_amount = amount1 / 1e18
            elif amount0 > 0 and amount1 < 0:
                weth_amount = abs(amount1) / 1e18
            else:
                weth_amount = abs(amount1) / 1e18
            usd_value = 0

        tx_hash = event['transactionHash'].hex()

        if talos_price_usd and weth_price_usd:
            price_line = f"💵 Value: ${usd_value:,.2f} (TALOS ${talos_price_usd:.6f})"
        else:
            price_line = "💵 Value: (price unavailable)"

        msg = (
            f"{swap_type} on {pool_name}

"
            f"💰 TALOS: {talos_amount:,.2f}
"
            f"💎 WETH: {weth_amount:.4f}
"
            f"{price_line}
"
            f"👤 Trader: {recipient[:6]}...{recipient[-4:]}
"
            f"🔗 TX: https://arbiscan.io/tx/{tx_hash}"
        )

        print(f"
{swap_type} detected on {pool_name}")
        print(f"TALOS: {talos_amount:,.2f}, WETH(est): {weth_amount:.4f}")
        print(price_line)
        print(f"TX: {tx_hash}")

        await bot.send_message(chat_id=CHAT_ID, text=msg)

    except Exception as e:
        print(f"Error handling swap on {pool_name}: {e}")

async def watch_pool(pool_address, pool_name):
    pool_address = Web3.to_checksum_address(pool_address)
    contract = w3.eth.contract(address=pool_address, abi=pool_abi)

    print(f'✅ Watching {pool_name} at {pool_address}')

    event_filter = None
    retry_count = 0

    while True:
        try:
            # Create or recreate filter
            if event_filter is None:
                event_filter = contract.events.Swap.create_filter(from_block='latest')

            if retry_count > 0:
                print(f'✅ Reconnected to {pool_name}')
                retry_count = 0

            # Check for new events
            for event in event_filter.get_new_entries():
                await handle_swap_event(event, pool_name)

            await asyncio.sleep(2)

        except Exception as e:
            retry_count += 1
            print(f'❌ Error watching {pool_name}: {str(e)[:100]}')
            print(f'⏳ Retry #{retry_count} in 10 seconds...')
            event_filter = None  # Force recreate on next loop
            await asyncio.sleep(10)

async def main():
    print('🚀 Starting TALOS Buy Bot...
')

    # Setup telegram bot
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler('ping', ping))

    # Start Telegram polling in background
    asyncio.create_task(application.initialize())
    asyncio.create_task(application.start())

    # Start watchers
    tasks = []
    for name, addr in POOLS.items():
        tasks.append(asyncio.create_task(watch_pool(addr, name)))

    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())