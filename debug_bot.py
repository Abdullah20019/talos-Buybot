print("Step 1: Importing modules...")
try:
    import os
    import asyncio
    from dotenv import load_dotenv
    from telegram import Bot
    from telegram.ext import Application, CommandHandler
    from web3 import Web3
    import json
    print("All imports successful")
except Exception as e:
    print(f"Import error: {e}")
    exit()

print("\nStep 2: Loading .env...")
try:
    load_dotenv()
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    CHAT_ID = os.getenv('CHAT_ID')
    ARB_RPC_URL = os.getenv('ARB_RPC_URL')
    TOKEN_ADDRESS = os.getenv('TOKEN_ADDRESS')
    WETH_ADDRESS = os.getenv('WETH_ADDRESS')
    
    print(f"BOT_TOKEN: {'Found' if BOT_TOKEN else 'MISSING'}")
    print(f"CHAT_ID: {CHAT_ID}")
    print(f"ARB_RPC_URL: {'Found' if ARB_RPC_URL else 'MISSING'}")
    print(f"TOKEN_ADDRESS: {TOKEN_ADDRESS}")
    print(f"WETH_ADDRESS: {WETH_ADDRESS}")
except Exception as e:
    print(f".env error: {e}")
    exit()

print("\nStep 3: Connecting to Web3...")
try:
    w3 = Web3(Web3.HTTPProvider(ARB_RPC_URL))
    print(f"Web3 connected: {w3.is_connected()}")
    print(f"Latest block: {w3.eth.block_number}")
except Exception as e:
    print(f"Web3 error: {e}")
    exit()

print("\nAll checks passed!")
