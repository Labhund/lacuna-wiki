"""lacuna add-source — register a source file or URL in the vault.

Writes extracted text + metadata to raw/. The daemon's watchdog picks up
new files and handles chunking, embedding, and DB registration — no
DuckDB connection needed in this process.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

import click
from rich.console import Console

from lacuna_wiki.config import load_config
from lacuna_wiki.sources.chunker import chunk_md
from lacuna_wiki.sources.extractor import extract_text
from lacuna_wiki.sources.fetcher import (
    arxiv_id_from_url, fetch_rxiv_html_meta, fetch_rxiv_pdf,
    fetch_url_as_markdown, is_rxiv_url, key_from_url, parse_jina_headers,
    rxiv_pdf_url,
)
from lacuna_wiki.sources.youtube import fetch_youtube_transcript, is_youtube_url, key_from_title
from lacuna_wiki.sources.key import derive_key, derive_key_from_bibtex, key_from_author_year
from lacuna_wiki.sources.metadata import extract_doi, fetch_bibtex, parse_bibtex_fields
from lacuna_wiki.vault import find_vault_root

console = Console()

_SOURCE_TYPES = [
    "paper", "preprint", "book", "blog", "url", "podcast",
    "transcript", "session", "note", "experiment",
]

# Chunking strategy per source type (used for the chunk count display only;
# actual chunking is done by the daemon)
_CHUNK_STRATEGY = {
    "paper": "heading", "preprint": "heading", "book": "heading",
    "blog": "paragraph", "url": "paragraph",
    "podcast": "heading", "transcript": "heading",
    "session": "paragraph", "note": "paragraph", "experiment": "paragraph",
}

_BIB_TYPE_NOTES = {
    "transcript": "YouTube video transcript",
    "blog": "Blog post",
    "url": "Web page",
    "podcast": "Podcast transcript",
    "note": "Personal note",
    "session": "Research session",
    "experiment": "Experiment log",
}


def _write_bib_sidecar(
    dest_dir: Path,
    key: str,
    title: str | None,
    authors: str | None,
    pub_date: "date | None",
    source_type: str,
    url: str | None = None,
) -> None:
    """Write a minimal BibTeX .bib sidecar for non-PDF sources."""
    lines = [f"@misc{{{key},"]
    if authors:
        lines.append(f"  author       = {{{authors}}},")
    if title:
        lines.append(f"  title        = {{{title}}},")
    if pub_date:
        lines.append(f"  year         = {{{pub_date.year}}},")
        lines.append(f"  month        = {{{pub_date.month}}},")
    if url:
        lines.append(f"  howpublished = {{\\url{{{url}}}}},")
    note = _BIB_TYPE_NOTES.get(source_type, "")
    if note:
        lines.append(f"  note         = {{{note}}}")
    lines.append("}")
    (dest_dir / f"{key}.bib").write_text("\n".join(lines) + "\n", encoding="utf-8")


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
        console.print("[red]Not inside an lacuna vault.[/red]")
        sys.exit(1)

    target_dir = vault_root / "raw" / concept if concept else vault_root / "raw"
    target_dir.mkdir(parents=True, exist_ok=True)

    config = load_config(vault_root)

    # Check embedding server reachability — daemon needs it for registration
    from lacuna_wiki.cli._warn import warn_embed_unreachable
    from lacuna_wiki.sources.embedder import check_embed_server
    check = check_embed_server(config["embed_url"], config["embed_model"])
    if not check.ok:
        warn_embed_unreachable(check.url, check.model, check.error)
        console.print("[yellow]Daemon will not be able to embed this source until the "
                      "embedding server is available.[/yellow]")

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
                sys.exit(1)

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

            yt_year = final_date.year if final_date else None
            if final_authors and yt_year:
                key = key_from_author_year(final_authors, yt_year, final_title, conn=None)
            elif final_title:
                key = key_from_title(final_title, conn=None)
            else:
                key = key_from_url(url, conn=None)

            md_dest = target_dir / f"{key}.md"
            md_dest.write_text(text, encoding="utf-8")
            _write_bib_sidecar(target_dir, key, final_title, final_authors, final_date,
                               source_type or "transcript", url=url)
            primary_dest = md_dest
            cite_ext = ".md"
            inferred_type = source_type or "transcript"

        elif is_rxiv_url(url):
            # --- rxiv path: download PDF directly, extract with pdftotext ---
            pdf_url = rxiv_pdf_url(url)
            console.print(f"  Downloading PDF from [bold]{pdf_url}[/bold]...")
            try:
                pdf_bytes = fetch_rxiv_pdf(url)
            except Exception as exc:
                console.print(f"[red]PDF download failed:[/red] {exc}")
                sys.exit(1)

            tmp = Path(tempfile.mktemp(suffix=".pdf"))
            try:
                tmp.write_bytes(pdf_bytes)
                text = extract_text(tmp)
            finally:
                tmp.unlink(missing_ok=True)

            bibtex_str = None
            parsed_meta: dict = {}
            doi = extract_doi(text[:4000])
            if not doi:
                arxiv_id = arxiv_id_from_url(url)
                if arxiv_id:
                    doi = f"10.48550/arXiv.{arxiv_id}"
            if doi:
                console.print(f"  DOI: {doi} — fetching bibtex from CrossRef...")
                bibtex_str = fetch_bibtex(doi)
                if bibtex_str:
                    parsed_meta = parse_bibtex_fields(bibtex_str)
                    console.print(f"  [green]✓[/green] Bibtex retrieved")
                else:
                    console.print(f"  [yellow]⚠[/yellow] CrossRef returned nothing")

            html_meta: dict = {}
            if bibtex_str:
                key = derive_key_from_bibtex(bibtex_str, conn=None)
            else:
                html_meta = fetch_rxiv_html_meta(url)
                author = html_meta.get("first_author_last", "")
                year = html_meta.get("year", "")
                if author and year:
                    from lacuna_wiki.sources.key import _disambiguate
                    key = _disambiguate(f"{author}{year}", conn=None)
                    console.print(f"  [dim]Key from page meta: {key}[/dim]")
                else:
                    key = key_from_url(url, conn=None)

            pdf_dest = target_dir / f"{key}.pdf"
            md_dest = target_dir / f"{key}.md"
            pdf_dest.write_bytes(pdf_bytes)
            md_dest.write_text(text, encoding="utf-8")
            if bibtex_str:
                (target_dir / f"{key}.bib").write_text(bibtex_str, encoding="utf-8")
            else:
                _bib_title = title or html_meta.get("title")
                _bib_authors = authors or html_meta.get("authors")
                _bib_date = None
                if pub_date:
                    _bib_date = date.fromisoformat(pub_date)
                elif html_meta.get("year"):
                    _bib_date = date(int(html_meta["year"]), 1, 1)
                _write_bib_sidecar(target_dir, key, _bib_title, _bib_authors,
                                   _bib_date, source_type or "preprint", url=url)

            primary_dest = pdf_dest
            cite_ext = ".pdf"
            inferred_type = source_type or "preprint"
            final_title = title or parsed_meta.get("title") or html_meta.get("title")
            final_authors = authors or parsed_meta.get("authors") or html_meta.get("authors")
            final_date = None
            if pub_date:
                final_date = date.fromisoformat(pub_date)
            elif "year" in parsed_meta:
                final_date = date(int(parsed_meta["year"]), 1, 1)
            elif html_meta.get("year"):
                final_date = date(int(html_meta["year"]), 1, 1)

        else:
            # --- General URL path: Jina reader ---
            console.print(f"  Fetching [bold]{url}[/bold] via Jina reader...")
            try:
                text = fetch_url_as_markdown(url)
            except Exception as exc:
                console.print(f"[red]Fetch failed:[/red] {exc}")
                sys.exit(1)

            jina_meta = parse_jina_headers(text)

            bibtex_str: str | None = None
            parsed_meta: dict = {}
            doi = extract_doi(text[:4000])
            if doi:
                console.print(f"  DOI found: {doi} — fetching bibtex from CrossRef...")
                bibtex_str = fetch_bibtex(doi)
                if bibtex_str:
                    parsed_meta = parse_bibtex_fields(bibtex_str)
                    console.print(f"  [green]✓[/green] Bibtex retrieved")

            from lacuna_wiki.sources.key import _disambiguate
            if bibtex_str:
                key = derive_key_from_bibtex(bibtex_str, conn=None)
            else:
                key = key_from_url(url, conn=None)

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

            md_dest = target_dir / f"{key}.md"
            md_dest.write_text(text, encoding="utf-8")
            if bibtex_str:
                (target_dir / f"{key}.bib").write_text(bibtex_str, encoding="utf-8")
            else:
                _write_bib_sidecar(target_dir, key, final_title, final_authors, final_date,
                                   source_type or "url", url=url)

            primary_dest = md_dest
            cite_ext = ".md"
            inferred_type = source_type or "url"

    else:
        # --- File path ---
        src = Path(input_path).resolve()
        if not src.exists():
            console.print(f"[red]File not found:[/red] {src}")
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

        if bibtex_str:
            key = derive_key_from_bibtex(bibtex_str, conn=None)
        else:
            key = derive_key(src.stem, conn=None)

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

    # Count chunks for display only — daemon handles actual embedding + registration
    strategy = _CHUNK_STRATEGY.get(source_type, "paragraph")
    chunks = chunk_md(md_dest, strategy=strategy)
    chunk_count = len(chunks)
    del chunks  # free memory — daemon re-chunks from file

    console.print(f"\n  Read:    {md_dest.relative_to(vault_root)}")
    console.print(f"  Cite as: [[{key}{cite_ext}]]", markup=False)
    console.print(f"  [dim]{chunk_count} chunks — daemon will embed and register[/dim]")
