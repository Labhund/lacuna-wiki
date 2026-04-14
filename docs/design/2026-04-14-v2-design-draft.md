# llm-wiki v2 — Design Draft

> Working document. Not a spec yet. Captures the design conversation to date.

---

## Mission

A personal research knowledge substrate that grounds LLM agents in current, specific, structured knowledge — overcoming training data cutoffs and the pull toward bland consensus synthesis. The adversarial interface (researcher ↔ agent) sparks ideas. The wiki makes that interface work at research quality.

This is not a RAG system. RAG re-derives. A wiki accumulates and compounds. The agent navigating it isn't averaging over training priors — it is traversing a compiled structure of specific claims from specific papers, built and maintained by the researcher's own harness.

**The north star:** each wiki page, given sufficient sources, should be publishable as a review paper on its topic. Not a bag of paragraphs — a synthesised, cited, evolving document that improves with every source added.

---

## Core Architecture

### The split

```
Body (markdown pages)          Soul (DuckDB)
──────────────────────         ──────────────────────────────────
Human + agent readable         Section-level vectors
Authored by harness LLM        Wikilink graph
Edited by anyone               Claims + sources + relationships
Git as audit trail             Supersession links
Obsidian-compatible            Recency-based contradiction flags
                               Token counts + section topology
```

The markdown files are truth. The DB is derived from them. The daemon watches the files and keeps the DB in sync — always, regardless of what edited the file (harness, Obsidian, vim, anything).

The skills directory is the schema. It is the most important part of the system — encoding what the wiki is, how pages are structured, how to ingest, how to integrate, when to create vs update. Karpathy's original called this CLAUDE.md; in v2 it is a skills directory that any harness can load. The schema co-evolves with the wiki.

### The daemon

Pure file-watcher and DB sync engine. **Zero LLM calls.** Ever.

On file change:
1. Parse section structure → update `sections`
2. Recompute section embeddings → update `sections.embedding`
3. Parse wikilinks → update `links`
4. Parse citation markers (`[[key.pdf]]`) → update `claims` + `claim_sources`
5. Update manifest

The daemon does not decide what to write. It does not summarise. It does not evaluate. It is infrastructure.

**Citation format:** `[[vaswani2017.pdf]]` — source key only, no path prefix, no `|N` number. Obsidian resolves by shortest unique filename match. The daemon assigns sequential citation numbers as a derived DB field (per page, per section). The agent never invents filenames — it uses the canonical key printed by `llm-wiki add-source`.

### The harness

The harness (Claude Code, Hermes, or anything with file tools + MCP) is the intelligent layer. It authors pages via native file tools (Edit/Write). It navigates via the MCP tool. It runs skills for evaluation and enrichment. The daemon never gets in its way.

### Crystallisation loop

Explorations compound into the knowledge base just like ingested sources do. When an agent session produces a meaningful insight, analysis, or synthesis — it is filed back into the wiki as a first-class source. The wiki grows not only from papers but from the accumulated reasoning of the sessions that used it. This is the adversarial dream engine's role: Phase 1 (generative, high temperature) produces hypotheses; Phase 2 (adversarial, low temperature) falsifies them against the wiki; survivors are crystallised as new wiki content.

---

## Source Registration CLI

**`llm-wiki add-source`** — the only way sources enter the wiki. Eliminates filename invention by the agent.

```
llm-wiki add-source path/to/paper.pdf [--concept {name}]
llm-wiki add-source https://arxiv.org/abs/1706.03762 [--concept {name}]
```

**Pipeline:**

```
1. Download / copy input to staging area
2. Extract metadata (title, authors, DOI, year) from PDF or URL
3. Fetch bibtex via CrossRef or Semantic Scholar (DOI lookup)
4. Derive canonical key: {firstauthorlastname}{year}  (e.g. vaswani2017)
5. Run PDF parser → {key}.md  (marker / pymupdf4llm / configured tool)
6. Write three files:
     raw/{concept}/{key}.pdf
     raw/{concept}/{key}.md    ← agent reads this
     raw/{concept}/{key}.bib   ← bibtex metadata
7. Register in sources table (slug=key, path=raw/{concept}/{key}.pdf,
   published_date from bibtex, source_type=paper|preprint|etc.)
8. Chunk .md by heading → embed each chunk (nomic-embed-text) → store in source_chunks
9. Print:
     Read:    raw/attention/vaswani2017.md
     Cite as: [[vaswani2017.pdf]]
```

The agent reads the `.md`, references the `.pdf` in citations. The canonical key is the only name it ever uses. If two papers resolve to the same key, the CLI appends a disambiguator (`vaswani2017b`).

### Concept clustering

`--concept {name}` organises all three files into `raw/{concept}/` and sets `cluster = {name}` on the source row. Wiki pages for that cluster live in `wiki/{concept}/`. The cluster field on pages is set by the ingest skill — not the daemon.

Cluster membership is the harness's judgment call, not a structural enforcement. The `cluster` field is advisory: it powers the `wiki_read_cluster` MCP call pattern and filters in SQL but does not gate anything.

### Directory anatomy

```
wiki/
  {concept}/         ← authored pages by cluster
  ...
raw/
  {concept}/
    vaswani2017.pdf
    vaswani2017.md   ← parsed, agent reads this
    vaswani2017.bib
  ...
sessions/            ← crystallised agent sessions (source_type=session)
```

---

## Database Schema

Six tables. Each earns its place against a concrete use case.

```sql
pages (
    id              INTEGER PRIMARY KEY,
    slug            TEXT UNIQUE NOT NULL,
    path            TEXT NOT NULL,
    title           TEXT,
    cluster         TEXT,
    last_modified   TIMESTAMP
)

sections (
    id              INTEGER PRIMARY KEY,
    page_id         INTEGER REFERENCES pages(id),
    name            TEXT NOT NULL,       -- matches review paper structure below
    content_hash    TEXT,
    token_count     INTEGER,
    embedding       FLOAT[1024]          -- text-embedding model, section-level
)

links (
    source_page_id  INTEGER REFERENCES pages(id),
    target_slug     TEXT NOT NULL        -- may not resolve yet; daemon flags broken links
)

sources (
    id              INTEGER PRIMARY KEY,
    slug            TEXT UNIQUE NOT NULL,
    path            TEXT NOT NULL,
    title           TEXT,
    authors         TEXT,
    published_date  DATE,                -- recency is the only authority signal
    source_type     TEXT                 -- paper | preprint | book | blog | url | session
)

claims (
    id              INTEGER PRIMARY KEY,
    page_id         INTEGER REFERENCES pages(id),
    section_id      INTEGER REFERENCES sections(id),
    text            TEXT NOT NULL,       -- citation-anchored sentence, verbatim from page
    embedding       FLOAT[1024],
    superseded_by   INTEGER REFERENCES claims(id)   -- explicit supersession link
)

claim_sources (
    claim_id        INTEGER REFERENCES claims(id),
    source_id       INTEGER REFERENCES sources(id),
    citation_number INTEGER,             -- daemon-assigned sequential number per page/section
    relationship    TEXT                 -- supports | refutes | gap
)

source_chunks (
    id              INTEGER PRIMARY KEY,
    source_id       INTEGER REFERENCES sources(id),
    chunk_index     INTEGER NOT NULL,
    heading         TEXT,                -- section heading if present
    text            TEXT NOT NULL,
    token_count     INTEGER,
    embedding       FLOAT[1024]          -- nomic-embed-text, same model as sections
)
```

### Why each table

- **pages**: the index. Slug → file path mapping, cluster membership.
- **sections**: the primary search unit. Section-level embeddings make search return useful results at the right granularity — not 3000-token pages, but the specific section that's relevant.
- **links**: wikilink graph. Powers the navigation panel (links in, links out). Required for InfraNodus integration.
- **sources**: source metadata with `published_date`. Recency is the only authority signal — no scoring system. `source_type = session` accommodates crystallised agent sessions as first-class sources.
- **claims**: deterministically parsed from citation markers. Every sentence containing a `[[key.pdf]]` marker is a claim. No LLM in the daemon. `superseded_by` enables explicit supersession: old claim preserved and linked, not deleted.
- **claim_sources**: the junction. `relationship` is populated by the adversary skill, not the daemon. Three values:
  - `supports` — source confirms the claim
  - `refutes` — source contradicts the claim (either fidelity failure or supersession by newer source)
  - `gap` — source identifies this as an open question; claim is a known unknown
- **source_chunks**: the raw evidence layer. Source `.md` files chunked by heading and embedded at `add-source` time. Enables semantic search over unsynth'd source material — catches what ingest missed, phrased differently. Queried by the adversary and ingest skills via `scope: "sources"` on the MCP tool.

### Claim types (following n7-ved's pattern)

Every claim in the wiki carries an implicit type based on how it was authored:

| Type | Meaning | Citation required |
|---|---|---|
| **Source** | Verbatim or direct paraphrase of a source | Yes — `[[raw/...]]` marker |
| **Analysis** | Inference drawn from sourced facts, reasoning shown | Yes — cites the facts it reasons from |
| **Unverified** | No authoritative source yet | No — but flagged as unverified |
| **Gap** | Known unknown — explicitly missing knowledge | No — `claim_sources.relationship = gap` when a source flags it |

The Analysis/Unverified split prevents paraphrasing-bias: the agent cannot silently rewrite what a source says and make it look like direct evidence.

### Supersession

When a newer source contradicts or updates an existing claim, the old claim is not deleted. Instead:
1. A new claim is written with the updated content
2. `claims.superseded_by` on the old claim points to the new one
3. The adversary skill sets the `refutes` relationship on the old claim
4. The old claim remains queryable (provenance is preserved) but is deprioritised in search

### Recency-based contradiction detection

```sql
-- Claims where a refuting source is newer than all supporting sources
SELECT c.text, p.slug, s_name.name AS section
FROM claims c
JOIN pages p ON c.page_id = p.id
JOIN sections s_name ON c.section_id = s_name.id
WHERE c.superseded_by IS NULL   -- skip already-superseded claims
  AND EXISTS (
    SELECT 1 FROM claim_sources cs_r
    JOIN sources s_r ON cs_r.source_id = s_r.id
    WHERE cs_r.claim_id = c.id
      AND cs_r.relationship = 'refutes'
      AND s_r.published_date > (
          SELECT MAX(s_s.published_date)
          FROM claim_sources cs_s
          JOIN sources s_s ON cs_s.source_id = s_s.id
          WHERE cs_s.claim_id = c.id
            AND cs_s.relationship = 'supports'
      )
  )
```

This is a skill script, not daemon behaviour. The daemon never evaluates claim relationships.

---

## Pages

Pages are just pages. The agent writes them. No imposed structure, no page types, no promotion events. The extra burden of deciding what kind of page to write is eliminated — the only question is what to write and where.

The review paper quality is a **north star communicated in the skill as writing guidance** — not a mechanical property of the system. The ingest skill tells the agent: write like you're contributing to a review paper on this topic. The agent is intelligent; it structures content appropriately without being told how.

A page that begins as one paragraph from one source and grows into a comprehensive multi-source document is not changing type. It is compounding. That is the entire point.

The only structural convention enforced across all pages is the citation format `[[raw/source|N]]`. Everything else — section headings, organisation, depth — is the agent's judgment. Callout markers (`[!gap]`, `[!analysis]`) are optional conventions the skill recommends, not requirements.

A page early in its life:

```markdown
# scaled-dot-product-attention

Attention scores are computed as QK^T/√dk, where dk is the key vector dimension.
This scaling prevents dot products from growing large in high-dimensional spaces,
pushing softmax into low-gradient saturation. Without it, training becomes unstable
for large dk. [[vaswani2017.pdf]]

> [!gap] How does this interact with sparse attention patterns?
> No source yet.
```

The same page after more sources — more sections, more citations, more cross-references. No different in kind. Just more complete.

---

## Ingest Skill — The Core Workflow

The ingest skill is the most important file in the system. It encodes the integration mandate that ensures pages compound toward review quality rather than accumulating duplicate paragraphs. It uses the task list pattern (same as superpowers) as shared state across what may be a 30+ step multi-turn session.

**The flow:**

```
Step 1 — Read the full source
  Agent reads the paper / tweet / session transcript / URL
  Using file tools or browser — no special tooling needed

Step 2 — Create todos
  For each concept worth writing about, create a task:
  "Write about [concept]: [one sentence describing the idea]"
  This is the full plan — all concepts identified before writing begins

Step 3 — For each todo (loop):
  a. COMMIT — agent says out loud:
     "I am going to write about [X]: [one sentence].
      But first I will search the wiki for similar content."

  b. SEARCH — wiki tool: {"q": "[one sentence summary]"}
     The summary is a better query than the concept name alone.
     Returns: section-level hits with scores, token counts, navigation context.

  c. READ — for any close matches (score > threshold):
     Read the matched section (file tools or MCP navigate).
     Check: same claim? slight nuance? contradiction?

  d. DECIDE — one of:
     - Same point → add this source citation to the existing sentence
     - Nuance → extend/modify the existing sentence, update citations
     - New angle → create a nugget page or add a new section
     - Contradiction → write new claim, note supersession in the page
     - Surface the decision to the user if judgment call is non-obvious

  e. WRITE — file tools (Edit/Write). Daemon syncs automatically.

  f. MARK COMPLETE — tick the todo

Step 4 — Done when todo list is empty
```

The commit step (saying it out loud) serves three purposes: it keeps the agent accountable to stated intent, it makes the process transparent to the user who can interrupt at any point, and it produces the natural language query for the search step.

The decision step surfaces non-obvious choices to the user — "this paper adds a gradient saturation argument to a claim already made by vaswani2017. Options: (a) add citation, (b) extend sentence, (c) new nugget. What do you think?" This is the adversarial interface in action — the user stays in the loop at integration decision points. The wiki earns its quality from these decisions.

### Routing policy

| Situation | Action |
|---|---|
| Concept already has its own page | Update that page |
| Concept exists as a section of another page | Update that section |
| Concept is genuinely new | Create nugget page |
| Partial overlap with existing section | Add to that section + cross-reference wikilink |
| Concept section has grown (≥ 3 sources, substantial content) | Promote to own page — harness judgment, not automatic |

---

## MCP Surface

**One tool.** Two call patterns. Everything else is CLI, skills scripts, or harness file tools.

```json
{ "q": "attention mechanism" }                                        // wiki sections (default)
{ "q": "attention mechanism", "scope": "sources" }                   // source chunks only
{ "q": "attention mechanism", "scope": "all" }                       // wiki + source chunks
{ "page": "attention-mechanism" }
{ "page": "attention-mechanism", "section": "Scaled Dot-Product" }
{ "pages": ["attention-mechanism", "transformer"] }
```

`scope` defaults to `"wiki"`. The adversary uses `"all"` — one call, one interface, searches compiled synthesis and raw source evidence. Ingest uses `"all"` in its search step to surface related content in registered-but-not-yet-ingested sources.

### Search response

Section-level hits, hybrid BM25 + vector. Score shows which mechanism fired.
BM25 hits get term highlighting. Vector hits surface the most relevant passage even without exact keyword match.

```
attention-mechanism › Scaled Dot-Product  (score 0.94, bm25+vec, 640 tok)
  "...the **attention** scores are computed as dot products between query
   and key vectors, scaled by √d_k to prevent gradient saturation..."

bahdanau-attention › Alignment Mechanism  (score 0.81, vec, 510 tok)
  "...a learned alignment function computes compatibility between decoder
   state and each encoder output, producing **attention** weights..."
```

### Navigate response

Section content + full navigation panel. Every field is DB-computed, zero LLM.

```
## attention-mechanism › Scaled Dot-Product

[section content]

--- navigation ---
sections on this page:
  Overview (420 tok) | Background (310 tok) | Mechanism (890 tok)
  Variants (640 tok) | Limitations (280 tok) | Open Questions (0 tok — empty)

links out:  positional-encoding | softmax | query-key-value
links in:   transformer | bert-architecture | gpt-2

semantically close sections:
  bahdanau-attention › Alignment Mechanism  (0.87, 640 tok)
  luong-attention › Global vs Local         (0.81, 510 tok)

sources cited on this page:
  [1] vaswani2017   Attention Is All You Need            2017-06-12
  [2] bahdanau2014  Neural Machine Translation by...     2014-09-01
  [3] luong2015     Effective Approaches to Attention... 2015-08-17
```

The bibliography block gives the agent recency context without a separate tool call. Citation numbers are daemon-assigned, sequentially per page.

Note: `Open Questions (0 tok — empty)` surfaces a gap without any additional tooling.

### What is not an MCP tool

| Capability | Mechanism |
|---|---|
| Status, health, sync state | `llm-wiki status` CLI or skills script |
| SQL queries (claims, contradictions, supersession) | Skills scripts — read-only DuckDB connection |
| Source ingest, claim extraction | CLI + harness ingest skill |
| Page writes | Harness file tools (Edit/Write) |
| Concept graph / gap detection | InfraNodus MCP server (separate tool) |
| Lint, audit, git | CLI |

---

## Concurrency

- Daemon: holds the single DuckDB read-write connection.
- Skills scripts: open DuckDB read-only. Multiple concurrent readers supported by DuckDB.
- Harness: never opens DuckDB directly. Reads via MCP tool or skills scripts. Writes files via file tools.

No write contention because there is exactly one writer by design.

---

## Claim Extraction

Claims are extracted **deterministically** by the daemon on every file change. No LLM.

The citation format `[[key.pdf]]` is the claim marker. The daemon:
1. Sentence-splits the changed section
2. Extracts sentences containing `[[*.pdf]]` markers
3. Resolves each key to a `source_id` in the sources table (key = slug)
4. Assigns sequential citation numbers per page (derived field, not authored)
5. Inserts into `claims` + `claim_sources` with `relationship = NULL`

`relationship` (supports | refutes | gap) is populated by the adversary skill — a harness-driven, multi-turn LLM evaluation invoked explicitly by the user. The daemon never calls it.

---

## Philosophy

Hard principles. These are not aspirations — they are design constraints. Anything that violates them gets cut.

### Seven hard points

**P1 — The agent is the sole intelligence.**
The daemon does not decide, summarise, or evaluate. Skills encode conventions. The harness is where reasoning happens. Automation of judgment is the failure mode, not a feature.

**P2 — The wiki records assertions, not truths.**
Every claim is a claim from a source. The wiki is a compiled record of what specific sources said, with the researcher's synthesis layer on top. It does not adjudicate. It does not average. It is not consensus.

**P3 — The citation is the only hard contract.**
`[[key.pdf]]` is the one syntactic commitment the agent makes. Everything else — section headings, callout markers, wikilinks — is convention, not requirement. The citation format is what makes the claims graph possible.

**P4 — Recency beats authority.**
No h-index, no journal tier, no citation count. The only authority signal is `published_date`. Newer evidence supersedes older evidence. The contradiction detection query is the mechanism.

**P5 — Compounding is directional.**
Pages move toward review quality, not away from it. A new source either adds to what's there or corrects it. Duplication is the failure mode. The ingest skill's commit→search→decide loop is the mechanism.

**P6 — The wiki is personal infrastructure.**
It is not a product. It is not a shared platform. It is a research instrument tuned to one researcher's domain and judgment. The skills directory is the researcher's schema — it co-evolves with the wiki.

**P8 — The wiki gets cheaper over time; re-extraction doesn't.**
Each ingest call pays the LLM cost once. That understanding is permanently encoded. Future sessions read compiled structure — the daemon serves it from DuckDB, zero LLM. Over a multi-year research arc the cost per insight falls as the wiki fills in. Tools that re-derive on demand (RAG, graphify over raw/) pay the extraction cost repeatedly. The wiki is the energy-efficient alternative because it compounds coherence rather than rebuilding it.

**P7 — Intelligence is never automated.**
The adversary skill runs when the researcher invokes it. Crystallisation of sessions happens when the researcher decides. No background LLM workers. No auto-resolution of contradictions. The researcher is always in the loop at judgment calls.

### Carried forward from v1

From `PHILOSOPHY.md` in the v1 repo:

| Principle | v1 ID | Status |
|---|---|---|
| LLM for understanding, code for bookkeeping | P13 | **Carried** — this is P1 above sharpened |
| Rebuildable state directory | P9 | **Carried** — daemon rebuilds DB from markdown |
| One source of truth | P3 (v1) | **Carried** — markdown files are truth, DB is derived |
| Talk pages for uncertainty | P4 (v1) | **Open** — see Open Questions |
| Single-file pages | P6 (v1) | **Updated** — pages may span sections, no structural enforcement |
| No scoring systems | P10 | **Carried** — recency only |
| Human judgment for contradictions | P11 | **Carried** — adversary skill, not daemon |

---

## Adversary Skill

### Why it exists

The ingest skill operates in synthesis mode — confirmatory, building toward a coherent page. It will naturally favour readings that fit the emerging narrative, gloss over caveats, overstate confidence, underweight limitations. This isn't a bug; it's the mode. The daemon extracts claims deterministically but leaves `relationship = NULL` — no verdict, no self-consistency.

The adversary skill fixes both. It re-reads with a completely different posture: falsification-first, low temperature, skeptical. It catches what ingest missed because it reads differently, not because it has access to different information.

**The adversary cannot be folded into ingest.** You cannot evaluate fidelity in the same cognitive mode that produced the claim.

### Two failure modes, two responses

**Fidelity failure** — the claim misrepresents its own source. Ingest read with synthesis eyes; the source actually hedges, caveats, or says something subtly different. Fix: edit the page directly. No ceremony, no supersession. The daemon picks up the change.

**Supersession** — the claim was a fair reading at ingest time, but a newer source contradicts it. Fix: pause, surface to user, confirm, write new claim with `superseded_by` link. Old claim preserved in DB for provenance.

Only supersession gets a user pause. Fidelity fixes are silent corrections.

### Targeting

Four entry points:

| Mode | Scope | Use case |
|---|---|---|
| `virgin` | `relationship = NULL` | First pass after batch ingest |
| `recency` | refuting source newer than supporting | Weekly hygiene run |
| `page` | all claims on one page | Before citing that page heavily |
| `claim` | single claim | Spot check |

Default: `virgin`. The skill accepts a mode argument.

### The flow

```
Step 1 — Target
  Run the appropriate DB query. Collect claims as todo list.
  Report: "Found N unevaluated claims across K pages."

Step 2 — For each claim (todo loop):

  a. COMMIT — state out loud:
     "Evaluating: '[claim text]'
      Source: [key] ([published_date])
      Page: [slug] › [section]"

  b. SEARCH — one MCP call, scope: "all"
     {"q": "[claim as natural language]", "scope": "all"}
     Returns: wiki section hits + source chunk hits combined.
     The claim's own source chunks surface first — fidelity check material.
     Other source chunks surface cross-source evidence.

  c. ADVERSARIAL CHECK — falsification-first posture:
     "What would have to be true for this claim to be wrong?
      Does the cited source actually support this, or does it hedge?
      Does any other source — especially a newer one — contradict it?"

  d. VERDICT:
     FIDELITY FAILURE → edit page directly, no pause. Move to next claim.
     SUPERSEDED       → pause. Surface to user:
                        "Claim: [X] ([source, date])
                         Superseded by: [newer source, date] — [one sentence]
                         Proposed new claim: [Y]
                         Approve / Skip / Override?"
     GAP              → set relationship = gap. No edit needed.
     SUPPORTS         → set relationship = supports. Move on.

  e. WRITE (if supersession approved):
     Edit page: add new claim sentence with new citation.
     Set claims.superseded_by on old claim row.
     Daemon syncs both changes.

  f. TICK — mark todo complete.

Step 3 — Report
  N claims evaluated. K supported, J gaps, M fidelity fixes (silent),
  L supersessions (P approved, Q skipped).
  List of superseded claims with their replacements.
```

### Prompt posture

The evaluation sub-step runs at low temperature with explicit adversarial framing:

```
You are evaluating a claim adversarially. Your job is to falsify it, not support it.

Claim: "{text}"
Cited source: {key} ({published_date})

Step 1: What would have to be true for this claim to be wrong?
Step 2: Does the cited source actually assert this — or does it hedge, caveat,
        or say something subtly different? Check the source chunks below.
Step 3: Does any other source in the results contradict this, especially
        a more recent one?
Step 4: State your verdict — SUPPORTS / FIDELITY FAILURE / SUPERSEDED / GAP
        One sentence of reasoning. No hedging. Pick the strongest verdict
        the evidence supports.
```

### Skill conventions (borrowed from superpowers)

- **Todo list as shared state** — survives multi-turn sessions, same pattern as ingest
- **Commit step** — agent states what it's evaluating before doing it
- **Surface only high-stakes decisions** — supersession gets user review; everything else is silent
- **Low temperature explicitly stated** — the skill instructs the harness to use skeptic mode
- **Falsification before confirmation** — the agent argues against the claim first

### Claim granularity (settled here)

Claim = the sentence(s) sharing one citation anchor. If `[[vaswani2017.pdf]]` appears at the end of a two-sentence logical unit, those two sentences are one claim. The daemon splits at citation boundaries, not sentence boundaries. The adversary evaluates at citation-anchor granularity — one verdict per anchor. Atomic enough for a clear verdict; natural enough that claims read as real sentences.

---

## Non-PDF Sources

All source types are first-class. Same sources table, same citation format, same `add-source` CLI. The pipeline branches at file type.

### Source taxonomy

| source_type | Example key | Date signal | Authored by |
|---|---|---|---|
| `paper` | `vaswani2017` | `published_date` from bibtex | External |
| `preprint` | `ho2020` | arXiv posted date | External |
| `book` | `goodfellow2016` | publication year | External |
| `blog` | `karpathy2023-rnn` | post date | External |
| `url` | `openai-gpt4-report` | fetched or published date | External |
| `podcast` | `lex-fridman-karpathy-2023` | episode date | External (transcribed) |
| `transcript` | `2026-04-14-lab-meeting` | recording date | Human (transcribed) |
| `session` | `2026-04-14-attn-investigation` | session date | LLM (crystallised) |
| `note` | `2026-04-14-meeting-kv-cache` | note date | Human |
| `experiment` | `2026-04-14-scaling-run` | experiment date | Human |

Citation format is the same regardless of type — file extension reflects the primary file: `[[vaswani2017.pdf]]`, `[[karpathy2023-rnn.md]]`, `[[2026-04-14-attn-investigation.md]]`.

### add-source pipeline by type

```
.pdf input  → bibtex fetch (CrossRef/Semantic Scholar) → PDF parse → .md
URL input   → fetch + readability/jina → .md, extract date from page metadata
.md input   → already markdown, register directly — no conversion
              --date flag for sources without discoverable date
              --type flag if type inference is wrong
```

### Date for session/note/experiment types

`published_date` = date the reasoning occurred, not the date it was filed. A session from April 2026 filed in May 2026 has `published_date = 2026-04-14`. This matters for recency-based contradiction detection.

---

## Crystallise Skill

The ingest skill mirrored. Where ingest asks "I found a source — what does the wiki already know?", crystallise asks "I ran an investigation — what did I learn, and where does it fit?"

**The skill is semi-structured and dialogic.** Like brainstorming, it presents findings to the user, surfaces connections, and works toward a concrete output. The agent doesn't silently write — it thinks out loud, the researcher stays in the loop.

**The flow:**

```
Step 1 — Present findings
  Agent summarises what the session/investigation/experiment produced.
  Key claims identified. User confirms or corrects the framing.

Step 2 — Search for existing pages
  For each key claim: wiki tool {"q": "[claim summary]"}
  Report back: "This connects to [page], [page]. This is genuinely new."

Step 3 — Dialogue
  For each connection: surface the relationship.
  "This experiment contradicts the claim in [page › section] from 2024."
  "This analysis extends [page] but hasn't been tested against [page]."
  User guides where each finding should land.

Step 4 — Write
  File session as source: sessions/{date}-{slug}.md
  Register via add-source (source_type=session)
  Update existing pages or create new page — same commit→search→decide loop as ingest.

Step 5 — File
  New wiki page or updated pages committed.
  Session is now citable: [[{date}-{slug}.md]]
```

The output is a filed session (citable, dated, preserved) plus a wiki page (or updates to existing pages). The session serves as the source; the page is the synthesis.

---

## What is Not In v2

| Feature | Status |
|---|---|
| Multimodal embeddings (images, figures) | Schema-ready (`source_type` + `claims.embedding` accommodate it), implementation v3 |
| Adversary skill | Skills directory — not a daemon behaviour |
| Confidence scoring | Derivable from claim_sources when adversary populates relationship |
| wiki_query (opaque answer box) | Removed — agent traverses directly |
| wiki_ingest MCP tool | Removed — CLI + harness ingest skill |
| Background LLM workers | None. Zero. |
| Complex authority scoring | Replaced by `published_date` + recency logic |
| Automatic contradiction resolution | Never automatic — adversary skill + human judgment |

---

## Open Questions

1. **Claim extraction granularity**: sentences are the current plan. Should multi-sentence passages sharing a citation be one claim? Coupled to adversary skill design — cannot settle until adversary is scoped.

2. **InfraNodus integration pattern**: agent calls it directly from harness, or a skill wraps it? Low priority given P8 — run over wiki pages (already compiled), not raw/.

---

## Settled Decisions

| Decision | Resolution |
|---|---|
| Embedding model | `nomic-embed-text` — text-only, already served locally on RTX 5080. Multimodal embeddings are v3. |
| Daemon trigger | Both: inotify live watcher (always-on, silent) + `llm-wiki sync` CLI (explicit, scriptable). Daemon is silent by default — logs to file, never stdout, never blocks writes. Visible only via `llm-wiki status`. |
| Talk pages | Cut. The crystallise skill covers uncertainty and ongoing debates as filed sessions. A separate talk file per page is friction with no payoff. |
| Review paper section enforcement | Advisory. Skill guidance, not daemon enforcement. |
| Video/audio ingest | Supported via optional pipeline: yt-dlp (audio-only download) → faster-whisper (local transcription, RTX 5080) → `.md` transcript → `add-source`. YouTube URLs and local audio/video files both handled. `source_type = podcast \| transcript`. Optional deps — not required for base install. |
