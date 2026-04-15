# lacuna-sweep — Design Spec
**Date:** 2026-04-15
**Status:** Approved for implementation

---

## Problem

The ingest skill enforces wikilinks during extraction, but two failure modes persist:

1. **Missed links** — agents (especially smaller models) skip wikilinks for concepts that don't feel important in the moment, violating the policy that all proper nouns and key concepts must be linked.
2. **Atomised facts** — repeated ingestion creates near-duplicate pages covering the same concept from different angles, where synthesis into a richer page would be better.

There is no current mechanism to detect or fix either. The ad-hoc prompt ("crawl the vault and add wikilinks") produces inconsistent results and overwhelms agents when the backlog is large.

**Scale context:** The vault is currently 100 pages from 10 sources. 600 sources are queued for migration, with daily additions. Target scale is 6,000+ pages. The design must be correct at that scale from the start.

---

## Scope

This spec covers the **sweep** — the detection layer:

- DB schema additions for audit tracking and synthesis queue
- A `wiki(link_audit=...)` extension to the existing MCP tool
- `lacuna status` additions for all four queue types
- The `lacuna-sweep` agent skill

**Not in this spec:**
- The synthesis engine (processes the synthesis queue — separate spec)
- `lacuna claims` UX refactor (separate spec)
- Missed-claims discovery / reverse adversary (separate spec)

The sweep populates the synthesis queue. The synthesis engine consumes it. They are independent units that communicate through a DB table.

---

## Architecture

```
lacuna sweep  →  fixes wikilinks
              →  populates synthesis_queue
              →  updates last_swept

lacuna synthesise  →  reads synthesis_queue        [separate spec]
                   →  writes synthesis pages
                   →  maps contradictions / consensus
                   →  runs on cron
```

Both queues are visible in `lacuna status`.

---

## Design

### 1. DB Schema Additions

#### Pages table additions

```sql
ALTER TABLE pages ADD COLUMN mean_embedding FLOAT[768];
ALTER TABLE pages ADD COLUMN last_swept     TIMESTAMPTZ;
```

**`mean_embedding`** — element-wise mean of all section embeddings, computed and updated by the daemon whenever sections change. Enables O(pages²) cosine similarity pre-filter for synthesis candidate detection. At 6,000 pages this is fast; beyond that, DuckDB's `vss` extension adds HNSW indexing on this column. Schema is ready — no migration required when HNSW is added.

**`last_swept`** — set by the tool when the agent marks a page swept. NULL means never swept. The sweep queue is always pages where `last_swept IS NULL OR updated > last_swept`. Progress persists across sessions; new pages from every ingest automatically queue themselves.

#### New synthesis cluster tables

The synthesis queue is modelled as **clusters, not pairs**. Five pages converging on one concept produce one cluster, not C(5,2)=10 pairs. The synthesis engine processes one cluster at a time as a unit.

```sql
CREATE TABLE synthesis_clusters (
    id               INTEGER DEFAULT nextval('synthesis_clusters_id_seq') PRIMARY KEY,
    concept_label    TEXT,        -- agent-assigned: "RISC assembly mechanism"
    agent_rationale  TEXT,        -- agent's one-sentence reasoning for the cluster
    status           TEXT DEFAULT 'pending',  -- pending | in_progress | done | dismissed
    queued_at        TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE synthesis_cluster_members (
    cluster_id  INTEGER REFERENCES synthesis_clusters(id),
    slug        TEXT NOT NULL,
    PRIMARY KEY (cluster_id, slug)
);

CREATE TABLE synthesis_cluster_edges (
    cluster_id     INTEGER REFERENCES synthesis_clusters(id),
    slug_a         TEXT NOT NULL,
    slug_b         TEXT NOT NULL,
    coverage_ratio FLOAT NOT NULL,
    PRIMARY KEY (cluster_id, slug_a, slug_b)
);
```

**Cluster formation is agent-driven, not threshold-driven.** The JxK computation surfaces candidates with coverage scores. The agent — having just read the page and added wikilinks — declares the cluster in the commit step, naming the concept and stating the rationale. `mark_swept` takes the agent's judgment as input. This is the critical design point: coverage ratio is the detection mechanism; the agent's contextual read is the actual intelligence that determines what belongs in a cluster.

The synthesis engine receives named, rationale-bearing clusters. It knows what the cluster is *about* before reading a single page. The sweep writes to these tables; the synthesis engine reads from them. Status: `pending → in_progress → done / dismissed`.

#### Stub and ghost page detection

**Stubs** — pages with fewer than 100 words OR fewer than 2 sections. They exist because the ingest skill created a placeholder for a concept before a source existed to support it. They are intentional research gap markers, not broken pages. Excluded from the sweep queue.

**Ghost pages** — slugs referenced in `[[wikilinks]]` that have no corresponding page. Queryable with no new schema:

```sql
SELECT DISTINCT l.target_slug
FROM links l
LEFT JOIN pages p ON l.target_slug = p.slug
WHERE p.slug IS NULL
```

Ghost pages represent named research intentions — a concept the agent decided was worth linking to before it could be written. Also excluded from the sweep queue but surfaced in `lacuna status`.

---

### 2. `lacuna status` Changes

Four new rows:

```
┏━━━━━━━━━━━━━━━━━━┳━━━━━━┓
┃ Table            ┃ Rows ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━┩
│ pages            │  106 │
│ research gaps    │    8 │  ← stubs: pages awaiting sources
│ ghost pages      │    5 │  ← slugs linked but not yet created
│ sweep backlog    │   23 │  ← pages with last_swept < updated
│ synthesis queue  │   12 │  ← pending candidates for synthesis engine
│ sections         │  464 │
│ sources          │   19 │
│ claims           │  320 │
│ claim_sources    │  303 │
│ source_chunks    │ 1569 │
│ links            │  231 │
└──────────────────┴──────┘
```

---

### 3. `wiki` Tool Extension

One new parameter: `link_audit`. All existing parameters unchanged.

#### `wiki(link_audit=True)` — full vault audit

Returns research gaps, ghost pages, and sweep queue:

```
research gaps (N):
  slug-a — "Concept Name" — 0 links, 12 words
  slug-b — "Other Concept" — 0 links, 34 words

ghost pages (N):
  missing-concept — linked from: page-x (×3), page-y (×1)
  other-missing   — linked from: page-z (×2)

sweep queue (N pages, ranked by link gap):
  1. slug-c — "Page Title" — 3 links / 847 words — unlinked: ago2 (×4), risc (×2)
  2. slug-d — "Page Title" — 1 link / 612 words — unlinked: dicer (×3)
  ...
```

#### `wiki(link_audit="slug")` — single-page audit

Returns:
- Unlinked candidates: page titles and slugs found as plain text in the body (case-insensitive regex, not inside `[[]]`) with occurrence counts and section locations
- Top-3 synthesis candidates by coverage ratio, with scores and overlapping section names

The synthesis candidates shown here are **read-only** — the sweep does not act on them, it queues them.

#### `wiki(link_audit="slug", mark_swept=True, cluster={...})` — mark page swept

Sets `last_swept = now()`. If the agent provides a `cluster` argument, creates or extends a synthesis cluster:

```python
wiki(
    link_audit="slug",
    mark_swept=True,
    cluster={
        "members": ["slug-a", "slug-b"],   # slugs the agent judged as belonging together
        "label": "RISC assembly mechanism", # agent-assigned concept name
        "rationale": "...",                 # agent's one-sentence reasoning
    }
)
```

If no `cluster` is provided, only `last_swept` is set — no cluster is written. The tool checks whether any member slug is already in a pending cluster and merges if so (union-find). Coverage ratios from the JxK computation are stored in `synthesis_cluster_edges`. Called by the skill in Step 1c.

#### Synthesis candidate backend (two-pass)

**Pass 1 — mean embedding pre-filter (O(pages) per target page):**
```sql
SELECT p2.slug, array_cosine_similarity(p1.mean_embedding, p2.mean_embedding) AS sim
FROM pages p1, pages p2
WHERE p1.slug = ? AND p2.slug != p1.slug
  AND sim > 0.50
ORDER BY sim DESC LIMIT 20
```

**Pass 2 — JxK section cross-product on the 20 candidates only:**
For each candidate, run `hybrid_search` with each section of the target page as a query. Compute:
```
coverage_ratio = sections of candidate appearing in top hits / total sections of candidate
```

Candidates with `coverage_ratio > 0.30` are inserted into `synthesis_queue`. The sweep skill never sees synthesis decisions — it only calls `mark_swept` and the tool handles queue population.

---

### 4. `lacuna-sweep` Skill

The editorial counterpart to `lacuna-ingest`. Where ingest adds knowledge, sweep tightens it: missing links are added, the synthesis queue is populated for the synthesis engine to act on overnight.

Structurally mirrors ingest: verbal commit before every action, search before write, active decisions cannot be silently skipped.

#### Mode

| Mode | Declared by | Behaviour |
|---|---|---|
| `standard` | default | Pause at Step 0 for queue approval |
| `auto` | "auto", "just run it" | Skip Step 0 pause. All per-page commits and decisions run identically. User accepts full responsibility for model quality. |

Auto mode exists to support cron execution. In auto mode the agent processes the full queue without pausing.

---

#### Step 0 — Get the queue

```
wiki(link_audit=True)
```

Agent presents the full picture out loud:

> "Vault audit:
> Research gaps (N): [slugs] — stub pages, awaiting sources.
> Ghost pages (N): [slugs] — linked but not yet created.
> Sweep backlog (N pages): ranked by link gap. Top entries: [[slug]], [[slug]], [[slug]].
> Synthesis queue currently holds N pending candidates for the synthesis engine.
> Any pages to skip or reprioritize?"

**Standard mode:** pause. Adjust if needed.
**Auto mode:** skip pause. Proceed immediately.

Create one task per page in the sweep queue before proceeding.

---

#### Step 1 — Per-page loop (streaming)

Mark task `in_progress` before starting; `completed` when done.

##### a. Commit

State out loud before touching anything:

> "Sweeping [[slug]]: [page title]
> Link gap: N links / N words — below vault median.
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

The judgment is the forcing function — the same role as the link declaration in ingest Step 3a. The agent has the page fully in context when it makes this call. Coverage ratio surfaces the candidates; the agent's read determines the cluster. Undeclared candidates are not silently dropped — they must be explicitly called false positives.

##### b. Missing wikilinks

For each unlinked candidate, one at a time:

> "[[concept]] appears N times in [section] without a wikilink. Adding to first mention."

Apply with Edit. Verify the link was written. Do not batch multiple candidates into one edit.

**Ghost page note:** if an unlinked candidate has no existing page (ghost page), still add the `[[wikilink]]`. This reinforces the research gap signal — more pages linking to a ghost increases its priority for the synthesis engine and for future ingest sessions.

##### c. Mark swept

```
wiki(link_audit="slug", mark_swept=True)
```

This sets `last_swept`, computes synthesis candidates, and writes them to `synthesis_queue`. The sweep does not process synthesis candidates — that is the synthesis engine's job.

> "Swept [[slug]]: N wikilinks added. Synthesis candidates queued if any. Next: [[next-slug]]."

Mark task completed.

---

#### Step 2 — Done

> "Sweep complete. N pages swept, N wikilinks added.
> Synthesis queue: now holds N pending candidates — run `lacuna synthesise` or schedule it to process.
> Remaining sweep backlog: N pages.
> Research gaps: N stubs, N ghost pages — visible in `lacuna status`."

---

## Decision Table

| Signal | Action |
|---|---|
| Page < 100 words or < 2 sections | Research gap — exclude from sweep queue, surface in `lacuna status` |
| Slug referenced in links but no page file | Ghost page — surface in `lacuna status`, still add `[[link]]` from referring pages |
| Known slug appears in body unlinked | Add `[[slug]]` to first mention in that section |
| Coverage ratio > 0.30 | Queued to `synthesis_queue` via `mark_swept` — synthesis engine decides |
| Coverage ratio < 0.30 | Not a synthesis candidate — not queued |

---

## What This Is Not

**Not the synthesis engine.** The sweep detects and queues. All decisions about merging pages, writing synthesis notes, mapping contradictions and consensus, and running on cron belong to the synthesis engine spec.

**Not daemon-driven.** The daemon never modifies page content. All edits are agent-applied. Automatic wikilink injection was considered and rejected: it bypasses agent judgment, violates the philosophy that the agent owns content mutations, and risks triggering the daemon's content-hash watcher in a feedback loop.

**Not a full adversary.** The sweep is editorial: links and queue population only. Claim verification is the adversary's job.

**Not a single-session operation.** The queue is a persistent backlog. Each sweep session processes as many pages as the agent can handle. `last_swept` tracks progress. The sweep is designed to be run repeatedly.
