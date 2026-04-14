# Ingest Modes Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `auto`, `standard`, and `aligned` modes to the ingest skill; add a session manifest for compaction resistance in aligned mode; make `wiki/reading-notes/` a first-class cluster; add daemon skip for `wiki/.sessions/`.

**Architecture:** The mode flag lives in the skill file (agent-driven, no CLI). Aligned mode writes a session manifest (`wiki/.sessions/{slug}-{date}.md`) that survives context compaction and makes sessions resumable. The daemon skips `.sessions/` in the watcher. `init` writes `.sessions/` to `.gitignore`. Reading notes land in `wiki/reading-notes/` and are synced by the daemon like any wiki page.

**Tech Stack:** Markdown skill file, Python daemon watcher (one-line filter), Click init command.

---

### Background

Three ingest modes address different researcher needs:

| Mode | Pause pattern | Best for |
|---|---|---|
| `standard` (default) | One pause at Step 2 for concept list approval | Normal use |
| `auto` | No pauses | Batch ingest, trusted material, re-ingest runs |
| `aligned` | Pause per concept — agent presents, human decides | New domain, contested sources, building shared understanding |

**Aligned mode** is the novel piece. The agent presents each concept as:
```
Source says: [direct quote or close paraphrase]
Wiki currently says: [navigate result — scope: "all"]
Delta: [gap, nuance, or contradiction]
My read: [one sentence framing]
→ Write this as: [proposed claim sentence with [[links]] and [[citation.md]]]

Does this framing match your understanding?
```

**Compaction resistance:** Aligned sessions run long. Context compaction loses the dialogue but must not lose the knowledge or the session state. Fix: write to wiki immediately on human approval (not at end of loop), and maintain a session manifest file the agent writes throughout.

**Session manifest** (`wiki/.sessions/{slug}-{date}.md`):
```markdown
## Source: hay2026wedon
## Started: 2026-04-14
## Human preferences:
- "Keep sections short, one claim per section"
- "Don't create separate pages for things that are just subsections of kv-cache"

## Completed: kv-cache, residual-stream, kv-direct
## Remaining: vector-walk, markov-property
## Pending questions:
- Is the vector walk claim strong enough to merit its own page?
```

The agent reads this back after compaction. It is the structured output of the conversation — enough to reconstruct intent.

**Session manifest location:** `wiki/.sessions/` (inside wiki/ so the agent can use file tools without any special path logic). The daemon must skip this directory — otherwise it will index scratch files as wiki pages.

**Reading notes** (`wiki/reading-notes/{slug}.md`): human commentary, questions, disagreements captured during aligned session. Citable like any wiki page. Future ingest sessions can search it.

---

### File Map

```
src/lacuna_wiki/skills/ingest.md        add mode sections, aligned presentation block, session manifest
src/lacuna_wiki/daemon/watcher.py       skip wiki/.sessions/ directory in sync
src/lacuna_wiki/cli/init.py             add wiki/.sessions/ to .gitignore
tests/test_daemon_integration.py     test .sessions/ files are not synced
docs/design/2026-04-14-v2-design-draft.md   document modes
```

---

### Task 1: Daemon skips wiki/.sessions/

**Files:**
- Modify: `src/lacuna_wiki/daemon/watcher.py`
- Modify: `tests/test_daemon_integration.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_daemon_integration.py`:

```python
def test_sessions_directory_not_synced(vault):
    vault_root, conn = vault
    handler = WikiEventHandler(conn, vault_root, fake_embed)

    # Create a file in wiki/.sessions/
    sessions_dir = vault_root / "wiki" / ".sessions"
    sessions_dir.mkdir()
    manifest = sessions_dir / "hay2026wedon-2026-04-14.md"
    manifest.write_text("## Source: hay2026wedon\n## Completed: kv-cache\n")

    fire_modified(handler, manifest)

    # Should not appear in pages table
    row = conn.execute(
        "SELECT id FROM pages WHERE slug='hay2026wedon-2026-04-14'"
    ).fetchone()
    assert row is None, "Session manifest must not be indexed as a wiki page"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_daemon_integration.py::test_sessions_directory_not_synced -v
```

Expected: FAIL — the session manifest IS synced (no skip logic yet)

- [ ] **Step 3: Add skip in watcher.py**

In `src/lacuna_wiki/daemon/watcher.py`, in the `_sync` method:

Current:
```python
def _sync(self, abs_path: Path) -> None:
    try:
        rel = abs_path.relative_to(self._vault_root)
    except ValueError:
        return
    with self._lock:
        sync_page(self._conn, self._vault_root, rel, self._embed_fn)
```

Replace with:
```python
def _sync(self, abs_path: Path) -> None:
    try:
        rel = abs_path.relative_to(self._vault_root)
    except ValueError:
        return
    # Skip wiki/.sessions/ — scratch space for ingest session manifests
    if ".sessions" in rel.parts:
        return
    with self._lock:
        sync_page(self._conn, self._vault_root, rel, self._embed_fn)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_daemon_integration.py::test_sessions_directory_not_synced -v
```

Expected: PASS

- [ ] **Step 5: Run full suite**

```bash
uv run pytest tests/ -q
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add src/lacuna_wiki/daemon/watcher.py tests/test_daemon_integration.py
git commit -m "feat: daemon skips wiki/.sessions/ directory"
```

---

### Task 2: init.py adds .sessions/ to .gitignore

**Files:**
- Modify: `src/lacuna_wiki/cli/init.py`

- [ ] **Step 1: Update the .gitignore block in init.py**

Find the gitignore creation block (around line 49):
```python
if not gitignore.exists():
    gitignore.write_text(
        "# lacuna database lives in ~/.lacuna/vaults/ — not in the vault itself\n"
    )
```

Replace with:
```python
if not gitignore.exists():
    gitignore.write_text(
        "# lacuna database lives in ~/.lacuna/vaults/ — not in the vault itself\n"
        "wiki/.sessions/\n"
    )
else:
    # Append if not already present
    content = gitignore.read_text()
    if "wiki/.sessions/" not in content:
        gitignore.write_text(content.rstrip("\n") + "\nwiki/.sessions/\n")
```

- [ ] **Step 2: Verify with test**

Add to `tests/test_init.py`:

```python
def test_init_gitignore_includes_sessions(tmp_path):
    from click.testing import CliRunner
    from lacuna_wiki.cli.main import cli
    runner = CliRunner()
    result = runner.invoke(cli, ["init", str(tmp_path / "vault")])
    gitignore = tmp_path / "vault" / ".gitignore"
    assert gitignore.exists()
    assert "wiki/.sessions/" in gitignore.read_text()
```

```bash
uv run pytest tests/test_init.py::test_init_gitignore_includes_sessions -v
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/lacuna_wiki/cli/init.py tests/test_init.py
git commit -m "feat: init adds wiki/.sessions/ to .gitignore"
```

---

### Task 3: Ingest skill — mode declaration

**Files:**
- Modify: `src/lacuna_wiki/skills/ingest.md`

- [ ] **Step 1: Add mode header section at the top of the skill**

After the skill frontmatter (`---` block) and the opening description, before Step 0, insert:

```markdown
## Mode

This skill runs in one of three modes. The user declares the mode at the start of the session:

| Mode | Declared by | Pause pattern |
|---|---|---|
| `standard` (default) | no declaration, or "standard" | One pause at Step 2 for concept list approval |
| `auto` | "auto", "just run it", "no pauses" | No pauses — full autonomous loop |
| `aligned` | "aligned", "walk me through this" | Pause per concept — present before writing |

If no mode is declared, use standard.

**Auto mode:** Skip the Step 2 pause entirely. Run the full todo loop without surfacing routing decisions — including the non-obvious routing decisions in Step 3d that standard mode would surface. The agent resolves these silently using its best judgment. This is intentional: auto mode is for trusted material where the researcher has opted out of the integration dialogue. Use for: batch ingest of multiple sources in sequence, re-ingesting already-known material, or when the user has explicitly said "just run it."

**Aligned mode:** See the Aligned Mode section at the end of this skill. Use for: first encounter with a new domain, contested sources, sources with counter-consensus claims, or when the user wants to build shared understanding of the material.
```

- [ ] **Step 2: Modify Step 2 to respect auto mode**

Find the current Step 2 section. After the "Wait for the user's response" line, add:

```markdown
**In auto mode:** skip this pause. Proceed directly to Step 3 with the full todo list as created.
```

- [ ] **Step 3: Commit**

```bash
git add src/lacuna_wiki/skills/ingest.md
git commit -m "skill: mode declaration (standard / auto / aligned)"
```

---

### Task 4: Ingest skill — aligned mode, session manifest, reading notes

**Files:**
- Modify: `src/lacuna_wiki/skills/ingest.md`

- [ ] **Step 1: Add Aligned Mode section at the end of ingest.md**

Append after the current "## Routing Reference" and "## Citation Format Rules" sections (or after the final section, wherever the skill currently ends):

```markdown
---

## Aligned Mode

Aligned mode replaces the Step 3 write loop with a per-concept dialogue. The agent presents each concept to the human before writing anything. Use when: new domain, contested source, counter-consensus claims, or building shared understanding.

### Session manifest

At the start of an aligned session, create the manifest file:

```
wiki/.sessions/{source-slug}-{YYYY-MM-DD}.md
```

Write to it throughout the session. It is your memory across compaction events.

Initial content:
```markdown
## Source: {slug}
## Started: {date}
## Mode: aligned
## Human preferences:
(fill in as the human expresses them)

## Completed:
(fill in as concepts are approved and written)

## Remaining:
(copy from the todo list; remove as completed)

## Pending questions:
(anything unresolved — flag here, not in the wiki page)
```

Update "Completed" and "Remaining" as you work. If the session compacts, read this file back immediately — it is your full session state.

**After the session ends:** delete the manifest file or move it to `wiki/reading-notes/` as archival. The daemon ignores `.sessions/` — it will not appear in the wiki.

### Per-concept aligned loop

For each concept in the todo list (instead of the standard Step 3 a–f):

**a. Search first**

```json
{"q": "[one sentence from Step 1 structured analysis]", "scope": "all"}
```

Read the top 3 results. Note what the wiki already says.

**b. Present to human**

> **Concept: [name]**
>
> Source says: [direct quote or close paraphrase from the source chunk]
>
> Wiki currently says: [one sentence summary of the best matching search result, or "nothing yet"]
>
> Delta: [what's genuinely new — gap, nuance, or contradiction]
>
> My read: [one sentence framing the relationship between source and wiki]
>
> → Proposed claim: [the actual sentence you would write, with [[links]] and [[citation.ext]]]
>
> Does this framing match your understanding? Or should it go somewhere else / be framed differently?

**c. Human responds**

Adjust framing, routing, or wikilinks based on human response. Capture any preferences expressed in the session manifest.

**d. Write (if approved)**

Write immediately on approval — not at the end of the loop. Update the session manifest: move this concept from Remaining to Completed.

**e. Tick todo**

Mark the task completed.

### Reading notes

During aligned mode, capture the human's commentary, questions, disagreements, and framings in a reading note page:

```
wiki/reading-notes/{source-slug}.md
```

Format:
```markdown
# Reading Notes: {source title}
{date} — {source slug}

## [Concept name]
[Human's comment verbatim or close paraphrase]

## Questions
[Unresolved questions flagged by human]
```

Reading notes are citable wiki pages — the daemon indexes them normally. Future ingest sessions can search them. A human comment like "I think the KV Direct framing undersells the Markov property" is a first-class intellectual artifact, not a chat log.
```

- [ ] **Step 2: Verify the skill reads coherently**

Read through `src/lacuna_wiki/skills/ingest.md` from top to bottom. Check:
- Mode section appears before Step 0 with natural-language "declared by" framing (no --flags)
- Step 2 has the auto mode skip note
- Aligned Mode section appears after all numbered steps
- Session manifest format is complete (Initial content block, update instructions)
- Per-concept aligned loop has all sub-steps (a–e)
- Reading notes section is present

- [ ] **Step 3: Commit**

```bash
git add src/lacuna_wiki/skills/ingest.md
git commit -m "skill: aligned mode with session manifest and reading notes"
```

---

### Task 5: Update spec

**Files:**
- Modify: `docs/design/2026-04-14-v2-design-draft.md`

- [ ] **Step 1: Add ingest modes to Settled Decisions**

Add to the Settled Decisions table:

```markdown
| Ingest modes | Three modes in the skill: `standard` (one pause at Step 2), `auto` (no pauses, batch use), `aligned` (per-concept dialogue with human). Mode is declared by the user at the start of the session — no CLI change. |
| Session manifest | `wiki/.sessions/{slug}-{date}.md` — aligned mode scratch file. Daemon skips `.sessions/` directory. Gitignored. Structured output of the aligned conversation; survives compaction. Deleted or archived to reading-notes after session ends. |
| Reading notes | `wiki/reading-notes/` — first-class wiki cluster. Human commentary from aligned sessions filed as citable pages. Daemon indexes normally. |
```

- [ ] **Step 2: Add `.sessions/` to daemon section**

In the daemon section, add a note after the "On `wiki/` file change" list:

```markdown
**Skipped:** `wiki/.sessions/` — ingest session manifests (aligned mode scratch files). The daemon skips any path whose parts include `.sessions`.
```

- [ ] **Step 3: Commit**

```bash
git add docs/design/2026-04-14-v2-design-draft.md
git commit -m "docs: ingest modes, session manifest, reading notes in spec"
```

---

### Task 6: Install updated skills

- [ ] **Step 1: Reinstall**

```bash
lacuna install-skills
```

- [ ] **Step 2: Run full test suite one final time**

```bash
uv run pytest tests/ -q
```

Expected: all pass
