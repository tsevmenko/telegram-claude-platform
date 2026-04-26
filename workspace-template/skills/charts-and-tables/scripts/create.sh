#!/usr/bin/env bash
# Create + publish a Datawrapper chart from a CSV file.
# Usage: create.sh <title> <type> <csv-data-or-file>
set -euo pipefail

TITLE="${1:?Usage: create.sh <title> <type> <csv-data-or-file>}"
TYPE="${2:?missing chart type}"
DATA="${3:?missing csv data or file path}"

KEY_FILE="${HOME}/.claude-lab/shared/secrets/datawrapper.key"
[ -f "$KEY_FILE" ] || { echo "Datawrapper token not found at $KEY_FILE" >&2; exit 1; }
TOKEN="$(cat "$KEY_FILE")"

# Accept either a file path or inline CSV text on stdin/arg.
if [ -f "$DATA" ]; then
    CSV="$(cat "$DATA")"
else
    CSV="$DATA"
fi

# 1. Create chart.
CREATE=$(curl -sS --fail --max-time 20 \
    "https://api.datawrapper.de/v3/charts" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "$(jq -nc --arg t "$TITLE" --arg ty "$TYPE" '{title: $t, type: $ty}')")
CHART_ID=$(echo "$CREATE" | jq -r '.id // empty')
[ -z "$CHART_ID" ] && { echo "create failed: $CREATE" >&2; exit 1; }

# 2. Upload data.
curl -sS --fail --max-time 20 \
    "https://api.datawrapper.de/v3/charts/${CHART_ID}/data" \
    -X PUT \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: text/csv" \
    --data-binary "$CSV" >/dev/null

# 3. Publish.
PUB=$(curl -sS --fail --max-time 20 \
    "https://api.datawrapper.de/v3/charts/${CHART_ID}/publish" \
    -X POST \
    -H "Authorization: Bearer ${TOKEN}")
URL=$(echo "$PUB" | jq -r '.data.publicUrl // empty')

if [ -n "$URL" ]; then
    echo "$URL"
else
    echo "https://app.datawrapper.de/chart/${CHART_ID}/visualize"
fi
