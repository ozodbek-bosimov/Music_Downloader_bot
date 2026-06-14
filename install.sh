#!/bin/bash

(
    set -euo pipefail

    if [ ! -f env/bin/activate ]; then
        echo 'Virtual environment not found. Run `python -m venv env` first.' >&2
        exit 1
    fi

    source env/bin/activate

    python -m pip install -U pip
    python -m pip install poetry
    poetry install

    read_env() {
        local prompt="$1"
        local var_name="$2"
        if [ -n "${ZSH_VERSION-}" ]; then
            read "$var_name?$prompt"
        else
            read -p "$prompt" "$var_name"
        fi
    }

    escape_env_value() {
        local value="$1"
        value=${value//\\/\\\\}
        value=${value//\"/\\\"}
        printf '"%s"' "$value"
    }

    read_env "Enter Telegram bot API-Token: " API_TOKEN
    read_env "Enter PostgreSQL database host: " POSTGRESQL_DATABASE_HOST
    read_env "Enter PostgreSQL database name: " POSTGRESQL_DATABASE_NAME
    read_env "Enter PostgreSQL database user: " POSTGRESQL_DATABASE_USER
    read_env "Enter PostgreSQL database password: " POSTGRESQL_DATABASE_PASSWORD

    {
        printf '# --- Required (entered during install) ---\n'
        printf 'BOT_TOKEN=%s\n' "$(escape_env_value "$API_TOKEN")"
        printf 'POSTGRESQL_DATABASE_HOST=%s\n' "$(escape_env_value "$POSTGRESQL_DATABASE_HOST")"
        printf 'POSTGRESQL_DATABASE_NAME=%s\n' "$(escape_env_value "$POSTGRESQL_DATABASE_NAME")"
        printf 'POSTGRESQL_DATABASE_USER=%s\n' "$(escape_env_value "$POSTGRESQL_DATABASE_USER")"
        printf 'POSTGRESQL_DATABASE_PASSWORD=%s\n' "$(escape_env_value "$POSTGRESQL_DATABASE_PASSWORD")"
        printf '\n'
        printf '# --- Channel & Admin ---\n'
        printf '# Channel users must subscribe to before using the bot (leave empty to disable).\n'
        printf 'REQUIRED_CHANNEL=\n'
        printf '# Comma-separated Telegram user IDs with admin access (/stats, /broadcast).\n'
        printf 'ADMIN_IDS=\n'
        printf '\n'
        printf '# --- Download tuning ---\n'
        printf '# Max parallel downloads.\n'
        printf 'MAX_PARALLEL_DOWNLOADS=4\n'
        printf '# Max on-disk track cache size in bytes (2 GB).\n'
        printf 'MAX_TRACK_STORAGE_SIZE=2147483648\n'
        printf '# Max audio file size in bytes (50 MB, Telegram bot upload limit).\n'
        printf 'MAX_AUDIO_FILESIZE=52428800\n'
        printf '# Max cached (query -> file_id) rows in the database.\n'
        printf 'CACHE_MAX_ENTRIES=5000\n'
        printf '\n'
        printf '# --- Audio format ---\n'
        printf '# Set to 1 to convert audio to MP3 (requires FFmpeg).\n'
        printf 'CONVERT_TO_MP3=0\n'
        printf '# Path to FFmpeg binary (only needed when CONVERT_TO_MP3=1).\n'
        printf 'FFMPEG_LOCATION=\n'
        printf '\n'
        printf '# --- YouTube ---\n'
        printf '# Netscape-format cookies file to bypass YouTube bot checks.\n'
        printf 'YTDLP_COOKIEFILE=\n'
        printf '# Comma-separated yt-dlp player clients (leave empty for defaults).\n'
        printf 'YTDLP_PLAYER_CLIENTS=\n'
        printf '\n'
        printf '# --- Logging ---\n'
        printf '# Set to 1 to write logs to rotating files under logs/.\n'
        printf 'LOG_TO_FILE=0\n'
    } > .env

    alembic upgrade head
)

