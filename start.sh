#!/usr/bin/env bash
# Startup script for bdbv-cpi-mcp server
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KEY_FILE="${SCRIPT_DIR}/biohub_api_key.txt"

# Read the Biohub API key from file
if [ ! -f "$KEY_FILE" ]; then
    echo "Error: API key file not found at $KEY_FILE" >&2
    echo "Create the file with your Biohub API token from:" >&2
    echo "  https://biohub.ai/developer-console/api-keys" >&2
    exit 1
fi

export BIOHUB_API_TOKEN="$(cat "$KEY_FILE" | tr -d '[:space:]')"

if [ -z "$BIOHUB_API_TOKEN" ]; then
    echo "Error: API key file is empty" >&2
    exit 1
fi

echo "Loaded Biohub API token from $KEY_FILE"

# Activate the project venv and start the server
exec "${SCRIPT_DIR}/.venv/bin/python" -m bdbv_cpi_mcp.server "$@"
