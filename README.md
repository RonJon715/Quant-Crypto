# Alpha Combination Crypto Trading Bot

A multi-signal alpha combination engine for automated crypto trading on Coinbase. It combines 20+ weak signals from 5 independent domains (momentum, mean reversion, volatility, microstructure, on-chain/macro) into a single optimally-weighted position estimate, then executes via VWAP limit orders.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Installation](#2-installation)
3. [API Keys & Configuration](#3-api-keys--configuration)
4. [Seed Historical Data](#4-seed-historical-data)
5. [Run the Tests](#5-run-the-tests)
6. [Paper Trading (Safe Mode)](#6-paper-trading-safe-mode)
7. [Live Trading](#7-live-trading)
8. [Backtesting](#8-backtesting)
9. [Monitoring & Alerts](#9-monitoring--alerts)
10. [Project Structure](#10-project-structure)
11. [Troubleshooting](#11-troubleshooting)
12. [Safety & Risk Controls](#12-safety--risk-controls)

---

## 1. Prerequisites

You need three things installed on your computer before starting.

### Install Python 3.11 or newer

**Mac:**
```bash
# Install Homebrew first if you don't have it:
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Then install Python:
brew install python@3.12
```

**Windows:**
1. Go to https://www.python.org/downloads/
2. Download Python 3.12 (or newer)
3. Run the installer
4. **IMPORTANT:** Check the box that says "Add Python to PATH" during installation
5. Click "Install Now"

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install python3.12 python3.12-venv python3-pip
```

### Verify Python is installed

Open a terminal (Mac/Linux) or Command Prompt (Windows) and type:
```bash
python3 --version
```
You should see something like `Python 3.12.x`. If you see an error, Python is not installed correctly — go back and retry the step above.

### Install Git

**Mac:**
```bash
brew install git
```

**Windows:**
1. Go to https://git-scm.com/download/win
2. Download and run the installer (use all default settings)

**Linux:**
```bash
sudo apt install git
```

---

## 2. Installation

### Step 1: Clone the repository

Open your terminal and run:
```bash
git clone https://github.com/RonJon715/Quant-Crypto.git
cd Quant-Crypto
```

### Step 2: Create a virtual environment

A virtual environment keeps this project's packages separate from the rest of your system. This is important — don't skip it.

```bash
# Create the virtual environment
python3 -m venv venv

# Activate it
# On Mac/Linux:
source venv/bin/activate

# On Windows (Command Prompt):
venv\Scripts\activate

# On Windows (PowerShell):
venv\Scripts\Activate.ps1
```

After activation, your terminal prompt will show `(venv)` at the beginning. **You must activate the virtual environment every time you open a new terminal window.**

### Step 3: Install dependencies

```bash
pip install -r requirements.txt
```

This will download and install all required Python packages. It may take 1-2 minutes.

If you see errors about `pip` not being found, try:
```bash
python3 -m pip install -r requirements.txt
```

### Step 4: Verify installation

```bash
python -m pytest tests/ -v
```

You should see `43 passed` at the end. If all tests pass, the installation is correct.

---

## 3. API Keys & Configuration

The bot needs API keys to fetch data and execute trades. **No API keys are stored in code** — they are loaded from environment variables.

### Required keys (free, get these first)

| Key | Where to get it | What it does |
|-----|----------------|--------------|
| `COINBASE_API_KEY` | https://www.coinbase.com/settings/api | Execute trades on Coinbase |
| `COINBASE_API_SECRET` | Same as above | Signs API requests |

### How to create a Coinbase API key

1. Log in to https://www.coinbase.com
2. Go to **Settings** > **API** (or visit https://www.coinbase.com/settings/api)
3. Click **"New API Key"**
4. Select the portfolio you want the bot to trade with
5. Set permissions: **View** + **Trade** (do NOT enable "Transfer")
6. Complete 2FA verification
7. Copy the **API Key** and **API Secret** — you won't be able to see the secret again

### Optional keys (free tiers available)

These give the bot more data sources, which improves signal quality:

| Key | Where to get it | What it does |
|-----|----------------|--------------|
| `FRED_API_KEY` | https://fred.stlouisfed.org/docs/api/api_key.html | US economic data (DXY, M2) |
| `GLASSNODE_API_KEY` | https://studio.glassnode.com/settings/api | On-chain metrics (MVRV) |
| `CRYPTOCOMPARE_API_KEY` | https://min-api.cryptocompare.com/ | Additional price data |
| `WHALE_ALERT_API_KEY` | https://whale-alert.io/signup | Large transaction alerts |

You do **not** need all of these to get started. The bot works with just the Coinbase keys.

### Set your environment variables

**Mac/Linux** — add these lines to `~/.bashrc` or `~/.zshrc`:
```bash
export COINBASE_API_KEY="your-api-key-here"
export COINBASE_API_SECRET="your-api-secret-here"

# Optional:
export FRED_API_KEY="your-fred-key"
export GLASSNODE_API_KEY="your-glassnode-key"
```
Then reload your shell:
```bash
source ~/.bashrc   # or source ~/.zshrc
```

**Windows (Command Prompt):**
```cmd
set COINBASE_API_KEY=your-api-key-here
set COINBASE_API_SECRET=your-api-secret-here
```

**Windows (PowerShell):**
```powershell
$env:COINBASE_API_KEY="your-api-key-here"
$env:COINBASE_API_SECRET="your-api-secret-here"
```

**Alternative: Use a `.env` file** (never commit this to git — it's already in `.gitignore`):
```bash
# Create a file called .env in the project root:
COINBASE_API_KEY=your-api-key-here
COINBASE_API_SECRET=your-api-secret-here
FRED_API_KEY=your-fred-key
```

### Configuration file

The main config is at `config/settings.yaml`. The defaults work out of the box. Key settings you might want to change:

```yaml
exchange:
  sandbox: true          # true = fake money (safe). false = real money.

universe:
  assets: ["BTC-USD", "ETH-USD", "SOL-USD"]   # Which coins to trade

engine:
  cycle_interval_minutes: 15   # How often the bot runs its analysis
```

**Leave `sandbox: true` until you are confident the bot works correctly.**

---

## 4. Seed Historical Data

Before trading, the bot needs historical price data to train its signals. This step downloads 6 months of hourly candle data for free from public exchanges.

### Step 1: Download price data

```bash
python -m scripts.seed_candles --exchange binance --months 6
```

This takes 5-15 minutes depending on your internet speed. You'll see progress logs:
```
Fetched 1000 candles for BTC/USDT, last: 2024-07-15T12:00:00+00:00
Fetched 1000 candles for BTC/USDT, last: 2024-09-03T16:00:00+00:00
...
Inserted 4380 candles for BTC-USD
```

**Options:**
```bash
# Download from a different exchange:
python -m scripts.seed_candles --exchange kraken --months 6

# Download only Bitcoin:
python -m scripts.seed_candles --pairs BTC-USD

# Download 12 months instead of 6:
python -m scripts.seed_candles --months 12
```

### Step 2: Download on-chain data (free, no API key)

```bash
python -m scripts.seed_onchain
```

This downloads BTC hash rate, transaction count, and DeFi TVL data from free public APIs.

### Step 3: Download macro/sentiment data

```bash
# Without FRED key (downloads Fear & Greed Index only):
python -m scripts.seed_macro

# With FRED key (also downloads DXY, M2 money supply, yield curve):
python -m scripts.seed_macro --fred-key YOUR_FRED_KEY
```

---

## 5. Run the Tests

Always run tests after installation and before trading:

```bash
python -m pytest tests/ -v
```

Expected output:
```
tests/test_combination_engine.py ... 10 passed
tests/test_executor.py ............. 4 passed
tests/test_kelly_sizer.py ......... 12 passed
tests/test_providers.py ............ 5 passed
tests/test_signals.py ............. 12 passed

43 passed
```

If any tests fail, something is wrong with your installation. Go back to Step 2 and make sure all dependencies installed correctly.

---

## 6. Paper Trading (Safe Mode)

Paper trading simulates real trading without using real money. **Always start here.**

```bash
python main.py --paper
```

What this does:
- Fetches real market data every 15 minutes
- Runs all signal calculations and the combination engine
- Logs what trades it *would* make, but doesn't actually place orders
- Writes logs to `alpha_bot.log` and `logs/` directory

Let it run for at least a few hours (ideally 1-2 days) and review the logs:
```bash
# Watch the live log:
tail -f alpha_bot.log

# Or run just one cycle to check everything works:
python main.py --paper --cycle-once
```

**What to look for:**
- No error messages in the log
- Signal updates happening each cycle
- Edge estimates being calculated
- Trade signals being generated (even if not executed)

---

## 7. Live Trading

**Only proceed to live trading after:**
- All 43 tests pass
- Paper trading runs without errors for 1-2 days
- You understand the risk controls (Section 12)

### Step 1: Switch to sandbox mode first

Coinbase has a sandbox environment for testing with fake money. The config already defaults to sandbox mode (`sandbox: true` in `config/settings.yaml`).

```bash
python main.py
```

### Step 2: Go live with real money

1. Edit `config/settings.yaml` and change:
   ```yaml
   exchange:
     sandbox: false    # NOW USING REAL MONEY
   ```

2. Start with minimum capital ($500 or less):
   ```bash
   python main.py
   ```

3. Monitor closely for the first 24-48 hours
4. Scale capital only after 30 days of positive performance

### Running in the background (Linux/Mac)

To keep the bot running after you close the terminal:

```bash
# Using nohup:
nohup python main.py > bot_output.log 2>&1 &

# Check if it's running:
ps aux | grep "python main.py"

# Stop it:
kill $(pgrep -f "python main.py")
```

Or use `screen` or `tmux`:
```bash
# Start a screen session:
screen -S trading_bot

# Run the bot:
python main.py

# Detach from screen: press Ctrl+A, then D
# Reattach later:
screen -r trading_bot
```

---

## 8. Backtesting

Test the strategy against historical data before risking real money.

### Run a backtest

```bash
# Backtest from January 2024 to present:
python -m scripts.backtest --start 2024-01-01

# Backtest only Bitcoin:
python -m scripts.backtest --pairs BTC-USD --start 2024-01-01
```

Output shows:
- **Total Return** — overall profit/loss
- **Sharpe Ratio** — risk-adjusted return (higher is better; >1.0 is good)
- **Max Drawdown** — worst peak-to-trough decline
- **Win Rate** — percentage of profitable trades

### Measure signal quality

Check whether individual signals have predictive power:
```bash
python -m scripts.measure_ic
```

Signals with IC > 0 and p-value < 0.05 are statistically significant. Only signals that pass this threshold are included in the combination engine.

---

## 9. Monitoring & Alerts

### Log files

| File/Directory | Contents |
|---------------|----------|
| `alpha_bot.log` | Main application log (all events) |
| `logs/cycles_YYYY-MM-DD.jsonl` | Detailed engine cycle data |
| `logs/trades_YYYY-MM-DD.jsonl` | All trade entries and exits |
| `logs/fills_YYYY-MM-DD.jsonl` | Order fill confirmations |

### Telegram alerts (optional)

Get real-time notifications on your phone:

1. Create a Telegram bot: message `@BotFather` on Telegram, send `/newbot`, follow the prompts
2. Copy the bot token
3. Get your chat ID: message `@userinfobot` on Telegram
4. Set environment variables:
   ```bash
   export TELEGRAM_BOT_TOKEN="your-bot-token"
   export TELEGRAM_CHAT_ID="your-chat-id"
   ```

### Discord alerts (optional)

1. In your Discord server, go to **Server Settings** > **Integrations** > **Webhooks**
2. Click **New Webhook**, copy the URL
3. Set the environment variable:
   ```bash
   export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
   ```

---

## 10. Project Structure

```
Quant-Crypto/
├── main.py                    # Entry point — start here
├── requirements.txt           # Python package dependencies
├── config/
│   ├── settings.yaml          # Bot configuration (API keys loaded from env vars)
│   └── signals.yaml           # Signal-specific parameters
├── core/
│   ├── combination_engine.py  # 11-step alpha combination (the brain)
│   ├── kelly_sizer.py         # Position sizing via Kelly criterion
│   └── portfolio.py           # Portfolio tracking & risk limits
├── signals/                   # Signal modules (5 independent domains)
│   ├── base.py                # Base class all signals inherit from
│   ├── momentum.py            # Price momentum signals
│   ├── mean_reversion.py      # Mean reversion signals
│   ├── volatility.py          # Volatility regime signals
│   ├── microstructure.py      # Orderbook/trade flow signals
│   ├── onchain.py             # Blockchain data signals
│   ├── sentiment.py           # Fear & Greed, social volume
│   └── macro.py               # DXY, M2 money supply signals
├── exchange/
│   ├── auth.py                # Coinbase API authentication
│   ├── rest_client.py         # REST API (place/cancel orders)
│   ├── ws_client.py           # WebSocket (live price/orderbook)
│   └── executor.py            # VWAP execution engine
├── data/
│   ├── schema.py              # Data type definitions
│   ├── candle_store.py        # SQLite price database
│   ├── orderbook_buffer.py    # Live orderbook buffer
│   ├── trade_tape.py          # Trade flow tracker
│   ├── l2_recorder.py         # Orderbook recording daemon
│   └── providers/             # 16 data source connectors
├── monitoring/
│   ├── journal.py             # Trade logging
│   ├── dashboard.py           # Terminal display
│   └── alerts.py              # Telegram/Discord notifications
├── scripts/
│   ├── seed_candles.py        # Download historical price data
│   ├── seed_onchain.py        # Download blockchain data
│   ├── seed_macro.py          # Download economic data
│   ├── backtest.py            # Test strategy on historical data
│   └── measure_ic.py          # Validate signal quality
└── tests/                     # 43 automated tests
```

---

## 11. Troubleshooting

### "ModuleNotFoundError: No module named 'ccxt'"
You forgot to activate the virtual environment. Run:
```bash
source venv/bin/activate   # Mac/Linux
venv\Scripts\activate      # Windows
```

### "pip: command not found"
Use `python3 -m pip` instead of `pip`:
```bash
python3 -m pip install -r requirements.txt
```

### "Permission denied" when running scripts
On Mac/Linux:
```bash
chmod +x main.py
python3 main.py --paper
```

### Tests fail with import errors
Make sure you're running from the project root directory:
```bash
cd Quant-Crypto
python -m pytest tests/ -v
```

### "COINBASE_API_KEY not set" or authentication errors
Check your environment variables are set:
```bash
echo $COINBASE_API_KEY    # Mac/Linux — should print your key
echo %COINBASE_API_KEY%   # Windows CMD
```
If blank, go back to Section 3 and set them again.

### Bot shows "Only X active signals (need 5), skipping cycle"
The bot requires at least 5 active signals to trade. This means some data sources are unavailable. Make sure you:
1. Ran `scripts/seed_candles.py` to download price history
2. Have an internet connection (live data feeds need it)
3. Optional data providers have API keys set if enabled in `config/signals.yaml`

### Seed script shows "Rate limited, sleeping 10s..."
This is normal. Public APIs limit how fast you can download data. The script automatically waits and retries. Be patient — it will complete.

### "aiosqlite" or database errors
Delete the old database and re-seed:
```bash
rm candles.db
python -m scripts.seed_candles --months 6
```

---

## 12. Safety & Risk Controls

The bot has multiple layers of protection that **cannot be overridden by signals**:

| Protection | Limit | What happens |
|-----------|-------|-------------|
| Max single position | 15% of portfolio | Won't put more than 15% into one coin |
| Max total exposure | 80% of portfolio | Always keeps 20% in cash (USDC) |
| 7-day drawdown | -10% from peak | Sells everything, pauses trading |
| 30-day drawdown | -15% from peak | Sells everything, **stops the bot** |
| VPIN spike | > 0.8 | Pauses execution for 1 cycle (informed trading detected) |
| API errors | > 5 in 60 seconds | Pauses all activity for 5 minutes |
| Stale data | Signal > 2 cycles old | Disables signal, recalculates weights |
| Kelly fraction | Never > 0.5x full Kelly | Cuts theoretical bet size in half |

**Key safety practices:**
- The bot **never places market orders** — only limit orders via VWAP
- `sandbox: true` is the default — you must explicitly switch to live
- Start with paper trading (`--paper` flag) before risking any money
- Start live with minimum capital ($500) and scale only after 30 days of profit
- The bot logs every decision to `logs/` — review these regularly

**This is experimental software. Past backtest performance does not guarantee future results. Never trade with money you cannot afford to lose.**
