#!/usr/bin/env bash
# Preflight: verify OS, baseline binaries, network reachability, pinned SHAs.
# Sourced by install.sh — defines step_main() plus shared helpers
# (fix_owner, verify_pins) used by later install lib/*.sh files.

# --- shared helpers reused by 50-vesna.sh / 60-user-gateway.sh / 70-openviking.sh --

# fix_owner USER:GROUP PATH
# Recursively chown a path. Idempotent; ignores non-existent targets so
# install.sh stays safe to rerun on a half-installed system.
fix_owner() {
    local owner="$1" path="$2"
    [[ -e "$path" ]] || return 0
    chown -RhP "$owner" "$path" 2>/dev/null || \
        warn "fix_owner: chown -R '${owner}' '${path}' failed (continuing)"
}

# verify_pins
# Reads installer/PINS, looks up the repo for each NAME via installer/PINS.repos,
# and confirms the SHA still resolves on github.com via the public API. Aborts
# the installer if any pin is 404 — that means a SHA was force-rebased or a
# repo deleted, and silently fetching from a moved target would replay broken
# code on every fresh install.
verify_pins() {
    local pins="${INSTALLER_ROOT:-}/installer/PINS"
    local map="${INSTALLER_ROOT:-}/installer/PINS.repos"
    if [[ ! -r "$pins" || ! -r "$map" ]]; then
        log "verify_pins: no PINS file (skipping — only Sprint-3 features need this)"
        return 0
    fi

    local fail=0 line name sha repo
    while IFS= read -r line; do
        # Strip leading whitespace and skip comments / blanks.
        line="${line#"${line%%[![:space:]]*}"}"
        [[ -z "$line" || "$line" == \#* ]] && continue

        name="${line%%=*}"
        sha="${line#*=}"
        sha="${sha%%#*}"  # drop inline comment
        sha="${sha// /}"
        [[ -z "$name" || -z "$sha" ]] && continue

        # Look up owner/repo for this NAME in PINS.repos.
        repo="$(grep -E "^${name}=" "$map" 2>/dev/null | head -n1 | cut -d= -f2)"
        if [[ -z "$repo" ]]; then
            err "verify_pins: ${name} listed in PINS but no repo in PINS.repos"
            fail=1
            continue
        fi

        # GitHub API: GET /repos/{owner}/{repo}/commits/{sha}. Tags also resolve.
        # Build curl args carefully — an empty CURL_OPTS array used to expand
        # to a stray "" argument that curl misread as a URL.
        local code
        if [[ ${#CURL_OPTS[@]} -gt 0 ]]; then
            code="$(curl "${CURL_OPTS[@]}" -fsS -o /dev/null -w '%{http_code}' \
                --max-time 10 \
                "https://api.github.com/repos/${repo}/commits/${sha}" 2>/dev/null || echo "")"
        else
            code="$(curl -fsS -o /dev/null -w '%{http_code}' --max-time 10 \
                "https://api.github.com/repos/${repo}/commits/${sha}" 2>/dev/null || echo "")"
        fi
        # `curl -f` makes 4xx and 5xx silent (returns rc != 0 + empty body),
        # but -w '%{http_code}' still prints the status code — so we can read
        # it from the output even on failure. An empty `code` means curl
        # itself blew up (no network, DNS, etc.).
        case "$code" in
            200|302)
                log "verify_pins: ${name}=${sha} @ ${repo} OK"
                ;;
            404)
                err "verify_pins: ${name}=${sha} @ ${repo} NOT FOUND (404)"
                err "  → SHA was rebased, deleted, or repo moved. Update installer/PINS."
                fail=1
                ;;
            "")
                # No network or curl error — warn loudly, don't gate (we
                # don't want operators offline to be blocked from installing
                # a previously-working pinned platform).
                warn "verify_pins: ${name}=${sha} @ ${repo} curl error (no network?) — continuing"
                ;;
            *)
                # 5xx / rate-limit. Warn, don't fail.
                warn "verify_pins: ${name}=${sha} @ ${repo} returned HTTP ${code} (continuing)"
                ;;
        esac
    done <"$pins"

    if (( fail )); then
        err "One or more pins are unreachable. Refusing to continue."
        return 1
    fi
}

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

    # Validate every pinned external SHA still resolves. Skipped silently if
    # PINS file is empty (Sprint-3 features add real pins).
    verify_pins || return 1
}
