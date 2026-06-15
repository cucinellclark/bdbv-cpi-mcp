#!/usr/bin/env bash
# Install script for bdbv-cpi-mcp
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"
KEY_FILE="${SCRIPT_DIR}/biohub_api_key.txt"
REQUIRED_PYTHON="3.12"

echo "========================================"
echo "  bdbv-cpi-mcp installer"
echo "========================================"
echo ""

# ── 1. Check Python version ──────────────────────────────────────────────
echo "[1/5] Checking Python..."

PYTHON=""
for candidate in python3.12 python3 python; do
    if command -v "$candidate" &>/dev/null; then
        version=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        if [[ "$version" == "$REQUIRED_PYTHON" ]]; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    echo "Error: Python ${REQUIRED_PYTHON} is required but not found."
    echo "Install it with:"
    echo "  conda install python=${REQUIRED_PYTHON}"
    echo "  or: pyenv install ${REQUIRED_PYTHON}"
    exit 1
fi

echo "  Found: $PYTHON ($($PYTHON --version))"

# ── 2. Create virtual environment ────────────────────────────────────────
echo ""
echo "[2/5] Setting up virtual environment..."

if [[ -d "$VENV_DIR" ]]; then
    echo "  Existing .venv found, removing..."
    rm -rf "$VENV_DIR"
fi

$PYTHON -m venv "$VENV_DIR"
echo "  Created .venv at ${VENV_DIR}"

# Upgrade pip
"${VENV_DIR}/bin/pip" install --upgrade pip --quiet

# ── 3. Install dependencies ──────────────────────────────────────────────
echo ""
echo "[3/5] Installing dependencies (this may take a few minutes)..."

"${VENV_DIR}/bin/pip" install -e "${SCRIPT_DIR}" 2>&1 | \
    while IFS= read -r line; do
        # Show progress but skip noise
        case "$line" in
            *Installing*|*Successfully*|*Collecting*esm*|*Collecting*mcp*|*Collecting*torch*)
                echo "  $line"
                ;;
        esac
    done

echo "  Dependencies installed."

# ── 4. Check for MAFFT ───────────────────────────────────────────────────
echo ""
echo "[4/5] Checking for MAFFT..."

if command -v mafft &>/dev/null; then
    mafft_version=$(mafft --version 2>&1 | head -1)
    echo "  Found: mafft ${mafft_version}"
else
    echo "  WARNING: MAFFT is not installed."
    echo "  The mafft_align tool will not work without it."
    echo "  Install with:"
    echo "    conda install -c bioconda mafft"
    echo "    or: sudo apt install mafft"
    echo "    or: https://mafft.cbrc.jp/alignment/software/"
fi

# ── 5. Biohub API key ───────────────────────────────────────────────────
echo ""
echo "[5/5] Biohub API key..."

if [[ -f "$KEY_FILE" ]] && [[ -s "$KEY_FILE" ]]; then
    echo "  Found existing key at ${KEY_FILE}"
else
    echo "  The ESMFold and ESMC tools require a Biohub API token."
    echo "  Get one from: https://biohub.ai/developer-console/api-keys"
    echo ""
    read -rp "  Paste your Biohub API token (or press Enter to skip): " token
    if [[ -n "$token" ]]; then
        echo -n "$token" > "$KEY_FILE"
        chmod 600 "$KEY_FILE"
        echo "  Saved to ${KEY_FILE}"
    else
        echo "  Skipped. Create ${KEY_FILE} later to use ESM tools."
    fi
fi

# ── Verify ───────────────────────────────────────────────────────────────
echo ""
echo "Verifying installation..."

"${VENV_DIR}/bin/python" -c "
import sys
errors = []

try:
    from bdbv_cpi_mcp.config import BLAST_API_URL
except Exception as e:
    errors.append(f'config: {e}')

try:
    import mcp
except Exception as e:
    errors.append(f'mcp: {e}')

try:
    import httpx
except Exception as e:
    errors.append(f'httpx: {e}')

try:
    import esm
except Exception as e:
    errors.append(f'esm: {e}')

try:
    import torch
except Exception as e:
    errors.append(f'torch: {e}')

if errors:
    print('  FAILED:')
    for err in errors:
        print(f'    - {err}')
    sys.exit(1)
else:
    print('  All imports OK.')
"

echo ""
echo "========================================"
echo "  Installation complete!"
echo "========================================"
echo ""
echo "Start the server:"
echo "  HTTP:  ./start.sh"
echo "  STDIO: .venv/bin/python -m bdbv_cpi_mcp.server stdio"
