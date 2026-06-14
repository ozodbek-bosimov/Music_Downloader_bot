# 🎧 Music Downloader Telegram Bot

A Telegram bot that downloads music from YouTube. Send a song name, a YouTube
link, or a Spotify track link — get the audio back with title, artist, and
cover art.

**Live:** [@OzodbeksMusicBot](https://t.me/OzodbeksMusicBot)

## Features

- Search by name, YouTube links, and Spotify track links (no API key needed)
- Instant repeats — cached `file_id` means the same song never re-downloads
- Audio-only (`.m4a`), no transcoding — light on CPU and disk
- Pre-download size check — rejects oversized tracks before downloading
- Ephemeral storage — files deleted immediately after sending
- Admin tools: `/stats`, `/broadcast`
- Forced-channel subscription gate (optional)
- Every failure returns a clear, specific message to the user

## How it works

```
user message → queue (PostgreSQL) → worker picks it up
  → cache hit?  → instant send (file_id)
  → cache miss? → yt-dlp download → send audio → cache file_id → delete file
```

YouTube links and Spotify tracks are routed through YouTube search (via oEmbed
title), which avoids the aggressive blocking YouTube applies to direct
extraction from datacenter IPs.

## Quick start

```bash
git clone https://github.com/ozodbek-bosimov/Music_Downloader_bot.git
cd Music_Downloader_bot
python3 -m venv env
source install.sh   # installs deps, prompts for tokens, writes .env, runs migrations
python main.py
```

> Only **one** instance at a time — Telegram allows a single poller per bot.

## Requirements

- Python 3.12+
- PostgreSQL
- [Deno](https://deno.land) (yt-dlp uses it for YouTube JS extraction)
- FFmpeg — only if `CONVERT_TO_MP3=1`

## Configuration

All settings via `.env` (see [`.env.example`](.env.example)).

| Variable | Default | Description |
|----------|---------|-------------|
| `BOT_TOKEN` | — | Telegram bot token (required) |
| `POSTGRESQL_DATABASE_*` | — | DB host, name, user, password (required) |
| `ADMIN_IDS` | — | Telegram IDs for admin commands |
| `REQUIRED_CHANNEL` | — | Channel users must join (e.g. `@mychannel`) |
| `MAX_PARALLEL_DOWNLOADS` | `4` | Concurrent downloads |
| `MAX_AUDIO_FILESIZE` | `52428800` | Reject audio above this (50 MB) |
| `CACHE_MAX_ENTRIES` | `5000` | Max cached tracks before LRU eviction |
| `YTDLP_COOKIEFILE` | — | YouTube cookies for anti-bot bypass |
| `LOG_TO_FILE` | `0` | `1` to write rotating logs to `logs/` |
| `CONVERT_TO_MP3` | `0` | `1` to transcode (needs FFmpeg) |

## Project structure

```
main.py                 entry point
musicbot/
  config.py             env-based settings
  cache.py              file_id cache (LRU, DB-backed)
  worker.py             async task queue + disk cleanup
  bot/
    handlers.py         commands & message routing
    admin.py            /stats, /broadcast
    middlewares.py      user creation, channel gate
    sender.py           audio delivery + cleanup
    session.py          retry-on-rate-limit session
  db/
    models.py           User, DownloadQueue, CachedTrack
  downloader/
    client.py           yt-dlp wrapper, Spotify resolver
    models.py           Song dataclass
    exceptions.py       typed error hierarchy
migrations/             Alembic (squashed)
```

## Deployment

Any Linux host with Python 3.12 and PostgreSQL works. A ready-made `systemd`
unit is included (`musicbot.service`).

Step-by-step guide: [docs/deploy.md](docs/deploy.md)

Key points:
- Install [Deno](https://deno.land) — yt-dlp requires it
- Set `YTDLP_COOKIEFILE` if YouTube starts blocking
- Keep yt-dlp updated: `poetry update yt-dlp` (YouTube changes often)
- Logs go to stdout/journald by default

## License

MIT
