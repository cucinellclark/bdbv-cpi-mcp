# bdbv-cpi-mcp

MCP server exposing bioinformatics tools — BLAST, MAFFT, ESMFold2, and ESMC — to LLM clients (Claude, ChatGPT, etc.) via the [Model Context Protocol](https://modelcontextprotocol.io/).

## Tools

| Tool | Description |
|---|---|
| `blast_search` | Submit a sequence search to NCBI BLAST (blastp, blastn, blastx, tblastn, tblastx) |
| `blast_get_results` | Retrieve and parse results for a submitted BLAST search by RID |
| `mafft_align` | Run multiple sequence alignment using MAFFT (auto, L-INS-i, G-INS-i, E-INS-i, FFT-NS-2) |
| `esmfold_predict` | Predict 3D protein structure from sequence using ESM3 (returns PDB with pTM/pLDDT scores) |
| `esm_embeddings` | Extract protein language model embeddings using ESMC (300M, 600M, 6B) |

## Prerequisites

- **Python 3.12**
- **MAFFT** — required for the `mafft_align` tool (`conda install -c bioconda mafft` or `sudo apt install mafft`)
- **Biohub API token** — required for ESMFold/ESMC tools ([get one here](https://biohub.ai/developer-console/api-keys))

## Installation

```bash
./install.sh
```

The installer creates a `.venv`, installs all dependencies (including the ESM SDK and PyTorch), checks for MAFFT, and prompts for your Biohub API key (saved to `biohub_api_key.txt`).

## Usage

```bash
.venv/bin/python -m bdbv_cpi_mcp.server stdio
```

## Configuration

Copy `.env.example` to `.env` or set these environment variables:

| Variable | Required | Description |
|---|---|---|
| `BIOHUB_API_TOKEN` | Yes (for ESM tools) | Biohub platform API token |
| `BIOHUB_API_URL` | No | Override Biohub API URL (default: `https://biohub.ai`) |
| `BLAST_EMAIL` | No | Email for NCBI BLAST API (recommended by NCBI) |

Alternatively, place your Biohub token in `biohub_api_key.txt` at the project root.

## Project Structure

```
src/bdbv_cpi_mcp/
├── server.py    # MCP server entry point
├── config.py    # Configuration and API token management
├── auth.py      # OAuth provider
└── tools/
    ├── blast.py # NCBI BLAST search and result parsing
    ├── mafft.py # MAFFT multiple sequence alignment
    └── esm.py   # ESMFold structure prediction & ESMC embeddings
```

## Local MCP Server Config
```
{
  "mcpServers": {
    "bdbv-cpi-mcp": {
      "command": "/path/to/bdbv-cpi-mcp/.venv/bin/bdbv-cpi-mcp",
      "args": ["stdio"],
      "env": {
        "BIOHUB_API_TOKEN": "<biohub_api_token>",
         "PATH": "<path_with_mafft>"
      }
    }
  }
}
```
