# MCP Surface — lacuna-v2

> Design artifact. One tool, two call patterns. Everything else is CLI, skills scripts, or harness file tools.

---

## The Tool: `wiki`

The single MCP tool. Stateless — all intelligence is in the harness. The daemon serves pure DB queries and formatted responses.

### Call patterns

```json
// Search — hybrid BM25 + vector, section-level results (wiki pages, default)
{ "q": "attention mechanism" }

// Search — source chunks only (raw evidence layer)
{ "q": "attention mechanism", "scope": "sources" }

// Search — wiki sections + source chunks combined
{ "q": "attention mechanism", "scope": "all" }

// Navigate — page view with navigation context
{ "page": "attention-mechanism" }

// Section view — specific section + navigation context
{ "page": "attention-mechanism", "section": "Scaled Dot-Product" }

// Multi-read — navigation view for each, concatenated
{ "pages": ["attention-mechanism", "transformer"] }
```

`scope` defaults to `"wiki"`. Adversary skill uses `"all"`. Ingest search step uses `"all"` to surface related content in registered-but-not-yet-ingested sources.

---

## Search response

Section-level hits, BM25 and/or vector. Score shows which mechanism fired.
BM25 hits: matched terms highlighted inline.
Vector hits: most relevant passage surfaced even without exact keyword match.

```
attention-mechanism › Scaled Dot-Product (score 0.94, bm25+vec, 640 tok)
  "...the **attention** scores are computed as dot products between query
   and key vectors, scaled by √d_k to prevent gradient saturation..."

bahdanau-attention › Alignment Mechanism (score 0.81, vec, 510 tok)
  "...a learned alignment function computes compatibility between decoder
   state and each encoder output, producing **attention** weights..."

transformer › Encoder Stack (score 0.74, bm25, 890 tok)
  "...multi-head **attention** allows the model to jointly attend to
   information from different representation subspaces..."
```

Agent jumps to any result by calling `{"page": "<slug>", "section": "<section>"}`.

---

## Navigate response

Full section content + navigation panel. Every field is DB-computed, zero LLM.

```
## attention-mechanism › Scaled Dot-Product

[section content...]

--- navigation ---
other sections on this page:
  Overview (420 tok) | Mechanism (890 tok) | Multi-Head Attention (1100 tok)

links out: positional-encoding, softmax, query-key-value
links in: transformer, bert-architecture, gpt-2

semantically close sections (by claim similarity):
  bahdanau-attention › Alignment Mechanism (score 0.87, 640 tok)
  luong-attention › Global vs Local (score 0.81, 510 tok)

sources cited on this page:
  [1] vaswani2017   Attention Is All You Need            2017-06-12
  [2] bahdanau2014  Neural Machine Translation by...     2014-09-01
  [3] luong2015     Effective Approaches to Attention... 2015-08-17
```

Citation numbers are daemon-assigned sequentially per page. Agent never authors `|N` numbers.

---

## Multi-read response

Same navigate view, replicated per page, concatenated. One call for orientation across multiple pages.

```
## attention-mechanism
[navigate view for attention-mechanism]

---

## transformer
[navigate view for transformer]
```

---

## What is NOT an MCP tool

| Capability | How |
|---|---|
| Vault status, health, sync state | `lacuna status` CLI or skills script |
| SQL queries (claims, confidence, authority) | Skills scripts with read-only DuckDB connection |
| Ingest / claim extraction | CLI + skills (harness-driven, LLM call outside daemon) |
| Write pages | Harness file tools (Edit/Write) — daemon watches and syncs |
| Lint, audit, git | CLI |

---

## Concurrency model

Daemon holds the single read-write DuckDB connection.
Skills scripts open read-only connections (multiple concurrent, supported by DuckDB).
No agents write to the DB directly — harness writes files, daemon syncs.
