# lacuna-synthesise Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `lacuna synthesise` — an agent-driven workflow that reads pending synthesis clusters, writes unified synthesis wiki pages from their member pages, marks members with a machine-parseable notice, and reopens clusters when new sources join.

**Architecture:** Mirrors `lacuna-sweep` end-to-end. The `wiki()` MCP tool gains `synthesise` and `commit` params dispatched through a new `mcp/synthesise.py` module. The daemon gains `%% synthesised-into: [[slug]] %%` notice detection, a shared `_strip_obsidian_comments` helper that gates body-hash computation (so notices don't trigger spurious re-indexing), and two schema v4 columns. The `lacuna-synthesise` skill mirrors `lacuna-sweep` in structure and wording.

**Tech Stack:** DuckDB 1.5.x, Python, FastMCP, Click, existing lacuna_wiki patterns.

---

## File Map

| Action | Path |
|---|---|
| Modify | `src/lacuna_wiki/db/schema.py` |
| Modify | `src/lacuna_wiki/daemon/sync.py` |
| Modify | `src/lacuna_wiki/mcp/audit.py` |
| Modify | `src/lacuna_wiki/mcp/server.py` |
| Create | `src/lacuna_wiki/mcp/synthesise.py` |
| Modify | `src/lacuna_wiki/cli/status.py` |
| Create | `src/lacuna_wiki/skills/synthesise.md` |
| Modify | `tests/test_schema.py` |
| Modify | `tests/test_daemon_integration.py` |
| Modify | `tests/test_mcp_integration.py` |
| Create | `tests/test_synthesise.py` |

---

## Task 1: Schema v4

**Files:**
- Modify: `src/lacuna_wiki/db/schema.py`
- Modify: `tests/test_schema.py`

### Steps

- [ ] **Write failing tests**

```python
def test_v4_pages_has_synthesised_into(vault):
    conn = duckdb.connect(str(db_path(vault)))
    init_db(conn)
    cols = {r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='pages'"
    ).fetchall()}
    assert "synthesised_into" in cols

def test_v4_clusters_has_synthesis_page_slug(vault):
    conn = duckdb.connect(str(db_path(vault)))
    init_db(conn)
    cols = {r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='synthesis_clusters'"
    ).fetchall()}
    assert "synthesis_page_slug" in cols

def test_init_db_is_idempotent_v4(vault):
    conn = duckdb.connect(str(db_path(vault)))
    init_db(conn)
    init_db(conn)  # second call must not raise
    tables = conn.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='main'"
    ).fetchone()[0]
    assert tables >= 12  # v4 adds no new tables; guard against regression not exact count
```

- [ ] **Run tests to verify they fail**

```bash
cd .worktrees/synthesise && python -m pytest tests/test_schema.py::test_v4_pages_has_synthesised_into -v
```
Expected: FAIL — column does not exist yet.

- [ ] **Add `_migrate_v4_synthesise` to `schema.py`**

```python
_CURRENT_VERSION = 4

def _migrate_v4_synthesise(conn: duckdb.DuckDBPyConnection) -> None:
    """v4: synthesised_into on pages; synthesis_page_slug on synthesis_clusters."""
    try:
        conn.execute("ALTER TABLE pages ADD COLUMN synthesised_into TEXT")
    except Exception:
        pass  # already exists
    try:
        conn.execute(
            "ALTER TABLE synthesis_clusters ADD COLUMN synthesis_page_slug TEXT"
        )
    except Exception:
        pass  # already exists
    conn.execute("UPDATE schema_version SET version=4")
```

In `init_db`, add inside the version-check block:
```python
if version < 4:
    _migrate_v4_synthesise(conn)
```

- [ ] **Run tests to verify they pass**

```bash
python -m pytest tests/test_schema.py::test_v4_pages_has_synthesised_into tests/test_schema.py::test_v4_clusters_has_synthesis_page_slug tests/test_schema.py::test_init_db_is_idempotent_v4 -v
```
Expected: PASS.

- [ ] **Commit**

```bash
git add src/lacuna_wiki/db/schema.py tests/test_schema.py
git commit -m "feat: schema v4 — synthesised_into on pages, synthesis_page_slug on clusters"
```

---

## Task 2: Daemon — strip Obsidian comments + notice detection

**Files:**
- Modify: `src/lacuna_wiki/daemon/sync.py`
- Modify: `tests/test_daemon_integration.py`

The `%% ... %%` Obsidian comment block must be invisible to the body hash so adding a synthesised-into notice does not trigger a re-index. A shared helper strips all `%%...%%` blocks before hashing. The same regex detects `synthesised_into` value and writes it to the DB on sync.

`_body_hash` already exists in `sync.py` as a one-liner. **Replace it** — do not add a second function alongside it.

The `synthesised_into` update goes unconditionally after the upsert block (after both the INSERT and UPDATE paths), not inside either branch. The correct placement: immediately after the `conn.commit()` call that follows the upsert, before `_update_mean_embedding`.

### Steps

- [ ] **Write failing tests**

```python
def test_body_hash_ignores_obsidian_comments(vault):
    """Adding a %% notice %% must not change the body hash."""
    from lacuna_wiki.daemon.sync import sync_page
    from lacuna_wiki.vault import db_path
    import duckdb
    from pathlib import Path

    conn = duckdb.connect(str(db_path(vault)))
    init_db(conn)

    page = vault / "wiki" / "concept.md"
    page.write_text("# concept\n\n## S1\n\n" + ("Word " * 60) + "\n")
    sync_page(conn, vault, Path("wiki/concept.md"), fake_embed)
    h1 = conn.execute("SELECT body_hash FROM pages WHERE slug='concept'").fetchone()[0]

    page.write_text(
        "# concept\n\n%% synthesised-into: [[synthesis-concept]] %%\n\n## S1\n\n"
        + ("Word " * 60) + "\n"
    )
    sync_page(conn, vault, Path("wiki/concept.md"), fake_embed)
    h2 = conn.execute("SELECT body_hash FROM pages WHERE slug='concept'").fetchone()[0]

    assert h1 == h2, "body hash must not change when only a %% notice %% is added"

def test_sync_detects_synthesised_into(vault):
    from lacuna_wiki.daemon.sync import sync_page
    from lacuna_wiki.vault import db_path
    import duckdb
    from pathlib import Path

    conn = duckdb.connect(str(db_path(vault)))
    init_db(conn)

    page = vault / "wiki" / "concept.md"
    page.write_text(
        "# concept\n\n%% synthesised-into: [[synthesis-concept]] %%\n\n## S1\n\nContent.\n"
    )
    sync_page(conn, vault, Path("wiki/concept.md"), fake_embed)
    row = conn.execute("SELECT synthesised_into FROM pages WHERE slug='concept'").fetchone()
    assert row[0] == "synthesis-concept"

def test_sync_detects_synthesised_into_case_insensitive(vault):
    """Notice detection must be case-insensitive."""
    from lacuna_wiki.daemon.sync import sync_page
    from lacuna_wiki.vault import db_path
    import duckdb
    from pathlib import Path

    conn = duckdb.connect(str(db_path(vault)))
    init_db(conn)

    page = vault / "wiki" / "concept2.md"
    page.write_text(
        "# concept2\n\n%% Synthesised-Into: [[synthesis-concept]] %%\n\n## S1\n\nContent.\n"
    )
    sync_page(conn, vault, Path("wiki/concept2.md"), fake_embed)
    row = conn.execute("SELECT synthesised_into FROM pages WHERE slug='concept2'").fetchone()
    assert row[0] == "synthesis-concept"
```

- [ ] **Run tests to verify they fail**

```bash
python -m pytest tests/test_daemon_integration.py::test_body_hash_ignores_obsidian_comments tests/test_daemon_integration.py::test_sync_detects_synthesised_into -v
```
Expected: FAIL.

- [ ] **Replace `_body_hash` and add helpers in `sync.py`**

Add to imports: `import re` (if not already present).

Replace the existing `_body_hash` one-liner and add helpers directly above it:

```python
_OBSIDIAN_COMMENT_RE = re.compile(r'%%.*?%%', re.DOTALL)
_SYNTHESISED_INTO_RE = re.compile(
    r'%%\s*synthesised-into:\s*\[\[([^\]]+)\]\]\s*%%', re.IGNORECASE
)

def _strip_obsidian_comments(text: str) -> str:
    return _OBSIDIAN_COMMENT_RE.sub('', text)

def _body_hash(body: str) -> str:
    return hashlib.sha256(_strip_obsidian_comments(body).encode("utf-8")).hexdigest()[:24]
```

After `conn.commit()` and before `_update_mean_embedding(conn, page_id)` in `sync_page`, add:

```python
m = _SYNTHESISED_INTO_RE.search(body)
synthesised_into = m.group(1) if m else None
conn.execute(
    "UPDATE pages SET synthesised_into=? WHERE slug=?",
    [synthesised_into, slug],
)
```

- [ ] **Run tests to verify they pass**

```bash
python -m pytest tests/test_daemon_integration.py::test_body_hash_ignores_obsidian_comments tests/test_daemon_integration.py::test_sync_detects_synthesised_into tests/test_daemon_integration.py::test_sync_detects_synthesised_into_case_insensitive -v
```
Expected: PASS.

- [ ] **Commit**

```bash
git add src/lacuna_wiki/daemon/sync.py tests/test_daemon_integration.py
git commit -m "feat: strip Obsidian comments from body hash; detect synthesised-into notice on sync"
```

---

## Task 3: Audit — filter synthesised pages from sweep + cluster reopen

**Files:**
- Modify: `src/lacuna_wiki/mcp/audit.py`
- Modify: `tests/test_audit.py`

Synthesised pages must be invisible to sweep. `_sweep_queue` filters them out. `_synthesis_candidates` excludes them from candidate pools. `_upsert_cluster` reopens a completed cluster when any proposed member matches its `synthesis_page_slug`.

When reopening a completed cluster, update `concept_label` and `agent_rationale` to the incoming values — a more descriptive label from a later sweep should win. Known limitation: if a member slug matches `synthesis_page_slug` in multiple completed clusters (edge case: post-merge revision cycle), only the first match is reopened.

### Steps

- [ ] **Write failing tests**

```python
def test_sweep_queue_excludes_synthesised_pages(vault):
    from lacuna_wiki.mcp.audit import vault_audit
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "concept.md",
                   "# concept\n\n## S\n\n" + ("Word " * 120) + "\n")
    conn.execute("UPDATE pages SET synthesised_into='synthesis-concept' WHERE slug='concept'")
    result = vault_audit(conn)
    # sweep queue must appear in output but concept must not be listed in it
    assert "sweep queue" in result.lower()
    lines = result.split("\n")
    in_queue = False
    queue_lines = []
    for line in lines:
        if "sweep queue" in line.lower():
            in_queue = True
        elif in_queue and line.strip() == "":
            break
        elif in_queue:
            queue_lines.append(line)
    assert not any("concept" in l for l in queue_lines), \
        "synthesised page must not appear in sweep queue"

def test_upsert_cluster_reopens_completed_cluster(vault):
    from lacuna_wiki.mcp.audit import mark_swept
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "page-a.md",
                   "# page-a\n\n## S\n\n" + ("Word " * 120) + "\n")
    write_and_sync(vault_root, conn, "page-b.md",
                   "# page-b\n\n## S\n\n" + ("Word " * 120) + "\n")
    # Create and complete a cluster; note the cluster id for assertions
    mark_swept(conn, "page-a", cluster={
        "members": ["page-a", "page-b"],
        "label": "Test",
        "rationale": "Test cluster",
    })
    cid = conn.execute(
        "SELECT id FROM synthesis_clusters WHERE concept_label='Test'"
    ).fetchone()[0]
    conn.execute(
        "UPDATE synthesis_clusters SET status='completed', synthesis_page_slug='synthesis-test'"
        " WHERE id=?", [cid]
    )
    # Sweep a new page that includes the synthesis page slug as a proposed member
    write_and_sync(vault_root, conn, "page-c.md",
                   "# page-c\n\n## S\n\n" + ("Word " * 120) + "\n")
    mark_swept(conn, "page-c", cluster={
        "members": ["page-c", "synthesis-test"],
        "label": "Test extended",
        "rationale": "New member joins existing synthesis",
    })
    row = conn.execute(
        "SELECT status, concept_label FROM synthesis_clusters WHERE id=?", [cid]
    ).fetchone()
    assert row[0] == "pending", "completed cluster must be reopened when synthesis page is a proposed member"
    assert row[1] == "Test extended", "label should be updated to the incoming value"
    members = {r[0] for r in conn.execute(
        "SELECT slug FROM synthesis_cluster_members WHERE cluster_id=?", [cid]
    ).fetchall()}
    assert "page-c" in members
```

- [ ] **Run tests to verify they fail**

```bash
python -m pytest tests/test_audit.py::test_sweep_queue_excludes_synthesised_pages tests/test_audit.py::test_upsert_cluster_reopens_completed_cluster -v
```
Expected: FAIL.

- [ ] **Update `_sweep_queue` in `audit.py`**

Add `AND p.synthesised_into IS NULL` to the WHERE clause of the inner subquery in `_sweep_queue`.

- [ ] **Update `_synthesis_candidates` to exclude synthesised pages**

In the pass-1 query, add `AND p1.synthesised_into IS NULL` and `AND p2.synthesised_into IS NULL` to the respective JOIN conditions on pages.

- [ ] **Update `_upsert_cluster` to reopen completed clusters**

After the existing union-find check for pending clusters, add:

```python
# Check if any proposed member is the synthesis_page_slug of a completed cluster
for member in members:
    row = conn.execute(
        "SELECT id FROM synthesis_clusters WHERE synthesis_page_slug=? AND status='completed'",
        [member],
    ).fetchone()
    if row is not None:
        cluster_id = row[0]
        conn.execute(
            "UPDATE synthesis_clusters SET status='pending', concept_label=?, agent_rationale=?"
            " WHERE id=?",
            [label, rationale, cluster_id],
        )
        for m in members:
            conn.execute(
                "INSERT INTO synthesis_cluster_members (cluster_id, slug) VALUES (?,?)"
                " ON CONFLICT DO NOTHING",
                [cluster_id, m],
            )
        return
```

- [ ] **Run tests to verify they pass**

```bash
python -m pytest tests/test_audit.py -v
```
Expected: all pass.

- [ ] **Commit**

```bash
git add src/lacuna_wiki/mcp/audit.py tests/test_audit.py
git commit -m "feat: filter synthesised pages from sweep; reopen completed clusters on new member"
```

---

## Task 4: MCP synthesise module

**Files:**
- Create: `src/lacuna_wiki/mcp/synthesise.py`
- Create: `tests/test_synthesise.py`

Three functions exposed through `wiki()`: `cluster_queue`, `cluster_detail`, `commit_synthesis`.

`cluster_queue` shows a diversity note for all three cases: 0 sources (unknown), 1 source (warning), N sources (count).

`commit_synthesis` docstring must note: member pages receive their `%% synthesised-into %%` notice via the agent (Steps 1d), not here. The daemon sets `synthesised_into` asynchronously on next sync. There is a window between `commit_synthesis` and daemon sync where the cluster is completed but member pages still appear in the sweep queue — the skill's step order (1d before 1e) mitigates this.

Variable names: the raw value from `SUM(token_count)` is `token_count`; multiply by 0.75 to estimate words and label it `approx_words`.

### Steps

- [ ] **Write failing tests**

```python
"""Tests for mcp/synthesise.py — cluster_queue, cluster_detail, commit_synthesis."""
import duckdb
import pytest
from pathlib import Path

from lacuna_wiki.db.schema import init_db
from lacuna_wiki.daemon.sync import sync_page
from lacuna_wiki.vault import db_path, state_dir_for


def fake_embed(texts):
    return [[1.0] + [0.0] * 767 for _ in texts]


@pytest.fixture
def vault(tmp_path):
    vault_root = tmp_path / "vault"
    (vault_root / "wiki").mkdir(parents=True)
    state = state_dir_for(vault_root)
    state.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path(vault_root)))
    init_db(conn)
    try:
        conn.execute("LOAD fts")
    except Exception:
        pass
    return vault_root, conn


def write_and_sync(vault_root, conn, name, content):
    path = vault_root / "wiki" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    sync_page(conn, vault_root, Path("wiki") / name, fake_embed)


def make_cluster(conn, members, label="Test cluster"):
    from lacuna_wiki.mcp.audit import mark_swept
    mark_swept(conn, members[0], cluster={
        "members": members,
        "label": label,
        "rationale": "Test rationale.",
    })
    return conn.execute(
        "SELECT id FROM synthesis_clusters WHERE concept_label=?", [label]
    ).fetchone()[0]


def test_cluster_queue_returns_pending(vault):
    from lacuna_wiki.mcp.synthesise import cluster_queue
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "a.md", "# a\n\n## S\n\n" + "W " * 60)
    write_and_sync(vault_root, conn, "b.md", "# b\n\n## S\n\n" + "W " * 60)
    make_cluster(conn, ["a", "b"])
    result = cluster_queue(conn)
    assert "Test cluster" in result
    assert "pending" in result.lower() or "1" in result


def test_cluster_queue_empty(vault):
    from lacuna_wiki.mcp.synthesise import cluster_queue
    _, conn = vault
    result = cluster_queue(conn)
    assert "0" in result or "no pending" in result.lower()


def test_cluster_queue_shows_diversity_note_zero(vault):
    from lacuna_wiki.mcp.synthesise import cluster_queue
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "a.md", "# a\n\n## S\n\nContent.\n")
    make_cluster(conn, ["a"])
    result = cluster_queue(conn)
    assert "unknown" in result.lower() or "source" in result.lower()


def test_cluster_detail_returns_members(vault):
    from lacuna_wiki.mcp.synthesise import cluster_detail
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "a.md", "# a\n\n## S\n\nContent.\n")
    write_and_sync(vault_root, conn, "b.md", "# b\n\n## S\n\nContent.\n")
    cid = make_cluster(conn, ["a", "b"])
    result = cluster_detail(conn, cid)
    assert "a" in result
    assert "b" in result
    assert "suggested slug" in result.lower()


def test_cluster_detail_shows_source_diversity(vault):
    from lacuna_wiki.mcp.synthesise import cluster_detail
    vault_root, conn = vault
    conn.execute(
        "INSERT INTO sources (slug, path, title, source_type)"
        " VALUES ('src1', 'raw/s.pdf', 'Source One', 'paper')"
    )
    write_and_sync(vault_root, conn, "a.md", "# a\n\n## S\n\nCite [[src1.pdf]].\n")
    write_and_sync(vault_root, conn, "b.md", "# b\n\n## S\n\nCite [[src1.pdf]].\n")
    cid = make_cluster(conn, ["a", "b"])
    result = cluster_detail(conn, cid)
    assert "source" in result.lower()
    assert "single-source" in result.lower() or "1" in result


def test_cluster_detail_existing_synthesis_page(vault):
    from lacuna_wiki.mcp.synthesise import cluster_detail
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "a.md", "# a\n\n## S\n\nContent.\n")
    write_and_sync(vault_root, conn, "b.md", "# b\n\n## S\n\nContent.\n")
    cid = make_cluster(conn, ["a", "b"])
    conn.execute(
        "UPDATE synthesis_clusters SET synthesis_page_slug='synth-ab' WHERE id=?", [cid]
    )
    result = cluster_detail(conn, cid)
    assert "synth-ab" in result
    assert "existing synthesis page" in result.lower()


def test_commit_synthesis_marks_completed(vault):
    from lacuna_wiki.mcp.synthesise import commit_synthesis
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "a.md", "# a\n\n## S\n\nContent.\n")
    write_and_sync(vault_root, conn, "b.md", "# b\n\n## S\n\nContent.\n")
    cid = make_cluster(conn, ["a", "b"])
    result = commit_synthesis(conn, cid, "synthesis-ab")
    assert "synthesis-ab" in result
    row = conn.execute(
        "SELECT status, synthesis_page_slug FROM synthesis_clusters WHERE id=?", [cid]
    ).fetchone()
    assert row[0] == "completed"
    assert row[1] == "synthesis-ab"


def test_commit_synthesis_not_found(vault):
    from lacuna_wiki.mcp.synthesise import commit_synthesis
    _, conn = vault
    result = commit_synthesis(conn, 9999, "slug")
    assert "not found" in result.lower() or "error" in result.lower()
```

- [ ] **Run tests to verify they fail**

```bash
python -m pytest tests/test_synthesise.py -v
```
Expected: FAIL — module does not exist.

- [ ] **Create `src/lacuna_wiki/mcp/synthesise.py`**

```python
"""lacuna MCP — synthesise operations: cluster_queue, cluster_detail, commit_synthesis."""
from __future__ import annotations

import re
import duckdb

_SLUG_RE = re.compile(r'[^a-z0-9]+')


def _label_to_slug(label: str) -> str:
    return _SLUG_RE.sub('-', label.lower()).strip('-')


def _source_diversity(conn: duckdb.DuckDBPyConnection, slugs: list[str]) -> int:
    """Count distinct sources cited across member pages via links to registered source slugs."""
    if not slugs:
        return 0
    placeholders = ','.join('?' * len(slugs))
    row = conn.execute(f"""
        SELECT COUNT(DISTINCT l.target_slug)
        FROM links l
        JOIN pages p ON l.source_page_id = p.id
        JOIN sources s ON l.target_slug = s.slug
        WHERE p.slug IN ({placeholders})
    """, slugs).fetchone()
    return row[0] if row else 0


def _diversity_note(source_count: int) -> str:
    if source_count == 0:
        return "source diversity: unknown (no source links detected)"
    if source_count == 1:
        return "source diversity: 1 distinct source  ⚠ single-source cluster"
    return f"source diversity: {source_count} distinct sources"


def cluster_queue(conn: duckdb.DuckDBPyConnection) -> str:
    rows = conn.execute(
        "SELECT id, concept_label FROM synthesis_clusters WHERE status='pending' ORDER BY id"
    ).fetchall()
    if not rows:
        return "Synthesis queue: 0 pending clusters."

    lines = [f"Synthesis queue: {len(rows)} pending cluster(s).", ""]
    for cid, label in rows:
        members = conn.execute(
            "SELECT slug FROM synthesis_cluster_members WHERE cluster_id=?", [cid]
        ).fetchall()
        member_slugs = [m[0] for m in members]
        source_count = _source_diversity(conn, member_slugs)
        lines.append(
            f"  cluster {cid}: \"{label}\" — {len(member_slugs)} members"
            f" — {_diversity_note(source_count)}"
        )
    return "\n".join(lines)


def cluster_detail(conn: duckdb.DuckDBPyConnection, cluster_id: int) -> str:
    row = conn.execute(
        "SELECT concept_label, agent_rationale, status, synthesis_page_slug "
        "FROM synthesis_clusters WHERE id=?",
        [cluster_id],
    ).fetchone()
    if row is None:
        return f"Cluster {cluster_id} not found."

    label, rationale, status, existing_slug = row
    members = conn.execute(
        "SELECT slug FROM synthesis_cluster_members WHERE cluster_id=?",
        [cluster_id],
    ).fetchall()
    member_slugs = [m[0] for m in members]

    lines = [
        f"cluster {cluster_id} — \"{label}\"",
        f"status: {status}",
        f"rationale: {rationale or '(none)'}",
        "",
        f"members ({len(member_slugs)}):",
    ]

    for slug in member_slugs:
        page = conn.execute(
            "SELECT title, synthesised_into FROM pages WHERE slug=?", [slug]
        ).fetchone()
        if page:
            title, synth = page
            synth_note = f"  [synthesised into [[{synth}]]]" if synth else ""
            token_count = conn.execute(
                "SELECT COALESCE(SUM(token_count), 0) FROM sections WHERE page_id="
                "(SELECT id FROM pages WHERE slug=?)", [slug]
            ).fetchone()[0]
            approx_words = int(token_count * 0.75)
            lines.append(
                f"  [[{slug}]] — \"{title or slug}\" — ~{approx_words} words{synth_note}"
            )
        else:
            lines.append(f"  [[{slug}]] — (ghost page)")

    source_count = _source_diversity(conn, member_slugs)
    lines.append("")
    lines.append(_diversity_note(source_count))
    lines.append("")
    lines.append(f"suggested slug: {_label_to_slug(label)}")

    if existing_slug:
        lines.append(f"existing synthesis page: [[{existing_slug}]] (revision run)")
    else:
        lines.append("existing synthesis page: none")

    return "\n".join(lines)


def commit_synthesis(
    conn: duckdb.DuckDBPyConnection,
    cluster_id: int,
    slug: str,
) -> str:
    """Mark cluster completed and record synthesis page slug.

    Note: member pages receive their %% synthesised-into %% notice via the agent
    (skill Step 1d), not here. The daemon sets synthesised_into asynchronously on
    next sync. There is a brief window where the cluster is completed but member
    pages still appear in the sweep queue — the skill's step order (notice before
    commit) mitigates this.
    """
    row = conn.execute(
        "SELECT id FROM synthesis_clusters WHERE id=?", [cluster_id]
    ).fetchone()
    if row is None:
        return f"Error: cluster {cluster_id} not found."

    conn.execute(
        "UPDATE synthesis_clusters SET status='completed', synthesis_page_slug=? WHERE id=?",
        [slug, cluster_id],
    )
    return f"Committed: cluster {cluster_id} marked completed. Synthesis page: [[{slug}]]."
```

- [ ] **Run tests to verify they pass**

```bash
python -m pytest tests/test_synthesise.py -v
```
Expected: all pass.

- [ ] **Commit**

```bash
git add src/lacuna_wiki/mcp/synthesise.py tests/test_synthesise.py
git commit -m "feat: mcp/synthesise.py — cluster_queue, cluster_detail, commit_synthesis"
```

---

## Task 5: Wire synthesise into MCP server

**Files:**
- Modify: `src/lacuna_wiki/mcp/server.py`
- Modify: `tests/test_mcp_integration.py`

`synthesise` and `link_audit` are mutually exclusive. If both are provided, return an error.

### Steps

- [ ] **Write failing tests**

```python
def test_synthesise_true_returns_queue(vault):
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "page-a.md",
                   "# page-a\n\n## S\n\n" + ("Word " * 120) + "\n")
    dispatch_wiki(conn, fake_embed, link_audit="page-a", mark_swept=True,
                  cluster={"members": ["page-a"], "label": "Test", "rationale": "r"})
    result = dispatch_wiki(conn, fake_embed, synthesise=True)
    assert "Test" in result or "pending" in result.lower()


def test_synthesise_int_returns_detail(vault):
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "page-a.md",
                   "# page-a\n\n## S\n\n" + ("Word " * 120) + "\n")
    dispatch_wiki(conn, fake_embed, link_audit="page-a", mark_swept=True,
                  cluster={"members": ["page-a"], "label": "Test", "rationale": "r"})
    cid = conn.execute(
        "SELECT id FROM synthesis_clusters WHERE concept_label='Test'"
    ).fetchone()[0]
    result = dispatch_wiki(conn, fake_embed, synthesise=cid)
    assert "page-a" in result
    assert "suggested slug" in result.lower()


def test_synthesise_commit(vault):
    vault_root, conn = vault
    write_and_sync(vault_root, conn, "page-a.md",
                   "# page-a\n\n## S\n\n" + ("Word " * 120) + "\n")
    dispatch_wiki(conn, fake_embed, link_audit="page-a", mark_swept=True,
                  cluster={"members": ["page-a"], "label": "Test", "rationale": "r"})
    cid = conn.execute(
        "SELECT id FROM synthesis_clusters WHERE concept_label='Test'"
    ).fetchone()[0]
    result = dispatch_wiki(conn, fake_embed, synthesise=cid,
                           commit={"slug": "synthesis-test"})
    assert "synthesis-test" in result
    row = conn.execute(
        "SELECT status FROM synthesis_clusters WHERE id=?", [cid]
    ).fetchone()
    assert row[0] == "completed"


def test_synthesise_string_true_normalised(vault):
    """Agents may pass synthesise='true' as a string."""
    _, conn = vault
    result = dispatch_wiki(conn, fake_embed, synthesise="true")
    assert "0" in result or "no pending" in result.lower()


def test_synthesise_and_link_audit_mutual_exclusion(vault):
    _, conn = vault
    result = dispatch_wiki(conn, fake_embed, synthesise=True, link_audit=True)
    assert "error" in result.lower() or "mutually exclusive" in result.lower()
```

- [ ] **Run tests to verify they fail**

```bash
python -m pytest tests/test_mcp_integration.py::test_synthesise_true_returns_queue -v
```
Expected: FAIL.

- [ ] **Update `dispatch_wiki` and `wiki()` in `server.py`**

Add `synthesise: "bool | int | str | None" = None` and `commit: dict | None = None` to both signatures.

Normalise string inputs at the top of `dispatch_wiki`, alongside the existing `link_audit` normalisation:

```python
if isinstance(synthesise, str) and synthesise.lower() == "true":
    synthesise = True
elif isinstance(synthesise, str) and synthesise.lower() == "false":
    synthesise = None
elif isinstance(synthesise, str) and synthesise.isdigit():
    synthesise = int(synthesise)
```

Mutual exclusion guard (before either dispatch block):

```python
if synthesise is not None and link_audit is not None:
    return "Error: synthesise and link_audit are mutually exclusive."
```

Synthesise dispatch block (before the `link_audit` block):

```python
if synthesise is not None:
    from lacuna_wiki.mcp.synthesise import (
        cluster_queue,
        cluster_detail,
        commit_synthesis,
    )
    if synthesise is True:
        return cluster_queue(conn)
    cluster_id = int(synthesise)
    if commit:
        return commit_synthesis(conn, cluster_id, commit["slug"])
    return cluster_detail(conn, cluster_id)
```

Add `synthesise` and `commit` to the `wiki()` tool function's parameter list and both `dispatch_wiki` call sites in `make_wiki_tool`.

- [ ] **Run tests to verify they pass**

```bash
python -m pytest tests/test_mcp_integration.py -v
```
Expected: all pass.

- [ ] **Commit**

```bash
git add src/lacuna_wiki/mcp/server.py tests/test_mcp_integration.py
git commit -m "feat: wire synthesise/commit params into wiki() MCP tool"
```

---

## Task 6: Status CLI — synthesised pages count

**Files:**
- Modify: `src/lacuna_wiki/cli/status.py`
- Modify: `tests/test_status.py`

Add one row to the status table: `"synthesised pages"` — count of pages where `synthesised_into IS NOT NULL`. Insert after `synthesis queue`.

### Steps

- [ ] **Write failing test**

```python
def test_status_shows_synthesised_pages_row(vault, monkeypatch):
    monkeypatch.chdir(vault)
    result = CliRunner().invoke(status)
    assert result.exit_code == 0, result.output
    assert "synthesised pages" in result.output
```

- [ ] **Run test to verify it fails**

```bash
python -m pytest tests/test_status.py::test_status_shows_synthesised_pages_row -v
```

- [ ] **Add `"synthesised pages"` to `_sweep_counts` in `status.py`**

```python
synthesised_pages = conn.execute(
    "SELECT COUNT(*) FROM pages WHERE synthesised_into IS NOT NULL"
).fetchone()[0]
```

Return it in the dict. Add the row after `synthesis queue` in the table.

- [ ] **Run tests to verify they pass**

```bash
python -m pytest tests/test_status.py -v
```

- [ ] **Commit**

```bash
git add src/lacuna_wiki/cli/status.py tests/test_status.py
git commit -m "feat: status shows synthesised pages count"
```

---

## Task 7: lacuna-synthesise skill

**Files:**
- Create: `src/lacuna_wiki/skills/synthesise.md`

Mirrors `lacuna-sweep` exactly in structure, wording register, and imperative instruction style. Every step is a hard instruction, not a suggestion.

### Steps

- [ ] **Create `src/lacuna_wiki/skills/synthesise.md`**

```markdown
# Synthesise Skill — lacuna

The synthesis counterpart to `lacuna-sweep`. Where sweep adds wikilinks and queues clusters, synthesise reads those clusters and produces unified synthesis pages — one page per cluster, written from all member pages, surfacing shared ground, disagreements, and weight of evidence in one place.

---

## Mode

| Mode | Declared by | Behaviour |
|---|---|---|
| `standard` | default | Pause at Step 0 for queue approval |
| `auto` | "auto", "just run it" | Skip Step 0 pause — all per-cluster steps run identically |

Auto mode exists to support cron execution. In auto mode the agent processes the full queue without pausing.

---

## MCP Tool Reference

All wiki operations go through the `wiki` MCP tool.

**Cluster queue:**
```
wiki(synthesise=True)
```

**Single cluster detail:**
```
wiki(synthesise=N)
```

**Mark cluster synthesised:**
```
wiki(synthesise=N, commit={"slug": "synthesis-slug"})
```

**`lacuna search` does not exist.** Use `wiki(q="...")` for search. Use `wiki(page="slug")` to navigate.

---

## Step 0 — Get the Queue

```
wiki(synthesise=True)
```

State the full picture out loud:

> "Synthesis queue:
> Pending clusters (N): [labels and member counts]
> Single-source clusters: [labels] — will note limitation inline.
> Any clusters to skip or reprioritise?"

**Standard mode:** pause. Adjust if needed.
**Auto mode:** skip pause. Proceed immediately.

Create one task per cluster before proceeding.

---

## Step 1 — Per-cluster Loop (streaming)

Mark task `in_progress` before starting; `completed` when done.

### a. Commit

State out loud before touching anything:

```
wiki(synthesise=N)
```

> "Synthesising cluster N: [label]
> Members (M): [[slug-a]], [[slug-b]], [[slug-c]]
> Source diversity: N distinct sources. [⚠ single-source — will note limitation in synthesis page]
> Existing synthesis page: [[slug]] / none — [new write / revision run]
> Noise members I am excluding: [[slug-x]] — [reason]. [[slug-y]] — [reason].
> Confirmed members: [[slug-a]], [[slug-b]], [[slug-c]]
> Proposed slug: [slug]
> Reading member pages now."

Every member surfaced in the cluster detail must be either confirmed or declared noise. Undeclared members are not silently dropped. A member is noise if it is: under 100 words, a reagent or tool rather than a concept, or clearly off-topic relative to the cluster label.

### b. Read Members

```
wiki(pages=["slug-a", "slug-b", "slug-c"])
```

For a revision run, read the existing synthesis page first:

```
wiki(page="existing-synthesis-slug")
```

After reading, confirm the proposed slug or revise it. The slug must be a good standalone concept name — not prefixed with "synthesis-" unless necessary for disambiguation.

### c. Write Synthesis Page

Write the synthesis page at `wiki/{cluster-path}/{slug}.md`.

**Frontmatter must open the file. Include `synthesis: true`:**

```markdown
---
tags: [tag1, tag2]
synthesis: true
---

# slug

[body]
```

Tag rules: include each segment of the cluster path (e.g. `sRNA`, `quantification`) plus 1–3 cross-cutting concept tags. Lowercase, hyphen-separated.

**Body structure:**
- Open with a one-paragraph synthesis of what all members agree on
- Separate section for disagreements or scope differences between sources
- Cite all contributing sources inline at the sentence level: `claim [[source-a.pdf]] [[source-b.pdf]]`
- For single-source clusters, add a note at the top: `> *This synthesis draws from a single source — [[source.pdf]].*`

**Framing rules (apply the same claim-type discipline as `lacuna-ingest`):**
- State weight of evidence across sources, not any single source's view
- Surface disagreements explicitly: "[[source-a.pdf]] argues X; [[source-b.pdf]] demonstrates Y at 270M parameters — the larger-scale result is more likely to generalise"
- Hedge unproven claims: "[[source.pdf]] hypothesises that..."
- Never write encyclopedic voice for experimental results

**Slug casing rule:** slugs are always lowercase. Use pipe syntax for display: `[[slug|Display Text]]`. Never put a wikilink inside a `##` heading.

**Revision run:** edit the synthesis page in place. Add new content from new members; do not erase prior synthesis. Add a revision callout directly below frontmatter:

```markdown
> *Revised [date]: added [[new-slug-a]], [[new-slug-b]].*
```

**Excluded members section:** at the bottom of every synthesis page, add:

```markdown
## Excluded members

| Page | Reason | Date |
|---|---|---|
| [[slug-x]] | Reagent, not a concept — d1-egfp is a reporter protein | 2026-04-15 |
| [[slug-y]] | Under 100 words — stub awaiting sources | 2026-04-15 |
```

Leave this table empty (headers only) if there are no noise members. Do not omit the section — it is the persistent record of agent judgments for future reviewers.

### d. Add Synthesised-Into Notice to Members

For each **confirmed** member page — not noise members, not the synthesis page itself — add one line directly below the frontmatter:

```
%% synthesised-into: [[slug]] %%
```

Apply with Edit, one page at a time. Verify each edit was written before moving to the next.

The daemon detects this notice on next sync and sets `synthesised_into` in the DB. Once set, the page disappears from the sweep backlog and synthesis candidate pool. Do not add the notice to noise members — they remain eligible for future sweeps.

### e. Commit

```
wiki(synthesise=N, commit={"slug": "synthesis-slug"})
```

> "Synthesised cluster N: [[synthesis-slug]] written. N members noticed. Excluded members recorded. Next: cluster M."

Mark task completed.

---

## Step 2 — Done

> "Synthesis complete. N clusters synthesised, N pages written.
> Synthesis queue: now holds N pending clusters — run `lacuna synthesise` or schedule it.
> Remaining sweep backlog: N pages.
> Research gaps: N stubs, N ghost pages — visible in `lacuna status`."

---

## Decision Table

| Signal | Action |
|---|---|
| Member page < 100 words or < 2 sections | Noise — exclude; record in Excluded members table; do not add notice |
| Member page already synthesised into a different page | Noise — note the conflict in Excluded members; do not add a second notice |
| Member is a reagent / tool rather than a concept | Noise — exclude; record reason |
| Single-source cluster | Proceed; add single-source callout at top of synthesis page |
| Revision run (existing synthesis page) | Read existing page first; edit in place; add revision callout |
| Cluster has > 10 members | Synthesise the highest-coverage members; record the rest as overflow in Excluded members table |
| Proposed slug conflicts with an existing page | Append a disambiguating suffix: `nav-channel-pain-pharmacology-synthesis` |
```

- [ ] **Run install-skills to verify it is picked up**

```bash
lacuna install-skills --claude-global
ls ~/.claude/skills/lacuna-synthesise/
```
Expected: `SKILL.md` present.

- [ ] **Commit**

```bash
git add src/lacuna_wiki/skills/synthesise.md
git commit -m "feat: add lacuna-synthesise agent skill"
```

---

## Task 8: Integration smoke test + push

### Steps

- [ ] **Run full test suite**

```bash
python -m pytest -v --ignore=tests/sources/test_fetcher.py --ignore=tests/test_add_source.py
```
Expected: all prior tests pass plus new synthesise tests.

- [ ] **Run `lacuna sync` in test vault to apply v4 schema**

```bash
cd ~/lacuna-test && lacuna sync
```

- [ ] **Verify `lacuna status` shows synthesised pages row**

```bash
lacuna status
```
Expected: table includes `synthesised pages` row with count 0.

- [ ] **Run `lacuna install-skills --claude-global`**

```bash
lacuna install-skills --claude-global
```
Expected: 5 skill(s) installed (adversary, ingest, query, sweep, synthesise).

- [ ] **Push branch and open PR**

```bash
git push -u origin feature/synthesise
gh pr create --title "feat: lacuna-synthesise — synthesis pages, cluster reopen, synthesised-into notice" \
  --body "..."
```
