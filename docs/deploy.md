# Deploying on a Linux VPS

This guide sets the bot up as a `systemd` service on a small Linux VPS
(tested on an Oracle Cloud **Always Free** VM: 1 OCPU, 1 GB RAM). Commands use
`dnf` (Oracle Linux / RHEL); on Ubuntu/Debian use `apt` equivalents.

## 1. System packages

```bash
sudo dnf install -y python3.12 git postgresql-server postgresql-contrib
# FFmpeg is only needed if you set CONVERT_TO_MP3=1.
```

## 2. Swap (important on a small-RAM host)

The bot peaks around ~250 MB, but YouTube extraction is bursty. On a 1 GB VM a
little swap turns a rare memory spike into a brief slowdown instead of an OOM
kill — a cheap, worthwhile reliability win.

```bash
# Create a 1 GB swap file (skip if the VM already has swap — check `free -h`).
sudo fallocate -l 1G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## 3. PostgreSQL

```bash
sudo postgresql-setup --initdb
sudo systemctl enable --now postgresql

sudo -u postgres psql <<'SQL'
CREATE USER musicbot WITH PASSWORD 'choose-a-password';
CREATE DATABASE musicbot OWNER musicbot;
SQL
```

## 4. Get the code

```bash
git clone <your-repo-url> ~/Music_Downloader_bot
cd ~/Music_Downloader_bot
python3.12 -m venv env
source install.sh        # installs deps, asks for tokens, writes .env, migrates
```

When prompted, use the database details from step 2
(host `localhost`, name `musicbot`, user `musicbot`, your password).

Optionally edit `.env` to add `ADMIN_IDS`, `REQUIRED_CHANNEL`, or
`YTDLP_COOKIEFILE`. The defaults (one download at a time) are tuned for a
small host and keep memory flat for long, unattended uptimes; only raise
`MAX_PARALLEL_DOWNLOADS` if you have plenty of spare RAM.

## 5. systemd service

A ready-made unit is in the repo (`musicbot.service`). Edit the `User` and
paths inside it if needed, then install it:

```bash
sudo cp musicbot.service /etc/systemd/system/musicbot.service
sudo systemctl daemon-reload
sudo systemctl enable --now musicbot
```

Check it:

```bash
systemctl status musicbot
journalctl -u musicbot -f      # live logs
```

> Run **only one** instance of the bot — Telegram allows a single poller, so a
> second one causes `TelegramConflictError`.

## 6. Updating

```bash
cd ~/Music_Downloader_bot
git pull
source env/bin/activate
poetry install                 # if dependencies changed
poetry update yt-dlp           # keep yt-dlp fresh (YouTube changes often)
alembic upgrade head           # if there are new migrations
sudo systemctl restart musicbot
```

## Notes

- **No inbound ports** are required — the bot only makes outbound requests.
- **YouTube blocking:** datacenter IPs sometimes get "Sign in to confirm you're
  not a bot". Set `YTDLP_COOKIEFILE` to a cookies file from a throwaway account
  if downloads start failing.
- **Logs** go to the journal by default. Set `LOG_TO_FILE=1` to also write
  rotating files under `logs/`.
