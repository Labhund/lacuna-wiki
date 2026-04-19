"""lacuna claims — list claims for adversary evaluation."""
from __future__ import annotations

import sys

import click
import duckdb

from lacuna_wiki.vault import db_path, find_vault_root


def list_claims(
    conn: duckdb.DuckDBPyConnection,
    mode: str,
    page_slug: str | None = None,
) -> list[dict]:
    """Return claims matching the targeting mode.

    mode: "virgin" | "stale" | "page"
    page_slug: required when mode == "page"

    Each dict has keys: claim_id, page_slug, section_name, text,
    source_slug, published_date.
    """
    base = """
        SELECT DISTINCT
            c.id          AS claim_id,
            p.slug        AS page_slug,
            s.name        AS section_name,
            c.text        AS text,
            src.slug      AS source_slug,
            src.published_date
        FROM claims c
        JOIN pages p ON c.page_id = p.id
        LEFT JOIN sections s ON c.section_id = s.id
        LEFT JOIN claim_sources cs ON cs.claim_id = c.id
        LEFT JOIN sources src ON cs.source_id = src.id
        WHERE c.superseded_by IS NULL
    """

    if mode == "virgin":
        sql = base + " AND c.last_adversary_check IS NULL ORDER BY p.slug, c.id"
        rows = conn.execute(sql).fetchall()

    elif mode == "stale":
        # When no sources have registered_at set, MAX(registered_at) IS NULL,
        # so `checked_at < NULL` is always false — stale degrades to virgin.
        # This is correct: stale means "not checked since a new source arrived";
        # if no source has a registered_at, there's nothing to be stale against.
        sql = base + """
          AND (
            c.last_adversary_check IS NULL
            OR c.last_adversary_check < (
                SELECT MAX(registered_at) FROM sources WHERE registered_at IS NOT NULL
            )
          )
          ORDER BY p.slug, c.id
        """
        rows = conn.execute(sql).fetchall()

    elif mode == "page":
        if page_slug is None:
            raise ValueError("page_slug required for mode='page'")
        sql = base + " AND p.slug = ? ORDER BY c.id"
        rows = conn.execute(sql, [page_slug]).fetchall()

    else:
        raise ValueError(f"Unknown mode: {mode!r}. Use: virgin, stale, page")

    return [
        {
            "claim_id": r[0],
            "page_slug": r[1],
            "section_name": r[2],
            "text": r[3],
            "source_slug": r[4],
            "published_date": r[5],
        }
        for r in rows
    ]


@click.command("claims")
@click.option(
    "--mode",
    type=click.Choice(["virgin", "stale", "page"]),
    default="virgin",
    show_default=True,
    help="Targeting mode.",
)
@click.option("--page", "page_slug", default=None, help="Slug for mode=page.")
def claims_command(mode: str, page_slug: str | None) -> None:
    """List claims for adversary evaluation."""
    vault_root = find_vault_root()
    if vault_root is None:
        click.echo("Not inside an lacuna vault.", err=True)
        sys.exit(1)

    db = db_path(vault_root)

    from lacuna_wiki.cli.status import _daemon_api_url
    api_url = _daemon_api_url(vault_root)
    if api_url:
        import json
        import urllib.request
        qs = f"?mode={mode}" + (f"&page={page_slug}" if page_slug else "")
        try:
            with urllib.request.urlopen(f"{api_url}/claims{qs}", timeout=5) as resp:
                results = json.loads(resp.read())["claims"]
        except Exception as exc:
            click.echo(f"Daemon running but claims API unreachable: {exc}", err=True)
            sys.exit(1)
    else:
        from lacuna_wiki.db.connection import get_connection
        conn = get_connection(db, readonly=True)
        try:
            results = list_claims(conn, mode, page_slug=page_slug)
        except ValueError as e:
            click.echo(str(e), err=True)
            sys.exit(1)
        finally:
            conn.close()

    if not results:
        click.echo(f"No claims found (mode={mode}).")
        return

    pages_seen: set[str] = set()
    for r in results:
        if r["page_slug"] not in pages_seen:
            if pages_seen:
                click.echo("")
            click.echo(f"  {r['page_slug']}")
            pages_seen.add(r["page_slug"])
        section = r["section_name"] or "—"
        source = r["source_slug"] or "—"
        date = str(r["published_date"]) if r["published_date"] else "—"
        text_preview = r["text"][:80].replace("\n", " ")
        click.echo(f"  [{r['claim_id']}] {section} | {source} ({date})")
        click.echo(f"        {text_preview!r}")

    click.echo(f"\n{len(results)} claim(s) (mode={mode}).")
