#!/usr/bin/env bash
# System dependencies: apt packages required for everything that follows.
# Sourced by install.sh — defines step_main().

step_main() {
    log "Updating apt index..."
    DEBIAN_FRONTEND=noninteractive apt-get update -qq

    log "Installing base packages..."
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        ca-certificates gnupg lsb-release software-properties-common \
        sudo \
        curl wget git jq rsync \
        build-essential \
        systemd \
        logrotate \
        cron \
        ffmpeg sox \
        sqlite3

    # Python 3.12: native on Ubuntu 24.04. On 22.04 the default python3 is 3.10
    # so we pull from the deadsnakes PPA.
    # shellcheck disable=SC1091
    . /etc/os-release
    case "${VERSION_ID:-}" in
        22.04)
            if ! command -v python3.12 >/dev/null 2>&1; then
                log "Adding deadsnakes PPA for Python 3.12 (Ubuntu 22.04)."
                add-apt-repository -y ppa:deadsnakes/ppa >/dev/null
                DEBIAN_FRONTEND=noninteractive apt-get update -qq
            fi
            DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
                python3.12 python3.12-venv python3.12-dev python3-pip
            update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 100 \
                >/dev/null 2>&1 || true
            update-alternatives --set python3 /usr/bin/python3.12 \
                >/dev/null 2>&1 || true
            ;;
        24.04|*)
            DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
                python3 python3-venv python3-pip python3-dev
            ;;
    esac

    local py_ver
    py_ver="$(python3 --version 2>&1 | awk '{print $2}')"
    ok "Base packages installed (python3=${py_ver})."

    # Ensure cron service is enabled now — minimal Ubuntu images sometimes
    # ship cron without the unit started.
    systemctl enable --now cron 2>/dev/null \
        || warn "cron service not started — memory rotation will run after next reboot."
}
