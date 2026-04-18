# Daemon Concurrency & Sweep Pre-computation — Design Spec

**Date:** 2026-04-19  
**Status:** Approved  
**Covers:** DB concurrency fix, daemon internal architecture (writer queue + reader pool + worker pool), `lacuna sweep` CLI, candidate cache schema, config additions.

---

## Problem Statement

Three independent but related issues discovered after a large ingest (1,653 pages, 3.7 GB vault):

1. **DB concurrency:** DuckDB 1.5.x uses a process-level exclusive write lock. When the daemon holds the lock, every external CLI command (`lacuna status`, `lacuna claims`, etc.) crashes with `IOException: Could not set lock on file`. The design spec assumed concurrent read-only access was possible across processes — it is not in DuckDB 1.5.x.

2. **Sweep timeout:** `_top_unlinked_candidates()` is O(N×body) per page at MCP call time. `vault_audit()` calls it for every unsewpt page — O(S×N×body) total. At 1,653 un-swept pages, every `wiki(link_audit=True)` call times out before returning.

3. **Sequential initial sync:** `initial_sync()` embeds all pages sequentially on daemon startup. With 1,653 un-embedded pages, this is correct behaviour but slow. No parallelism, no concurrency control on embed requests.

---

## Design Constraints (from spec)

- **P1:** Daemon is zero intelligence. No generative LLM calls. Embedding only (deterministic).
- **P7:** Intelligence lives in the agent harness. The daemon and CLI never make content decisions.
- DuckDB 1.5.x: one process holds the write lock; within that process, multiple RW connections are allowed (but not mixed RW + read-only).
- The markdown files are truth. The DB is derived state.

---

## Section 1: DB Concurrency & External HTTP API

### Root cause

DuckDB's process-level write lock is exclusive. When the daemon runs, no external process can open the DB file — even read-only. The design spec's concurrency model ("skills scripts open DB read-only; multiple concurrent readers supported") breaks specifically because of the daemon's write connection.

### Fix

The daemon exposes a minimal HTTP API on `mcp_port + 1` (default `7655`). Every CLI command that reads the DB checks the PID file first:

- **Daemon running:** route read request to HTTP API — never open DB directly.
- **Daemon not running:** open DB directly as read-only — exactly as the design spec originally described.

Write commands (`add-source`, `adversary-commit`, `move-source`, `sync`) keep the existing SIGUSR1 pause protocol unchanged.

### HTTP API surface

```
GET  /status              → JSON vault status (table counts, sweep metrics)
GET  /claims?mode=&page=  → JSON claims list
POST /sweep               → submit sweep pre-computation job, returns job_id
GET  /sweep/status        → JSON {done, total, eta_seconds, job_id}
```

Implementation: stdlib `http.server.HTTPServer` on a daemon thread. No new dependencies. Responses are JSON.

### CLI routing table

| Command | Daemon running | Daemon not running |
|---|---|---|
| `lacuna status` | `GET /status` | open DB read-only directly |
| `lacuna claims` | `GET /claims?...` | open DB read-only directly |
| `lacuna sweep` | `POST /sweep` + poll `/sweep/status` | run directly with local connection + pool |
| `lacuna sync` | SIGUSR1 pause (unchanged) | open DB read-write directly |
| `lacuna add-source` | SIGUSR1 pause (unchanged) | open DB read-write directly |
| `lacuna adversary-commit` | SIGUSR1 pause (unchanged) | open DB read-write directly |
| `lacuna move-source` | SIGUSR1 pause (unchanged) | open DB read-write directly |

**Status API port:** always `mcp_port + 1`. Derived, not configured.

---

## Section 2: Daemon Internal Architecture

### Components

```
┌─────────────────────────── Daemon Process ────────────────────────────────┐
│                                                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │  Write Queue  (queue.Queue — unbounded, thread-safe)                 │ │
│  │  Writer Thread — sole owner of write_conn                            │ │
│  │    drains queue, executes WriteOp tuples                             │ │
│  │    never does network I/O (no embed calls)                           │ │
│  │    FTS rebuild batched: once per sync/sweep job, not per page        │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│                                                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │  Reader Pool  (reader_pool_size connections, all RW, SELECT-only)    │ │
│  │    pool.acquire() / pool.release() via threading.Semaphore           │ │
│  │    shared by: MCP server · status HTTP API · sweep read queries      │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│                                                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │  Worker Pool  (ThreadPoolExecutor, max_workers=sync_workers)         │ │
│  │    reads via Reader Pool                                             │ │
│  │    embeds via Embed Semaphore                                        │ │
│  │    writes via Write Queue (producer-consumer)                        │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│                                                                            │
│  ┌────────────────────┐  ┌─────────────────────────────────────────────┐  │
│  │  MCP SSE  :7654    │  │  Status HTTP API  :mcp_port+1               │  │
│  │  reads via pool    │  │  reads via pool · sweep jobs via pool       │  │
│  └────────────────────┘  └─────────────────────────────────────────────┘  │
│                                                                            │
│  Embed Semaphore  (threading.Semaphore, value=embed_concurrency)           │
└────────────────────────────────────────────────────────────────────────────┘
```

### Writer thread contract

- **Sole writer.** Nothing writes to the DB except the writer thread.
- Workers push `WriteOp` named tuples: `(sql: str, params: list)` or `(fn: Callable, args: tuple)` for operations needing their own write result mid-transaction (e.g. `INSERT` then fetch new `id`).
- If a worker needs a write result back (e.g. newly inserted `page_id`), it creates a `concurrent.futures.Future`, puts `(fn, args, future)` on the queue, then blocks on `future.result()`. The writer executes `fn(*args)` and resolves the future. The writer thread always makes progress (FIFO, never blocks on futures itself) — no deadlock risk.
- The writer thread never calls `embed_fn`. It executes SQL only.

### Reader pool contract

- Pool size = `reader_pool_size` (default 3: MCP + status API + sweep reads).
- Each connection opened once at startup without `readonly=True` (DuckDB same-process RW+RW is allowed; RW+RO is not).
- Connections are used SELECT-only by all pool consumers.
- `pool.acquire()` blocks if pool exhausted — correct backpressure.
- Connections are never closed mid-run except during SIGUSR1 pause/resume.

### Worker pool & embed semaphore

- `ThreadPoolExecutor(max_workers=sync_workers)`.
- Each worker: read file → parse → acquire embed semaphore → embed → release semaphore → push WriteOps to queue.
- Embed semaphore (`threading.Semaphore(embed_concurrency)`) caps simultaneous HTTP requests to the embedding server. Prevents GPU queue buildup on local servers.
- **Parallelism ceiling:** effectively `embed_concurrency / embed_latency_per_page`. At `embed_concurrency=4` and 100ms/page: ~40 pages/sec. `sync_workers` can be set to nproc — it governs parse/embed concurrency, not write concurrency. The writer thread is never the bottleneck.

### Daemon startup sequence

1. Open `write_conn`, start writer thread.
2. Open `reader_pool_size` connections, initialise reader pool.
3. Start worker pool (`ThreadPoolExecutor`).
4. Submit `initial_sync` as a sweep job to the worker pool (same code path as `lacuna sweep`).
5. Start watchdog observer — single-file events enqueue one worker task each.
6. Start MCP SSE server and status HTTP API.

### Watchdog events

Single-file changes are low-volume. Each watchdog event submits one task to the worker pool: read → parse → embed → push WriteOps. The writer thread processes them as they arrive. No special path — same producer-consumer as batch sync.

### SIGUSR1 pause (unchanged mechanism, updated teardown)

On pause signal:
1. Drain the write queue (finish in-flight writes).
2. Stop watchdog observer.
3. Close `write_conn`.
4. Write pause ack file.

Reader pool connections remain open during pause — they hold no write lock. The CLI's exclusive `write_conn` does not conflict with open read connections in another process (they were opened by the daemon process, which is paused but alive).

On resume: reopen `write_conn`, restart watchdog, clear pause event.

---

## Section 3: `lacuna sweep` CLI and Candidate Cache

### Philosophy

`lacuna sweep` is pre-computation, not intelligence. It does the O(N) vault-wide work offline and stores results as DB state. The sweep skill reads that state and makes decisions. P1 is not touched.

### What moves from MCP call time to sweep pre-computation

**Unlinked candidates** (currently O(N×body) per page at MCP time):

Build an inverted index in one vault pass: iterate all page bodies once, for each page collect slugs/titles of other pages that appear unlinked in its body. Total cost O(N×body) once, not per-page.

New table:

```sql
unlinked_candidates (
    page_id        INTEGER REFERENCES pages(id),
    candidate_slug TEXT NOT NULL,
    mention_count  INTEGER NOT NULL,
    computed_at    TIMESTAMP NOT NULL,
    PRIMARY KEY (page_id, candidate_slug)
)
```

**Synthesis candidates** (currently O(N + k×M²) per page at MCP time):

Page-level embedding similarity (Pass 1) is a single DuckDB query across all `page_embeddings` — run once for the whole vault. Coverage ratios (Pass 2) computed only for top-k pairs. Results stored in existing `synthesis_clusters` and `synthesis_cluster_edges` tables.

### CLI interface

```
lacuna sweep [--batch N] [--force]
```

- No args: pre-compute candidates for all pages in the sweep queue.
- `--batch N`: process next N pages. For incremental top-ups after small ingests.
- `--force`: recompute all pages regardless of `last_swept`.

**When daemon running:** `POST /sweep` → daemon runs job on worker pool → CLI polls `GET /sweep/status` → prints live progress (`[342/1653] pages pre-computed, ETA ~18s`) → returns on completion.

**When daemon not running:** instantiates a local `ThreadPoolExecutor` and runs `_run_sweep_job()` directly with its own DB connection.

### Same code path

`_run_sweep_job(conn_pool, write_queue, embed_fn, config, page_slugs)` is a standalone function. The daemon calls it on its internal pool; the standalone CLI instantiates a local equivalent and calls the same function. No duplication.

### How the sweep skill changes

- `wiki(link_audit=True)` vault audit becomes a fast DB read from `unlinked_candidates` and `synthesis_cluster_edges` — O(1) per page.
- `wiki(link_audit="slug")` page audit reads pre-computed candidates directly.
- **Fallback:** if a page has no pre-computed candidates (created after last sweep), live computation runs for that page only. The skill degrades gracefully; it does not fail.

### Sweep timing fix

`mark_swept` currently sets `last_swept = now()`. If the daemon syncs the page *after* `mark_swept` is called (because the agent just added wikilinks), `last_modified` (daemon sync time) > `last_swept` (mark time) → page re-enters the queue incorrectly.

**Fix:** `mark_swept` sets `last_swept = last_modified` (the current DB value at mark time). This is idempotent against the daemon's subsequent frontmatter writeback — the frontmatter write does not change `last_modified` (body hash unchanged → early exit → no `last_modified` update). A page only re-enters the queue if its body genuinely changes after sweeping.

---

## Section 4: Config Schema

New `[worker]` section in `.lacuna.toml`:

```toml
[worker]
sync_workers      = 4   # threads in the sync/sweep worker pool
embed_concurrency = 2   # max simultaneous embed HTTP requests
reader_pool_size  = 3   # reader connections in daemon pool
```

**Defaults:**
- `sync_workers = 4` — conservative; user bumps to nproc for large ingests.
- `embed_concurrency = 2` — safe for local GPU server; bump to 4–8 if server handles it.
- `reader_pool_size = 3` — MCP (1) + status API (1) + sweep reads (1).

**Status API port** = `mcp_port + 1`. Derived, not configured. One fewer thing to set.

**Environment variable overrides:**
```
LACUNA_SYNC_WORKERS
LACUNA_EMBED_CONCURRENCY
LACUNA_READER_POOL_SIZE
```

**`lacuna init`** writes the `[worker]` section with defaults. Existing vaults without the section use hardcoded defaults — no migration required.

---

## Schema Changes

### New table: `unlinked_candidates`

```sql
CREATE TABLE unlinked_candidates (
    page_id        INTEGER NOT NULL REFERENCES pages(id),
    candidate_slug TEXT NOT NULL,
    mention_count  INTEGER NOT NULL,
    computed_at    TIMESTAMP NOT NULL,
    PRIMARY KEY (page_id, candidate_slug)
);
```

Added as schema version 5. Migration: create table if not exists — no data migration needed (populated by first `lacuna sweep` run).

### `pages.last_swept` (already exists in v3)

No change to column. Fix is in `mark_swept` logic only: set `last_swept = last_modified` not `now()`.

---

## What Does Not Change

- Daemon is still zero generative LLM calls.
- SIGUSR1 pause protocol for write commands is unchanged.
- MCP tool surface (`wiki(...)`) is unchanged — faster, not different.
- Markdown files remain the source of truth.
- The sweep skill's intelligence (which links to add, which pages to synthesise) remains entirely in the agent harness.
- `lacuna sync` remains available as an explicit one-shot sync command.
