"""BLAST search tools using the NCBI REST API."""

import io
import re
import xml.etree.ElementTree as ET
import zipfile

import httpx

from bdbv_cpi_mcp.config import BLAST_API_URL, BLAST_TOOL_NAME, BLAST_EMAIL
from bdbv_cpi_mcp.server import mcp

_VALID_PROGRAMS = {"blastp", "blastn", "blastx", "tblastn", "tblastx"}
_TIMEOUT = httpx.Timeout(30.0, read=60.0)


@mcp.tool()
async def blast_search(
    query: str,
    program: str = "blastp",
    database: str = "nr",
    expect: float = 10.0,
    matrix: str = "BLOSUM62",
    hitlist_size: int = 50,
) -> str:
    """Submit a BLAST search to NCBI and return a Request ID (RID).

    Use blast_get_results with the returned RID to retrieve results
    once the search completes (typically 30s-5min).

    Args:
        query: Protein or nucleotide sequence (raw or FASTA format)
        program: BLAST program: blastp, blastn, blastx, tblastn, tblastx
        database: Target database, e.g. nr, swissprot, pdb, core_nt, nt
        expect: E-value threshold (default 10.0)
        matrix: Scoring matrix for protein searches (e.g. BLOSUM62, BLOSUM45)
        hitlist_size: Maximum number of hits to return (default 50)
    """
    if program not in _VALID_PROGRAMS:
        return f"Error: Invalid program '{program}'. Must be one of: {', '.join(sorted(_VALID_PROGRAMS))}"

    if not query.strip():
        return "Error: Query sequence cannot be empty."

    params = {
        "CMD": "Put",
        "QUERY": query.strip(),
        "DATABASE": database,
        "PROGRAM": program,
        "EXPECT": str(expect),
        "HITLIST_SIZE": str(hitlist_size),
        "TOOL": BLAST_TOOL_NAME,
    }
    if program in ("blastp", "blastx", "tblastn"):
        params["MATRIX_NAME"] = matrix
    if BLAST_EMAIL:
        params["EMAIL"] = BLAST_EMAIL

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(BLAST_API_URL, data=params)
            resp.raise_for_status()
    except httpx.HTTPError as e:
        return f"Error submitting BLAST search: {e}"

    text = resp.text

    # Extract RID
    rid_match = re.search(r"RID\s*=\s*(\S+)", text)
    if not rid_match:
        return f"Error: Could not extract RID from NCBI response.\n\n{text[:500]}"
    rid = rid_match.group(1)

    # Extract estimated time
    rtoe_match = re.search(r"RTOE\s*=\s*(\d+)", text)
    rtoe = int(rtoe_match.group(1)) if rtoe_match else 60

    return (
        f"BLAST search submitted successfully.\n\n"
        f"  RID: {rid}\n"
        f"  Program: {program}\n"
        f"  Database: {database}\n"
        f"  Estimated wait: ~{rtoe} seconds\n\n"
        f'Use blast_get_results(rid="{rid}") to retrieve results. '
        f"Wait at least {rtoe} seconds before the first check."
    )


@mcp.tool()
async def blast_get_results(
    rid: str,
    format_type: str = "XML2",
    max_hits: int = 10,
) -> str:
    """Retrieve results for a submitted BLAST search.

    Call this after blast_search returns an RID. If the search is still
    running, this will indicate to wait and try again.

    Args:
        rid: Request ID returned by blast_search
        format_type: Output format (XML2 recommended for parsing)
        max_hits: Number of top hits to include in the summary (default 10)
    """
    if not rid.strip():
        return "Error: RID cannot be empty."

    params = {
        "CMD": "Get",
        "RID": rid.strip(),
        "FORMAT_TYPE": format_type,
        "TOOL": BLAST_TOOL_NAME,
    }
    if BLAST_EMAIL:
        params["EMAIL"] = BLAST_EMAIL

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(BLAST_API_URL, params=params)
            resp.raise_for_status()
    except httpx.HTTPError as e:
        return f"Error retrieving BLAST results: {e}"

    # NCBI may return XML2 results inside a ZIP archive
    content = resp.content
    text = ""
    if content[:2] == b"PK":  # ZIP magic bytes
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                # The ZIP contains a wrapper XML with xi:include and the
                # actual results XML (named like <RID>_1.xml). Read the
                # largest XML file which contains the actual hits.
                xml_files = [n for n in zf.namelist() if n.endswith(".xml")]
                if xml_files:
                    # Pick the largest file (the one with actual results)
                    biggest = max(xml_files, key=lambda n: zf.getinfo(n).file_size)
                    text = zf.read(biggest).decode("utf-8")
                else:
                    text = zf.read(zf.namelist()[0]).decode("utf-8")
        except zipfile.BadZipFile:
            text = resp.text
    else:
        text = resp.text

    # Check status
    if "Status=WAITING" in text:
        return f"Search {rid} is still running. Please try again in ~60 seconds."
    if "Status=UNKNOWN" in text:
        return (
            f"Search {rid} not found. The RID may have expired "
            f"(NCBI results expire after ~24 hours) or is invalid."
        )
    if "Status=FAILED" in text:
        return f"Search {rid} failed on the NCBI server."

    # Parse XML2 results
    if format_type == "XML2":
        return _parse_blast_xml2(text, max_hits)

    # For other formats, return raw (truncated)
    if len(text) > 5000:
        return text[:5000] + f"\n\n... (truncated, {len(text)} total characters)"
    return text


def _parse_blast_xml2(xml_text: str, max_hits: int) -> str:
    """Parse BLAST XML2 output into a readable summary."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        # Might not be XML yet (still HTML status page)
        if "Status=WAITING" in xml_text:
            return "Search is still running. Please try again in ~60 seconds."
        return f"Could not parse BLAST response as XML.\n\n{xml_text[:2000]}"

    # Navigate XML2 structure
    ns = ""
    # Try to find BlastOutput2
    report = root.find(f"{ns}BlastOutput2")
    if report is None:
        # Try without namespace, iterate children
        for child in root:
            if "BlastOutput2" in child.tag:
                report = child
                break

    if report is None:
        report = root  # try using root directly

    # Find the search results
    results = []
    hit_count = 0

    # Walk through all Hit elements
    for hit in root.iter():
        if not hit.tag.endswith("Hit"):
            continue
        if hit_count >= max_hits:
            break

        hit_num = _get_text(hit, "num", "?")
        description = ""
        accession = ""

        # Get description from HitDescr
        for descr in hit.iter():
            if descr.tag.endswith("HitDescr"):
                accession = _get_text(descr, "accession", "")
                title = _get_text(descr, "title", "")
                description = title
                break

        # Get best HSP stats
        best_evalue = None
        best_identity = None
        best_align_len = None
        best_query_cover = None

        for hsp in hit.iter():
            if not hsp.tag.endswith("Hsp"):
                continue
            evalue = _get_float(hsp, "evalue")
            identity = _get_float(hsp, "identity")
            align_len = _get_int(hsp, "align-len")
            query_from = _get_int(hsp, "query-from")
            query_to = _get_int(hsp, "query-to")

            if best_evalue is None or (evalue is not None and evalue < best_evalue):
                best_evalue = evalue
                best_identity = identity
                best_align_len = align_len
                if query_from and query_to:
                    best_query_cover = abs(query_to - query_from) + 1

        # Format identity as percentage
        identity_pct = ""
        if best_identity is not None and best_align_len:
            identity_pct = f"{best_identity / best_align_len * 100:.1f}%"

        evalue_str = f"{best_evalue:.2e}" if best_evalue is not None else "N/A"

        hit_count += 1
        results.append(
            f"  {hit_count}. {accession}\n"
            f"     {description[:80]}\n"
            f"     E-value: {evalue_str} | Identity: {identity_pct} | "
            f"Align length: {best_align_len or 'N/A'}"
        )

    if not results:
        return "BLAST search completed but returned no hits."

    # Get query info
    query_title = ""
    for elem in root.iter():
        if elem.tag.endswith("query-title"):
            query_title = elem.text or ""
            break

    header = f"BLAST Results ({hit_count} hits shown)"
    if query_title:
        header += f"\nQuery: {query_title}"

    return header + "\n\n" + "\n\n".join(results)


def _get_text(parent: ET.Element, tag_suffix: str, default: str = "") -> str:
    for child in parent.iter():
        if child.tag.endswith(tag_suffix) and child.text:
            return child.text
    return default


def _get_float(parent: ET.Element, tag_suffix: str) -> float | None:
    text = _get_text(parent, tag_suffix, "")
    try:
        return float(text) if text else None
    except ValueError:
        return None


def _get_int(parent: ET.Element, tag_suffix: str) -> int | None:
    text = _get_text(parent, tag_suffix, "")
    try:
        return int(text) if text else None
    except ValueError:
        return None
