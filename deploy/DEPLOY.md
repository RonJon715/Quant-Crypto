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
