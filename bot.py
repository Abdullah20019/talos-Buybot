# Updated: Feb 4, 2026 - Enhanced with first-time buyers & whale tracking + 40K sell minimum
import os
import asyncio
from dotenv import load_dotenv
from telegram import Bot
from telegram.ext import Application, CommandHandler
from web3 import Web3
import json
import aiohttp
from datetime import datetime, timedelta

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
ARB_RPC_URL = os.getenv('ARB_RPC_URL')
TOKEN_ADDRESS = Web3.to_checksum_address('0x30a538eFFD91ACeFb1b12CE9Bc0074eD18c9dFc9')

w3 = Web3(Web3.HTTPProvider(ARB_RPC_URL))
bot = Bot(token=BOT_TOKEN)

# Token info
TOKEN_SYMBOL = "TALOS"
TOKEN_DECIMALS = 9

# Logo path
LOGO_PATH = "image.jpg.jpeg"

# WETH address on Arbitrum
WETH_ADDRESS = '0x82aF49447D8a07e3bd95BD0d56f35241523fBab1'

# Whale alert threshold (WETH)
WHALE_THRESHOLD = 0.3  # 0.3 ETH

# Minimum trade amounts to track
MIN_BUY_AMOUNT = 10        # Minimum TALOS for buy notifications
MIN_SELL_AMOUNT = 40000    # Minimum TALOS for sell notifications

# Known whale/project wallets (add addresses here)
KNOWN_WALLETS = {
    # Example format - add real addresses:
    # '0x...': '🏦 Project Treasury',
    # '0x...': '🐋 Known Whale "BigBuyer"',
    # '0x...': '👨‍💼 Team Wallet',
    # Add more as you discover them
}

# Track all wallets that have ever traded
seen_wallets = set()
first_time_buyers = set()

# Minimal Transfer event ABI (ERC20)
transfer_abi = [{
    "anonymous": False,
    "inputs": [
        {"indexed": True, "name": "from", "type": "address"},
        {"indexed": True, "name": "to", "type": "address"},
        {"indexed": False, "name": "value", "type": "uint256"}
    ],
    "name": "Transfer",
    "type": "event"
}]

# DEX Router addresses (lowercase)
DEX_ROUTERS = {
    '0xa51afafe0263b40edaef0df8781ea9aa03e381a3': 'Uniswap V2',
    '0x1b02da8cb0d097eb8d57a175b88c7d8b47997506': 'SushiSwap',
    '0xc873fecbd354f5a56e00e710b90ef4201db2448d': 'Camelot',
    '0x1f721e2e82f6676fce4ea07a5958cf098d339e18': 'Camelot V3',
    '0xb4315e873dbcf96ffd0acd8ea43f689d8c20fb30': 'TraderJoe',
}

# Known pool addresses
KNOWN_POOLS = {
    '0x50c8e97feb1e629196012b7ccca4d4785ed1eb1f': 'Camelot',
}

processed_txs = set()

# Cache for price and market cap
price_cache = {'price': 0, 'mcap': 0, 'last_update': 0}

# Daily volume tracking
daily_volume = {
    'date': datetime.now().date(),
    'buy_volume_weth': 0,
    'sell_volume_weth': 0,
    'buy_volume_talos': 0,
    'sell_volume_talos': 0,
    'buy_count': 0,
    'sell_count': 0,
}

# Top 20 holders tracking
top_20_holders = set()
top_20_last_update = 0

async def get_eth_price():
    """Get ETH price in USD"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get('https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd') as resp:
                data = await resp.json()
                return data['ethereum']['usd']
    except:
        return 2800

async def get_token_info():
    """Get TALOS price and market cap from DexScreener"""
    try:
        now = datetime.now().timestamp()
        if now - price_cache['last_update'] < 30:
            return price_cache['price'], price_cache['mcap']
        
        async with aiohttp.ClientSession() as session:
            url = f'https://api.dexscreener.com/latest/dex/tokens/{TOKEN_ADDRESS}'
            async with session.get(url) as resp:
                data = await resp.json()
                if data.get('pairs'):
                    pair = data['pairs'][0]
                    price = float(pair.get('priceUsd', 0))
                    mcap = float(pair.get('marketCap', 0))
                    
                    price_cache['price'] = price
                    price_cache['mcap'] = mcap
                    price_cache['last_update'] = now
                    
                    return price, mcap
    except Exception as e:
        print(f"Error fetching token info: {e}")
    
    return price_cache.get('price', 0), price_cache.get('mcap', 0)

async def update_top_20_holders():
    """Update top 20 holders list (simplified version)"""
    global top_20_holders, top_20_last_update
    
    # Update every 10 minutes
    now = datetime.now().timestamp()
    if now - top_20_last_update < 600:
        return
    
    try:
        # In production, you'd fetch from Arbiscan API or The Graph
        # For now, we'll track holders as we see large holders
        print("📊 Top 20 holders cache refreshed")
        top_20_last_update = now
    except Exception as e:
        print(f"Error updating top 20: {e}")

def is_top_20_holder(wallet):
    """Check if wallet is in top 20 holders"""
    return wallet.lower() in top_20_holders

def add_to_top_20(wallet, balance_pct):
    """Add wallet to top 20 if they hold enough"""
    if balance_pct >= 0.5:  # Top 20 usually holds >0.5% each
        top_20_holders.add(wallet.lower())
        if len(top_20_holders) > 20:
            # Keep only 20 (in production, you'd sort by balance)
            top_20_holders.pop()

def is_first_time_buyer(wallet):
    """Check if this is the wallet's first buy"""
    wallet = wallet.lower()
    if wallet not in seen_wallets:
        seen_wallets.add(wallet)
        first_time_buyers.add(wallet)
        return True
    return False

def get_wallet_label(wallet):
    """Get special label for known wallets"""
    wallet_lower = wallet.lower()
    if wallet_lower in KNOWN_WALLETS:
        return KNOWN_WALLETS[wallet_lower]
    return None

async def get_holder_percentage(wallet):
    """Get percentage of supply held by wallet"""
    try:
        token_contract = w3.eth.contract(
            address=TOKEN_ADDRESS,
            abi=[{
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function"
            }, {
                "constant": True,
                "inputs": [],
                "name": "totalSupply",
                "outputs": [{"name": "", "type": "uint256"}],
                "type": "function"
            }]
        )
        
        balance = token_contract.functions.balanceOf(Web3.to_checksum_address(wallet)).call()
        total_supply = token_contract.functions.totalSupply().call()
        
        percentage = (balance / total_supply) * 100
        
        # Update top 20 list
        add_to_top_20(wallet, percentage)
        
        return percentage
    except:
        return 0

def get_whale_category(weth_amount):
    """Categorize buyer/seller by WETH amount"""
    if weth_amount >= 10:
        return "🐋 MEGA WHALE", "🤖" * 30
    elif weth_amount >= 5:
        return "🐳 HUGE WHALE", "🤖" * 25
    elif weth_amount >= 2:
        return "🐋 BIG WHALE", "🤖" * 20
    elif weth_amount >= 1:
        return "🐬 WHALE", "🤖" * 15
    elif weth_amount >= 0.5:
        return "🐬 DOLPHIN", "🤖" * 10
    elif weth_amount >= 0.1:
        return "🐟 FISH", "🤖" * 5
    else:
        return "🦐 SHRIMP", "🤖" * 2

def get_holder_emoji(percentage):
    """Get holder type based on percentage"""
    if percentage >= 5:
        return "🐋 Mega Holder"
    elif percentage >= 2:
        return "🐳 Big Holder"
    elif percentage >= 1:
        return "🐬 Whale Holder"
    elif percentage >= 0.5:
        return "🐟 Fish Holder"
    else:
        return "🦐 Small Holder"

def detect_dex(tx_to, transfer_addresses):
    """Detect which DEX is being used"""
    if tx_to in DEX_ROUTERS:
        return DEX_ROUTERS[tx_to]
    
    if tx_to in KNOWN_POOLS:
        return KNOWN_POOLS[tx_to]
    
    for addr in transfer_addresses:
        if addr in KNOWN_POOLS:
            return KNOWN_POOLS[addr]
    
    return "DEX Swap"

def reset_daily_volume_if_needed():
    """Reset volume tracking at midnight"""
    global daily_volume
    
    today = datetime.now().date()
    if daily_volume['date'] != today:
        daily_volume = {
            'date': today,
            'buy_volume_weth': 0,
            'sell_volume_weth': 0,
            'buy_volume_talos': 0,
            'sell_volume_talos': 0,
            'buy_count': 0,
            'sell_count': 0,
        }
        print(f"\n📅 Daily volume reset for {today}")

def update_daily_volume(swap_type, weth_amount, talos_amount):
    """Update daily volume stats"""
    reset_daily_volume_if_needed()
    
    if swap_type == "BUY":
        daily_volume['buy_volume_weth'] += weth_amount
        daily_volume['buy_volume_talos'] += talos_amount
        daily_volume['buy_count'] += 1
    else:
        daily_volume['sell_volume_weth'] += weth_amount
        daily_volume['sell_volume_talos'] += talos_amount
        daily_volume['sell_count'] += 1

async def send_whale_alert(swap_type, weth_amount, usd_value, talos_amount, user_wallet, tx_hash, dex_name):
    """Send special alert for whale transactions"""
    emoji = "🚨🐋" if swap_type == "BUY" else "🚨💸"
    
    msg = (
        f"{'='*30}\n"
        f"{emoji} WHALE ALERT {emoji}\n"
        f"{'='*30}\n\n"
        f"🔥 MASSIVE {swap_type}! 🔥\n\n"
        f"💵 {weth_amount:.3f} WETH (${usd_value:,.2f})\n"
        f"💰 {talos_amount:,.1f} ${TOKEN_SYMBOL}\n"
        f"🏪 {dex_name}\n"
        f"👤 [{user_wallet[:6]}...{user_wallet[-4:]}](https://arbiscan.io/address/{user_wallet})\n"
        f"🔗 [View Transaction](https://arbiscan.io/tx/{tx_hash})\n\n"
        f"⚠️ This is a significant trade!"
    )
    
    try:
        if os.path.exists(LOGO_PATH):
            with open(LOGO_PATH, 'rb') as photo:
                await bot.send_photo(
                    chat_id=CHAT_ID,
                    photo=photo,
                    caption=msg,
                    parse_mode='Markdown'
                )
        else:
            await bot.send_message(
                chat_id=CHAT_ID,
                text=msg,
                parse_mode='Markdown',
                disable_web_page_preview=True
            )
        print("🚨 Whale alert sent!")
    except Exception as e:
        print(f"Error sending whale alert: {e}")

async def send_top_20_alert(swap_type, user_wallet, talos_amount, holder_pct, tx_hash, weth_amount, usd_value):
    """Send alert when top 20 holder trades"""
    emoji = "👑🟢" if swap_type == "BUY" else "👑🔴"
    
    msg = (
        f"{emoji} TOP 20 HOLDER ACTIVITY {emoji}\n\n"
        f"A TOP 20 holder just made a {swap_type}!\n\n"
        f"💵 {weth_amount:.3f} WETH (${usd_value:,.2f})\n"
        f"💰 {talos_amount:,.1f} ${TOKEN_SYMBOL}\n"
        f"👤 Holds {holder_pct:.2f}% of supply\n"
        f"🔗 [View Transaction](https://arbiscan.io/tx/{tx_hash})\n\n"
        f"⚠️ Monitor this carefully!"
    )
    
    try:
        await bot.send_message(
            chat_id=CHAT_ID,
            text=msg,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
        print("👑 Top 20 holder alert sent!")
    except Exception as e:
        print(f"Error sending top 20 alert: {e}")

async def ping(update, context):
    total_wallets = len(seen_wallets)
    new_buyers = len(first_time_buyers)
    await update.message.reply_text(
        f'🤖 Monitoring {TOKEN_SYMBOL} swaps!\n\n'
        f'👥 Tracked wallets: {total_wallets}\n'
        f'🆕 First-time buyers: {new_buyers}\n'
        f'👑 Top 20 tracked: {len(top_20_holders)}\n\n'
        f'📊 Minimums:\n'
        f'  • Buys: ≥{MIN_BUY_AMOUNT} {TOKEN_SYMBOL}\n'
        f'  • Sells: ≥{MIN_SELL_AMOUNT:,} {TOKEN_SYMBOL}'
    )

async def volume_command(update, context):
    """Show daily volume stats"""
    reset_daily_volume_if_needed()
    
    eth_price = await get_eth_price()
    
    buy_usd = daily_volume['buy_volume_weth'] * eth_price
    sell_usd = daily_volume['sell_volume_weth'] * eth_price
    total_usd = buy_usd + sell_usd
    
    msg = (
        f"📊 Daily Volume Report\n"
        f"Date: {daily_volume['date']}\n\n"
        f"🟢 BUYS:\n"
        f"  • {daily_volume['buy_count']} transactions\n"
        f"  • {daily_volume['buy_volume_weth']:.3f} WETH (${buy_usd:,.2f})\n"
        f"  • {daily_volume['buy_volume_talos']:,.0f} {TOKEN_SYMBOL}\n\n"
        f"🔴 SELLS:\n"
        f"  • {daily_volume['sell_count']} transactions\n"
        f"  • {daily_volume['sell_volume_weth']:.3f} WETH (${sell_usd:,.2f})\n"
        f"  • {daily_volume['sell_volume_talos']:,.0f} {TOKEN_SYMBOL}\n\n"
        f"💰 Total Volume: ${total_usd:,.2f}\n"
        f"📈 Buy/Sell Ratio: {daily_volume['buy_count']}:{daily_volume['sell_count']}"
    )
    
    await update.message.reply_text(msg)

async def handle_transfer(event):
    try:
        tx_hash = event['transactionHash'].hex()
        
        if tx_hash in processed_txs:
            return
        
        print(f"\n🔍 Processing: {tx_hash[:10]}...")
        
        # Get ALL Transfer events
        tx_receipt = w3.eth.get_transaction_receipt(tx_hash)
        contract = w3.eth.contract(address=TOKEN_ADDRESS, abi=transfer_abi)
        weth_contract = w3.eth.contract(address=Web3.to_checksum_address(WETH_ADDRESS), abi=transfer_abi)
        
        all_transfers = contract.events.Transfer().process_receipt(tx_receipt)
        weth_transfers = weth_contract.events.Transfer().process_receipt(tx_receipt)
        
        print(f"📊 {len(all_transfers)} TALOS | {len(weth_transfers)} WETH transfers")
        
        if not all_transfers:
            processed_txs.add(tx_hash)
            return
        
        # Filter mints/burns
        zero_addr = '0x0000000000000000000000000000000000000000'
        valid_transfers = [
            t for t in all_transfers 
            if t['args']['from'] != zero_addr and t['args']['to'] != zero_addr
        ]
        
        if not valid_transfers:
            processed_txs.add(tx_hash)
            return
        
        # Get transaction details
        tx = w3.eth.get_transaction(tx_hash)
        tx_from = tx['from'].lower()
        tx_to = tx['to'].lower() if tx['to'] else None
        
        # Check if DEX swap
        is_router_swap = tx_to and tx_to in DEX_ROUTERS
        is_pool_swap = len(valid_transfers) >= 2
        
        if not (is_router_swap or is_pool_swap):
            processed_txs.add(tx_hash)
            return
        
        # Collect all addresses involved
        transfer_addresses = set()
        for t in valid_transfers:
            transfer_addresses.add(t['args']['from'].lower())
            transfer_addresses.add(t['args']['to'].lower())
        
        # Detect DEX name
        dex_name = detect_dex(tx_to, transfer_addresses)
        
        print(f"✅ DEX: {dex_name}")
        
        # Find swaps
        for transfer in valid_transfers:
            from_addr = transfer['args']['from'].lower()
            to_addr = transfer['args']['to'].lower()
            value = transfer['args']['value']
            talos_amount = value / (10 ** TOKEN_DECIMALS)
            
            # Determine swap type first
            swap_type = None
            user_wallet = None
            
            if from_addr == tx_from:
                swap_type = "SELL"
                user_wallet = tx_from
            elif to_addr == tx_from:
                swap_type = "BUY"
                user_wallet = tx_from
            elif is_router_swap:
                user_receives = any(t['args']['to'].lower() == tx_from for t in valid_transfers)
                user_sends = any(t['args']['from'].lower() == tx_from for t in valid_transfers)
                
                if user_receives:
                    swap_type = "BUY"
                    user_wallet = tx_from
                elif user_sends:
                    swap_type = "SELL"
                    user_wallet = tx_from
            
            if not swap_type or not user_wallet:
                continue
            
            # Apply different minimums for buys and sells
            if swap_type == "BUY" and talos_amount < MIN_BUY_AMOUNT:
                print(f"⏭️ Skipping small buy: {talos_amount:.1f} TALOS")
                continue
            elif swap_type == "SELL" and talos_amount < MIN_SELL_AMOUNT:
                print(f"⏭️ Skipping small sell: {talos_amount:.1f} TALOS (min: {MIN_SELL_AMOUNT:,})")
                continue
            
            # Calculate WETH amount
            weth_amount = 0
            for weth_tx in weth_transfers:
                weth_val = weth_tx['args']['value'] / 1e18
                if weth_val > 0:
                    weth_amount = max(weth_amount, weth_val)
            
            # Get prices
            eth_price = await get_eth_price()
            usd_value = weth_amount * eth_price
            
            # Get token info
            token_price, market_cap = await get_token_info()
            
            # Get holder percentage
            holder_pct = await get_holder_percentage(user_wallet)
            holder_emoji = get_holder_emoji(holder_pct)
            
            # Check special wallet status
            is_first_timer = is_first_time_buyer(user_wallet) and swap_type == "BUY"
            is_top_20 = is_top_20_holder(user_wallet)
            wallet_label = get_wallet_label(user_wallet)
            
            # Get whale category
            category, robots = get_whale_category(weth_amount)
            
            # Update daily volume
            update_daily_volume(swap_type, weth_amount, talos_amount)
            
            # Format amounts
            talos_formatted = f"{talos_amount/1000:.1f}K" if talos_amount >= 1000 else f"{talos_amount:.1f}"
            mcap_formatted = f"${market_cap/1e6:.2f}M" if market_cap >= 1e6 else f"${market_cap/1e3:.1f}K"
            
            # Build message
            if swap_type == "BUY":
                emoji = "🛒"
                action = "Buy!"
            else:
                emoji = "💸"
                action = "Sell!"
            
            # Build badges
            badges = ""
            if is_first_timer:
                badges += " 🆕"
            if is_top_20:
                badges += " 👑"
            if wallet_label:
                badges += f" {wallet_label}"
            
            # Make wallet address clickable
            wallet_link = f"https://arbiscan.io/address/{user_wallet}"
            
            msg = (
                f"{emoji} ${TOKEN_SYMBOL} {action} {emoji}{badges}\n"
                f"🏪 {dex_name}\n\n"
                f"{robots}\n\n"
                f"💵 {weth_amount:.3f} WETH (${usd_value:,.2f})\n"
                f"💰 {talos_formatted} ${TOKEN_SYMBOL}\n"
                f"👤 [{user_wallet[:6]}...{user_wallet[-4:]}]({wallet_link}) | [Txn](https://arbiscan.io/tx/{tx_hash})\n"
                f"🐟 {holder_emoji} | {holder_pct:.1f}%\n"
                f"💲 Price: ${token_price:.6f}\n"
                f"📊 Market Cap: {mcap_formatted}"
            )
            
            print(f"\n{'='*50}")
            print(f"{swap_type}: {talos_amount:.2f} {TOKEN_SYMBOL}")
            print(f"DEX: {dex_name}")
            print(f"WETH: {weth_amount:.3f} (${usd_value:,.2f})")
            print(f"Category: {category}")
            if is_first_timer:
                print("🆕 FIRST-TIME BUYER!")
            if is_top_20:
                print("👑 TOP 20 HOLDER!")
            if wallet_label:
                print(f"🏷️  {wallet_label}")
            print(f"{'='*50}")
            
            # Send regular message
            try:
                if os.path.exists(LOGO_PATH):
                    with open(LOGO_PATH, 'rb') as photo:
                        await bot.send_photo(
                            chat_id=CHAT_ID,
                            photo=photo,
                            caption=msg,
                            parse_mode='Markdown'
                        )
                else:
                    await bot.send_message(
                        chat_id=CHAT_ID,
                        text=msg,
                        parse_mode='Markdown',
                        disable_web_page_preview=True
                    )
                print("✅ Sent")
            except Exception as e:
                print(f"⚠️  Send failed: {e}")
                msg_plain = msg.replace('[', '').replace(']', '').replace('(', ' (').replace(')', ')')
                await bot.send_message(chat_id=CHAT_ID, text=msg_plain)
                print("✅ Sent as plain text")
            
            # Send whale alert if threshold met
            if weth_amount >= WHALE_THRESHOLD:
                await send_whale_alert(swap_type, weth_amount, usd_value, talos_amount, user_wallet, tx_hash, dex_name)
            
            # Send top 20 holder alert
            if is_top_20:
                await send_top_20_alert(swap_type, user_wallet, talos_amount, holder_pct, tx_hash, weth_amount, usd_value)
        
        processed_txs.add(tx_hash)
        if len(processed_txs) > 100:
            processed_txs.pop()
        
    except Exception as e:
        print(f'\n❌ ERROR: {e}')
        import traceback
        traceback.print_exc()

async def send_daily_summary():
    """Send daily volume summary at midnight"""
    while True:
        try:
            now = datetime.now()
            # Calculate time until midnight
            tomorrow = now + timedelta(days=1)
            midnight = datetime.combine(tomorrow.date(), datetime.min.time())
            seconds_until_midnight = (midnight - now).total_seconds()
            
            await asyncio.sleep(seconds_until_midnight)
            
            # Send summary
            eth_price = await get_eth_price()
            buy_usd = daily_volume['buy_volume_weth'] * eth_price
            sell_usd = daily_volume['sell_volume_weth'] * eth_price
            total_usd = buy_usd + sell_usd
            
            msg = (
                f"📅 DAILY SUMMARY - {daily_volume['date']}\n"
                f"{'='*30}\n\n"
                f"🟢 BUYS: {daily_volume['buy_count']} | ${buy_usd:,.2f}\n"
                f"🔴 SELLS: {daily_volume['sell_count']} | ${sell_usd:,.2f}\n\n"
                f"💰 Total Volume: ${total_usd:,.2f}\n"
                f"📊 {TOKEN_SYMBOL} Traded: {(daily_volume['buy_volume_talos'] + daily_volume['sell_volume_talos']):,.0f}\n\n"
                f"🆕 New buyers today: {len(first_time_buyers)}"
            )
            
            await bot.send_message(chat_id=CHAT_ID, text=msg)
            print("📅 Daily summary sent!")
            
            # Reset first-time buyers for new day
            first_time_buyers.clear()
            
        except Exception as e:
            print(f"Error sending daily summary: {e}")
            await asyncio.sleep(3600)  # Retry in 1 hour

async def watch_token_transfers():
    contract = w3.eth.contract(address=TOKEN_ADDRESS, abi=transfer_abi)
    print(f'✅ Monitoring {TOKEN_SYMBOL} Swaps')
    print(f'   Token: {TOKEN_ADDRESS}')
    print(f'   Min Buy: {MIN_BUY_AMOUNT} {TOKEN_SYMBOL}')
    print(f'   Min Sell: {MIN_SELL_AMOUNT:,} {TOKEN_SYMBOL}')
    print(f'   Whale Alert: ≥{WHALE_THRESHOLD} ETH')
    
    if os.path.exists(LOGO_PATH):
        print(f'   Logo: ✅ {LOGO_PATH}\n')
    else:
        print(f'   Logo: ⚠️  Not found\n')
    
    # Update top 20 holders periodically
    asyncio.create_task(periodic_top_20_update())
    
    event_filter = None
    retry_count = 0
    poll_count = 0
    
    while True:
        try:
            if event_filter is None:
                event_filter = contract.events.Transfer.create_filter(fromBlock='latest')
                if retry_count > 0:
                    print(f'✅ Reconnected')
                retry_count = 0
            
            events = event_filter.get_new_entries()
            poll_count += 1
            
            if events:
                for event in events:
                    await handle_transfer(event)
            else:
                if poll_count % 20 == 0:
                    # Show volume update
                    print(f'⏳ Monitoring... | Today: {daily_volume["buy_count"]}B / {daily_volume["sell_count"]}S | Tracked: {len(seen_wallets)} wallets')
            
            await asyncio.sleep(3)
            
        except Exception as e:
            retry_count += 1
            print(f'❌ Error: {str(e)[:80]}')
            event_filter = None
            await asyncio.sleep(10)

async def periodic_top_20_update():
    """Periodically update top 20 holders"""
    while True:
        await asyncio.sleep(600)  # Every 10 minutes
        await update_top_20_holders()

async def main():
    print('\n' + '='*60)
    print(f'  🚀 {TOKEN_SYMBOL} ADVANCED SWAP MONITOR')
    print('='*60 + '\n')
    
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler('ping', ping))
    application.add_handler(CommandHandler('volume', volume_command))
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    print('🤖 Telegram Bot: CONNECTED')
    print('📊 Features: Whale Alerts | Volume | Top 20 | First-Timers\n')
    
    # Start daily summary task
    asyncio.create_task(send_daily_summary())
    
    await watch_token_transfers()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('\n\n👋 Bot stopped')
    except Exception as e:
        print(f'\n\n❌ Fatal error: {e}')
