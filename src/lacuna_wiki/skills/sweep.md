# Sweep Skill — lacuna

The editorial counterpart to `lacuna-ingest`. Where ingest adds knowledge, sweep tightens it: missing `[[wikilinks]]` are added and synthesis candidates are queued for the synthesis engine.

---

## Mode

| Mode | Declared by | Behaviour |
|---|---|---|
| `standard` | default | Pause at Step 0 for queue approval |
| `auto` | "auto", "just run it" | Skip Step 0 pause — all per-page steps run identically |

Auto mode exists to support cron execution. In auto mode the agent processes the full queue without pausing.

---

## MCP Tool Reference

All wiki operations go through the `wiki` MCP tool.

**Vault audit:**
```
wiki(link_audit=True)
```

**Single-page audit:**
```
wiki(link_audit="slug")
```

**Mark page swept (no cluster):**
```
wiki(link_audit="slug", mark_swept=True)
```

**Mark page swept with synthesis cluster:**
```
wiki(
    link_audit="slug",
    mark_swept=True,
    cluster={
        "members": ["slug-a", "slug-b"],
        "label": "Concept name",
        "rationale": "One sentence explaining why these pages belong together.",
    }
)
```

**`lacuna search` does not exist.** Use `wiki(q="...")` for search. Use `wiki(page="slug")` to navigate.

---

## Step 0 — Get the Queue

```
wiki(link_audit=True)
```

State the full picture out loud:

> "Vault audit:
> Research gaps (N): [slugs] — stub pages, awaiting sources.
> Ghost pages (N): [slugs] — linked but not yet created.
> Sweep backlog (N pages): ranked by link gap. Top entries: [[slug]], [[slug]], [[slug]].
> Synthesis queue currently holds N pending clusters for the synthesis engine.
> Any pages to skip or reprioritize?"

**Standard mode:** pause. Adjust if needed.
**Auto mode:** skip pause. Proceed immediately.

Create one task per page in the sweep queue before proceeding.

---

## Step 1 — Per-page Loop (streaming)

Mark task `in_progress` before starting; `completed` when done.

### a. Commit

State out loud before touching anything:

> "Sweeping [[slug]]: [page title]
> Link gap: N links / N words.
> Unlinked candidates: [concept] (×N in [section]), [concept] (×N in [section])
> Synthesis candidates: [[neighbour-a]] (0.84), [[neighbour-b]] (0.71), [[neighbour-c]] (0.51)
> Reading the page now — will declare cluster judgment after."

```
wiki(link_audit="slug")
wiki(page="slug")
```

After reading, state the cluster judgment before calling `mark_swept`:

> "Cluster judgment: [[neighbour-a]] and [[neighbour-b]] are both describing [concept] from different angles — one cluster. [[neighbour-c]] is related but genuinely distinct, false positive.
> Cluster label: '[concept name]'
> Rationale: [one sentence]"

Every synthesis candidate surfaced in the page audit must be explicitly either included in the cluster or declared a false positive. Undeclared candidates are not silently dropped.

### b. Missing Wikilinks

For each unlinked candidate, one at a time:

> "[[concept]] appears N times in [section] without a wikilink. Adding to first mention."

Apply with Edit. Verify the link was written. Do not batch multiple candidates into one edit.

**Slug casing rule:** when *adding* a new wikilink, the slug (the part the system resolves) must be lowercase. If the word appears capitalised in the text — protein names, proper nouns, acronyms — preserve the display text using the pipe syntax: `[[dicer|Dicer]]`, `[[ago2|AGO2]]`, `[[nav17-pain-signaling|NaV1.7]]`. Do **not** rewrite existing `[[Wikilinks]]` already in the file; only add links where none exist. Never put a wikilink inside a `##` section heading.

**Semantic false-positive check:** before adding a link, confirm the word in context refers to the wiki concept, not a different sense of the same word. Example: "ninja throwing star" should not get `[[star]]` if `star` is an RNA aligner — read the sentence.

**Ghost page rule:** if an unlinked candidate has no existing page (ghost page), still add the `[[wikilink]]`. This reinforces the research gap signal — more pages linking to a ghost increases its priority.

### c. Mark Swept

If no synthesis cluster was declared:

```
wiki(link_audit="slug", mark_swept=True)
```

If the agent declared a cluster:

```
wiki(
    link_audit="slug",
    mark_swept=True,
    cluster={"members": ["slug-a", "slug-b"], "label": "...", "rationale": "..."}
)
```

> "Swept [[slug]]: N wikilinks added. Synthesis candidates queued if any. Next: [[next-slug]]."

Mark task completed.

---

## Step 2 — Done

> "Sweep complete. N pages swept, N wikilinks added.
> Synthesis queue: now holds N pending clusters — run `lacuna synthesise` or schedule it.
> Remaining sweep backlog: N pages.
> Research gaps: N stubs, N ghost pages — visible in `lacuna status`."

---

## Decision Table

| Signal | Action |
|---|---|
| Page < 100 words or < 2 sections | Research gap — skip, visible in `lacuna status` |
| Slug referenced in links but no page exists | Ghost page — still add `[[link]]` from referring pages |
| Known slug appears in body unlinked | Add `[[slug]]` to first mention in that section |
| Coverage ratio > 0.30 | Include in cluster passed to `mark_swept` |
| Coverage ratio < 0.30 | Explicitly call as false positive in cluster judgment |
