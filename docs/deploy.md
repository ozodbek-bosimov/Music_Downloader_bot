# Deploying on Ubuntu 24.04 (ARM64)

Tested on Oracle Cloud **Always Free** VM.Standard.A1.Flex (4 OCPU, 24 GB RAM).

## 1. System packages

```bash
sudo apt update && sudo apt install -y postgresql postgresql-contrib git python3-pip python3-venv
```

## 2. PostgreSQL

```bash
sudo -u postgres psql -c "CREATE USER musicbot WITH PASSWORD 'your-password';"
sudo -u postgres psql -c "CREATE DATABASE musicbot OWNER musicbot;"
```

## 3. Get the code

```bash
cd ~
git clone <your-repo-url> Music_Downloader_bot
cd Music_Downloader_bot
python3 -m venv env
source env/bin/activate
pip install poetry
poetry install --only main
```

## 4. Configure

```bash
cp .env.example .env
nano .env
```

Fill in `BOT_TOKEN`, database credentials (`localhost`, `musicbot`, `musicbot`,
your password), `ADMIN_IDS`, and optionally `REQUIRED_CHANNEL`.

## 5. Run migrations

```bash
env/bin/alembic upgrade head
```

## 6. systemd service

```bash
sudo cp musicbot.service /etc/systemd/system/musicbot.service
sudo systemctl daemon-reload
sudo systemctl enable --now musicbot
```

Check it:

```bash
systemctl status musicbot
journalctl -u musicbot -f
```

> Run **only one** instance of the bot — Telegram allows a single poller, so a
> second one causes `TelegramConflictError`.

## 7. Updating

```bash
cd ~/Music_Downloader_bot
git pull
source env/bin/activate
poetry install
poetry update yt-dlp
alembic upgrade head
sudo systemctl restart musicbot
```

## Notes

- **No inbound ports** required — the bot only makes outbound requests.
- **YouTube blocking:** datacenter IPs sometimes get "Sign in to confirm you're
  not a bot". Set `YTDLP_COOKIEFILE` to a Netscape-format cookies file if
  downloads start failing.
- **Logs** go to journald by default (`journalctl -u musicbot`). Set
  `LOG_TO_FILE=1` to also write rotating files under `logs/`.
