# Deployment Guide

Tested on Ubuntu 24.04, CentOS 9, Fedora 41, Arch Linux, Alpine 3.20, macOS 15.

## Quick Install (recommended)

The installer auto-detects your OS, installs all dependencies, and sets
everything up interactively:

```bash
git clone https://github.com/ozodbek-bosimov/Music_Downloader_bot.git
cd Music_Downloader_bot
bash install.sh
```

That's it. The script handles:
- System packages (Python 3.12+, PostgreSQL, FFmpeg, git, curl)
- Deno (required by yt-dlp for YouTube JS extraction)
- PostgreSQL database and user creation
- Python virtual environment and dependencies (incl. ytmusicapi + yt-dlp PO-token plugin)
- Interactive `.env` configuration
- Database migrations
- systemd service installation (optional, Linux only)

---

## Manual Install

If you prefer to set things up yourself:

### 1. System packages

**Ubuntu / Debian:**
```bash
sudo apt update && sudo apt install -y python3 python3-pip python3-venv \
  postgresql postgresql-contrib git curl unzip ffmpeg
```

**CentOS / RHEL / Amazon Linux:**
```bash
sudo dnf install -y python3 python3-pip python3-devel \
  postgresql-server postgresql-contrib git curl unzip ffmpeg
sudo postgresql-setup --initdb
sudo systemctl enable --now postgresql
```

**Fedora:**
```bash
sudo dnf install -y python3 python3-pip python3-devel \
  postgresql-server postgresql-contrib git curl unzip ffmpeg
sudo postgresql-setup --initdb
sudo systemctl enable --now postgresql
```

**Arch Linux:**
```bash
sudo pacman -Syu --noconfirm --needed python python-pip \
  postgresql git curl unzip ffmpeg
sudo -u postgres initdb -D /var/lib/postgres/data
sudo systemctl enable --now postgresql
```

**Alpine Linux:**
```bash
sudo apk add python3 py3-pip python3-dev \
  postgresql postgresql-client postgresql-contrib \
  git curl unzip ffmpeg gcc musl-dev libffi-dev
sudo rc-update add postgresql default
sudo rc-service postgresql start
```

**macOS:**
```bash
brew install python@3.12 postgresql@16 git curl ffmpeg
brew services start postgresql@16
```

### 2. Deno

```bash
curl -fsSL https://deno.land/install.sh | sh
# Add to your shell:
echo 'export PATH="$HOME/.deno/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

### 3. PostgreSQL

```bash
# Ubuntu/Debian/Fedora/CentOS/Arch:
sudo -u postgres psql -c "CREATE USER musicbot WITH PASSWORD 'your-password';"
sudo -u postgres psql -c "CREATE DATABASE musicbot OWNER musicbot;"

# macOS:
createuser musicbot
psql postgres -c "ALTER USER musicbot WITH PASSWORD 'your-password';"
createdb -O musicbot musicbot
```

### 4. Application

```bash
cd ~
git clone <your-repo-url> Music_Downloader_bot
cd Music_Downloader_bot
python3 -m venv env
source env/bin/activate
pip install poetry
poetry install --only main
cp .env.example .env
nano .env                  # fill in your values
alembic upgrade head
```

### 5. PO-token provider (recommended — cookieless YouTube)

Datacenter IPs get YouTube's "Sign in to confirm you're not a bot" challenge.
The bot answers it automatically using a small local **PO-token provider** — no
cookies required. It runs as a Docker container:

```bash
# Requires Docker: https://docs.docker.com/engine/install/
docker compose up -d          # starts brainicism/bgutil-ytdlp-pot-provider
docker compose logs -f        # optional: watch it
```

The provider listens on `127.0.0.1:4416` (local only). The bot's yt-dlp plugin
(`bgutil-ytdlp-pot-provider`, installed with the Python deps) finds it there
automatically — no extra config. To run it on another host/port, set
`POT_PROVIDER_BASE_URL` in `.env`.

> Without the provider the bot still works — it falls back to SoundCloud
> (`SOUNDCLOUD_FALLBACK=1`) — but YouTube, the more accurate and higher-quality
> source, may be blocked.

### 6. systemd service (Linux)

```bash
# Edit musicbot.service — set User, WorkingDirectory, and ExecStart paths
nano musicbot.service
sudo cp musicbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now musicbot
```

Check it:
```bash
systemctl status musicbot
journalctl -u musicbot -f
```

> Run **only one** instance — Telegram allows a single poller per bot.

---

## Updating

```bash
cd ~/Music_Downloader_bot
git pull
source env/bin/activate
poetry install
poetry update yt-dlp
alembic upgrade head
docker compose pull && docker compose up -d   # refresh the PO-token provider
sudo systemctl restart musicbot
```

## Notes

- **No inbound ports** required — the bot only makes outbound requests.
- **YouTube blocking:** datacenter IPs get "Sign in to confirm you're not a
  bot". The PO-token provider (step 5) fixes this **without cookies**. As an
  alternative you can still set `YTDLP_COOKIEFILE` to a cookies file.
- **Search & sources:** search uses YouTube Music (accurate song results); the
  exact match downloads from YouTube, with SoundCloud as an automatic fallback
  (`SOUNDCLOUD_FALLBACK`).
- **Logs** go to journald by default (`journalctl -u musicbot`). Set
  `LOG_TO_FILE=1` for rotating file logs under `logs/`.
- **FFmpeg** is installed by default for future use. Set `CONVERT_TO_MP3=1` to
  enable MP3 transcoding.
