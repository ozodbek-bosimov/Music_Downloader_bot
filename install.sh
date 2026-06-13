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
        printf 'BOT_TOKEN=%s\n\n' "$(escape_env_value "$API_TOKEN")"
        printf 'POSTGRESQL_DATABASE_HOST=%s\n' "$(escape_env_value "$POSTGRESQL_DATABASE_HOST")"
        printf 'POSTGRESQL_DATABASE_NAME=%s\n' "$(escape_env_value "$POSTGRESQL_DATABASE_NAME")"
        printf 'POSTGRESQL_DATABASE_USER=%s\n' "$(escape_env_value "$POSTGRESQL_DATABASE_USER")"
        printf 'POSTGRESQL_DATABASE_PASSWORD=%s\n' "$(escape_env_value "$POSTGRESQL_DATABASE_PASSWORD")"
    } > .env

    alembic upgrade head
)
