#!/usr/bin/env bash
# Preflight: verify OS, baseline binaries, network reachability.
# Sourced by install.sh — defines step_main().

step_main() {
    if [[ ! -r /etc/os-release ]]; then
        err "Cannot read /etc/os-release — unsupported OS."
        return 1
    fi
    # shellcheck disable=SC1091
    . /etc/os-release

    if [[ "${ID:-}" != "ubuntu" ]]; then
        err "Unsupported OS: ID=${ID:-unknown}. Ubuntu 22.04 or 24.04 required."
        return 1
    fi

    case "${VERSION_ID:-}" in
        22.04|24.04)
            ok "Ubuntu ${VERSION_ID} detected."
            ;;
        *)
            if [[ "${ALLOW_UNTESTED_UBUNTU:-0}" == "1" ]]; then
                warn "Ubuntu ${VERSION_ID:-?} is untested. Continuing (ALLOW_UNTESTED_UBUNTU=1)."
            else
                err "Ubuntu ${VERSION_ID:-?} is untested. Set ALLOW_UNTESTED_UBUNTU=1 to override."
                return 1
            fi
            ;;
    esac

    # Bootstrap curl if missing — every later step needs it.
    if ! command -v curl &>/dev/null; then
        log "Bootstrapping curl..."
        DEBIAN_FRONTEND=noninteractive apt-get update -qq
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq curl
    fi

    # Network sanity check — non-fatal warning, not a hard failure.
    if ! curl "${CURL_OPTS[@]}" -o /dev/null https://api.github.com/ 2>/dev/null; then
        warn "Network check to api.github.com failed. Installer may fail later."
    else
        ok "Network reachable."
    fi

    # Disk space — need at least ~3GB for Node, Python deps, OpenViking.
    local avail_kb
    avail_kb="$(df -k / | awk 'NR==2 {print $4}')"
    if (( avail_kb < 3145728 )); then
        warn "Less than 3GB free on / — installer may run out of space."
    fi
}
