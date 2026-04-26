#!/usr/bin/env bats
# Installer foundation tests — Phase 1.
# These run inside an Ubuntu Docker container as root.

setup() {
    REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
    export REPO_ROOT
    # Sandbox state and log paths so tests don't pollute the container.
    export STATE_DIR_OVERRIDE="/tmp/test-installer-state-$$"
    export LOG_FILE_OVERRIDE="/tmp/test-installer.log-$$"
}

teardown() {
    rm -rf "$STATE_DIR_OVERRIDE" "$LOG_FILE_OVERRIDE" 2>/dev/null || true
}

# Run install.sh with sandboxed paths and only the preflight step.
run_installer() {
    INSTALLER_STEPS_OVERRIDE="00-preflight" \
    INSTALLER_ROOT="$REPO_ROOT" \
    bash -c "
        export STATE_DIR='${STATE_DIR_OVERRIDE}'
        export STATE_FILE='${STATE_DIR_OVERRIDE}/state.json'
        export LOG_FILE='${LOG_FILE_OVERRIDE}'
        # Source install.sh with our overrides applied via env (the script
        # reads STATE_DIR/STATE_FILE/LOG_FILE as readonly, so we patch via sed).
        sed -e \"s|^readonly STATE_DIR=.*|readonly STATE_DIR='${STATE_DIR_OVERRIDE}'|\" \
            -e \"s|^readonly STATE_FILE=.*|readonly STATE_FILE='${STATE_DIR_OVERRIDE}/state.json'|\" \
            -e \"s|^readonly LOG_FILE=.*|readonly LOG_FILE='${LOG_FILE_OVERRIDE}'|\" \
            ${REPO_ROOT}/install.sh > /tmp/install-test.sh
        bash /tmp/install-test.sh
    "
}

@test "install.sh exits with usage error when not run as root" {
    if [ "$EUID" -eq 0 ]; then
        skip "Cannot test non-root behaviour while running as root"
    fi
    run bash "${REPO_ROOT}/install.sh"
    [ "$status" -ne 0 ]
    [[ "$output" == *"must be run as root"* ]]
}

@test "install.sh runs to completion with only preflight step" {
    run run_installer
    [ "$status" -eq 0 ]
    [[ "$output" == *"Ubuntu"* ]] || [[ "$output" == *"Network reachable"* ]]
}

@test "install.sh creates state file with completed step" {
    run_installer
    [ -f "${STATE_DIR_OVERRIDE}/state.json" ]
    grep -q "00-preflight" "${STATE_DIR_OVERRIDE}/state.json"
}

@test "install.sh is idempotent — second run skips completed steps" {
    run_installer
    run run_installer
    [ "$status" -eq 0 ]
    [[ "$output" == *"already completed — skipping"* ]]
}

@test "install.sh writes a log file" {
    run_installer
    [ -f "${LOG_FILE_OVERRIDE}" ]
    grep -q "Starting Telegram Claude Platform installer" "${LOG_FILE_OVERRIDE}"
}
