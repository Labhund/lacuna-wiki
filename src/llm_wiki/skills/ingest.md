---
name: llm-wiki-ingest
description: Ingest a source (PDF, URL, note, transcript) into the wiki. Search before writing. One concept at a time.
---

# Ingest Skill — llm-wiki

Ingest a source into the wiki. The source may be a registered PDF, URL, markdown note, or session transcript. This skill guides you from source to wiki pages, always searching before writing.

---

## Step 0 — Register the Source

```bash
llm-wiki add-source path/or/url   # no --concept yet
```

Note both output lines:
```
Read:    raw/path/to/key.md        ← read this in Step 1
Cite as: [[key.ext]]               ← use this cite key in Step 3e — do not invent another
```

After Step 1, assign a concept:
```bash
llm-wiki move-source KEY --concept domain/subdomain
```

Shortcut: if the concept is obvious from the title before reading, pass `--concept` directly to `add-source` instead.

Do not ingest a source you did not just register. Verify with:
```bash
llm-wiki status
```

---

## Step 1 — Structured Source Analysis

Read the source in full. For local files: use the Read tool. For URLs: fetch the page.

Output this structure before creating any todos:

```
## Main thesis: [one sentence — the source's central claim]
## Supporting evidence: [what was measured or demonstrated, at what scale — "270M 18-layer model", "benchmark X on dataset Y"]
## Secondary insights: [things said in passing that are independently interesting — not the thesis, just valuable]
## Surprising / counter-consensus claims: [anything that flies against established knowledge]
## Not worth a concept: [what you are skipping and why — source-intrinsic reasons: "too speculative", "assertion without evidence", "too tangential", "out of scope"]
```

Fill every row. "Not worth a concept" is not optional — name your exclusions. Wiki-coverage exclusions ("already in wiki") do not belong here; you have not searched yet. Those decisions happen in Step 3d.

---

## Step 2 — Create Todos and Pause

For each concept worth writing about, create a task in imperative form:
> "Write about [concept]: [one sentence describing the idea]"

Present the full list before starting:
> "Found N concepts. Here's what I'm planning:
>  1. [concept]: [one sentence]
>  2. [concept]: [one sentence]
>  ...
>  Anything to add, remove, or reframe before I start?"

Wait for the user's response. Adjust if needed. Then proceed.

**This is the only mandatory user pause.** The only other pauses are non-obvious routing decisions (see Step 3d) and supersession confirmations.

---

## Step 3 — For Each Todo

Mark each task `in_progress` before starting it; mark it `completed` when done. Repeat until all tasks are ticked.

### a. Commit

State out loud before acting:
> "I am going to write about [X]: [one sentence].
>  Concepts I will link: [[slug-a]], [[slug-b]], [[slug-c]].
>  But first I will search the wiki for similar content."

This is not commentary — it is three forcing functions in one:

1. **The one sentence** generates your search query. Articulating it first makes the next search precise.
2. **The slug list** normalises link targets before you write a single word. Declaring `[[kv-cache]]` upfront prevents `[[KV Cache]]`, `[[kv cache]]`, and `[[key-value-cache]]` drift across the session. If a slug doesn't exist yet, note it — you'll create that page later in this session.
3. **The constraint:** if a concept is not in your commit declaration, it does not appear as a `[[wikilink]]` in the text. Forces completeness before writing, not after.

The commit declaration is your best effort, not a completeness guarantee — Step 4 catches what it misses.

### b. Search

```json
{"q": "[one sentence from the commit step]", "scope": "all"}
```

`scope: "all"` catches compiled wiki sections AND raw source chunks from other registered papers. One-sentence summaries outperform concept names as queries.

### c. Read Close Matches

For any hit with score > 0.7, navigate to it:

```json
{"page": "[slug]", "section": "[section name]"}
```

Read the content. Determine: same claim? Nuance? Contradiction?

### d. Decide

| Situation | Action |
|---|---|
| Same point already in wiki | Add this source citation inline: `existing sentence. [[old.pdf]] [[new.pdf]]` |
| Slight nuance — this source adds a qualifier or extension | Edit the sentence; preserve old citation; add new |
| New angle — distinct enough for its own section | Add `## Section` to the existing page |
| Contradiction — this source disagrees with an existing claim | Write new claim; surface to user for supersession confirmation |
| Concept is entirely new to the wiki | Create a new page named after the concept |
| Partial overlap | Add to that section + add `[[wikilink]]` cross-reference |

**Non-obvious routing? Surface it:**
> "Options: (a) add citation to existing sentence in [page › section], (b) new section, (c) new page. Which?"

**Promotion heuristic:** if the section you're writing into already has ≥ 3 source citations and substantial content, raise it:
> "This section is getting dense — worth promoting to its own page?"

### e. Write

Use Edit or Write tools to modify or create wiki pages.

**Citation format:** `[[source-key.pdf]]` inline at the end of the sentence. Never author `|N` — citation numbers are daemon-assigned. The daemon watches `wiki/` and syncs automatically. Wait ~2s after writing before reading back.

**Link verification:** before finishing, confirm every concept from your commit declaration (Step 3a) appears as a `[[wikilink]]` in the text. A concept declared but not linked is a write error — either add the link or remove it from the declaration.

### f. Mark Complete

Mark the task `completed`. Move to the next todo.

---

## Step 4 — Editorial Pass

Read back each page you wrote or edited this session. This is an editorial review — structure, links, placement. It is not an epistemic review (that is the adversary's job).

### a. Links

For each concept mentioned by name that is not already a `[[wikilink]]`:

1. Does a wiki page exist for this concept? Check with search or navigate.
2. Did you create one this session?

If yes to either: wrap the first mention as `[[slug]]`. Apply with Edit.

### b. Placement

Does each claim belong on the page it is on? Ask:
- Is this claim about the concept this page is named after, or does it belong on a different page?
- Is this section dense enough to promote to its own page?

If something is misrouted: move it. Cut from here, add to the right page.

### c. Flag for Adversary

For any sentence where the written text and the source intent feel misaligned — or where you are uncertain whether the claim is fully supported — add an inline comment:

```markdown
The residual stream encodes full conversation history. <!-- TODO: adversary check -->
```

Do not rewrite or second-guess. Flag and move on. The adversary resolves these.

**Boundary:** This pass is editorial, not epistemic. If you find yourself wanting to re-search or re-read the source to resolve a doubt, that is adversary work — flag it instead.

This step is bounded to pages touched this session. Pages from previous sessions that should now link to something created this session are the residual case — the daemon's broken-link detection surfaces those.

---

## Step 5 — Done

When all tasks are ticked and the link pass is complete:

> "Ingested [N] concepts from [source slug]. [N] pages updated, [N] pages created. [N] links added in link pass."

Optional status check:

```bash
llm-wiki status
```

---

## Routing Reference

| Pattern | Rule |
|---|---|
| Concept has its own page | Update that page |
| Concept is a section of another page | Update that section |
| Concept is new | Create a page named after the concept |
| Source confirms existing claim | Add citation: `claim. [[old.pdf]] [[new.pdf]]` |
| Source adds nuance | Edit sentence + keep old citation + add new |
| Source contradicts a newer claim | Note the discrepancy; do not supersede older by newer |
| Source contradicts an older claim | Write new claim; confirm supersession with user |

