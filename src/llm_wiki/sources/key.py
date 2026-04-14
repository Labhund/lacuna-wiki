from __future__ import annotations

import re
import duckdb


def derive_key(stem: str, conn: duckdb.DuckDBPyConnection) -> str:
    """Derive canonical key from a filename stem, disambiguating against the sources table."""
    base = re.sub(r"[^a-z0-9]", "", stem.lower())[:40] or "source"
    return _disambiguate(base, conn)


def derive_key_from_bibtex(bibtex: str, conn: duckdb.DuckDBPyConnection) -> str:
    """Build author+year key from a BibTeX string, disambiguating against the sources table."""
    author_m = re.search(r"author\s*=\s*\{(.+?)\}", bibtex, re.IGNORECASE | re.DOTALL)
    year_m = re.search(r"year\s*=\s*\{?(\d{4})\}?", bibtex, re.IGNORECASE)

    if author_m and year_m:
        authors_raw = author_m.group(1)
        year = year_m.group(1)
        # Take first author. BibTeX lists: "Last, First and Last2, First2" or "First Last and ..."
        author_list = [a.strip() for a in authors_raw.split(" and ")]
        if "," in author_list[0]:
            # "Last, First" format — take first listed author's last name
            last_name = author_list[0].split(",")[0].strip()
        else:
            # "First Last" format — sort by last name alphabetically, take first
            last_names = [a.split()[-1] for a in author_list if a.split()]
            last_name = sorted(last_names, key=str.lower)[0]
        base = re.sub(r"[^a-z]", "", last_name.lower()) + year
    else:
        # Fall back to bibtex entry key
        key_m = re.search(r"@\w+\{([^,]+),", bibtex)
        base = re.sub(r"[^a-z0-9]", "", key_m.group(1).lower()) if key_m else "source"

    return _disambiguate(base, conn)


def _disambiguate(base: str, conn: duckdb.DuckDBPyConnection) -> str:
    existing = {row[0] for row in conn.execute("SELECT slug FROM sources").fetchall()}
    if base not in existing:
        return base
    for suffix in "bcdefghijklmnopqrstuvwxyz":
        candidate = base + suffix
        if candidate not in existing:
            return candidate
    raise ValueError(f"Cannot find unique key for '{base}' — too many disambiguations")
