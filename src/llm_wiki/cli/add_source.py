"""llm-wiki add-source — register a source in the vault."""
from __future__ import annotations

import shutil
import sys
from datetime import date
from pathlib import Path

import click
from rich.console import Console

from llm_wiki.db.connection import get_connection
from llm_wiki.sources.chunker import chunk_md
from llm_wiki.sources.embedder import embed_texts
from llm_wiki.sources.extractor import extract_text
from llm_wiki.sources.key import derive_key, derive_key_from_bibtex
from llm_wiki.sources.metadata import extract_doi, fetch_bibtex, parse_bibtex_fields
from llm_wiki.sources.register import register_chunks, register_source
from llm_wiki.vault import db_path, find_vault_root

console = Console()

_SOURCE_TYPES = [
    "paper", "preprint", "book", "blog", "url", "podcast",
    "transcript", "session", "note", "experiment",
]

# Chunking strategy per source type
_CHUNK_STRATEGY = {
    "paper": "heading", "preprint": "heading", "book": "heading",
    "blog": "paragraph", "url": "paragraph",
    "podcast": "heading", "transcript": "heading",
    "session": "paragraph", "note": "paragraph", "experiment": "paragraph",
}


@click.command("add-source")
@click.argument("input_path", metavar="PATH")
@click.option("--concept", default="", help="Subdirectory within raw/ (e.g. machine-learning/attention)")
@click.option("--type", "source_type", type=click.Choice(_SOURCE_TYPES), default=None,
              help="Source type (inferred from extension if omitted)")
@click.option("--date", "pub_date", default=None, metavar="YYYY-MM-DD",
              help="Published date (for sources without discoverable date)")
@click.option("--title", default=None, help="Override title")
@click.option("--authors", default=None, help="Override authors")
def add_source(
    input_path: str,
    concept: str,
    source_type: str | None,
    pub_date: str | None,
    title: str | None,
    authors: str | None,
) -> None:
    """Register a source file in the wiki."""
    vault_root = find_vault_root()
    if vault_root is None:
        console.print("[red]Not inside an llm-wiki vault.[/red]")
        sys.exit(1)

    src = Path(input_path).resolve()
    if not src.exists():
        console.print(f"[red]File not found:[/red] {src}")
        sys.exit(1)

    suffix = src.suffix.lower()
    if source_type is None:
        source_type = "paper" if suffix == ".pdf" else "note"

    target_dir = vault_root / "raw" / concept if concept else vault_root / "raw"
    target_dir.mkdir(parents=True, exist_ok=True)

    conn = get_connection(db_path(vault_root))

    # 1 — Extract text
    console.print(f"  Extracting [bold]{src.name}[/bold]...")
    text = extract_text(src)

    # 2 — Metadata + key
    bibtex_str: str | None = None
    parsed_meta: dict = {}

    if suffix == ".pdf":
        doi = extract_doi(text[:4000])  # scan first ~page for DOI
        if doi:
            console.print(f"  DOI found: {doi} — fetching bibtex from CrossRef...")
            bibtex_str = fetch_bibtex(doi)
            if bibtex_str:
                parsed_meta = parse_bibtex_fields(bibtex_str)
                console.print(f"  [green]✓[/green] Bibtex retrieved")
            else:
                console.print(f"  [yellow]⚠[/yellow] CrossRef returned nothing — using filename as key")

    key = (derive_key_from_bibtex(bibtex_str, conn) if bibtex_str
           else derive_key(src.stem, conn))

    # 3 — Write files
    if suffix == ".pdf":
        primary_dest = target_dir / f"{key}.pdf"
        md_dest = target_dir / f"{key}.md"
        shutil.copy2(src, primary_dest)
        md_dest.write_text(text, encoding="utf-8")
        if bibtex_str:
            (target_dir / f"{key}.bib").write_text(bibtex_str, encoding="utf-8")
        cite_ext = ".pdf"
    else:
        md_dest = target_dir / f"{key}{suffix}"
        shutil.copy2(src, md_dest)
        primary_dest = md_dest
        cite_ext = suffix

    console.print(f"  [green]✓[/green] {primary_dest.relative_to(vault_root)}")

    # 4 — Resolve metadata
    final_title = title or parsed_meta.get("title")
    final_authors = authors or parsed_meta.get("authors")
    final_date: date | None = None
    if pub_date:
        final_date = date.fromisoformat(pub_date)
    elif "year" in parsed_meta:
        final_date = date(int(parsed_meta["year"]), 1, 1)

    # 5 — Chunk + embed
    strategy = _CHUNK_STRATEGY.get(source_type, "paragraph")
    chunks = chunk_md(md_dest, strategy=strategy)
    if not chunks:
        console.print("  [yellow]⚠[/yellow] No chunks produced — file may be empty")
        conn.close()
        return

    console.print(f"  {len(chunks)} chunks — embedding...")
    embeddings = embed_texts([c.text for c in chunks])

    # 6 — Register
    rel_path = str(primary_dest.relative_to(vault_root))
    source_id = register_source(conn, key, rel_path, final_title, final_authors, final_date, source_type)
    register_chunks(conn, source_id, chunks, embeddings)
    conn.close()

    # 7 — Report
    console.print(f"\n  Read:    {md_dest.relative_to(vault_root)}")
    console.print(f"  Cite as: [[{key}{cite_ext}]]", markup=False)
