"""Configuration for bdbv-cpi-mcp server."""

import os
from pathlib import Path


# Project root is three levels up from this file (src/bdbv_cpi_mcp/config.py)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_KEY_FILE = _PROJECT_ROOT / "biohub_api_key.txt"


def get_biohub_token() -> str:
    """Get the Biohub API token from env var or biohub_api_key.txt file."""
    # 1. Check environment variable (set by start.sh)
    token = os.environ.get("BIOHUB_API_TOKEN", "").strip()
    if token:
        return token

    # 2. Fall back to reading the key file directly
    if _KEY_FILE.exists():
        token = _KEY_FILE.read_text().strip()
        if token:
            return token

    raise ValueError(
        "Biohub API token not found. Either:\n"
        "  - Set the BIOHUB_API_TOKEN environment variable, or\n"
        f"  - Create {_KEY_FILE} with your token.\n"
        "Get a token from https://biohub.ai/developer-console/api-keys"
    )


BIOHUB_API_URL = os.environ.get("BIOHUB_API_URL", "https://biohub.ai")

BLAST_API_URL = "https://blast.ncbi.nlm.nih.gov/blast/Blast.cgi"
BLAST_TOOL_NAME = "bdbv-cpi-mcp"
BLAST_EMAIL = os.environ.get("BLAST_EMAIL", "")
