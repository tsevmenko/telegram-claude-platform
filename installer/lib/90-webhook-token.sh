#!/usr/bin/env bash
# Generate the webhook token used by the user-gateway's external-injection API.
# Token is written to:
#   /root/vesna/webhook-token.txt           (root-only — Vesna owns the source of truth)
#   /home/agent/secrets/webhook-token.txt   (agent-readable, used by user-gateway at runtime)

readonly TOKEN_FILE_ROOT="/root/vesna/webhook-token.txt"
readonly TOKEN_FILE_AGENT="/home/agent/secrets/webhook-token.txt"

step_main() {
    install -d -m 0700 -o root  -g root  /root/vesna
    install -d -m 0700 -o agent -g agent /home/agent/secrets

    if [[ -f "$TOKEN_FILE_ROOT" ]]; then
        ok "Webhook token already present at ${TOKEN_FILE_ROOT}."
    else
        local token
        token="$(openssl rand -hex 32)"
        umask 077
        printf '%s\n' "$token" >"$TOKEN_FILE_ROOT"
        chmod 0600 "$TOKEN_FILE_ROOT"
        chown root:root "$TOKEN_FILE_ROOT"
        ok "Generated webhook token at ${TOKEN_FILE_ROOT}."
    fi

    install -m 0600 -o agent -g agent "$TOKEN_FILE_ROOT" "$TOKEN_FILE_AGENT"
    ok "Webhook token mirrored to ${TOKEN_FILE_AGENT}."
}
