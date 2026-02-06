import os
import asyncio
import json
from collections import defaultdict
from decimal import Decimal

from dotenv import load_dotenv
from web3 import Web3
from telegram.ext import Application

# ────────────────────── ENV ──────────────────────
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
ARB_RPC_URL = os.getenv("ARB_RPC_URL")
TOKEN_ADDRESS = Web3.to_checksum_address(os.getenv("TOKEN_ADDRESS"))

# ────────────────────── WEB3 ──────────────────────
w3 = Web3(Web3.HTTPProvider(ARB_RPC_URL))

# ────────────────────── ABIs ──────────────────────
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
    "type": "function"
  },
  {
    "constant": true,
    "inputs": [],
    "name": "symbol",
    "outputs": [{"name": "", "type": "string"}],
    "type": "function"
  }
]
""")

TRANSFER_TOPIC = Web3.keccak(text="Transfer(address,address,uint256)").hex()

# ────────────────────── STABLES ──────────────────────
STABLES = {
    Web3.to_checksum_address("0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8"),  # USDC
    Web3.to_checksum_address("0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9"),  # USDT
    Web3.to_checksum_address("0xDA10009cBd5D07dd0CeCc66161FC93D7c9000da1"),  # DAI
}

# ────────────────────── DEX / AGGREGATORS ──────────────────────
DEX_ROUTERS = {Web3.to_checksum_address(r) for r in [
    # Uniswap
    "0xE592427A0AEce92De3Edee1F18E0157C05861564",
    "0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45",

    # Camelot
    "0xc873fEcbd354f5A56E00E710B90EF4201db2448d",

    # Sushi
    "0x1b02da8cb0d097eb8d57a175b88c7d8b47997506",

    # Aggregators
    "0x1111111254EEB25477B68fb85Ed929f73A960582",  # 1inch
    "0x19cEeAd7105607Cd444F5ad10dd51356436095a1",  # Odos
    "0x7Ed9d62C8C4D45E9249f327F57e06adF4Adad5FA",  # OpenOcean
    "0xDEF171Fe48CF0115B1d80b88dc8eAB59176FEe57",  # Paraswap
]}

# ────────────────────── TOKEN META ──────────────────────
token_contract = w3.eth.contract(address=TOKEN_ADDRESS, abi=ERC20_ABI)
TOKEN_DECIMALS = token_contract.functions.decimals().call()
TOKEN_SYMBOL = token_contract.functions.symbol().call()

ERC20_CACHE = {}


def get_erc20(addr):
    if addr not in ERC20_CACHE:
        ERC20_CACHE[addr] = w3.eth.contract(address=addr, abi=ERC20_ABI)
    return ERC20_CACHE[addr]


# ────────────────────── TX PROCESSOR ──────────────────────
async def process_tx(tx_hash, app):
    try:
        receipt = w3.eth.get_transaction_receipt(tx_hash)
    except Exception:
        return

    deltas = defaultdict(Decimal)
    participants = set()

    for log in receipt.logs:
        if log["topics"][0].hex() != TRANSFER_TOPIC:
            continue

        token = Web3.to_checksum_address(log["address"])
        contract = get_erc20(token)

        try:
            evt = contract.events.Transfer().process_log(log)
        except Exception:
            continue

        frm = evt["args"]["from"]
        to = evt["args"]["to"]
        val = Decimal(evt["args"]["value"]) / Decimal(10 ** contract.functions.decimals().call())

        deltas[(frm, token)] -= val
        deltas[(to, token)] += val
        participants |= {frm, to}

    # Identify trader (EOA)
    trader = next((a for a in participants if a not in DEX_ROUTERS), None)
    if not trader:
        return

    token_delta = deltas.get((trader, TOKEN_ADDRESS), Decimal(0))
    if token_delta == 0:
        return

    is_buy = token_delta > 0
    direction = "🟢 BUY" if is_buy else "🔴 SELL"

    # USD value via stables
    usd_value = sum(
        abs(v) for (addr, token), v in deltas.items()
        if addr == trader and token in STABLES
    )

    msg = (
        f"${TOKEN_SYMBOL} {direction}\n\n"
        f"💰 Amount: {abs(token_delta):,.4f}\n"
        f"💵 USD: ${usd_value:,.2f}\n"
        f"👤 Trader: {trader[:6]}...{trader[-4:]}\n"
        f"🔗 https://arbiscan.io/tx/{tx_hash.hex()}"
    )

    await app.bot.send_message(chat_id=CHAT_ID, text=msg)


# ────────────────────── BLOCK WATCHER ──────────────────────
async def watch(app):
    last_block = w3.eth.block_number
    print("🚀 Bot live. Watching Arbitrum swaps...")

    while True:
        try:
            current = w3.eth.block_number
            if current > last_block:
                for b in range(last_block + 1, current + 1):
                    block = w3.eth.get_block(b, full_transactions=True)
                    for tx in block.transactions:
                        if tx["to"] and tx["to"] in DEX_ROUTERS:
                            await process_tx(tx["hash"], app)
                last_block = current

            await asyncio.sleep(1)

        except Exception as e:
            print("⚠️ Watcher error:", str(e)[:120])
            await asyncio.sleep(5)


# ────────────────────── MAIN ──────────────────────
async def main():
    app = Application.builder().token(BOT_TOKEN).build()

    await app.initialize()
    await app.start()

    try:
        await watch(app)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("🛑 Shutting down...")
    finally:
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
