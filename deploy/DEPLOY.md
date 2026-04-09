# Deploying the Alpha Bot to a Cloud Server

This guide walks you through renting a cheap server and running the bot 24/7. No prior server experience required.

---

## Cost Summary

| Provider | Plan | Monthly Cost | Specs |
|----------|------|-------------|-------|
| **Hetzner** (recommended) | CX22 | **$4.35/mo** | 2 vCPU, 4GB RAM, 40GB SSD |
| DigitalOcean | Basic Droplet | $6/mo | 1 vCPU, 1GB RAM, 25GB SSD |
| AWS Lightsail | Small | $5/mo | 1 vCPU, 1GB RAM, 40GB SSD |
| Vultr | Cloud Compute | $6/mo | 1 vCPU, 1GB RAM, 25GB SSD |
| Oracle Cloud | Free Tier | **$0/mo** | 1 vCPU, 1GB RAM, 50GB (always free) |

The bot uses very little resources — it wakes up every 15 minutes, does math for a few seconds, then sleeps. The cheapest tier from any provider is more than enough.

**Recommendation:** Hetzner CX22 at $4.35/mo is the best value. Oracle Cloud's free tier works but may have availability issues.

---

## Part 1: Rent a Server

Pick one provider below and follow the steps. You only need one.

### Option A: Hetzner (Best Value — $4.35/month)

1. Go to https://www.hetzner.com/cloud
2. Click **"Sign Up"** and create an account (email + payment method)
3. After login, click **"Add Server"**
4. Choose these settings:
   - **Location:** Nearest to you (any works)
   - **Image:** Ubuntu 22.04
   - **Type:** Shared vCPU → **CX22** ($4.35/mo)
   - **Networking:** Leave defaults (public IPv4 is included)
   - **SSH Keys:** See "Create an SSH Key" section below
5. Click **"Create & Buy Now"**
6. Note the **IP address** shown on your server's dashboard

### Option B: DigitalOcean ($6/month)

1. Go to https://www.digitalocean.com
2. Sign up (you may get $200 free credits for 60 days)
3. Click **"Create"** → **"Droplets"**
4. Choose:
   - **Image:** Ubuntu 22.04
   - **Plan:** Basic → Regular → **$6/mo** (1GB / 1 CPU)
   - **Region:** Nearest to you
   - **Authentication:** SSH Key (see below)
5. Click **"Create Droplet"**
6. Note the **IP address**

### Option C: Oracle Cloud (Free Forever)

1. Go to https://cloud.oracle.com and create an account
2. Navigate to **Compute** → **Instances** → **Create Instance**
3. Choose:
   - **Image:** Ubuntu 22.04
   - **Shape:** VM.Standard.E2.1.Micro (Always Free)
   - **Add SSH Key** (see below)
4. Click **"Create"**
5. Note the **Public IP**

---

## Part 2: Create an SSH Key (How You'll Log In)

SSH keys let you securely connect to your server without a password.

### If you've never made one before:

**Mac/Linux** — open Terminal:
```bash
ssh-keygen -t ed25519 -C "your-email@example.com"
```
Press Enter for all prompts (default file location, no passphrase is fine for now).

Then copy the public key:
```bash
cat ~/.ssh/id_ed25519.pub
```
Copy the entire output — you'll paste it when creating the server.

**Windows** — open PowerShell:
```powershell
ssh-keygen -t ed25519 -C "your-email@example.com"
```
Then:
```powershell
cat $env:USERPROFILE\.ssh\id_ed25519.pub
```

---

## Part 3: Connect to Your Server

Once your server is created and you have its IP address:

**Mac/Linux:**
```bash
ssh root@YOUR_SERVER_IP
```

**Windows (PowerShell):**
```powershell
ssh root@YOUR_SERVER_IP
```

Type `yes` if asked about fingerprint verification.

You should now see a prompt like:
```
root@ubuntu-server:~#
```

**You are now on your server.** Every command from here runs on the server, not your local computer.

---

## Part 4: Install the Bot (One Command)

Run these commands on your server:

```bash
# Download the setup script
git clone --branch claude/crypto-trading-bot-f2BeU https://github.com/RonJon715/Quant-Crypto.git /opt/alpha-bot

# Make it executable and run it
chmod +x /opt/alpha-bot/deploy/setup_server.sh
/opt/alpha-bot/deploy/setup_server.sh
```

This takes 2-3 minutes and:
- Installs Python 3.12, Git, SQLite
- Creates a dedicated `botuser` (security best practice)
- Clones the code to `/opt/alpha-bot`
- Creates a virtual environment and installs all dependencies
- Installs a systemd service (auto-start on boot, auto-restart on crash)
- Creates a `.env` file for your API keys

---

## Part 5: Configure Your API Keys

```bash
sudo nano /opt/alpha-bot/.env
```

Fill in your keys (at minimum, the Coinbase ones):
```
COINBASE_API_KEY=your-key-here
COINBASE_API_SECRET=your-secret-here
```

Save and exit: press **Ctrl+X**, then **Y**, then **Enter**.

The `.env` file has restricted permissions (only `botuser` can read it).

---

## Part 6: Seed Historical Data

Before the bot can trade, it needs historical price data:

```bash
cd /opt/alpha-bot

# Download 6 months of hourly candles (takes 5-15 min)
sudo -u botuser ./venv/bin/python -m scripts.seed_candles --months 6

# Download free on-chain data
sudo -u botuser ./venv/bin/python -m scripts.seed_onchain

# Download free macro/sentiment data
sudo -u botuser ./venv/bin/python -m scripts.seed_macro
```

---

## Part 7: Run Tests

```bash
cd /opt/alpha-bot
sudo -u botuser ./venv/bin/python -m pytest tests/ -v
```

All 43 tests should pass. If not, something went wrong — check the error messages.

---

## Part 8: Start the Bot

### Paper trading (recommended first)

The service defaults to paper trading mode (`--paper`):

```bash
sudo systemctl start alpha-bot
```

### Check it's running

```bash
sudo systemctl status alpha-bot
```

You should see:
```
● alpha-bot.service - Alpha Combination Crypto Trading Bot
     Loaded: loaded (/etc/systemd/system/alpha-bot.service; enabled)
     Active: active (running)
```

### View live logs

```bash
# Follow logs in real time (Ctrl+C to stop watching):
sudo journalctl -u alpha-bot -f

# View last 100 lines:
sudo journalctl -u alpha-bot -n 100

# View today's logs only:
sudo journalctl -u alpha-bot --since today
```

### Stop the bot

```bash
sudo systemctl stop alpha-bot
```

### Restart the bot

```bash
sudo systemctl restart alpha-bot
```

---

## Part 9: Switch to Live Trading

**Only after paper trading looks good for 1-2 days:**

### Step 1: Edit the service to remove `--paper`

```bash
sudo nano /etc/systemd/system/alpha-bot.service
```

Find this line:
```
ExecStart=/opt/alpha-bot/venv/bin/python main.py --paper
```

Change it to:
```
ExecStart=/opt/alpha-bot/venv/bin/python main.py
```

### Step 2: Make sure sandbox mode is on first

```bash
sudo -u botuser nano /opt/alpha-bot/config/settings.yaml
```

Verify `sandbox: true` is set. This uses Coinbase's test environment with fake money.

### Step 3: Apply changes and restart

```bash
sudo systemctl daemon-reload
sudo systemctl restart alpha-bot
```

### Step 4: When ready for real money

Edit `config/settings.yaml` and change `sandbox: false`, then restart:
```bash
sudo systemctl restart alpha-bot
```

---

## Part 10: Updating the Bot

When new code is available:

```bash
chmod +x /opt/alpha-bot/deploy/update.sh
sudo /opt/alpha-bot/deploy/update.sh
```

This pulls the latest code, updates dependencies, runs tests, and restarts the bot.

---

## Part 11: Server Maintenance

### Keep your server secure

Ubuntu auto-installs security updates (set up during installation). You can also manually update:
```bash
sudo apt update && sudo apt upgrade -y
```

### Monitor disk space

```bash
df -h
```

The bot uses very little disk (~100MB for 6 months of data). You won't run out of space.

### Monitor memory

```bash
htop
```

Press `q` to exit. The bot typically uses <200MB of RAM.

### Reboot the server

The bot auto-starts after reboot:
```bash
sudo reboot
```

### Check bot uptime

```bash
sudo systemctl status alpha-bot | grep Active
```

---

## Part 12: Quick Reference

| Task | Command |
|------|---------|
| Start bot | `sudo systemctl start alpha-bot` |
| Stop bot | `sudo systemctl stop alpha-bot` |
| Restart bot | `sudo systemctl restart alpha-bot` |
| Check status | `sudo systemctl status alpha-bot` |
| View live logs | `sudo journalctl -u alpha-bot -f` |
| View recent logs | `sudo journalctl -u alpha-bot -n 100` |
| Edit API keys | `sudo nano /opt/alpha-bot/.env` |
| Edit config | `sudo -u botuser nano /opt/alpha-bot/config/settings.yaml` |
| Run tests | `cd /opt/alpha-bot && sudo -u botuser ./venv/bin/python -m pytest tests/ -v` |
| Update bot | `sudo /opt/alpha-bot/deploy/update.sh` |
| SSH into server | `ssh root@YOUR_SERVER_IP` |

---

## Troubleshooting

### "Connection refused" when SSHing

Your server might still be booting. Wait 1-2 minutes and try again. If it persists, check your cloud provider's console to make sure the server is running.

### "Permission denied (publickey)"

Your SSH key isn't recognized. Make sure:
1. You added your public key when creating the server
2. You're using the right key: `ssh -i ~/.ssh/id_ed25519 root@YOUR_SERVER_IP`

### Bot keeps restarting (check with `systemctl status`)

Look at the logs for the error:
```bash
sudo journalctl -u alpha-bot -n 50
```

Common causes:
- Missing API keys in `.env`
- No historical data (forgot to run seed scripts)
- Python dependency issue (re-run: `sudo -u botuser /opt/alpha-bot/venv/bin/pip install -r /opt/alpha-bot/requirements.txt`)

### "No space left on device"

```bash
# Check what's using space:
du -sh /opt/alpha-bot/*

# Clear old logs if needed:
sudo journalctl --vacuum-size=100M
```

### Server ran out of memory (killed by OOM)

This shouldn't happen on a 1GB+ server. If it does:
- Upgrade to the next tier (2GB RAM)
- Or reduce `monte_carlo_paths` in `config/settings.yaml` from 10000 to 1000

### I can't connect — forgot my server IP

Log in to your cloud provider's web dashboard. The IP is shown on your server/droplet/instance page.

---

## Part 13: Running Multiple Different Bots on One Server

You can run completely different trading bots (different codebases, different strategies, different exchanges) on the same cheap server. Each bot gets its own isolated environment.

### How it works

```
Your $4-6/mo Server
├── /opt/alpha-bot/          ← This bot (alpha combination engine)
│   ├── venv/                   Own Python packages
│   ├── .env                    Own API keys
│   └── candles.db              Own database
│
├── /opt/dca-bot/            ← A DCA bot (completely different code)
│   ├── venv/
│   ├── .env
│   └── ...
│
├── /opt/grid-bot/           ← A grid trading bot
│   ├── venv/
│   ├── .env
│   └── ...
│
└── /opt/arb-bot/            ← An arbitrage bot
    ├── venv/
    ├── .env
    └── ...
```

Each bot:
- Has its own directory under `/opt/`
- Has its own Python virtual environment (no package conflicts)
- Has its own `.env` file for API keys (different exchange accounts)
- Has its own systemd service (independent start/stop/restart)
- Has its own log stream (view with `journalctl`)
- Auto-starts on server reboot
- Auto-restarts if it crashes

### Add a new bot (one command)

The `add_bot.sh` script works with any Python bot from any git repository:

```bash
sudo /opt/alpha-bot/deploy/add_bot.sh <name> <git-repo-url> [branch] [start-command]
```

### Example: Add a DCA bot

```bash
sudo /opt/alpha-bot/deploy/add_bot.sh dca-bot https://github.com/youruser/dca-bot.git
```

This will:
1. Clone the repo to `/opt/dca-bot/`
2. Create a virtual environment and install dependencies
3. Create a `.env` file for API keys
4. Create and enable a systemd service

Then configure and start it:
```bash
# Add API keys
sudo nano /opt/dca-bot/.env

# Start it
sudo systemctl start dca-bot

# Check it's running
sudo systemctl status dca-bot

# View logs
sudo journalctl -u dca-bot -f
```

### Example: Add a grid trading bot with a custom start command

```bash
sudo /opt/alpha-bot/deploy/add_bot.sh grid-bot https://github.com/youruser/grid-bot.git main "python run.py --config prod.yaml"
```

### Example: Add a bot from a private repo

```bash
# Use an SSH URL for private repos (requires SSH key on server)
sudo /opt/alpha-bot/deploy/add_bot.sh my-private-bot git@github.com:youruser/private-bot.git
```

To set up SSH keys on your server for private repos:
```bash
# Generate a deploy key
sudo -u botuser ssh-keygen -t ed25519 -f /home/botuser/.ssh/id_ed25519 -N ""

# Show the public key — add this as a deploy key in your GitHub repo settings
sudo cat /home/botuser/.ssh/id_ed25519.pub
```

### See all bots running on your server

```bash
sudo /opt/alpha-bot/deploy/list_all_bots.sh
```

Output:
```
============================================
  All Trading Bots on This Server
============================================

BOT                  STATUS     MEMORY     DIRECTORY
---                  ------     ------     ---------
alpha-bot            active     180MB      /opt/alpha-bot/
dca-bot              active     45MB       /opt/dca-bot/
grid-bot             active     92MB       /opt/grid-bot/
arb-bot              inactive   --         /opt/arb-bot/

System Resources:
  Memory:   420MB used / 3600MB available
  Disk:     2.1G used / 37G available
  Load:     0.02, 0.01, 0.00
```

### Managing individual bots

Every bot follows the same pattern:

| Task | Command |
|------|---------|
| Start | `sudo systemctl start <bot-name>` |
| Stop | `sudo systemctl stop <bot-name>` |
| Restart | `sudo systemctl restart <bot-name>` |
| Status | `sudo systemctl status <bot-name>` |
| Logs (live) | `sudo journalctl -u <bot-name> -f` |
| Logs (recent) | `sudo journalctl -u <bot-name> -n 100` |
| Edit secrets | `sudo nano /opt/<bot-name>/.env` |
| Update code | `cd /opt/<bot-name> && sudo -u botuser git pull && sudo systemctl restart <bot-name>` |
| Disable on boot | `sudo systemctl disable <bot-name>` |

### Remove a bot completely

```bash
# Stop and disable the service
sudo systemctl stop <bot-name>
sudo systemctl disable <bot-name>

# Remove the service file
sudo rm /etc/systemd/system/<bot-name>.service
sudo systemctl daemon-reload

# Remove the bot directory
sudo rm -rf /opt/<bot-name>
```

### How many bots can one server handle?

| Server Tier | RAM | Approx. Bots |
|-------------|-----|---------------|
| $4-6/mo (1-2GB) | 1-2 GB | 3-5 lightweight bots |
| $8-12/mo (4GB) | 4 GB | 8-15 bots |
| $20/mo (8GB) | 8 GB | 20+ bots |

Most Python trading bots use 50-200MB of RAM. The alpha combination bot in this repo is on the heavier end (~180MB) because of numpy/pandas/sklearn. Simpler bots (DCA, grid) typically use 30-80MB.

**CPU is almost never the bottleneck.** Trading bots spend 99% of their time sleeping between cycles. Even a single-core VPS can handle many bots.

### Tips for running multiple bots

1. **Use different Coinbase API keys per bot.** Each key can be scoped to a specific portfolio. This prevents bots from interfering with each other's positions.

2. **Stagger cycle times.** If two bots both run every 15 minutes, offset them so they don't hit APIs simultaneously:
   - Bot A: cycles at :00, :15, :30, :45
   - Bot B: cycles at :05, :20, :35, :50

3. **Monitor total memory.** Run `htop` or `free -m` occasionally. If memory gets tight, upgrade the server — it's cheaper than debugging OOM kills.

4. **Use Telegram/Discord alerts for all bots.** You can use the same Telegram bot token but different chat groups, or separate Discord webhook channels.

5. **Back up your `.env` files.** They contain your API keys. If you need to rebuild the server, you'll need them:
   ```bash
   sudo tar czf ~/bot-env-backup.tar.gz /opt/*/.env
   ```
