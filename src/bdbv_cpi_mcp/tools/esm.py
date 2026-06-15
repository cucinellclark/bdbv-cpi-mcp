"""ESM tools: structure prediction (ESMFold) and protein embeddings (ESMC)."""

import asyncio
import json
import re
import sys

from bdbv_cpi_mcp.config import get_biohub_token, BIOHUB_API_URL
from bdbv_cpi_mcp.server import mcp

_VALID_AA = set("ACDEFGHIKLMNPQRSTVWY")

_FOLD_MODELS = {
    "esm3-open",
    "esm3-medium",
    "esm3-large",
}

_EMBED_MODELS = {
    "esmc-300m-2024-12": "esmc-300m-2024-12",
    "esmc-600m-2024-12": "esmc-600m-2024-12",
    "esmc-6b-2024-12": "esmc-6b-2024-12",
    # Backwards-compatible aliases used by older ESM SDK constants.
    "esmc_300m": "esmc-300m-2024-12",
    "esmc_600m": "esmc-600m-2024-12",
    "esmc_6b": "esmc-6b-2024-12",
}


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


def _get_client(model: str):
    """Create an ESM3ForgeInferenceClient."""
    from esm.sdk.forge import ESM3ForgeInferenceClient

    token = get_biohub_token()
    return ESM3ForgeInferenceClient(
        model=model,
        url=BIOHUB_API_URL,
        token=token,
    )


def _get_esmc_client(model: str):
    """Create an ESMCForgeInferenceClient."""
    from esm.sdk import esmc_client

    token = get_biohub_token()
    return esmc_client(
        model=model,
        url=BIOHUB_API_URL,
        token=token,
    )


@mcp.tool()
async def esmfold_predict(
    sequence: str,
    model: str = "esm3-open",
    num_steps: int = 20,
) -> str:
    """Predict 3D protein structure from an amino acid sequence using ESM3.

    Returns the predicted structure as a PDB string with confidence scores.
    Uses the ESM3 model via the Biohub platform API (no local GPU needed).

    Args:
        sequence: Protein amino acid sequence (single-letter codes).
                  Can include a FASTA header line starting with '>'.
        model: Model variant. Options:
               - esm3-open (fast, good for most uses)
               - esm3-medium
               - esm3-large (highest quality, slower)
        num_steps: Number of generation steps (1-50, higher = better quality
                   but slower). Default 20.
    """
    # Validate
    err = _validate_sequence(sequence)
    if err:
        return err

    seq = _clean_sequence(sequence)

    if model not in _FOLD_MODELS:
        return (
            f"Error: Invalid model '{model}'. "
            f"Must be one of: {', '.join(sorted(_FOLD_MODELS))}"
        )

    if not 1 <= num_steps <= 50:
        return "Error: num_steps must be between 1 and 50."

    if len(seq) > 1024:
        return (
            f"Error: Sequence is {len(seq)} residues. "
            f"Maximum supported length is 1024 residues for API inference."
        )

    try:
        from esm.sdk.api import (
            ESMProtein,
            ESMProteinError,
            GenerationConfig,
        )

        client = _get_client(model)
        protein = ESMProtein(sequence=seq)

        config = GenerationConfig(
            track="structure",
            num_steps=num_steps,
        )

        # Run in thread pool since the SDK is synchronous
        result = await asyncio.to_thread(client.generate, protein, config)

        if isinstance(result, ESMProteinError):
            return f"Error from ESM API: {result.error_msg}"

        # Get PDB string
        pdb_str = result.to_pdb_string()

        # Extract confidence metrics
        plddt = result.plddt
        ptm = result.ptm

        header = f"ESM3 Structure Prediction\n"
        header += f"  Model: {model}\n"
        header += f"  Sequence length: {len(seq)} residues\n"
        header += f"  Generation steps: {num_steps}\n"

        if ptm is not None:
            header += f"  pTM score: {float(ptm):.3f}\n"
        if plddt is not None:
            try:
                import torch

                if isinstance(plddt, torch.Tensor):
                    mean_plddt = float(plddt.mean())
                else:
                    mean_plddt = float(sum(plddt) / len(plddt))
                header += f"  Mean pLDDT: {mean_plddt:.1f}\n"
            except Exception:
                pass

        header += "\n"
        return header + pdb_str

    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error during structure prediction: {type(e).__name__}: {e}"


@mcp.tool()
async def esm_embeddings(
    sequence: str,
    model: str = "esmc-600m-2024-12",
) -> str:
    """Extract protein language model embeddings using ESMC.

    Returns the mean embedding vector for the input sequence. Useful for
    downstream tasks like sequence similarity, clustering, and classification.

    Args:
        sequence: Protein amino acid sequence (single-letter codes).
                  Can include a FASTA header line starting with '>'.
        model: ESMC model variant. Options:
               - esmc-300m-2024-12 (fastest, smallest)
               - esmc-600m-2024-12 (balanced, recommended)
               - esmc-6b-2024-12 (most powerful, slowest)
    """
    err = _validate_sequence(sequence)
    if err:
        return err

    seq = _clean_sequence(sequence)

    api_model = _EMBED_MODELS.get(model)
    if api_model is None:
        return (
            f"Error: Invalid model '{model}'. "
            f"Must be one of: {', '.join(sorted(_EMBED_MODELS))}"
        )

    if len(seq) > 2048:
        return (
            f"Error: Sequence is {len(seq)} residues. "
            f"Maximum supported length is 2048 residues for API inference."
        )

    try:
        from esm.sdk.api import (
            ESMProtein,
            ESMProteinError,
            LogitsConfig,
        )

        client = _get_esmc_client(api_model)
        protein = ESMProtein(sequence=seq)

        # Encode the protein to tensor
        protein_tensor = await asyncio.to_thread(client.encode, protein)
        if isinstance(protein_tensor, ESMProteinError):
            return f"Error encoding sequence: {protein_tensor.error_msg}"

        # Get embeddings via logits endpoint
        config = LogitsConfig(
            sequence=True,
            return_mean_embedding=True,
        )
        logits_output = await asyncio.to_thread(client.logits, protein_tensor, config)
        if isinstance(logits_output, ESMProteinError):
            return f"Error computing embeddings: {logits_output.error_msg}"

        # Extract mean embedding
        if logits_output.mean_embedding is not None:
            import torch

            emb = logits_output.mean_embedding
            if isinstance(emb, torch.Tensor):
                emb = emb.detach().cpu()
                emb_list = emb.squeeze().tolist()
            else:
                emb_list = list(emb)

            # Format output
            dim = len(emb_list)
            header = (
                f"ESMC Protein Embedding\n"
                f"  Model: {api_model}\n"
                f"  Sequence length: {len(seq)} residues\n"
                f"  Embedding dimension: {dim}\n\n"
            )

            # Return as JSON array for easy downstream use
            emb_json = json.dumps(
                [round(v, 6) for v in emb_list],
            )
            return header + f"Mean embedding vector ({dim}d):\n{emb_json}"
        else:
            return (
                "Error: API did not return embeddings. "
                "The model may not support this feature."
            )

    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error computing embeddings: {type(e).__name__}: {e}"
