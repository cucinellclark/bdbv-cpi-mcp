"""MAFFT multiple sequence alignment tool."""

import asyncio
import shutil
import tempfile
from pathlib import Path

from bdbv_cpi_mcp.server import mcp

_ALGORITHMS = {
    "auto": ["--auto"],
    "linsi": ["--localpair", "--maxiterate", "1000"],
    "ginsi": ["--globalpair", "--maxiterate", "1000"],
    "einsi": ["--ep", "0", "--genafpair", "--maxiterate", "1000"],
    "fftns2": [],  # default (no special flags)
}

_TIMEOUT_SECONDS = 300


@mcp.tool()
async def mafft_align(
    sequences: str,
    algorithm: str = "auto",
) -> str:
    """Run multiple sequence alignment using MAFFT.

    Args:
        sequences: Input sequences in FASTA format (must contain at least 2 sequences).
                   Each sequence should start with a header line beginning with '>'.
        algorithm: Alignment strategy:
                   - auto: let MAFFT choose the best method (recommended)
                   - linsi: most accurate for <200 sequences (L-INS-i)
                   - ginsi: global alignment (G-INS-i)
                   - einsi: allows large gaps (E-INS-i)
                   - fftns2: fast default (FFT-NS-2)
    """
    # Validate algorithm
    if algorithm not in _ALGORITHMS:
        return (
            f"Error: Invalid algorithm '{algorithm}'. "
            f"Must be one of: {', '.join(sorted(_ALGORITHMS.keys()))}"
        )

    # Validate input
    sequences = sequences.strip()
    if not sequences:
        return "Error: No sequences provided."

    if not sequences.startswith(">"):
        return (
            "Error: Input must be in FASTA format. "
            "Each sequence should start with a header line beginning with '>'.\n\n"
            "Example:\n"
            ">seq1\nMKFLILFNILV...\n>seq2\nMKTIIALSYIF..."
        )

    # Count sequences
    seq_count = sequences.count(">")
    if seq_count < 2:
        return "Error: At least 2 sequences are required for alignment."

    # Check that mafft is installed
    mafft_path = shutil.which("mafft")
    if not mafft_path:
        return (
            "Error: MAFFT is not installed or not found on PATH.\n"
            "Install from: https://mafft.cbrc.jp/alignment/software/"
        )

    # Write sequences to a temp file
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".fasta", delete=False)
    try:
        tmp.write(sequences)
        tmp.flush()
        tmp.close()

        # Build command
        cmd = [mafft_path] + _ALGORITHMS[algorithm] + [tmp.name]

        # Run MAFFT
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return (
                f"Error: MAFFT timed out after {_TIMEOUT_SECONDS} seconds. "
                f"Try reducing the number of sequences or using a faster "
                f"algorithm (e.g. fftns2)."
            )

        if proc.returncode != 0:
            err = stderr.decode().strip()
            return f"Error: MAFFT failed (exit code {proc.returncode}).\n\n{err}"

        aligned = stdout.decode()
        if not aligned.strip():
            return "Error: MAFFT produced no output."

        return (
            f"MAFFT alignment completed ({seq_count} sequences, "
            f"algorithm: {algorithm}).\n\n{aligned}"
        )

    finally:
        Path(tmp.name).unlink(missing_ok=True)
