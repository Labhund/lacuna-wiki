# Skills + Install Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Write the ingest and adversary skill documents, ship them as package data inside `src/lacuna_wiki/skills/`, and build `lacuna install-skills` to copy them into Hermes or Claude Code skill directories.

**Architecture:** Skill files are markdown documents at `src/lacuna_wiki/skills/ingest.md` and `src/lacuna_wiki/skills/adversary.md`. They are declared as package data in `pyproject.toml` so they're available via `Path(__file__)` relative paths after editable install. `install-skills` copies them to a user-specified target directory. Hermes requires real copies (no symlinks); Claude Code project skills live in `.claude/skills/lacuna/` by convention.

**Tech Stack:** Python `shutil.copy2`, Click CLI, `hatchling` package data (`[tool.hatch.build.targets.wheel.shared-data]` not needed — files in `src/lacuna_wiki/` are included automatically). Skills are plain markdown, no special syntax beyond the skill front-matter convention used by the Superpowers plugin.

---

## Background: where skills live

Skills are markdown files that a Claude Code session (or Hermes) loads when the user invokes them. They encode the full workflow — what to do, in what order, with what tools. This repo is the authoritative source. Each consumer (Hermes, Claude Code project, Claude Code global) needs a physical copy — symlinks are silently ignored by Hermes skill discovery.

`install-skills` is the sync mechanism. Running it after pulling the repo updates all copies.

---

## File Map

```
src/lacuna_wiki/
  skills/
    ingest.md      — Create: ingest skill document
    adversary.md   — Create: adversary skill document
  cli/
    install_skills.py — Create: copy_skills() + `lacuna install-skills` command
    main.py           — Modify: register install-skills command

pyproject.toml — Modify: declare skills/*.md as package data

tests/
  test_install_skills.py — Create
```

---

## Task 1: Ingest Skill Document

**Files:**
- Create: `src/lacuna_wiki/skills/ingest.md`

The ingest skill encodes the full workflow for reading a source and integrating its claims into the wiki. It uses the TaskCreate/TaskUpdate tool loop as shared state across what may be a multi-turn session.

**No tests for this task** — it's a document. Verification is: does it render? Does it make sense end to end? Read it yourself after writing it.

- [ ] **Step 1: Create `src/lacuna_wiki/skills/`**

```bash
mkdir -p src/lacuna_wiki/skills
```

- [ ] **Step 2: Write `src/lacuna_wiki/skills/ingest.md`**

```markdown
---
name: lacuna-ingest
description: Ingest a source (PDF, URL, note, transcript) into the wiki. Search before writing. One concept at a time.
---

# Ingest Skill — lacuna

Ingest a source into the wiki. The source may be a registered PDF, URL, markdown note, or session transcript. This skill guides you from source to wiki pages, always searching before writing.

**Prerequisite:** the source must be registered. If it isn't:

```bash
lacuna add-source raw/path/to/file.pdf
```

Wait for the daemon to sync before proceeding.

---

## Step 1 — Read the Full Source

Read the source in full. For local files: use the Read tool. For URLs: fetch the page. For registered PDFs, you can also search existing chunks:

```json
{"q": "summary of [title or key concept]", "scope": "sources"}
```

Goal: understand what the source argues, what its key claims are, what concepts it introduces or refutes.

---

## Step 2 — Create Todos and Pause

For each concept worth writing about, create a task:
> "Write about [concept]: [one sentence describing the idea]"

Present the full list to the user before starting:
> "Found N concepts. Here's what I'm planning:
>  1. [concept]: [one sentence]
>  2. [concept]: [one sentence]
>  ...
>  Anything to add, remove, or reframe before I start?"

Wait. Adjust if needed. Then proceed.

**This is the only mandatory user pause.** The only other pauses are non-obvious routing decisions (see Step 3d) and supersession confirmations.

---

## Step 3 — For Each Todo

Repeat this loop until all tasks are ticked. Mark each task in_progress before starting it; mark it completed when done.

### a. Commit

Say out loud before acting:
> "I am going to write about [X]: [one sentence].
>  But first I will search the wiki for similar content."

This articulates your search query. Do not skip it.

### b. Search

```json
{"q": "[one sentence summary from the commit step]", "scope": "all"}
```

`scope: "all"` catches compiled wiki sections AND raw source chunks from other registered papers. The one-sentence summary is a better query than the concept name alone.

### c. Read Close Matches

For any hit with score > 0.7, navigate to it:

```json
{"page": "[slug]", "section": "[section name]"}
```

Read the content. Determine: same claim? Nuance? Contradiction?

### d. Decide

| Situation | Action |
|---|---|
| Same point already in wiki | Add this source citation inline: `existing sentence. [[old-source.pdf]] [[new-source.pdf]]` |
| Slight nuance — this source adds a qualifier or extension | Edit the sentence; preserve old citation; add new |
| New angle on an existing page — distinct enough for its own section | Add a new `## Section` to the existing page |
| Contradiction — this source disagrees with an existing claim | Write new claim; surface to user for supersession confirmation |
| Concept is entirely new to the wiki | Create a new nugget page |
| Partial overlap | Add to that section + add wikilink cross-reference |

**Non-obvious routing decision? Surface it.**
> "Options: (a) add citation to existing sentence in [page], (b) create new section, (c) new page. Which?"

**Promotion heuristic:** if the section you're writing into already has ≥ 3 source citations and substantial content, mention to the user: "This section is getting dense — worth promoting to its own page?"

### e. Write

Use Edit or Write tools to modify or create wiki pages.

**Citation format:** `[[source-key.pdf]]` inline at the end of the sentence. Never author `|N` — citation numbers are daemon-assigned. The daemon watches `wiki/` and syncs automatically.

**Wait ~2s after writing** before reading back — the daemon debounces.

### f. Mark Complete

Mark the task completed. Move to the next todo.

---

## Step 4 — Done

When all tasks are ticked:

> "Ingested [N] concepts from [source slug].
>  [N] pages updated, [N] pages created."

Optional status check:

```bash
lacuna status
```

---

## Routing Reference

| Pattern | Rule |
|---|---|
| Concept has its own page | Update that page |
| Concept is a section of another page | Update that section |
| Concept is new | Create nugget page named after the concept |
| Source confirms existing claim | Add citation: `claim. [[old.pdf]] [[new.pdf]]` |
| Source adds nuance | Edit sentence + keep old citation |
| Source contradicts — recent | Write new claim; user confirms supersession |
| Source contradicts — older | Note the discrepancy; do not supersede |

---

## Citation Format Rules

- One citation marker per claim: `[[key.pdf]]` at the end of the sentence.
- Multiple sources for one claim: `claim text. [[key1.pdf]] [[key2.pdf]]`
- Never add `|N` citation numbers — the daemon assigns them.
- Key = the source slug used at `add-source` time. Extension matches the source file type: `.pdf`, `.md`, `.txt`.
```

- [ ] **Step 3: Verify the file exists and is non-empty**

```bash
wc -l src/lacuna_wiki/skills/ingest.md
```

Expected: > 80 lines.

- [ ] **Step 4: Commit**

```bash
git add src/lacuna_wiki/skills/ingest.md
git commit -m "docs: add lacuna ingest skill"
```

---

## Task 2: Adversary Skill Document

**Files:**
- Create: `src/lacuna_wiki/skills/adversary.md`

The adversary skill runs at low temperature with a falsification-first posture. It uses `lacuna claims` to build a todo list and `lacuna adversary-commit` to batch-write all verdicts at the end. Plan 5 must be complete before this skill can be used end-to-end.

**No tests** — document. Verify by reading.

- [ ] **Step 1: Write `src/lacuna_wiki/skills/adversary.md`**

```markdown
---
name: lacuna-adversary
description: Evaluate wiki claims for fidelity and supersession. Falsification-first. Requires Plan 5 CLI tools.
---

# Adversary Skill — lacuna

Evaluate claims in the wiki for fidelity and supersession. Runs at low temperature. Falsification-first posture: your job is to find what is wrong, not to confirm what is right.

**Prerequisite:** `lacuna adversary-commit` must be available (Plan 5). The daemon must be running.

---

## Targeting Modes

| Mode | When |
|---|---|
| `virgin` | First pass after a batch ingest — all claims never evaluated |
| `stale` | After adding new sources — claims not checked since the last source was registered |
| `page SLUG` | Before citing a specific page heavily |

Default mode: `virgin`.

---

## Step 1 — Target

List the claims to evaluate:

```bash
lacuna claims --mode virgin
# or
lacuna claims --mode stale
# or
lacuna claims --mode page attention-mechanism
```

Create one task per claim:
> "Evaluate claim [ID]: [first 60 characters of claim text]"

Report to the user:
> "Found N unevaluated claims across K pages. Starting evaluation."

---

## Step 2 — For Each Claim (Loop)

Mark each task in_progress before starting it. Mark it completed when done.

### a. Commit

State out loud before acting:
> "Evaluating: '[full claim text]'
>  Source: [source_slug] ([published_date])
>  Page: [page_slug] › [section_name]"

### b. Search

```json
{"q": "[claim text without the [[citation]] marker]", "scope": "all"}
```

The claim's own source chunks surface first — these are the fidelity check material. Other source chunks surface cross-source evidence.

### c. Adversarial Check

Work through these questions before forming a verdict. Do not skip them:

1. **Falsifiability:** What would have to be true for this claim to be wrong?
2. **Fidelity:** Does the cited source actually assert this — or does it hedge, caveat, or say something subtly different? Check the source chunks in the search results against the claim text word by word if needed.
3. **Cross-source:** Does any other source — especially a more recent one — contradict this?
4. **Verdict:** State it. One of: SUPPORTS / FIDELITY FAILURE / SUPERSEDED / GAP. No hedging. Pick the strongest verdict the evidence supports.

### d. Verdict and Action

**SUPPORTS** — source confirms the claim, no contradictory evidence found:
- Accumulate: `claim_id=[ID] rel=supports`
- Move to next claim.

**FIDELITY FAILURE** — claim misrepresents its own source (overstates confidence, omits a key caveat, paraphrases imprecisely):
- Edit the page directly with Edit tool. Fix the sentence to match what the source actually says. The daemon picks up the change automatically.
- Do not write a DB verdict for this — the edited claim is a new claim row after daemon sync.
- Note the fix in your accumulator: `FIDELITY FIX: [page › section] — [one sentence description]`
- Move to next claim.

**GAP** — source identifies this as a known unknown, an open question, or a recognised limitation:
- Accumulate: `claim_id=[ID] rel=gap`
- Move to next claim.

**SUPERSEDED** — a newer source contradicts this claim:
- Pause. Surface to the user:
  > "Claim: [X] ([source_slug], [published_date])
  >  Superseded by: [newer_source_slug] ([newer_date]) — [one sentence summary]
  >  Proposed new claim: [Y]
  >  Approve / Skip / Override?"
- **If approved:**
  - Edit the page: add the new claim sentence with the new source citation.
  - Wait ~3s for daemon sync.
  - Run `lacuna claims --mode page [slug]` to find the new claim ID (it will have no `last_adversary_check`).
  - Accumulate: `claim_id=[old_ID] rel=refutes` and `supersede old=[old_ID] new=[new_ID]`
- **If skipped:** no record, move on.

### e. Accumulate

Keep a running list. Do not commit until the full loop is done.

```
VERDICTS:
  claim_id=42  rel=supports
  claim_id=17  rel=gap
  claim_id=99  rel=refutes

SUPERSESSIONS:
  old=99  new=107

FIDELITY FIXES:
  attention-mechanism › Scaled Dot-Product — overstated source confidence; softened wording
```

### f. Tick

Mark the task completed. Move to next claim.

---

## Step 3 — Commit + Report

When all tasks are ticked, batch-commit all verdicts in one call:

```bash
lacuna adversary-commit \
  --verdict "claim_id=42,rel=supports" \
  --verdict "claim_id=17,rel=gap" \
  --verdict "claim_id=99,rel=refutes" \
  --supersede "old=99,new=107"
```

Report:
> "N claims evaluated.
>  K supported, J gaps, M fidelity fixes (edited inline), L supersessions.
>
>  Fidelity fixes:
>    [page › section] — [one sentence description]
>
>  Supersessions:
>    Claim [old text] ([old source]) → [new text] ([new source])"

---

## Posture Reminder

You are reading to falsify, not to confirm. If a claim seems fine on first read, look harder. Read the actual source chunk, not just your memory of it. Check whether the source hedges where the claim does not. Check whether any newer source in the results changes the picture. Only then — if no weakness is found — record SUPPORTS.

A SUPPORTS verdict means: "I looked hard for a problem and found none." It is not the default.
```

- [ ] **Step 2: Verify**

```bash
wc -l src/lacuna_wiki/skills/adversary.md
```

Expected: > 100 lines.

- [ ] **Step 3: Commit**

```bash
git add src/lacuna_wiki/skills/adversary.md
git commit -m "docs: add lacuna adversary skill"
```

---

## Task 3: `install-skills` command

**Files:**
- Create: `src/lacuna_wiki/cli/install_skills.py`
- Modify: `src/lacuna_wiki/cli/main.py`
- Modify: `pyproject.toml`
- Create: `tests/test_install_skills.py`

Copies skills from the package to a target directory. The source is `src/lacuna_wiki/skills/` resolved relative to the module file — works correctly for editable installs (`pip install -e .`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_install_skills.py
from pathlib import Path
import pytest
from lacuna_wiki.cli.install_skills import copy_skills, SKILLS_DIR


def test_skills_dir_exists():
    assert SKILLS_DIR.is_dir()


def test_skills_dir_contains_ingest():
    assert (SKILLS_DIR / "ingest.md").exists()


def test_skills_dir_contains_adversary():
    assert (SKILLS_DIR / "adversary.md").exists()


def test_copy_skills_creates_both_files(tmp_path):
    copy_skills(tmp_path)
    assert (tmp_path / "ingest.md").exists()
    assert (tmp_path / "adversary.md").exists()


def test_copy_skills_file_has_content(tmp_path):
    copy_skills(tmp_path)
    content = (tmp_path / "ingest.md").read_text()
    assert len(content) > 200
    assert "lacuna" in content


def test_copy_skills_overwrites_stale(tmp_path):
    (tmp_path / "ingest.md").write_text("old stale content")
    copy_skills(tmp_path)
    content = (tmp_path / "ingest.md").read_text()
    assert content != "old stale content"
    assert len(content) > 200


def test_copy_skills_creates_target_dir(tmp_path):
    target = tmp_path / "new" / "subdir"
    copy_skills(target)
    assert (target / "ingest.md").exists()
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/pytest tests/test_install_skills.py -v 2>&1 | tail -8
```

Expected: `ModuleNotFoundError: No module named 'lacuna_wiki.cli.install_skills'`

- [ ] **Step 3: Write `src/lacuna_wiki/cli/install_skills.py`**

```python
"""lacuna install-skills — copy skill documents to Hermes or Claude Code."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import click

# Skills live alongside this package in src/lacuna_wiki/skills/
SKILLS_DIR = Path(__file__).parent.parent / "skills"


def copy_skills(target: Path) -> list[Path]:
    """Copy all skill .md files from the package to target directory.

    Creates target if it doesn't exist. Overwrites existing files.
    Returns list of destination paths.
    """
    target.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for skill_file in sorted(SKILLS_DIR.glob("*.md")):
        dest = target / skill_file.name
        shutil.copy2(skill_file, dest)
        copied.append(dest)
    return copied


@click.command("install-skills")
@click.option(
    "--hermes",
    "hermes_path",
    default=None,
    metavar="PATH",
    help="Copy to this Hermes skills directory (must be an absolute path).",
)
@click.option(
    "--claude-project",
    "claude_project",
    default=None,
    metavar="PATH",
    help="Copy to .claude/skills/lacuna/ inside this directory (default: current dir).",
)
@click.option(
    "--claude-global",
    "claude_global",
    is_flag=True,
    default=False,
    help="Copy to ~/.claude/skills/lacuna/ (global Claude Code skills).",
)
def install_skills(
    hermes_path: str | None,
    claude_project: str | None,
    claude_global: bool,
) -> None:
    """Copy lacuna skill documents to Hermes or Claude Code skill directories."""
    targets: list[Path] = []

    if hermes_path:
        targets.append(Path(hermes_path))

    if claude_project is not None:
        base = Path(claude_project) if claude_project else Path.cwd()
        targets.append(base / ".claude" / "skills" / "lacuna")
    elif claude_global:
        targets.append(Path.home() / ".claude" / "skills" / "lacuna")

    if not targets:
        click.echo(
            "Specify a target: --hermes PATH, --claude-project [PATH], or --claude-global",
            err=True,
        )
        sys.exit(1)

    for target in targets:
        copied = copy_skills(target)
        click.echo(f"Installed {len(copied)} skill(s) → {target}")
        for f in copied:
            click.echo(f"  {f.name}")
```

- [ ] **Step 4: Add skills to pyproject.toml package data**

Hatchling includes all files in `src/lacuna_wiki/` by default when they are part of the package. For non-Python files, add explicit include. In `pyproject.toml`, update:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/lacuna_wiki"]
include = ["src/lacuna_wiki/skills/*.md"]
```

- [ ] **Step 5: Register in main.py**

In `src/lacuna_wiki/cli/main.py`, add:

```python
from lacuna_wiki.cli.install_skills import install_skills  # noqa: E402

cli.add_command(install_skills)
```

The full `main.py`:

```python
import click


@click.group()
def cli():
    """lacuna v2 — personal research knowledge substrate."""
    pass


from lacuna_wiki.cli.add_source import add_source              # noqa: E402
from lacuna_wiki.cli.init import init                          # noqa: E402
from lacuna_wiki.cli.status import status                      # noqa: E402
from lacuna_wiki.cli.daemon import start, stop, daemon_run     # noqa: E402
from lacuna_wiki.cli.mcp_cmd import mcp_command                # noqa: E402
from lacuna_wiki.cli.claims import claims_command              # noqa: E402
from lacuna_wiki.cli.adversary_commit import adversary_commit  # noqa: E402
from lacuna_wiki.cli.install_skills import install_skills      # noqa: E402

cli.add_command(add_source)
cli.add_command(init)
cli.add_command(status)
cli.add_command(start)
cli.add_command(stop)
cli.add_command(daemon_run)
cli.add_command(mcp_command)
cli.add_command(claims_command)
cli.add_command(adversary_commit)
cli.add_command(install_skills)
```

- [ ] **Step 6: Run the tests**

```bash
.venv/bin/pytest tests/test_install_skills.py -v 2>&1 | tail -10
```

Expected: 7 tests PASS.

- [ ] **Step 7: Run full suite**

```bash
.venv/bin/pytest tests/ 2>&1 | tail -5
```

Expected: all PASS.

- [ ] **Step 8: Smoke test**

```bash
.venv/bin/lacuna install-skills --help
```

Expected: shows `--hermes`, `--claude-project`, `--claude-global` options.

- [ ] **Step 9: Commit**

```bash
git add src/lacuna_wiki/cli/install_skills.py src/lacuna_wiki/cli/main.py pyproject.toml tests/test_install_skills.py
git commit -m "feat: install-skills CLI copies skill docs to Hermes or Claude Code"
```

---

## Self-Review

**Spec coverage:**

| Requirement | Task |
|---|---|
| Ingest skill with search-before-write loop | Task 1 |
| Ingest cite format `[[key.ext]]` documented | Task 1 |
| Ingest routing policy table | Task 1 |
| Adversary targeting modes (virgin/stale/page) | Task 2 |
| Adversary SUPPORTS/FIDELITY FAILURE/SUPERSEDED/GAP verdicts | Task 2 |
| Adversary commit step (`lacuna adversary-commit`) | Task 2 |
| Adversary posture reminder (falsification-first) | Task 2 |
| `install-skills` copies to Hermes path | Task 3 — `--hermes` flag |
| `install-skills` copies to Claude Code project | Task 3 — `--claude-project` flag |
| `install-skills` copies to Claude Code global | Task 3 — `--claude-global` flag |
| No symlinks (real copies) | Task 3 — `shutil.copy2` |
| Overwrites stale copies | Task 3 — `shutil.copy2` replaces existing |

**Placeholder scan:** None found. Both skill documents are complete and actionable.

**Type consistency:** `copy_skills(target: Path) -> list[Path]` — consistent between implementation and tests. `SKILLS_DIR` referenced in both tests and implementation.
