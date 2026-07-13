# 🎧 Music Downloader Telegram Bot

A Telegram bot that finds and downloads music. Send a song name, a YouTube
link, or a Spotify track link — get the audio back with title, artist, and
cover art. Search runs on YouTube Music for accurate results; audio downloads
straight from YouTube (cookieless, via a local PO-token provider) with
SoundCloud as an automatic fallback.

**Live:** [@OzodbeksMusicBot](https://t.me/OzodbeksMusicBot)

## Features

- Accurate search via YouTube Music (no API key needed)
- Search by name, YouTube links, and Spotify track links
- Interactive search results with pagination (5 per page, up to 20 results)
- Cookieless YouTube downloads via a local PO-token provider; SoundCloud fallback
- Instant repeats — cached `file_id` means the same song never re-downloads
- Faststart remux + verified duration, so seeking/scrubbing works in Telegram
- Cover art and accurate title / artist / duration metadata
- DRM / unavailable tracks detected and reported gracefully
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

Search runs on YouTube Music (accurate song metadata). The chosen track is
downloaded straight from YouTube by its video id — a local PO-token provider
answers YouTube's "not a bot" check, so no cookies are needed. If YouTube fails,
the bot automatically falls back to SoundCloud for the same track.

## Quick start

```bash
git clone https://github.com/ozodbek-bosimov/Music_Downloader_bot.git
cd Music_Downloader_bot
bash install.sh    # auto-detects OS, installs everything, prompts for config
```

The installer supports **Ubuntu/Debian, CentOS/RHEL/Fedora, Arch, Alpine, and macOS**.

> Only **one** instance at a time — Telegram allows a single poller per bot.

## Requirements

- Python 3.12+
- PostgreSQL
- [Deno](https://deno.land) (yt-dlp uses it for YouTube JS extraction)
- Docker — runs the PO-token provider for cookieless YouTube (recommended)
- FFmpeg — faststart remux / duration probe (recommended) and MP3 (`CONVERT_TO_MP3=1`)

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
| `MUSIC_SEARCH_LIMIT` | `20` | Search results shown in the pick-a-track menu |
| `SOUNDCLOUD_FALLBACK` | `1` | Fall back to SoundCloud if YouTube fails |
| `POT_PROVIDER_BASE_URL` | — | bgutil PO-token provider URL (empty = local default) |
| `REMUX_FOR_SEEK` | `1` | Faststart remux + duration fix (needs FFmpeg) |
| `YTDLP_COOKIEFILE` | — | YouTube cookies (usually unneeded with the POT provider) |
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
    client.py           YouTube Music search, yt-dlp download, Spotify resolver
    models.py           Song dataclass
    exceptions.py       typed error hierarchy
migrations/             Alembic (squashed)
```

## Deployment

Any Linux host (or macOS) with Python 3.12 and PostgreSQL works.
`bash install.sh` handles everything automatically.

Step-by-step guide: [docs/deploy.md](docs/deploy.md)

Key points:
- Install [Deno](https://deno.land) — yt-dlp requires it (installer does this)
- Run the PO-token provider for cookieless YouTube: `docker compose up -d`
- Keep yt-dlp updated: `poetry update yt-dlp`
- Logs go to stdout/journald by default

## License

MIT
