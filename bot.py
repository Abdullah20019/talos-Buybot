import os
import asyncio
from dotenv import load_dotenv
from telegram import Bot
from telegram.ext import Application, CommandHandler
from web3 import Web3
import json

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
ARB_RPC_URL = os.getenv('ARB_RPC_URL')
TOKEN_ADDRESS = Web3.to_checksum_address(os.getenv('TOKEN_ADDRESS'))
WETH_ADDRESS = Web3.to_checksum_address(os.getenv('WETH_ADDRESS'))

w3 = Web3(Web3.HTTPProvider(ARB_RPC_URL))

# V3 Pool ABI
with open('abi/pool.json', 'r') as f:
    v3_pool_abi = json.load(f)

# V2 Pool ABI
v2_pool_abi = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "sender", "type": "address"},
            {"indexed": True, "name": "to", "type": "address"},
            {"indexed": False, "name": "amount0In", "type": "uint256"},
            {"indexed": False, "name": "amount1In", "type": "uint256"},
            {"indexed": False, "name": "amount0Out", "type": "uint256"},
            {"indexed": False, "name": "amount1Out", "type": "uint256"}
        ],
        "name": "Swap",
        "type": "event"
    }
]

bot = Bot(token=BOT_TOKEN)

# ALL TALOS POOLS (all available on Arbitrum)
POOLS = [
    ('0xdaae914e4bae2aae4f536006c353117b90fb37e3', 'v2', 'Uniswap V2 TALOS/WETH'),
    ('0xd971ff5a7530919ae67e06695710b262a72e8f2f', 'v3', 'Camelot V3 TALOS/WETH'),
]

async def ping(update, context):
    await update.message.reply_text('🤖 Bot is alive!\n✅ Monitoring ALL TALOS pools (V2+V3)')

async def handle_v2_swap(event, pool_name):
    try:
        sender = event['args']['sender']
        to = event['args']['to']
        amount0In = event['args']['amount0In']
        amount1In = event['args']['amount1In']
        amount0Out = event['args']['amount0Out']
        amount1Out = event['args']['amount1Out']
        
        if amount0In > 0 and amount1Out > 0:
            swap_type = "🔴 SELL"
            talos_amount = amount0In / 1e18
            weth_amount = amount1Out / 1e18
        elif amount1In > 0 and amount0Out > 0:
            swap_type = "🟢 BUY"
            talos_amount = amount0Out / 1e18
            weth_amount = amount1In / 1e18
        else:
            return
        
        tx_hash = event['transactionHash'].hex()
        usd_value = weth_amount * 3000
        
        msg = (
            f"{swap_type} on {pool_name}\n\n"
            f"💰 TALOS: {talos_amount:,.2f}\n"
            f"💎 WETH: {weth_amount:.6f}\n"
            f"💵 Value: ~${usd_value:.2f}\n"
            f"👤 Trader: {to[:6]}...{to[-4:]}\n"
            f"🔗 https://arbiscan.io/tx/{tx_hash}"
        )
        
        print(f'\n{"="*50}')
        print(f'{swap_type} DETECTED!')
        print(f'Pool: {pool_name}')
        print(f'TALOS: {talos_amount:,.2f}')
        print(f'WETH: {weth_amount:.6f}')
        print(f'Value: ~${usd_value:.2f}')
        print(f'TX: {tx_hash}')
        print(f'{"="*50}\n')
        
        await bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        print(f'Error handling V2 swap: {e}')

async def handle_v3_swap(event, pool_name):
    try:
        sender = event['args']['sender']
        recipient = event['args']['recipient']
        amount0 = event['args']['amount0']
        amount1 = event['args']['amount1']
        
        if amount0 < 0 and amount1 > 0:
            swap_type = "🟢 BUY"
            talos_amount = abs(amount0) / 1e18
            weth_amount = amount1 / 1e18
        elif amount0 > 0 and amount1 < 0:
            swap_type = "🔴 SELL"
            talos_amount = amount0 / 1e18
            weth_amount = abs(amount1) / 1e18
        else:
            return
        
        tx_hash = event['transactionHash'].hex()
        usd_value = weth_amount * 3000
        
        msg = (
            f"{swap_type} on {pool_name}\n\n"
            f"💰 TALOS: {talos_amount:,.2f}\n"
            f"💎 WETH: {weth_amount:.6f}\n"
            f"💵 Value: ~${usd_value:.2f}\n"
            f"👤 Trader: {recipient[:6]}...{recipient[-4:]}\n"
            f"🔗 https://arbiscan.io/tx/{tx_hash}"
        )
        
        print(f'\n{"="*50}')
        print(f'{swap_type} DETECTED!')
        print(f'Pool: {pool_name}')
        print(f'TALOS: {talos_amount:,.2f}')
        print(f'WETH: {weth_amount:.6f}')
        print(f'Value: ~${usd_value:.2f}')
        print(f'TX: {tx_hash}')
        print(f'{"="*50}\n')
        
        await bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        print(f'Error handling V3 swap: {e}')

async def watch_pool(pool_address, pool_type, pool_name):
    pool_address = Web3.to_checksum_address(pool_address)
    
    abi = v2_pool_abi if pool_type == 'v2' else v3_pool_abi
    handler = handle_v2_swap if pool_type == 'v2' else handle_v3_swap
    
    contract = w3.eth.contract(address=pool_address, abi=abi)
    print(f'✅ Watching: {pool_name}')
    print(f'   Type: {pool_type.upper()}')
    print(f'   Address: {pool_address}\n')
    
    event_filter = None
    retry_count = 0
    poll_count = 0
    
    while True:
        try:
            if event_filter is None:
                event_filter = contract.events.Swap.create_filter(from_block='latest')
                if retry_count > 0:
                    print(f'✅ Reconnected to {pool_name}')
                retry_count = 0
            
            events = event_filter.get_new_entries()
            poll_count += 1
            
            if events:
                for event in events:
                    await handler(event, pool_name)
            else:
                if poll_count % 20 == 0:
                    print(f'⏳ {pool_name[:20]}... - Active ({poll_count} checks)')
            
            await asyncio.sleep(3)
            
        except Exception as e:
            retry_count += 1
            print(f'❌ Error on {pool_name}: {str(e)[:80]}')
            print(f'⏳ Reconnecting in 10s...')
            event_filter = None
            await asyncio.sleep(10)

async def main():
    print('\n' + '='*60)
    print('  🚀 TALOS BUY BOT - ALL POOLS (V2 + V3)')
    print('='*60 + '\n')
    
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler('ping', ping))
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    print('🤖 Telegram Bot: CONNECTED')
    print(f'📊 Monitoring: {len(POOLS)} pools')
    print('💡 Note: Only NEW swaps detected (after bot starts)\n')
    
    tasks = [watch_pool(addr, ptype, name) for addr, ptype, name in POOLS]
    await asyncio.gather(*tasks)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('\n\n👋 Bot stopped by user')
    except Exception as e:
        print(f'\n\n❌ Fatal error: {e}')
