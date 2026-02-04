import os
import time
from web3 import Web3
import requests
from dotenv import load_dotenv

load_dotenv()

# Configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
ARB_RPC_URL = os.getenv('ARB_RPC_URL')

# TALOS Contract on Arbitrum
TALOS_ADDRESS = "0x30a538eFFD91ACeFb1b12CE9Bc0074eD18c9dFc9"
w3 = Web3(Web3.HTTPProvider(ARB_RPC_URL))

# Swap event signature
SWAP_EVENT = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"

def send_telegram(message):
    """Send message to Telegram"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': CHAT_ID,
        'text': message,
        'parse_mode': 'HTML'
    }
    try:
        response = requests.post(url, json=payload)
        return response.json()
    except Exception as e:
        print(f"❌ Telegram error: {e}")

def format_swap_message(tx_hash, block_number):
    """Format swap notification"""
    message = f"""
🚀 <b>TALOS SWAP DETECTED!</b>

📦 Block: {block_number}
🔗 TX: <code>{tx_hash}</code>

🌐 <a href="https://arbiscan.io/tx/{tx_hash}">View on Arbiscan</a>
"""
    return message

def monitor_swaps():
    """Monitor TALOS swaps"""
    print("=" * 60)
    print("🚀 TALOS ADVANCED SWAP MONITOR")
    print("=" * 60)
    print(f"✅ Connected to Arbitrum")
    print(f"✅ Monitoring: {TALOS_ADDRESS}")
    print(f"✅ Telegram Bot Ready")
    print("=" * 60)
    
    last_block = w3.eth.block_number
    
    while True:
        try:
            current_block = w3.eth.block_number
            
            if current_block > last_block:
                # Check new blocks for swap events
                for block_num in range(last_block + 1, current_block + 1):
                    block = w3.eth.get_block(block_num, full_transactions=True)
                    
                    for tx in block.transactions:
                        if tx['to'] and tx['to'].lower() == TALOS_ADDRESS.lower():
                            receipt = w3.eth.get_transaction_receipt(tx['hash'])
                            
                            # Check for Swap event in logs
                            for log in receipt['logs']:
                                if log['topics'][0].hex() == SWAP_EVENT:
                                    print(f"🔥 SWAP FOUND! Block: {block_num}")
                                    message = format_swap_message(
                                        tx['hash'].hex(),
                                        block_num
                                    )
                                    send_telegram(message)
                
                last_block = current_block
            
            time.sleep(2)  # Check every 2 seconds
            
        except Exception as e:
            print(f"⚠️ Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    monitor_swaps()
