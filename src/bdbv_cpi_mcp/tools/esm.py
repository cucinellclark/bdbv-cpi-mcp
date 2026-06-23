"""ESM tools: structure prediction (ESMFold2) and protein embeddings."""

import json
import httpx

from bdbv_cpi_mcp.config import ESM_FOLD_URL
from bdbv_cpi_mcp.server import mcp

_VALID_AA = set("ACDEFGHIKLMNPQRSTVWY")

# Timeout for folding requests (can be slow for long sequences)
_REQUEST_TIMEOUT = 600.0  # 10 minutes


def _validate_sequence(sequence: str) -> str | None:
    """Validate a protein sequence. Returns error message or None."""
    sequence = sequence.strip().upper()
    if not sequence:
        return "Error: Sequence cannot be empty."
    # Remove FASTA header if present
    if sequence.startswith(">"):
        lines = sequence.split("\n")
        sequence = "".join(l for l in lines[1:] if not l.startswith(">"))
    invalid = set(sequence) - _VALID_AA
    if invalid:
        return (
            f"Error: Invalid amino acid characters: {', '.join(sorted(invalid))}. "
            f"Sequence must contain only standard amino acids: "
            f"{''.join(sorted(_VALID_AA))}"
        )
    return None


def _clean_sequence(sequence: str) -> str:
    """Clean a protein sequence: strip whitespace, remove FASTA header."""
    sequence = sequence.strip()
    if sequence.startswith(">"):
        lines = sequence.split("\n")
        sequence = "".join(l.strip() for l in lines[1:] if not l.startswith(">"))
    return sequence.upper().replace(" ", "").replace("\n", "")


@mcp.tool()
async def esmfold_predict(
    sequence: str,
    chain_id: str = "A",
    num_loops: int = 3,
    num_sampling_steps: int = 50,
    num_diffusion_samples: int = 1,
    seed: int = 0,
) -> str:
    """Predict 3D protein structure from an amino acid sequence using ESMFold2.

    Returns the predicted structure as an mmCIF string with confidence scores
    (pLDDT, pTM, ipTM).

    Args:
        sequence: Protein amino acid sequence (single-letter codes).
                  Can include a FASTA header line starting with '>'.
        chain_id: Chain identifier for the output structure. Default "A".
        num_loops: Number of recycling loops. Higher values may improve
                   quality. Default 3.
        num_sampling_steps: Number of diffusion sampling steps (1-50).
                            Higher = better quality but slower. Default 50.
        num_diffusion_samples: Number of independent diffusion samples to
                               generate. Default 1.
        seed: Random seed for reproducibility. Default 0.
    """
    # Validate
    err = _validate_sequence(sequence)
    if err:
        return err

    seq = _clean_sequence(sequence)

    if not 1 <= num_sampling_steps <= 50:
        return "Error: num_sampling_steps must be between 1 and 50."

    if num_loops < 1:
        return "Error: num_loops must be at least 1."

    if num_diffusion_samples < 1:
        return "Error: num_diffusion_samples must be at least 1."

    payload = {
        "sequence": seq,
        "chain_id": chain_id,
        "num_loops": num_loops,
        "num_sampling_steps": num_sampling_steps,
        "num_diffusion_samples": num_diffusion_samples,
        "seed": seed,
    }

    try:
        url = f"{ESM_FOLD_URL}/fold"
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            response = await client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                follow_redirects=True,
            )
            response.raise_for_status()

        data = response.json()

        # Build header with confidence metrics
        plddt_mean = data.get("plddt_mean")
        ptm = data.get("ptm")
        iptm = data.get("iptm")
        mmcif = data.get("mmcif", "")

        header = "ESMFold2 Structure Prediction\n"
        header += f"  Sequence length: {len(seq)} residues\n"
        header += f"  Chain ID: {chain_id}\n"
        header += f"  Sampling steps: {num_sampling_steps}\n"
        header += f"  Loops: {num_loops}\n"
        header += f"  Diffusion samples: {num_diffusion_samples}\n"
        header += f"  Seed: {seed}\n"

        if plddt_mean is not None:
            header += f"  Mean pLDDT: {float(plddt_mean):.2f}\n"
        if ptm is not None:
            header += f"  pTM score: {float(ptm):.4f}\n"
        if iptm is not None:
            header += f"  ipTM score: {float(iptm):.4f}\n"

        header += "\n"
        return header + mmcif

    except httpx.HTTPStatusError as e:
        return (
            f"Error from ESMFold2 server (HTTP {e.response.status_code}): "
            f"{e.response.text}"
        )
    except httpx.ConnectError:
        return (
            f"Error: Could not connect to ESMFold2 server at {ESM_FOLD_URL}. "
            f"Ensure the proxy is running on ash and accessible."
        )
    except Exception as e:
        return f"Error during structure prediction: {type(e).__name__}: {e}"


@mcp.tool()
async def esm_embeddings(
    sequence: str,
) -> str:
    """Extract protein language model embeddings using the ESM server.

    NOTE: This tool is currently being migrated to a new backend.
    It will return an error until the embeddings endpoint is configured
    on the new server.

    Args:
        sequence: Protein amino acid sequence (single-letter codes).
                  Can include a FASTA header line starting with '>'.
    """
    return (
        "Error: The ESM embeddings endpoint is not yet available on the new server. "
        "This tool is being migrated. Please check back later or contact the admin."
    )
