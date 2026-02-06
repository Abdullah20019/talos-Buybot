

# TALOS Buy/Sell Bot (Arbitrum)

A Telegram **buy/sell bot** for the TALOS token on **Arbitrum**, with:

- Live monitoring of on-chain TALOS transfers  
- Accurate **BUY / SELL detection** using LP + router logic  
- **DEX tagging** (Uniswap / Camelot)  
- **Price, FDV, and USD value** via Dexscreener  
- **Tiered media alerts** (image, 100$ videos, 500$ video)  
- **Per-side thresholds** (BUY ≥ 100 USD, SELL ≥ 3000 USD)  
- Clickable **trader** and **txn** links in Telegram

***

## Features

- Watches TALOS `Transfer` events on **Arbitrum**.
- Classifies swaps as:
  - 🟢 **BUY** – DEX (LP/router) → wallet  
  - 🔴 **SELL** – wallet → DEX (LP/router)
- Detects trades routed through:
  - Uniswap, Camelot  
  - 1inch, Odos, Sushi, TraderJoe  
  - OpenOcean, OKX DEX (Jumper)  
- Uses LP address to label the DEX:
  - Uniswap LP → “Uniswap Swap”  
  - Camelot LP → “Camelot Swap”
- Pulls live **price** and **FDV** from Dexscreener.
- Sends rich Telegram alerts:
  - TALOS amount  
  - WETH amount (best-effort from logs)  
  - USD value and price  
  - FDV  
  - Clickable **Trader** and **Txn** links (Markdown).

***

## Media logic (image & videos)

Media files (in repo root):

- `newimage.jpeg` – default image for smaller trades.  
- `100$Buy.mp4` – used for BUY trades ≥ 100 USD.  
- `100$sell.mp4` – used for SELL trades ≥ 3000 USD (3k–<5k).  
- `500$BuyorSell.mp4` – used for any trade ≥ 500 USD (BUY or SELL), with fallback to 100$ videos if it fails.

Alert rules:

- **BUY side**
  - < 100 USD → no alert.  
  - 100–499 USD → `100$Buy.mp4`.  
  - ≥ 500 USD → try `500$BuyorSell.mp4`, fallback to `100$Buy.mp4`.  

- **SELL side**
  - < 3000 USD → no alert.  
  - 3000–4999 USD → `100$sell.mp4`.  
  - ≥ 5000 USD → try `500$BuyorSell.mp4`, fallback to `100$sell.mp4`.  

If no suitable video is sent (missing/failed), the bot sends `newimage.jpeg` with the caption instead.

***

## Requirements

- Python 3.10+  
- `python-telegram-bot` (v20+)  
- `web3`  
- `aiohttp`  
- `python-dotenv`

Install from `requirements.txt`:

```bash
pip install -r requirements.txt
```

***

## Environment variables

Configure via `.env` or your hosting provider (Railway, etc.):

```env
BOT_TOKEN=your_telegram_bot_token
CHAT_ID=your_target_chat_id

ARB_RPC_URL=https://your-arbitrum-rpc

# TALOS + WETH on Arbitrum
TOKEN_ADDRESS=0x30a538eFFD91ACeFb1b12CE9Bc0074eD18c9dFc9
WETH_ADDRESS=0x...   # Arbitrum WETH

# LPs (TALOS–WETH)
UNISWAP_LP_ADDRESS=0x...  # TALOS–WETH LP on Uniswap
CAMELOT_LP_ADDRESS=0x...  # TALOS–WETH LP on Camelot
```

The media files (`newimage.jpeg`, `100$Buy.mp4`, `100$sell.mp4`, `500$BuyorSell.mp4`) must be in the **repo root**, next to `bot.py`.

***

## How it works (logic overview)

1. Connects to Arbitrum RPC and TALOS/WETH contracts using `web3.py`.
2. Builds a `Transfer` event filter for the TALOS token.
3. In small block ranges, calls `eth_getLogs` for TALOS `Transfer` events.
4. For each event:
   - Skips pure wallet→wallet transfers.  
   - If one side is an LP or known router, classifies as BUY or SELL.  
   - Determines which LP is involved to label **Uniswap** vs **Camelot**.  
   - Looks up WETH transfers in the same tx to estimate WETH amount.  
   - Fetches price + FDV from Dexscreener to compute USD value.  
   - Applies thresholds (BUY ≥ 100, SELL ≥ 3000) and media rules.  
   - Sends a Telegram alert with clickable links.

Example Telegram caption:

```text
$TALOS 🟢 BUY! 🛒
Camelot Swap
🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖

💰 TALOS: 249,803.96
💎 WETH: 0.1300
💵 Value: $590.54
💲 Price: $0.002365
🏦 FDV: $12,345,678.9
👤 Trader: 0x1234...ABCD
🔗 Txn
```

(“Trader” and “Txn” are clickable links.)

***

## Running locally

```bash
# 1. Clone
git clone https://github.com/Abdullah20019/talos-Buybot.git
cd talos-Buybot

# 2. Install deps
pip install -r requirements.txt

# 3. Set env vars (.env or shell)

# 4. Run
python bot.py
```

Use `/ping` in your Telegram chat to confirm the bot is alive.

***

## Deployment (Railway example)

1. Create a new Railway project from this GitHub repo.  
2. Set all required environment variables in Railway’s dashboard.  
3. Ensure the service uses Python and `python bot.py` as the start command (handled via `railway.toml` if present).  
4. Deploy and watch the logs for:
   - RPC connection success  
   - “Watching TALOS LP/router-based buys/sells on Arbitrum…”  

Then perform a test BUY/SELL to see Telegram alerts.

***

## Notes / Limitations

- Only tracks TALOS on **Arbitrum** (hard-coded token).  
- Router list is curated; new aggregators may require adding their router addresses manually.  
- WETH amount is best-effort (first tries trader-related transfers, then falls back to total WETH volume in the tx).  
- `eth_getLogs` ranges are kept small to avoid 413 errors from some RPC providers.

***

## License

MIT (or your preferred license – update this section if you choose a different one).

Citations:
[1] 1000355731.jpeg https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/images/161286790/0dc0d849-d235-4c07-a7bb-ae54005e6a85/1000355731.jpeg
[2] cccc.jpg https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/images/161286790/0f5518e0-97b2-4e06-88c5-9fc38c0adab2/cccc.jpg
[3] newyyy.jpg https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/images/161286790/b0cd8aa4-a2c8-4090-b94b-8e11528b27f2/newyyy.jpg
