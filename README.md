# 🎧 Music Downloader Telegram Bot

A lightweight Telegram bot that downloads music from YouTube. Send it a **song
name**, a **YouTube link**, or a single **Spotify track link** and it replies
with the audio — complete with title, artist and cover art.

Lightweight enough for a small VPS or free-tier VM (1+ GB RAM, 1+ CPU).

## Features

- **Search by name**, **YouTube links**, and **Spotify track links** (resolved
  via public metadata — no Spotify API key needed).
- **Instant repeats.** Every sent track's Telegram `file_id` is cached, so the
  same request is served instantly and never re-hits YouTube. Only the id
  string is stored — no audio is kept.
- **Audio-only, no transcoding** (`.m4a`) — light on CPU and disk.
- **Pre-download size check** — oversized tracks are rejected from metadata
  before any bytes are downloaded.
- **Ephemeral storage** — files are deleted right after sending.
- **Admin tools** (optional): `/stats` and `/broadcast`.
- **Required-channel gate** (optional): force users to join your channel first.
- **Resilient** — background loops never crash, and every failure replies with
  a clear, specific message.

## How it works

```
message → handlers.py → queued in Postgres → worker.py picks it up
        → cache hit?  → send instantly (file_id)
        → cache miss? → downloader (yt-dlp) → send audio → cache the file_id
```

YouTube links and Spotify tracks are resolved through YouTube **search** (using
the link's title), which YouTube blocks far less than direct extraction.

## Project layout

```
main.py                     entry point  (python main.py)
musicbot/
    config.py               settings loaded from environment / .env
    cache.py                Telegram file_id cache (skip re-downloading)
    worker.py               background queue + cleanup
    bot/
        handlers.py         /start, /help, search, subscription callback
        admin.py            /stats, /broadcast
        middlewares.py      user creation, channel gate
        sender.py           sends the audio, then deletes it locally
        session.py          retry-on-rate-limit HTTP session
    db/
        __init__.py         engine + session factory
        models.py           User, DownloadQueue, CachedTrack
    downloader/
        client.py           Downloader: resolve a query and download audio
        models.py           lightweight Song
        exceptions.py
migrations/                 Alembic migrations
docs/                       privacy policy
```

## Requirements

- Python 3.12+
- PostgreSQL
- FFmpeg only if you set `CONVERT_TO_MP3=1` (off by default)

## Quick start

```bash
git clone <your-repo-url>
cd Music_Downloader_bot
python -m venv env
source install.sh          # installs deps, asks for tokens, writes .env, migrates
```

Run it (only **one** instance at a time — Telegram allows a single poller):

```bash
source env/bin/activate
python main.py
```

## Configuration

Set via environment / `.env` (see [`.env.example`](.env.example)).

**Required:** `BOT_TOKEN`, `POSTGRESQL_DATABASE_HOST`, `POSTGRESQL_DATABASE_NAME`,
`POSTGRESQL_DATABASE_USER`, `POSTGRESQL_DATABASE_PASSWORD`.

**Optional** (defaults shown):

| Variable | Default | Description |
| --- | --- | --- |
| `ADMIN_IDS` | — | Comma-separated Telegram IDs allowed to use admin commands |
| `REQUIRED_CHANNEL` | — | Channel users must join first (e.g. `@mychannel`) |
| `MAX_PARALLEL_DOWNLOADS` | `4` | Concurrent downloads |
| `MAX_AUDIO_FILESIZE` | `52428800` | Skip audio bigger than this (50 MB Telegram limit) |
| `MAX_TRACK_STORAGE_SIZE` | `2147483648` | On-disk cache cap (2 GB) |
| `CACHE_MAX_ENTRIES` | `5000` | Max cached tracks before oldest are dropped |
| `LOG_TO_FILE` | `0` | `1` to also write rotating logs in `logs/` |
| `CONVERT_TO_MP3` | `0` | `1` to transcode to MP3 (needs FFmpeg) |
| `FFMPEG_LOCATION` | — | FFmpeg path (only if converting) |
| `YTDLP_PLAYER_CLIENTS` | — | Override yt-dlp YouTube clients (comma-separated) |
| `YTDLP_COOKIEFILE` | — | YouTube cookies file (see below) |

## Commands

Public:

- `/start` — welcome and usage
- `/help` — how to use the bot

Admin (only for IDs in `ADMIN_IDS`):

- `/stats` — user, cache and queue counts
- `/broadcast <text>` — send a message to all users (or reply to a message with `/broadcast`)

## YouTube blocking

YouTube may reply "Sign in to confirm you're not a bot" from datacenter IPs.
The bot reduces this with caching and search-routing, and tells the user to
retry when it happens. For reliable downloads, point `YTDLP_COOKIEFILE` at a
Netscape-format cookies file exported from a (throwaway) logged-in account, and
keep yt-dlp updated (`poetry update yt-dlp`).

## Deployment

Any host that can run a long-lived Python process plus PostgreSQL works
(a VPS, a small cloud instance, or a free tier with ~1 GB RAM).

1. **Database** — create a PostgreSQL database and put its credentials in
   `.env`.
2. **Install & migrate** — `poetry install` then `alembic upgrade head`
   (`install.sh` does both).
3. **Run under a supervisor** — start `python main.py` with something that
   restarts it on failure. A ready-made `systemd` unit ships in the repo
   (`musicbot.service`). Run **only one** instance — Telegram allows a single
   poller per bot, so a second one causes `TelegramConflictError`.

Step-by-step VPS walkthrough (with systemd): see [docs/deploy.md](docs/deploy.md).

Tips for reliability:

- **YouTube blocking:** on datacenter IPs, set `YTDLP_COOKIEFILE` (see above).
- **Keep yt-dlp fresh:** `poetry update yt-dlp` periodically, then restart.
- **Logs:** go to stdout by default (your host/journal captures them). Set
  `LOG_TO_FILE=1` to also keep rotating files in `logs/`.
- **Memory:** the bot tunes glibc malloc (`MALLOC_ARENA_MAX`) and the thread
  pool automatically at startup to keep RSS low — no setup needed.

## License

MIT — see [LICENSE](LICENSE).
