#!/usr/bin/env bash
# Telegram Claude Platform installer
#
# Installs Vesna (root admin agent) + Leto (first user-level chat agent) on a
# fresh Ubuntu 22.04 / 24.04 VPS, with a 5-layer memory hierarchy, OpenViking
# semantic search, voice transcription, and live-streaming Telegram UI.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/tsevmenko/telegram-claude-platform/main/install.sh | sudo bash
#   # or
#   sudo ./install.sh
#
# Idempotent. Safe to rerun — completed steps are skipped via state markers.

set -euo pipefail

# =============================================================================
# CONSTANTS
# =============================================================================

readonly INSTALLER_VERSION="0.0.1"
readonly INSTALLER_REPO="https://github.com/tsevmenko/telegram-claude-platform.git"
readonly STATE_DIR="/var/lib/agent-installer"
readonly STATE_FILE="${STATE_DIR}/state.json"
readonly LOG_FILE="/var/log/agent-installer.log"
readonly CURL_OPTS=(-fsSL --max-time 60 --retry 2 --retry-delay 3)

# Step ordering — each NN-*.sh in installer/lib/ runs in sequence.
# This list grows phase by phase. Override with INSTALLER_STEPS_OVERRIDE for tests.
if [[ -n "${INSTALLER_STEPS_OVERRIDE:-}" ]]; then
    # Allow tests to inject a custom step list (space-separated string).
    # shellcheck disable=SC2206
    INSTALLER_STEPS=( ${INSTALLER_STEPS_OVERRIDE} )
else
    INSTALLER_STEPS=(
        00-preflight
        10-system-deps
        20-claude-cli
        30-users
        40-secrets
        70-openviking
        50-vesna
        55-plugins
        60-user-gateway
        85-cron
        90-webhook-token
        99-self-check
    )
fi
readonly INSTALLER_STEPS

# Resolve installer root — works both for `./install.sh` and `curl | bash`.
_SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null || echo "$0")"
_SCRIPT_DIR="$(cd "$(dirname "$_SCRIPT_PATH")" 2>/dev/null && pwd || pwd)"
INSTALLER_ROOT="${INSTALLER_ROOT:-$_SCRIPT_DIR}"
unset _SCRIPT_PATH _SCRIPT_DIR

# =============================================================================
# TERMINAL OUTPUT
# =============================================================================

if [[ -t 1 ]]; then
    C_RED=$'\033[0;31m'; C_GREEN=$'\033[0;32m'; C_YELLOW=$'\033[1;33m'
    C_BLUE=$'\033[0;34m'; C_BOLD=$'\033[1m'; C_NC=$'\033[0m'
else
    C_RED=''; C_GREEN=''; C_YELLOW=''; C_BLUE=''; C_BOLD=''; C_NC=''
fi

log() { printf '%b[%s]%b %s\n' "$C_BLUE" "$(date '+%H:%M:%S')" "$C_NC" "$*" | tee -a "$LOG_FILE" >&2; }
ok()  { printf '%b✓%b %s\n' "$C_GREEN" "$C_NC" "$*" | tee -a "$LOG_FILE" >&2; }
warn(){ printf '%b!%b %s\n' "$C_YELLOW" "$C_NC" "$*" | tee -a "$LOG_FILE" >&2; }
err() { printf '%b✗%b %s\n' "$C_RED" "$C_NC" "$*" | tee -a "$LOG_FILE" >&2; }
die() { err "$*"; exit 1; }

step_header() {
    local name="$1"
    printf '\n%b── %s ──%b\n' "$C_BOLD" "$name" "$C_NC" | tee -a "$LOG_FILE" >&2
}

banner() {
    printf '%b' "$C_YELLOW"
    cat <<'EOF'

  Telegram Claude Platform installer
  ──────────────────────────────────

EOF
    printf '  v%s\n%b\n' "$INSTALLER_VERSION" "$C_NC"
}

# =============================================================================
# STATE MANAGEMENT (idempotency)
# =============================================================================

state_init() {
    install -d -m 0755 "$STATE_DIR"
    install -d -m 0755 "$(dirname "$LOG_FILE")"
    : >>"$LOG_FILE"
    chmod 0640 "$LOG_FILE"
    if [[ ! -f "$STATE_FILE" ]]; then
        printf '{"version":"%s","completed_steps":[]}\n' "$INSTALLER_VERSION" >"$STATE_FILE"
        chmod 0640 "$STATE_FILE"
    fi
}

state_step_done() {
    local step="$1"
    if ! command -v jq &>/dev/null; then
        # jq not yet installed — fall back to grep (00/10 steps run before apt).
        grep -q "\"$step\"" "$STATE_FILE" 2>/dev/null
    else
        jq -e --arg s "$step" '.completed_steps | index($s)' "$STATE_FILE" >/dev/null 2>&1
    fi
}

state_mark_done() {
    local step="$1"
    if ! command -v jq &>/dev/null; then
        # Append step name into the JSON file's array as a string. Pre-jq path.
        # We rewrite the file with a minimal awk transform.
        local tmp; tmp="$(mktemp)"
        awk -v s="$step" '
            /"completed_steps": *\[\]/  { sub(/\[\]/, "[\"" s "\"]"); print; next }
            /"completed_steps": *\[/    { sub(/\[/, "[\"" s "\","); print; next }
            { print }
        ' "$STATE_FILE" >"$tmp"
        mv "$tmp" "$STATE_FILE"
    else
        local tmp; tmp="$(mktemp)"
        jq --arg s "$step" '.completed_steps += [$s] | .completed_steps |= unique' \
            "$STATE_FILE" >"$tmp"
        mv "$tmp" "$STATE_FILE"
    fi
    chmod 0640 "$STATE_FILE"
}

# =============================================================================
# CLEANUP
# =============================================================================

TMPFILES=()
TMPDIRS=()
_cleanup() {
    local f d
    for f in "${TMPFILES[@]:-}"; do
        [[ -n "$f" && -f "$f" ]] && rm -f "$f" || true
    done
    for d in "${TMPDIRS[@]:-}"; do
        [[ -n "$d" && -d "$d" ]] && rm -rf "$d" || true
    done
}
trap _cleanup EXIT

# =============================================================================
# BOOTSTRAP — clone repo if running via `curl | bash` (no local installer/lib/)
# =============================================================================

source_helpers() {
    local helpers="${INSTALLER_ROOT}/installer/lib/_helpers.sh"
    if [[ -f "$helpers" ]]; then
        # shellcheck disable=SC1090
        source "$helpers"
    fi
}

ensure_installer_files() {
    if [[ -d "${INSTALLER_ROOT}/installer/lib" ]]; then
        return 0
    fi
    log "installer/lib/ not present at ${INSTALLER_ROOT} — cloning repo into temp."
    if ! command -v git &>/dev/null; then
        log "git not found — installing via apt."
        DEBIAN_FRONTEND=noninteractive apt-get update -qq
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git
    fi
    local clone_dir
    clone_dir="$(mktemp -d)"
    TMPDIRS+=("$clone_dir")
    git clone --quiet --depth 1 "$INSTALLER_REPO" "$clone_dir" \
        || die "Failed to clone installer repo from ${INSTALLER_REPO}"
    INSTALLER_ROOT="$clone_dir"
    log "Installer files at ${INSTALLER_ROOT}"
}

# =============================================================================
# STEP RUNNER
# =============================================================================

run_step() {
    local step="$1"
    local script="${INSTALLER_ROOT}/installer/lib/${step}.sh"

    if [[ ! -f "$script" ]]; then
        die "Step script missing: $script"
    fi

    # The self-check is ALWAYS rerun, even on idempotent re-installs — its
    # whole job is to surface the current state of the system. Skipping it
    # would hide newly-fixed (or newly-broken) issues from the operator.
    if [[ "$step" != "99-self-check" ]] && state_step_done "$step"; then
        log "Step ${step} already completed — skipping."
        return 0
    fi

    step_header "$step"
    # Each step script is sourced so it can access shared functions and
    # exported variables. Each script must define a function named
    # `step_main` that does the actual work and exits non-zero on failure.
    # shellcheck disable=SC1090
    source "$script"
    if ! declare -F step_main >/dev/null; then
        die "Step ${step} did not define step_main()"
    fi
    if step_main; then
        # Self-check is intentionally NOT marked done — it must always rerun.
        if [[ "$step" != "99-self-check" ]]; then
            state_mark_done "$step"
        fi
        ok "Step ${step} complete."
    else
        die "Step ${step} failed. See ${LOG_FILE}."
    fi
    unset -f step_main
}

# =============================================================================
# PREFLIGHT (runs before everything else, even before state init)
# =============================================================================

preflight_root() {
    if [[ $EUID -ne 0 ]]; then
        die "This installer must be run as root: sudo bash install.sh"
    fi
}

# =============================================================================
# MAIN
# =============================================================================

main() {
    preflight_root
    state_init
    banner
    log "Starting Telegram Claude Platform installer v${INSTALLER_VERSION}"
    log "Installer root: ${INSTALLER_ROOT}"
    log "State file:     ${STATE_FILE}"
    log "Log file:       ${LOG_FILE}"

    ensure_installer_files
    source_helpers

    local step
    for step in "${INSTALLER_STEPS[@]}"; do
        run_step "$step"
    done

    ok "All steps complete."
    log "Installer finished successfully."
}

main "$@"
