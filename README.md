# Music Downloader Telegram Bot

A lightweight Telegram bot that downloads music from YouTube. Send it a **song
name**, a **YouTube link**, or a single **Spotify track link** and it replies
with the audio file.

Built to run on tiny hosts (tested on a 256 MB RAM / 0.25 CPU / 1 GB disk plan).

> For educational use only. It downloads publicly available YouTube content. The
> author isn't responsible for how it's used.

## Features

- Search by name, YouTube links, and Spotify **track** links (via metadata, no
  Spotify API needed).
- **Caching** — each track's Telegram `file_id` is stored, so repeat requests
  are instant and never re-hit YouTube. Only the id string is kept, no audio.
- Audio-only downloads (`.m4a`), no transcoding — light on CPU and disk.
- Ephemeral storage — files are deleted right after sending.
- Clear, specific replies on every failure; background loops never crash.

## How it works

```
message → handlers.py → queued in Postgres → worker.py picks it up
        → cache hit?  → send instantly
        → cache miss? → downloader (yt-dlp) → send audio → cache the file_id
```

`YouTube link` and `Spotify track` are resolved through YouTube **search**
(via the link's title), which YouTube blocks far less than direct extraction.

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

Run it (only one instance at a time):

```bash
source env/bin/activate
python main.py
```

## Configuration

Set via environment / `.env`.

**Required**

| Variable | Description |
| --- | --- |
| `BOT_TOKEN` | Telegram bot token from @BotFather |
| `POSTGRESQL_DATABASE_HOST` | Database host |
| `POSTGRESQL_DATABASE_NAME` | Database name |
| `POSTGRESQL_DATABASE_USER` | Database user |
| `POSTGRESQL_DATABASE_PASSWORD` | Database password |

**Optional** (defaults shown)

| Variable | Default | Description |
| --- | --- | --- |
| `MAX_PARALLEL_DOWNLOADS` | `1` | Concurrent downloads |
| `MAX_AUDIO_FILESIZE` | `52428800` | Skip files bigger than this (Telegram's 50 MB limit) |
| `MAX_TRACK_STORAGE_SIZE` | `209715200` | Disk cleanup cap (200 MB) |
| `CACHE_MAX_ENTRIES` | `5000` | Max cached tracks before oldest are dropped |
| `LOG_TO_FILE` | `0` | `1` to also write rotating logs in `logs/` |
| `CONVERT_TO_MP3` | `0` | `1` to transcode to MP3 (needs FFmpeg) |
| `FFMPEG_LOCATION` | — | FFmpeg path (only if converting) |
| `YTDLP_PLAYER_CLIENTS` | — | Override yt-dlp YouTube clients (comma-separated) |
| `YTDLP_COOKIEFILE` | — | YouTube cookies file (see below) |

## YouTube blocking

YouTube may reply "Sign in to confirm you're not a bot" from datacenter IPs.
The bot reduces this with caching and search-routing, and tells the user to
retry when it happens. For reliable downloads, point `YTDLP_COOKIEFILE` at a
Netscape-format cookies file exported from a (throwaway) logged-in account, and
keep yt-dlp updated (`poetry update yt-dlp`).

## Deployment

Any host that can run a long-lived Python process plus PostgreSQL works:

1. Create a PostgreSQL database and put its credentials in `.env`.
2. Install deps and migrate: `poetry install` then `alembic upgrade head`
   (`install.sh` does both).
3. Run `python main.py` under a process supervisor so it restarts on failure.
   Run **only one** instance (Telegram allows a single poller per bot).

Free-tier walkthrough: see [docs/alwaysdata.md](docs/alwaysdata.md).

## License

MIT — see [LICENSE](LICENSE).
