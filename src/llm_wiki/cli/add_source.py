"""llm-wiki add-source — register a source file or URL in the vault."""
from __future__ import annotations

import shutil
import sys
from datetime import date
from pathlib import Path

import click
from rich.console import Console

from llm_wiki.config import load_config
from llm_wiki.db.connection import get_connection
from llm_wiki.sources.chunker import chunk_md
from llm_wiki.sources.embedder import embed_texts
from llm_wiki.sources.extractor import extract_text
from llm_wiki.sources.fetcher import fetch_url_as_markdown, key_from_url, parse_jina_headers
from llm_wiki.sources.youtube import fetch_youtube_transcript, is_youtube_url, key_from_title
from llm_wiki.sources.key import derive_key, derive_key_from_bibtex, key_from_author_year
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
@click.argument("input_path", metavar="PATH_OR_URL")
@click.option("--concept", default="", help="Subdirectory within raw/ (e.g. machine-learning/attention)")
@click.option("--type", "source_type", type=click.Choice(_SOURCE_TYPES), default=None,
              help="Source type (inferred from input if omitted)")
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
    """Register a source file or URL in the wiki."""
    vault_root = find_vault_root()
    if vault_root is None:
        console.print("[red]Not inside an llm-wiki vault.[/red]")
        sys.exit(1)

    target_dir = vault_root / "raw" / concept if concept else vault_root / "raw"
    target_dir.mkdir(parents=True, exist_ok=True)

    config = load_config(vault_root)
    conn = get_connection(db_path(vault_root))

    is_url = input_path.startswith(("http://", "https://"))

    if is_url:
        url = input_path

        if is_youtube_url(url):
            # --- YouTube path: yt-dlp transcript ---
            console.print(f"  Downloading transcript for [bold]{url}[/bold] via yt-dlp...")
            try:
                text, yt_meta = fetch_youtube_transcript(url)
            except RuntimeError as exc:
                console.print(f"[red]Transcript download failed:[/red] {exc}")
                conn.close()
                sys.exit(1)

            # Metadata first — key derivation needs author and year
            final_title = title or yt_meta.get("title")
            final_authors = authors or yt_meta.get("channel")
            final_date: date | None = None
            if pub_date:
                final_date = date.fromisoformat(pub_date)
            elif "upload_date" in yt_meta:
                try:
                    final_date = date.fromisoformat(yt_meta["upload_date"])
                except ValueError:
                    pass

            # Key: author+year+title prefix (matches bibtex convention)
            yt_year = final_date.year if final_date else None
            if final_authors and yt_year:
                key = key_from_author_year(final_authors, yt_year, final_title, conn)
            elif final_title:
                key = key_from_title(final_title, conn)
            else:
                key = key_from_url(url, conn)

            md_dest = target_dir / f"{key}.md"
            md_dest.write_text(text, encoding="utf-8")
            primary_dest = md_dest
            cite_ext = ".md"
            inferred_type = source_type or "transcript"

        else:
            # --- General URL path: Jina reader ---
            console.print(f"  Fetching [bold]{url}[/bold] via Jina reader...")
            try:
                text = fetch_url_as_markdown(url)
            except Exception as exc:
                console.print(f"[red]Fetch failed:[/red] {exc}")
                conn.close()
                sys.exit(1)

            jina_meta = parse_jina_headers(text)

            # Key: prefer bibtex (via DOI) for academic URLs, fall back to URL segment
            bibtex_str: str | None = None
            parsed_meta: dict = {}
            doi = extract_doi(text[:4000])
            if doi:
                console.print(f"  DOI found: {doi} — fetching bibtex from CrossRef...")
                bibtex_str = fetch_bibtex(doi)
                if bibtex_str:
                    parsed_meta = parse_bibtex_fields(bibtex_str)
                    console.print(f"  [green]✓[/green] Bibtex retrieved")

            key = (derive_key_from_bibtex(bibtex_str, conn) if bibtex_str
                   else key_from_url(url, conn))

            md_dest = target_dir / f"{key}.md"
            md_dest.write_text(text, encoding="utf-8")
            if bibtex_str:
                (target_dir / f"{key}.bib").write_text(bibtex_str, encoding="utf-8")

            primary_dest = md_dest
            cite_ext = ".md"
            inferred_type = source_type or "url"

            # Metadata: CLI flags > bibtex > Jina headers
            final_title = title or parsed_meta.get("title") or jina_meta.get("title")
            final_authors = authors or parsed_meta.get("authors")
            final_date = None
            if pub_date:
                final_date = date.fromisoformat(pub_date)
            elif "year" in parsed_meta:
                final_date = date(int(parsed_meta["year"]), 1, 1)
            elif "published_time" in jina_meta:
                try:
                    final_date = date.fromisoformat(jina_meta["published_time"])
                except ValueError:
                    pass

    else:
        # --- File path ---
        src = Path(input_path).resolve()
        if not src.exists():
            console.print(f"[red]File not found:[/red] {src}")
            conn.close()
            sys.exit(1)

        suffix = src.suffix.lower()
        inferred_type = source_type or ("paper" if suffix == ".pdf" else "note")

        console.print(f"  Extracting [bold]{src.name}[/bold]...")
        text = extract_text(src)

        bibtex_str = None
        parsed_meta = {}
        if suffix == ".pdf":
            doi = extract_doi(text[:4000])
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

        final_title = title or parsed_meta.get("title")
        final_authors = authors or parsed_meta.get("authors")
        final_date = None
        if pub_date:
            final_date = date.fromisoformat(pub_date)
        elif "year" in parsed_meta:
            final_date = date(int(parsed_meta["year"]), 1, 1)

    source_type = inferred_type
    console.print(f"  [green]✓[/green] {primary_dest.relative_to(vault_root)}")

    # --- Shared: chunk → embed → register ---
    strategy = _CHUNK_STRATEGY.get(source_type, "paragraph")
    chunks = chunk_md(md_dest, strategy=strategy)
    if not chunks:
        console.print("  [yellow]⚠[/yellow] No chunks produced — file may be empty")
        conn.close()
        return

    console.print(f"  {len(chunks)} chunks — embedding...")
    embeddings = embed_texts(
        [c.text for c in chunks],
        url=config["embed_url"],
        model=config["embed_model"],
    )

    rel_path = str(primary_dest.relative_to(vault_root))
    source_id = register_source(conn, key, rel_path, final_title, final_authors, final_date, source_type)
    register_chunks(conn, source_id, chunks, embeddings)
    conn.close()

    console.print(f"\n  Read:    {md_dest.relative_to(vault_root)}")
    console.print(f"  Cite as: [[{key}{cite_ext}]]", markup=False)
