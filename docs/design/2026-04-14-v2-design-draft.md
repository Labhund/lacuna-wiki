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
4. Parse citation markers (`[[raw/paper.pdf|1]]`) → update `claims` + `claim_sources`
5. Update manifest

The daemon does not decide what to write. It does not summarise. It does not evaluate. It is infrastructure.

### The harness

The harness (Claude Code, Hermes, or anything with file tools + MCP) is the intelligent layer. It authors pages via native file tools (Edit/Write). It navigates via the MCP tool. It runs skills for evaluation and enrichment. The daemon never gets in its way.

### Crystallisation loop

Explorations compound into the knowledge base just like ingested sources do. When an agent session produces a meaningful insight, analysis, or synthesis — it is filed back into the wiki as a first-class source. The wiki grows not only from papers but from the accumulated reasoning of the sessions that used it. This is the adversarial dream engine's role: Phase 1 (generative, high temperature) produces hypotheses; Phase 2 (adversarial, low temperature) falsifies them against the wiki; survivors are crystallised as new wiki content.

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
    citation_number INTEGER,
    relationship    TEXT                 -- supports | refutes | gap
)
```

### Why each table

- **pages**: the index. Slug → file path mapping, cluster membership.
- **sections**: the primary search unit. Section-level embeddings make search return useful results at the right granularity — not 3000-token pages, but the specific section that's relevant.
- **links**: wikilink graph. Powers the navigation panel (links in, links out). Required for InfraNodus integration.
- **sources**: source metadata with `published_date`. Recency is the only authority signal — no scoring system. `source_type = session` accommodates crystallised agent sessions as first-class sources.
- **claims**: deterministically parsed from citation markers. Every sentence containing `[[raw/...]]` is a claim. No LLM in the daemon. `superseded_by` enables explicit supersession: old claim preserved and linked, not deleted.
- **claim_sources**: the junction. `relationship` is populated by the adversary skill, not the daemon. Three values:
  - `supports` — source confirms the claim
  - `refutes` — source contradicts the claim
  - `gap` — source identifies this as an open question; claim is a known unknown

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

## Page Structure — The Review Paper Template

Every wiki page follows a standard skeleton. Sections are named consistently so routing decisions are unambiguous and the page compounds toward review quality over time.

```markdown
# {concept}

## Overview
One-paragraph synthesis. What this is, why it matters, current consensus.
Updated on every ingest — the most-maintained section.

## Background
Historical context, predecessor ideas, the problem this solves.

## Mechanism
How it works. The core technical or conceptual content.

## Variants
Significant variations, extensions, competing approaches.

## Applications
Where and how it is used in practice.

## Limitations
Known failure modes, scope constraints, open criticisms.

## Open Questions
Explicitly unknown. Gaps in current knowledge. Gap-type claims live here.

## Contradictions
Active debates in the field. Claims with refuting sources surface here.

## References
Auto-maintained by daemon from citation markers. Not hand-written.
```

Not every page needs all sections. Small pages may only have Overview and References. But the section names are fixed — agents always know where content belongs.

**Empty sections are visible gaps.** A Limitations section with no content is a known structural gap that the adversary skill or dream engine should target.

---

## Ingest Skill — Integration Mandate

The ingest skill enforces read-before-write. The agent never writes to a page without first understanding what is already there. This is what prevents the append-by-default failure mode (second source adds a new paragraph instead of integrating with the first).

**Mandatory ingest flow:**

1. **Search first** — call the wiki tool with `{"q": "<concept>"}`. Find relevant pages and sections before committing to any routing decision.
2. **Route** — decide: update an existing page, add to a section of a related page, or create a new page. Creating a new page is the least preferred option. See routing policy below.
3. **Read the target section** — call the wiki tool with `{"page": "<slug>", "section": "<section>"}`. Get the current content and the navigation panel.
4. **Check existing claims** — query the DB: what claims already exist in this section? (skills script). Surface any claim with embedding similarity > 0.85 to the new content.
5. **Decide on integration**:
   - Same point, same claim → add the new source citation to the existing sentence. No new paragraph.
   - Same point, slight nuance → modify the existing sentence to incorporate both perspectives. Update citation.
   - Genuinely new point → add new content in the appropriate section.
   - Contradicts existing claim → write the new claim, mark old as superseded.
6. **Write** — using file tools (Edit/Write). The daemon syncs.

This flow is encoded in the ingest skill. It is not optional. The skill is what ensures pages compound toward review quality rather than accumulating duplicate paragraphs.

### Routing policy

| Situation | Action |
|---|---|
| Concept already has its own page | Update that page |
| Concept exists as a section of another page | Update that section; promote to own page only if coverage warrants it |
| Concept is genuinely new | Create new page with review paper skeleton |
| Partial overlap with existing section | Add to that section; cross-reference with wikilink |

**Promote-to-page rule**: a concept section gets its own page when it has accumulated content from ≥ 3 independent sources and its Mechanism section is non-trivial. Harness judgment call — not automatic.

---

## MCP Surface

**One tool.** Two call patterns. Everything else is CLI, skills scripts, or harness file tools.

```json
{ "q": "attention mechanism" }
{ "page": "attention-mechanism" }
{ "page": "attention-mechanism", "section": "Scaled Dot-Product" }
{ "pages": ["attention-mechanism", "transformer"] }
```

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
```

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

The citation format `[[raw/paper.pdf|1]]` is the claim marker. The daemon:
1. Sentence-splits the changed section
2. Extracts sentences containing `[[raw/...]]` markers
3. Parses the source slug and citation number from each marker
4. Inserts into `claims` + `claim_sources` with `relationship = NULL`

`relationship` (supports | refutes | gap) is populated by the adversary skill — a harness-driven, multi-turn LLM evaluation invoked explicitly by the user. The daemon never calls it.

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

1. **Embedding model**: which model for section + claim embeddings? Needs to run locally on RTX 5080. Candidates: `nomic-embed-text`, `mxbai-embed-large`. Multimodal-capable model for v3 path.

2. **Claim extraction granularity**: sentences are the current plan. Should multi-sentence passages sharing a citation be one claim? Affects adversary evaluation granularity.

3. **Daemon trigger**: inotify file watcher for live sync, or `llm-wiki sync` CLI run as a hook? Live watcher is seamless; CLI hook is more explicit and testable.

4. **InfraNodus integration pattern**: agent calls it directly from harness, or a skill wraps it? Skill wrapper standardises how gap detection is invoked and lets us log what was found.

5. **Cluster concept**: v1 had named clusters. Worth keeping for multi-page operations and manifest structure? Cluster = a set of pages that form a sub-topic together.

6. **Review paper section enforcement**: are section names enforced by the daemon (reject unknown section names) or advisory (skill-level convention only)? Enforcement gives structural guarantees; advisory is more flexible for domain-specific wikis.
