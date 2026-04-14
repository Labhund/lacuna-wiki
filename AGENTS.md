# llm-wiki-v2 — Agent Instructions

**Read this before doing anything in this repository.**

This is a personal research knowledge substrate. You are the intelligent layer. The system is designed around your judgment — do not shortcut it.

---

## Read the design spec first

Before any substantive work, read the full design document:

```
docs/design/2026-04-14-v2-design-draft.md
```

It specifies: the daemon, the database schema (seven tables), the MCP surface, the ingest skill flow, the adversary skill flow, the crystallise skill, the source registration CLI, and the concurrency model. The document is the authority. These instructions are a summary of the constraints that most directly affect agent behaviour.

---

## Nine hard principles

These are design constraints, not aspirations. Anything that violates them is wrong.

**P1 — You are the sole intelligence.**
The daemon does not decide, summarise, or evaluate. Skills encode conventions. You are where reasoning happens. Do not delegate judgment to infrastructure.

**P2 — The wiki records assertions, not truths.**
Every claim is a claim from a source. Do not adjudicate. Do not average. Do not synthesise toward consensus. Record what specific sources said, with your synthesis layer on top.

**P3 — The citation is the only hard contract.**
`[[key.pdf]]` is the one syntactic commitment you make. Everything else — section headings, callout markers, wikilinks — is convention. The citation format is what makes the claims graph possible. Do not invent citation formats.

**P4 — No manual authority scoring.**
No h-index, no journal tier, no citation count. Recency is one input to supersession judgment — not a rule. The adversary skill determines whether newer evidence actually supersedes.

**P5 — Compounding is directional.**
Pages move toward review quality, not away from it. A new source either adds to what's there or corrects it. Duplication is the failure mode. Always search before writing.

**P6 — This is personal infrastructure.**
It is not a product. It is a research instrument tuned to one researcher's domain and judgment. The skills directory is the researcher's schema — it co-evolves with the wiki.

**P7 — Intelligence is never automated.**
The adversary skill runs when the researcher invokes it. Crystallisation happens when the researcher decides. No auto-resolution of contradictions. The researcher is always in the loop at judgment calls.

**P8 — Do not re-synthesise what the wiki has already compiled.**
Each ingest call pays the LLM cost once; the result is permanently encoded. Read compiled structure from DuckDB. Re-synthesising wiki content from scratch is the failure mode — it signals the wiki is not doing its job.

**P9 — The files are the user's files.**
Sit passively on top of the file system. Add value without adding friction or obscure rituals. The user can reorganise directories, edit in Obsidian, vim, or anything else — the system adapts silently. The only contract the user must honour is the citation format. Everything else is the system's problem.

---

## Citation format

```
[[vaswani2017.pdf]]
```

- Source key only. No path prefix. No `|N` number. No invented filenames.
- The key is printed by `llm-wiki add-source` when the source is registered. Use exactly that key.
- Citation numbers are assigned by the daemon and appear only in the MCP navigate response — never in the file.
- Every sentence containing a `[[key.pdf]]` marker is a claim. The daemon extracts it deterministically.

---

## Writing pages

- Pages are just pages. No frontmatter. No imposed structure. No page types.
- `slug` = filename without `.md`. `title` = first `# heading`.
- Cluster = relative directory path from `wiki/`. Never authored — derived from file location.
- Write like you're contributing to a section of a review paper: synthesised, cited, integrating across sources.
- Always search before writing a new section. The ingest skill's commit→search→decide loop is the mechanism that prevents duplication.

---

## Directory placement

- `wiki/` — compiled pages. Authored by agent or human.
- `raw/` — sources. Written once by `add-source`. **Immutable content after registration.**
- Directory placement reflects intellectual domain. `source_type` is DB metadata — orthogonal to directory.
- A session about attention goes in `raw/machine-learning/attention/`, not `raw/sessions/`.
- Moving files between directories is safe. Renaming breaks the slug→filename mapping.

---

## What you write to

- **Wiki pages**: file tools (Edit/Write). Daemon syncs automatically.
- **Sources**: never. `raw/` is immutable after `add-source`.
- **Database**: never directly. Harness writes files; daemon syncs DB. The one exception is adversary results, committed via `llm-wiki adversary-commit` CLI at end of adversary run.

---

## MCP tool

One tool, five call patterns:

```json
{ "q": "attention mechanism" }                        // search wiki sections (default)
{ "q": "attention mechanism", "scope": "sources" }   // source chunks only
{ "q": "attention mechanism", "scope": "all" }        // wiki + source chunks
{ "page": "attention-mechanism" }                     // navigate: full page + nav panel
{ "pages": ["attention-mechanism", "transformer"] }   // multi-read
```

Use `scope: "all"` in the ingest search step and during adversary evaluation. Use `scope: "wiki"` for general navigation.

---

## Claim types (agent convention, not daemon-enforced)

| Type | Meaning | Citation |
|---|---|---|
| Source | Verbatim or direct paraphrase | `[[key.pdf]]` required |
| Analysis | Inference from sourced facts, reasoning shown | `[[key.pdf]]` — cites the facts it reasons from |
| Unverified | No authoritative source yet | None — flag with `[!unverified]` |
| Gap | Known unknown | None — `[!gap]` callout |

The daemon only sees citation markers. Unverified and gap claims are invisible to the claims graph.
