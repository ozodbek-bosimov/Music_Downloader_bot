#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Music Downloader Bot — Universal Installer
#
# Supports: Ubuntu/Debian, CentOS/RHEL/Fedora/Amazon Linux, Arch, Alpine, macOS
# Usage:    bash install.sh
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

info()    { echo -e "${BLUE}ℹ${NC}  $*"; }
success() { echo -e "${GREEN}✔${NC}  $*"; }
warn()    { echo -e "${YELLOW}⚠${NC}  $*"; }
error()   { echo -e "${RED}✖${NC}  $*" >&2; }
step()    { echo -e "\n${CYAN}${BOLD}── $* ──${NC}"; }

# ── Detect OS / distro ───────────────────────────────────────────────────────
detect_os() {
    OS="$(uname -s)"
    DISTRO="unknown"
    PKG=""

    case "$OS" in
        Linux)
            if [ -f /etc/os-release ]; then
                . /etc/os-release
                DISTRO="${ID:-unknown}"
            elif [ -f /etc/redhat-release ]; then
                DISTRO="rhel"
            fi

            case "$DISTRO" in
                ubuntu|debian|pop|linuxmint|elementary|zorin)
                    PKG="apt" ;;
                centos|rhel|rocky|alma|ol|amzn)
                    PKG="yum"
                    command -v dnf &>/dev/null && PKG="dnf"
                    ;;
                fedora)
                    PKG="dnf" ;;
                arch|manjaro|endeavouros)
                    PKG="pacman" ;;
                alpine)
                    PKG="apk" ;;
                *)
                    error "Unsupported Linux distro: $DISTRO"
                    error "Supported: Ubuntu, Debian, CentOS, RHEL, Fedora, Arch, Alpine, Amazon Linux"
                    exit 1
                    ;;
            esac
            ;;
        Darwin)
            DISTRO="macos"
            PKG="brew"
            if ! command -v brew &>/dev/null; then
                error "Homebrew is required on macOS. Install it from https://brew.sh"
                exit 1
            fi
            ;;
        *)
            error "Unsupported OS: $OS"
            exit 1
            ;;
    esac

    success "Detected: ${BOLD}$DISTRO${NC} (package manager: $PKG)"
}

# ── Privilege helper ─────────────────────────────────────────────────────────
SUDO=""
setup_sudo() {
    if [ "$(id -u)" -ne 0 ] && [ "$DISTRO" != "macos" ]; then
        if command -v sudo &>/dev/null; then
            SUDO="sudo"
        else
            warn "Not running as root and 'sudo' not found."
            warn "System package installation may fail."
        fi
    fi
}

# ── Install system packages ──────────────────────────────────────────────────
install_system_deps() {
    step "Installing system dependencies"

    case "$PKG" in
        apt)
            $SUDO apt-get update -qq
            $SUDO apt-get install -y -qq \
                python3 python3-pip python3-venv \
                postgresql postgresql-contrib \
                git curl unzip ffmpeg
            ;;
        dnf|yum)
            $SUDO $PKG install -y \
                python3 python3-pip python3-devel \
                postgresql-server postgresql-contrib \
                git curl unzip ffmpeg
            # Initialize PostgreSQL if not already done
            if ! $SUDO test -f /var/lib/pgsql/data/PG_VERSION 2>/dev/null; then
                info "Initializing PostgreSQL database..."
                if command -v postgresql-setup &>/dev/null; then
                    $SUDO postgresql-setup --initdb 2>/dev/null || true
                fi
            fi
            $SUDO systemctl enable --now postgresql 2>/dev/null || true
            ;;
        pacman)
            $SUDO pacman -Syu --noconfirm --needed \
                python python-pip \
                postgresql \
                git curl unzip ffmpeg
            # Initialize PostgreSQL if needed
            if ! $SUDO test -d /var/lib/postgres/data/base 2>/dev/null; then
                info "Initializing PostgreSQL database..."
                $SUDO -u postgres initdb -D /var/lib/postgres/data 2>/dev/null || true
            fi
            $SUDO systemctl enable --now postgresql 2>/dev/null || true
            ;;
        apk)
            $SUDO apk update
            $SUDO apk add --no-cache \
                python3 py3-pip python3-dev \
                postgresql postgresql-client postgresql-contrib \
                git curl unzip ffmpeg \
                gcc musl-dev libffi-dev
            # Start PostgreSQL
            $SUDO rc-update add postgresql default 2>/dev/null || true
            $SUDO rc-service postgresql start 2>/dev/null || true
            ;;
        brew)
            brew install python@3.12 postgresql@16 git curl ffmpeg
            brew services start postgresql@16 2>/dev/null || true
            ;;
    esac

    success "System dependencies installed"
}

# ── Check Python version ─────────────────────────────────────────────────────
check_python() {
    step "Checking Python version"

    PYTHON=""
    for cmd in python3.13 python3.12 python3; do
        if command -v "$cmd" &>/dev/null; then
            version=$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
            major=$(echo "$version" | cut -d. -f1)
            minor=$(echo "$version" | cut -d. -f2)
            if [ "$major" -ge 3 ] && [ "$minor" -ge 12 ]; then
                PYTHON="$cmd"
                break
            fi
        fi
    done

    if [ -z "$PYTHON" ]; then
        error "Python 3.12+ is required but not found."
        error "Install Python 3.12 or newer and try again."
        exit 1
    fi

    success "Using $PYTHON ($($PYTHON --version))"
}

# ── Install Deno ──────────────────────────────────────────────────────────────
install_deno() {
    step "Checking Deno (required by yt-dlp)"

    if command -v deno &>/dev/null; then
        success "Deno already installed: $(deno --version | head -1)"
        return
    fi

    info "Installing Deno..."
    curl -fsSL https://deno.land/install.sh | sh

    # Add Deno to PATH for this session
    DENO_DIR="$HOME/.deno"
    if [ -d "$DENO_DIR/bin" ]; then
        export PATH="$DENO_DIR/bin:$PATH"
    fi

    if command -v deno &>/dev/null; then
        success "Deno installed: $(deno --version | head -1)"
    else
        warn "Deno installed but not in PATH."
        warn "Add this to your ~/.bashrc or ~/.zshrc:"
        warn "  export PATH=\"\$HOME/.deno/bin:\$PATH\""
    fi
}

# ── PO-token provider (cookieless YouTube) ────────────────────────────────────
setup_pot_provider() {
    step "PO-token provider (cookieless YouTube downloads)"

    if ! command -v docker &>/dev/null; then
        warn "Docker not found — YouTube may be blocked on this host without it."
        info "For cookieless YouTube, install Docker then run: ${BOLD}docker compose up -d${NC}"
        info "The bot still works via SoundCloud fallback in the meantime."
        return
    fi

    read_input "Start the PO-token provider with Docker now? (y/n)" START_POT "y"
    if [[ ! "$START_POT" =~ ^[Yy] ]]; then
        info "Skipped. Start later with: ${BOLD}docker compose up -d${NC}"
        return
    fi

    if docker compose version &>/dev/null; then
        POT_CMD=(docker compose up -d)
    elif command -v docker-compose &>/dev/null; then
        POT_CMD=(docker-compose up -d)
    else
        POT_CMD=(docker run -d --restart unless-stopped --name bgutil-pot-provider
                 -p 127.0.0.1:4416:4416 brainicism/bgutil-ytdlp-pot-provider:latest)
    fi

    if "${POT_CMD[@]}"; then
        success "PO-token provider running on 127.0.0.1:4416"
    else
        warn "Couldn't start the provider. Start it later with: ${BOLD}docker compose up -d${NC}"
    fi
}

# ── Helper: read user input ──────────────────────────────────────────────────
read_input() {
    local prompt="$1"
    local var_name="$2"
    local default="${3:-}"

    if [ -n "$default" ]; then
        prompt="$prompt [${default}]: "
    else
        prompt="$prompt: "
    fi

    echo -en "${CYAN}?${NC} $prompt"
    read -r value
    value="${value:-$default}"

    eval "$var_name=\"\$value\""
}

read_secret() {
    local prompt="$1"
    local var_name="$2"

    echo -en "${CYAN}?${NC} $prompt: "
    read -rs value
    echo ""

    eval "$var_name=\"\$value\""
}

# ── Setup PostgreSQL database ─────────────────────────────────────────────────
setup_database() {
    step "Setting up PostgreSQL database"

    read_input "Database name" DB_NAME "musicbot"
    read_input "Database user" DB_USER "musicbot"
    read_secret "Database password" DB_PASS
    read_input "Database host" DB_HOST "localhost"

    info "Creating PostgreSQL user and database..."

    # Try to create user and database (may already exist)
    if [ "$DISTRO" = "macos" ]; then
        createuser "$DB_USER" 2>/dev/null || warn "User '$DB_USER' may already exist"
        psql postgres -c "ALTER USER $DB_USER WITH PASSWORD '$DB_PASS';" 2>/dev/null || true
        createdb -O "$DB_USER" "$DB_NAME" 2>/dev/null || warn "Database '$DB_NAME' may already exist"
    else
        $SUDO -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';" 2>/dev/null \
            || warn "User '$DB_USER' may already exist"
        $SUDO -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;" 2>/dev/null \
            || warn "Database '$DB_NAME' may already exist"
    fi

    success "Database ready: $DB_NAME (user: $DB_USER @ $DB_HOST)"
}

# ── Setup Python venv & deps ─────────────────────────────────────────────────
setup_python_env() {
    step "Setting up Python environment"

    if [ ! -d "env" ]; then
        info "Creating virtual environment..."
        $PYTHON -m venv env
    fi

    source env/bin/activate

    info "Installing pip and poetry..."
    python -m pip install -U pip --quiet
    python -m pip install poetry --quiet

    info "Installing project dependencies..."
    poetry install --only main --quiet

    success "Python environment ready"
}

# ── Generate .env ─────────────────────────────────────────────────────────────
generate_env() {
    step "Configuring the bot"

    read_input "Telegram Bot Token (from @BotFather)" BOT_TOKEN

    # Optional settings
    echo ""
    info "Optional settings (press Enter to skip):"
    read_input "Required channel (e.g. @mychannel)" REQUIRED_CHANNEL ""
    read_input "Admin Telegram IDs (comma-separated)" ADMIN_IDS ""
    read_input "Max parallel downloads" MAX_PARALLEL "2"

    escape_val() {
        local v="$1"
        v=${v//\\/\\\\}
        v=${v//\"/\\\"}
        printf '"%s"' "$v"
    }

    cat > .env << ENVEOF
# --- Required (entered during install) ---
BOT_TOKEN=$(escape_val "$BOT_TOKEN")
POSTGRESQL_DATABASE_HOST=$(escape_val "$DB_HOST")
POSTGRESQL_DATABASE_NAME=$(escape_val "$DB_NAME")
POSTGRESQL_DATABASE_USER=$(escape_val "$DB_USER")
POSTGRESQL_DATABASE_PASSWORD=$(escape_val "$DB_PASS")

# --- Channel & Admin ---
# Channel users must subscribe to before using the bot (leave empty to disable).
REQUIRED_CHANNEL=$REQUIRED_CHANNEL
# Comma-separated Telegram user IDs with admin access (/stats, /broadcast).
ADMIN_IDS=$ADMIN_IDS

# --- Download tuning ---
# Max parallel downloads.
MAX_PARALLEL_DOWNLOADS=$MAX_PARALLEL
# Max on-disk track cache size in bytes (2 GB).
MAX_TRACK_STORAGE_SIZE=2147483648
# Max audio file size in bytes (50 MB, Telegram bot upload limit).
MAX_AUDIO_FILESIZE=52428800
# Max cached (query -> file_id) rows in the database.
CACHE_MAX_ENTRIES=5000

# --- Audio format ---
# Set to 1 to convert audio to MP3 (requires FFmpeg).
CONVERT_TO_MP3=0
# Path to FFmpeg binary (only needed when CONVERT_TO_MP3=1).
FFMPEG_LOCATION=

# --- YouTube ---
# Netscape-format cookies file to bypass YouTube bot checks (usually not needed
# when the PO-token provider is running).
YTDLP_COOKIEFILE=
# Comma-separated yt-dlp player clients (leave empty for defaults).
YTDLP_PLAYER_CLIENTS=

# --- Search & download source ---
# How many search results to show in the pick-a-track menu.
MUSIC_SEARCH_LIMIT=20
# Try SoundCloud when a YouTube download fails (1=on, 0=off).
SOUNDCLOUD_FALLBACK=1
# bgutil PO-token provider URL (empty = local default http://127.0.0.1:4416).
POT_PROVIDER_BASE_URL=

# --- Logging ---
# Set to 1 to write logs to rotating files under logs/.
LOG_TO_FILE=0
ENVEOF

    success ".env file created"
}

# ── Run migrations ────────────────────────────────────────────────────────────
run_migrations() {
    step "Running database migrations"
    env/bin/alembic upgrade head
    success "Database migrated"
}

# ── Install systemd service (Linux only) ──────────────────────────────────────
install_service() {
    if [ "$DISTRO" = "macos" ] || [ "$DISTRO" = "alpine" ]; then
        return
    fi

    step "Systemd service"

    local install_dir
    install_dir="$(pwd)"
    local run_user
    run_user="$(whoami)"

    echo ""
    read_input "Install systemd service? (y/n)" INSTALL_SVC "y"

    if [[ "$INSTALL_SVC" =~ ^[Yy] ]]; then
        # Generate service file with correct paths
        cat > /tmp/musicbot.service << SVCEOF
[Unit]
Description=Music Downloader Telegram Bot
After=network-online.target postgresql.service
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=$run_user
WorkingDirectory=$install_dir
ExecStart=$install_dir/env/bin/python $install_dir/main.py
Restart=always
RestartSec=5
# Deno path for yt-dlp
Environment="PATH=$HOME/.deno/bin:/usr/local/bin:/usr/bin:/bin"

[Install]
WantedBy=multi-user.target
SVCEOF

        $SUDO cp /tmp/musicbot.service /etc/systemd/system/musicbot.service
        rm /tmp/musicbot.service
        $SUDO systemctl daemon-reload
        $SUDO systemctl enable musicbot

        success "Service installed and enabled"
        info "Start with:  ${BOLD}sudo systemctl start musicbot${NC}"
        info "Check with:  ${BOLD}journalctl -u musicbot -f${NC}"
    else
        info "Skipped service installation."
        info "Run manually: ${BOLD}env/bin/python main.py${NC}"
    fi
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
    echo -e "\n${BOLD}${CYAN}🎧 Music Downloader Bot — Installer${NC}\n"

    detect_os
    setup_sudo
    install_system_deps
    check_python
    install_deno
    setup_database
    setup_python_env
    generate_env
    run_migrations
    setup_pot_provider
    install_service

    echo ""
    echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}${BOLD}  ✔ Installation complete!${NC}"
    echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo -e "  Start the bot:     ${BOLD}sudo systemctl start musicbot${NC}"
    echo -e "  Or run manually:   ${BOLD}env/bin/python main.py${NC}"
    echo -e "  PO-token provider: ${BOLD}docker compose up -d${NC}  (cookieless YouTube)"
    echo ""
}

main "$@"
