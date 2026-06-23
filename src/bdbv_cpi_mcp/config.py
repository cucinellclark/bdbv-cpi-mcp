"""Configuration for bdbv-cpi-mcp server."""

import os

# ESMFold2 server (proxied through ash)
ESM_FOLD_URL = os.environ.get("ESM_FOLD_URL", "https://dev-9.bv-brc.org")

BLAST_API_URL = "https://blast.ncbi.nlm.nih.gov/blast/Blast.cgi"
BLAST_TOOL_NAME = "bdbv-cpi-mcp"
BLAST_EMAIL = os.environ.get("BLAST_EMAIL", "")
