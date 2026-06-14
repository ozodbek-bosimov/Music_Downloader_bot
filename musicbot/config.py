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

# Telegram user IDs that have access to admin commands (/stats, /broadcast,
# /ban, /unban).  Comma-separated in the environment variable.
ADMIN_IDS: Final[list[int]] = [
    int(uid.strip())
    for uid in os.getenv('ADMIN_IDS', '').split(',')
    if uid.strip()
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
# Defaults are tuned for a tiny free-tier host (e.g. alwaysdata Free:
# 256 MB RAM, 0.25 CPU, 1 GB disk). Override via environment variables if you
# run on something bigger.

# How many downloads may run at the same time. On 0.25 CPU keep this at 1 so
# concurrent downloads don't starve each other (and so RAM stays low).
MAX_PARALLEL_DOWNLOADS: Final[int] = int(os.getenv('MAX_PARALLEL_DOWNLOADS', '1'))

# Safety net for the on-disk cache. Tracks are normally deleted right after
# being sent, so this only matters for leftovers from failed sends. Keep it
# well under the 1 GB free-tier disk.
MAX_TRACK_STORAGE_SIZE: Final[int] = int(
    os.getenv('MAX_TRACK_STORAGE_SIZE', '209715200')  # 200 MB
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

# Converting to MP3 needs FFmpeg and is CPU-heavy. On 0.25 CPU we send the
# native audio (usually .m4a) instead, which Telegram plays fine. Set this to
# '1' only if FFmpeg is available and you really want MP3 output.
CONVERT_TO_MP3: Final[bool] = os.getenv('CONVERT_TO_MP3', '0') == '1'

# Optional path to an FFmpeg binary (only used when CONVERT_TO_MP3 is on).
FFMPEG_LOCATION: Final[str | None] = os.getenv('FFMPEG_LOCATION') or None

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
