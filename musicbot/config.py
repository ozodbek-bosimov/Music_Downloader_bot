from __future__ import annotations

from dotenv import load_dotenv

from pathlib import Path
from typing import Any, Final
import logging.config
import os

load_dotenv()


BASE_DIR: Final[Path] = Path(__file__).resolve().parent.parent

BOT_TOKEN: Final[str] = os.environ['BOT_TOKEN']

# Channel users must be subscribed to before they can use the bot (e.g.
# '@mychannel'). Leave empty to disable the requirement. The bot must be an
# admin of the channel for the membership check to work.
REQUIRED_CHANNEL: Final[str] = os.getenv('REQUIRED_CHANNEL', '@ozodbekswe')

# Telegram user IDs that have access to admin commands (/stats, /broadcast).
# Comma-separated in the environment variable.
ADMIN_IDS: Final[list[int]] = [
    int(uid.strip()) for uid in os.getenv('ADMIN_IDS', '').split(',') if uid.strip()
]


POSTGRESQL_DATABASE_HOST: Final[str] = os.environ['POSTGRESQL_DATABASE_HOST']
POSTGRESQL_DATABASE_NAME: Final[str] = os.environ['POSTGRESQL_DATABASE_NAME']
POSTGRESQL_DATABASE_USER: Final[str] = os.environ['POSTGRESQL_DATABASE_USER']
POSTGRESQL_DATABASE_PASSWORD: Final[str] = os.environ['POSTGRESQL_DATABASE_PASSWORD']

DATABASE_URL: Final[str] = (
    f'postgresql+psycopg://{POSTGRESQL_DATABASE_USER}:{POSTGRESQL_DATABASE_PASSWORD}'
    f'@{POSTGRESQL_DATABASE_HOST}/{POSTGRESQL_DATABASE_NAME}'
)

# --- Download tuning -------------------------------------------------------
# Defaults are tuned for a dedicated VPS (4 OCPU, 24 GB RAM). Adjust via
# environment variables if you deploy on a smaller machine.

# How many downloads may run at the same time.
MAX_PARALLEL_DOWNLOADS: Final[int] = int(os.getenv('MAX_PARALLEL_DOWNLOADS', '4'))

# Maximum on-disk cache for finished tracks. Tracks are deleted after being
# sent, so this only matters for leftovers from failed sends.
MAX_TRACK_STORAGE_SIZE: Final[int] = int(
    os.getenv('MAX_TRACK_STORAGE_SIZE', '2147483648')  # 2 GB
)

# Telegram bots can upload files up to 50 MB. Reject larger downloads early.
# This (not video length) is the real limit on disk and I/O usage.
MAX_AUDIO_FILESIZE: Final[int] = int(
    os.getenv('MAX_AUDIO_FILESIZE', '52428800')  # 50 MB
)

# Maximum number of cached (query -> file_id) rows to keep. When exceeded, the
# oldest entries are dropped so the table can't grow without bound. Each row is
# tiny (a few hundred bytes), so the default stays well under any DB quota.
CACHE_MAX_ENTRIES: Final[int] = int(os.getenv('CACHE_MAX_ENTRIES', '5000'))

# Converting to MP3 needs FFmpeg and is CPU-heavy, so by default we send the
# native audio (usually .m4a), which Telegram plays fine. Set this to '1' only
# if FFmpeg is available and you really want MP3 output.
CONVERT_TO_MP3: Final[bool] = os.getenv('CONVERT_TO_MP3', '0') == '1'

# Optional path to an FFmpeg binary (used for MP3 conversion and, when
# REMUX_FOR_SEEK is on, for the faststart remux / duration probe steps).
FFMPEG_LOCATION: Final[str | None] = os.getenv('FFMPEG_LOCATION') or None

# After download, remux MP4-family files (.m4a/.mp4/...) with +faststart so
# Telegram's player can seek, and correct the reported duration from the real
# file via ffprobe. Best-effort: falls back to the original file/duration if
# FFmpeg is missing or fails. Set to '0' to disable (e.g. no FFmpeg installed).
REMUX_FOR_SEEK: Final[bool] = os.getenv('REMUX_FOR_SEEK', '1') == '1'

# How far the extractor-reported duration may differ from the probed (real)
# duration before we trust the probe instead. Guards against tiny rounding
# differences triggering a needless correction.
DURATION_TOLERANCE_SECONDS: Final[int] = int(os.getenv('DURATION_TOLERANCE_SECONDS', '2'))

# Optional Netscape-format cookies file for YouTube. Helps when YouTube blocks
# the server's datacenter IP ("Sign in to confirm you're not a bot").
YTDLP_COOKIEFILE: Final[str | None] = os.getenv('YTDLP_COOKIEFILE') or None

# YouTube "player clients" yt-dlp pretends to be. Leave empty to use yt-dlp's
# own (well-maintained) default set, which returns proper audio-only formats.
# Override (comma-separated) only if YouTube changes what works — but note that
# app clients like "tv" often only offer combined video formats.
YTDLP_PLAYER_CLIENTS: Final[list[str]] = [
    client.strip()
    for client in os.getenv('YTDLP_PLAYER_CLIENTS', '').split(',')
    if client.strip()
]

# --- Search & source strategy ----------------------------------------------
# Search is done on YouTube Music (accurate song metadata) and the exact match
# is downloaded from YouTube. SoundCloud is only used as a fallback source when
# a YouTube download fails, so availability stays high without cookies.

# How many search results to show the user in the pick-a-track menu.
MUSIC_SEARCH_LIMIT: Final[int] = int(os.getenv('MUSIC_SEARCH_LIMIT', '20'))

# When a YouTube download fails (blocked, unavailable, etc.), try SoundCloud as
# a fallback source for the same track. Set to '0' to disable the fallback.
SOUNDCLOUD_FALLBACK: Final[bool] = os.getenv('SOUNDCLOUD_FALLBACK', '1') == '1'

# Base URL of the bgutil PO-token provider HTTP server, which lets yt-dlp fetch
# YouTube audio WITHOUT cookies (it answers the "Sign in to confirm you're not
# a bot" challenge). Leave unset for the standard local Docker deployment — the
# yt-dlp bgutil plugin then uses its own default of http://127.0.0.1:4416.
POT_PROVIDER_BASE_URL: Final[str | None] = os.getenv('POT_PROVIDER_BASE_URL') or None

LOGS_PATH: Final[Path] = BASE_DIR / 'logs'
TRACKS_PATH: Final[Path] = BASE_DIR / 'tracks'

# Write logs to rotating files under logs/. Off by default so logs never fill a
# small server disk — the console output is always on for the host to capture.
LOG_TO_FILE: Final[bool] = os.getenv('LOG_TO_FILE', '0') == '1'

_log_handlers: dict[str, Any] = {
    'console': {
        'level': 'INFO',
        'class': 'logging.StreamHandler',
        'formatter': 'standard',
    },
}
_root_handlers: list[str] = ['console']

if LOG_TO_FILE:
    LOGS_PATH.mkdir(exist_ok=True)
    _log_handlers['info_file'] = {
        'level': 'INFO',
        'class': 'logging.handlers.RotatingFileHandler',
        'filename': LOGS_PATH / 'info.log',
        'maxBytes': 5242880,  # 5 MB
        'backupCount': 3,
        'formatter': 'standard',
    }
    _log_handlers['error_file'] = {
        'level': 'ERROR',
        'class': 'logging.handlers.RotatingFileHandler',
        'filename': LOGS_PATH / 'error.log',
        'maxBytes': 5242880,  # 5 MB
        'backupCount': 3,
        'formatter': 'standard',
    }
    _root_handlers += ['info_file', 'error_file']

LOGGING: Final[dict[str, Any]] = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '[{asctime}]: {levelname} > {message}',
            'style': '{',
        },
    },
    'handlers': _log_handlers,
    'loggers': {
        'root': {
            'level': 'INFO',
            'handlers': _root_handlers,
            'propagate': True,
        },
    },
}

TRACKS_PATH.mkdir(exist_ok=True)

logging.config.dictConfig(LOGGING)
