---
name: lacuna-ingest
description: Ingest a source (PDF, URL, note, transcript) into the wiki. Search before writing. One concept at a time.
---

# Ingest Skill — lacuna

Ingest a source into the wiki. The source may be a registered PDF, URL, markdown note, or session transcript. This skill guides you from source to wiki pages, always searching before writing.

---

## Mode

The user declares the mode at the start of the session:

| Mode | Declared by | Pause pattern |
|---|---|---|
| `standard` (default) | no declaration, or "standard" | One pause at Step 2 for concept list approval |
| `auto` | "auto", "just run it", "no pauses" | No pauses — full autonomous loop |
| `aligned` | "aligned", "walk me through this" | Pause per concept — present before writing |

If no mode is declared, use standard.

**Auto mode:** Skip the Step 2 pause entirely. Run the full todo loop without surfacing routing decisions — including the non-obvious decisions in Step 3d that standard mode would surface. The agent resolves these silently. Use for: batch ingest of trusted material, re-ingesting already-known sources, or when the user has explicitly opted out of the integration dialogue.

**Aligned mode:** See the Aligned Mode section at the end of this skill.



---

## MCP Tool Reference

All wiki queries go through a single MCP tool named **`wiki`**. It has three modes — exactly one of `q`, `page`, or `pages` must be provided per call.

**Search** — hybrid semantic + keyword search:
```
wiki(q="your query here", scope="all")
```
`scope` values: `"wiki"` (compiled pages only, default), `"sources"` (raw source chunks only), `"all"` (both).

**Navigate to a page** — read a full page or one section:
```
wiki(page="slug")
wiki(page="slug", section="Section Name")
```

**Multi-read** — read several pages at once:
```
wiki(pages=["slug-a", "slug-b"])
```

**`lacuna search` does not exist.** There is no search CLI command. Do not attempt `lacuna search`, `wiki_search`, or `wiki_navigate` — there is only the `wiki` MCP tool called directly.

If the `wiki` MCP tool is unavailable: use the Read tool on individual wiki files. Do not fall back to Bash.

---

## Step 0 — Register the Source

```bash
lacuna add-source path/or/url   # no --concept yet
```

Note both output lines:
```
Read:    raw/path/to/key.md        ← read this in Step 1
Cite as: [[key.ext]]               ← use this cite key in Step 3e — do not invent another
```

Do not ingest a source you did not just register. Verify with:
```bash
lacuna status
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

## Step 1b — Assign a Cluster

List the existing wiki clusters:

```bash
ls wiki/
```

Pick or declare a cluster path for the new pages — a two-level path like `machine-learning/training` or `biochemistry/protein-folding`. All pages written this session go under `wiki/{cluster}/`.

State the cluster before creating todos:
> "Cluster: machine-learning/training — all new pages will go under wiki/machine-learning/training/"

Rules:
- If a matching cluster already exists, use it.
- If no cluster fits, declare a new one — name it to match the domain and subdomain of the source.
- All pages from one ingest session go into one cluster. If two concepts belong to different clusters, use the primary one and link across.

Once the cluster is confirmed, move the raw source into the matching subtree:

```bash
lacuna move-source KEY --concept machine-learning/training
```

The concept arg must equal the cluster path — raw source and wiki pages live under the same domain tree.

Also check for orphaned pages — files sitting flat in `wiki/` instead of inside a cluster subdirectory:

```bash
ls wiki/*.md 2>/dev/null
```

If any exist, **move them now before proceeding**:

```bash
mkdir -p wiki/{cluster}/
mv wiki/slug.md wiki/{cluster}/slug.md
# repeat for each orphaned page
```

Then sync:

```bash
lacuna sync
```

Do not proceed to Step 2 until the wiki root contains no loose `.md` files.

---

## Step 2 — Create Todos and Pause

For each concept worth writing about, create a task in imperative form:
> "Write about [concept]: [one sentence describing the idea]"

Present the full list before starting:
> "Found N concepts. Here's what I'm planning:
>  Cluster: machine-learning/training
>  1. [concept]: [one sentence]
>  2. [concept]: [one sentence]
>  ...
>  Anything to add, remove, or reframe before I start?"

Wait for the user's response. Adjust if needed. Then proceed.

**In auto mode:** skip this pause. Proceed directly to Step 3 with the full todo list as created.

**This is the only mandatory user pause (in standard mode).** The only other pauses are non-obvious routing decisions (see Step 3d) and supersession confirmations.

---

## Step 3 — For Each Todo

Mark each task `in_progress` before starting it; mark it `completed` when done. Repeat until all tasks are ticked.

### a. Commit

State out loud before acting:
> "I am going to write about [X]: [one sentence].
>  Claim type: [established consensus | experimental result at [scale] | novel hypothesis | counter-consensus]
>  Concepts I will link: [[slug-a]], [[slug-b]], [[slug-c]].
>  But first I will search the wiki for similar content."

Claim types:
- **Established consensus** — widely accepted; cite inline: `"Attention computes a weighted sum. [[vaswani2017.pdf]]"`
- **Experimental result** — demonstrated at a specific scale; attribute inline: `"[[hay2026wedon.md]] demonstrates, on a 270M-parameter model, that..."`
- **Novel hypothesis** — proposed but not proven; hedge the verb: `"[[key.md]] hypothesises that..."`
- **Counter-consensus** — contradicts established view; flag inline: `"Contrary to [view], [[key.md]] argues that..."`

Claim type declared here determines framing in Step 3e.

The commit is not commentary — it is three forcing functions:
1. **The one sentence** is your search query. Articulating it first makes Step 3b precise.
2. **The slug list** normalises link targets before you write a word. `[[kv-cache]]` declared here cannot drift to `[[KV Cache]]` in the text. Undeclared concepts do not appear as wikilinks.
3. **The constraint:** if it is not in the commit, it is not a wikilink. Forces completeness before writing, not after.

### b. Search

**Use the `wiki` MCP tool directly. Do not run `lacuna search` — that command does not exist.**

```
wiki(q="[one sentence from the commit step]", scope="all")
```

`scope="all"` catches compiled wiki sections AND raw source chunks from other registered papers. One-sentence summaries outperform concept names as queries.

### c. Read Close Matches

For any hit with score > 0.7:

```
wiki(page="[slug]", section="[section name]")
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

**Before writing any new page, confirm:**

1. **Path** — `wiki/{cluster}/slug.md` using the cluster from Step 1b. Never write to `wiki/slug.md` directly.
2. **Frontmatter** — the file must open with a tags block. No exceptions.

```markdown
---
tags: [tag1, tag2, tag3]
---

# page-slug
...
```

Tag rules:
- Include each segment of the cluster path: `machine-learning/training` → `machine-learning`, `training`
- Add 1–3 cross-cutting concept tags from the page content (e.g. `regularization`, `phase-transitions`)
- Lowercase, hyphen-separated

The daemon adds `created`/`updated` dates — do not write them yourself.

**Editing existing pages:** preserve frontmatter already present. Do not rewrite or remove it.

**Framing check — apply the claim type declared in Step 3a:**

| Claim type | Required framing |
|---|---|
| Established consensus | State as fact, cite inline: `"...claim. [[key.ext]]"` |
| Experimental result | Attribute + scope: `"[[key.ext]] demonstrates, on [N-parameter M-layer model / benchmark X], that..."` |
| Novel hypothesis | Hedge verb: `"[[key.ext]] hypothesises / proposes / suggests that..."` |
| Counter-consensus | Flag inline: `"Contrary to [view], [[key.ext]] argues that..."` |

Never write source-specific claims in encyclopedic voice. `"The residual stream satisfies the Markov property"` is encyclopedic. `"[[key.md]] hypothesises that the residual stream satisfies the Markov property"` is attributed. Test: if removing the citation makes the sentence sound like a textbook, the framing is wrong.

Experimental scope is part of the claim — never drop it. `"[[key.md]] demonstrates on a 270M-parameter model that X"` is different from `"X has been demonstrated"`.

**Citation format:** `[[source-key.ext]]` inline at the end of the sentence. Never author `|N` — citation numbers are daemon-assigned. The daemon watches `wiki/` and syncs automatically. Wait ~2s after writing before reading back.

**Link verification:** before finishing, confirm every concept from your commit declaration (Step 3a) appears as a `[[wikilink]]` in the text. A concept declared but not linked is a write error — either add the link or remove it from the declaration.

### f. Mark Complete

Mark the task `completed`. Move to the next todo.

---

## Step 4 — Editorial Pass

Read back each page you wrote or edited this session. This is an editorial review — structure, links, placement. It is not an epistemic review (that is the adversary's job).

### a. Links

For each page you created or edited, navigate to it:

```
wiki(page="slug")
```

The nav block exposes two signals not visible from the file alone:

**links in** — pages that already cite this slug. If you created a new concept and the nav block shows zero links in, that's a gap: other pages that mention this concept by name should link to it. Check those pages and add the wikilink.

**semantically close sections** — sections from other pages scoring above 0.75. Any high-scoring hit from a page you *didn't* touch this session is a candidate for a cross-link or consolidation. If the content is near-duplicate, flag it for the adversary. If it's complementary, add a `[[wikilink]]`.

For each concept mentioned by name in your pages that is not already a `[[wikilink]]`:

1. Does a wiki page exist for this concept? Check: `wiki(page="slug")` — if it returns content, it exists.
2. Did you create one this session?

If yes to either: wrap the first mention as `[[slug]]`. Apply with Edit.

### b. Placement

Pull in the neighbors of each page you wrote:

```
wiki(pages=["slug-a", "slug-b", ...])   # slugs from the links-out list in the nav block
```

For each neighbor: does any claim on your new page actually belong there instead? Ask:
- Is this claim about the concept this page is named after, or does it belong on a neighbor page?
- Is this section dense enough to promote to its own page?

If something is misrouted: move it. Cut from here, add to the right page.

### c. Flag for Adversary

For any sentence where claim and source feel misaligned, add:

```markdown
Claim sentence here. [[key.ext]] <!-- TODO: adversary check -->
```

Flag if any of these apply:
1. **Assertion strength** — claim says "proves" or states a general truth; source says "suggests" or ran a limited experiment.
2. **Scope creep** — claim implies universal applicability; source demonstrated on one architecture, one dataset, or one scale.
3. **Hedging omitted** — source caveats something the wiki text does not reflect.

Do not rewrite. Do not re-read the source. Flag and move on — reaching for the source to resolve a doubt is adversary work, not editorial.

This step is bounded to pages touched this session. Pages from previous sessions that should now link to something created this session are the residual case — the daemon's broken-link detection surfaces those.

---

## Step 5 — Done

When all tasks are ticked and the link pass is complete:

> "Ingested [N] concepts from [source slug]. [N] pages updated, [N] pages created. [N] links added in link pass."

If the orphaned-pages todo was created in Step 1b, surface it now:
> "Note: [N] pages are sitting flat in wiki/ and should be moved to their clusters. Run the cleanup todo when ready."

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
| Concept is new | Create a page named after the concept |
| Source confirms existing claim | Add citation: `claim. [[old.pdf]] [[new.pdf]]` |
| Source adds nuance | Edit sentence + keep old citation + add new |
| Source contradicts a newer claim | Note the discrepancy; do not supersede older by newer |
| Source contradicts an older claim | Write new claim; confirm supersession with user |


---

## Aligned Mode

Aligned mode replaces the Step 3 write loop with a per-concept dialogue. Present each concept to the user before writing anything.

Use when: new domain, contested source, counter-consensus claims, or building shared understanding.

### Session manifest

At the start of an aligned session, create:

```
wiki/.sessions/{source-slug}-{YYYY-MM-DD}.md
```

Write to it throughout the session — it is your memory across compaction events. Read it back immediately after any compaction.

Initial content:
```markdown
## Source: {slug}
## Started: {date}
## Mode: aligned
## Human preferences:
(fill in as the user expresses them)

## Completed:
(fill in as concepts are approved and written)

## Remaining:
(copy from the todo list; remove as completed)

## Pending questions:
(anything unresolved — flag here, not in the wiki page)
```

After the session ends: delete the manifest or archive it to `wiki/reading-notes/`.

### Per-concept aligned loop

For each concept in the todo list (instead of the standard Step 3 a–f):

**a. Search first**

```
wiki(q="[one sentence from Step 1 structured analysis]", scope="all")
```

Read the top results. Note what the wiki already says.

**b. Present to user**

> **Concept: [name]**
>
> Source says: [direct quote or close paraphrase from source]
>
> Wiki currently says: [one sentence summary of best match, or "nothing yet"]
>
> Delta: [gap, nuance, or contradiction]
>
> My read: [one sentence framing]
>
> → Proposed claim: [the sentence you would write, with [[links]] and [[citation.ext]]]
>
> Does this framing match your understanding?

**c. Adjust and write (on approval)**

Adjust framing, routing, or wikilinks based on the user's response. Capture any stated preferences in the session manifest.

Write immediately on approval — not at the end of the loop. Update the manifest: move this concept from Remaining to Completed.

**d. Tick todo**

Mark the task completed.

### Reading notes

Capture the user's commentary, questions, disagreements, and framings in a reading note page:

```
wiki/reading-notes/{source-slug}.md
```

Format:
```markdown
# Reading Notes: {source title}
{date} — {source slug}

## [Concept name]
[User's comment verbatim or close paraphrase]

## Questions
[Unresolved questions flagged by user]
```

Reading notes are citable wiki pages — the daemon indexes them. A comment like "I think the KV Direct framing undersells the Markov property" is a first-class intellectual artifact, not a chat log.
