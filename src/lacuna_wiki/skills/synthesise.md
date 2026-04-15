# Synthesise Skill — lacuna

The synthesis counterpart to `lacuna-sweep`. Where sweep adds wikilinks and queues clusters, synthesise reads those clusters and produces unified synthesis pages — one page per cluster, written from all member pages, surfacing shared ground, disagreements, and weight of evidence in one place.

---

## Mode

| Mode | Declared by | Behaviour |
|---|---|---|
| `standard` | default | Pause at Step 0 for queue approval |
| `auto` | "auto", "just run it" | Skip Step 0 pause — all per-cluster steps run identically |

Auto mode exists to support cron execution. In auto mode the agent processes the full queue without pausing.

---

## Forbidden Operations

**Never use Glob, Grep, Find, Search, or `ls` to locate wiki files.**
**Never use the Read tool on wiki files to discover paths or read content.**
All paths, content, and structure come from `wiki()`. File paths appear in cluster detail.
Using filesystem tools instead of `wiki()` pollutes the context window and bypasses the index.

---

## MCP Tool Reference

All wiki operations go through the `wiki` MCP tool.

**Cluster queue:**
```
wiki(synthesise=True)
```

**Single cluster detail:**
```
wiki(synthesise=N)
```

**Mark cluster synthesised:**
```
wiki(synthesise=N, commit={"slug": "synthesis-slug"})
```

**`lacuna search` does not exist.** Use `wiki(q="...")` for search. Use `wiki(page="slug")` to navigate.

---

## Step 0 — Get the Queue

```
wiki(synthesise=True)
```

State the full picture out loud:

> "Synthesis queue:
> Pending clusters (N): [labels and member counts]
> Single-source clusters: [labels] — will note limitation inline.
> Any clusters to skip or reprioritise?"

**Standard mode:** pause. Adjust if needed.
**Auto mode:** skip pause. Proceed immediately.

Create one task per cluster before proceeding.

---

## Step 1 — Per-cluster Loop (streaming)

Mark task `in_progress` before starting; `completed` when done.

### a. Commit

State out loud before touching anything:

```
wiki(synthesise=N)
```

> "Synthesising cluster N: [label]
> Members (M): [[slug-a]], [[slug-b]], [[slug-c]]
> Source diversity: N distinct sources. [⚠ single-source — will note limitation in synthesis page]
> Existing synthesis page: [[slug]] / none — [new write / revision run]
> Noise members I am excluding: [[slug-x]] — [reason]. [[slug-y]] — [reason].
> Confirmed members: [[slug-a]], [[slug-b]], [[slug-c]]
> Proposed slug: [slug]
> Reading member pages now."

Every member surfaced in the cluster detail must be either confirmed or declared noise. Undeclared members are not silently dropped. A member is noise if it is: under 100 words, a reagent or tool rather than a concept, or clearly off-topic relative to the cluster label.

### b. Read Members

```
wiki(pages=["slug-a", "slug-b", "slug-c"])
```

For a revision run, read the existing synthesis page first:

```
wiki(page="existing-synthesis-slug")
```

After reading, confirm the proposed slug or revise it. The slug must be a good standalone concept name — not prefixed with "synthesis-" unless necessary for disambiguation.

### c. Extract Concepts and Create Section Todos

After reading the member pages, extract the distinct concepts that appear across them. Each concept becomes one section of the synthesis page.

State the concept list out loud:

> "Concepts for [[slug]]:
> 1. [concept name]: [one sentence — what all members say about this]
> 2. [concept name]: ...
> N. Disagreements / scope conflicts: [list any, or 'none']"

**Create one todo per concept before entering the write loop.** Do not begin writing until the full todo list exists. Include a todo for the frontmatter/header and a todo for the Excluded members section.

**Derive the cluster path from the member page paths shown in the cluster detail.**
Each member line includes `path: wiki/{cluster-path}/{slug}.md`. Take the directory
of any confirmed member — that is your cluster path.

> Example: if a member path is `wiki/neuroscience/pain-biology/nav17-pain-signaling.md`,
> the synthesis page goes at `wiki/neuroscience/pain-biology/{slug}.md`.

### c-ii. Create File with Frontmatter

Mark the frontmatter todo `in_progress`. Write the file with frontmatter and title heading only — no body yet:

```markdown
---
tags: [tag1, tag2]
synthesis: true
---

# slug
```

Tag rules: include each segment of the cluster path plus 1–3 cross-cutting concept tags. Lowercase, hyphen-separated.

For single-source clusters, add this callout immediately after the title:

```markdown
> *This synthesis draws from a single source — [[source.pdf]].*
```

For revision runs, add the revision callout immediately after frontmatter:

```markdown
> *Revised [date]: added [[new-slug-a]], [[new-slug-b]].*
```

Mark the frontmatter todo `completed`.

### c-iii. Per-Concept Write Loop

For each concept todo, in order:

**Mark todo `in_progress`. Then work through these steps before writing anything.**

**i. Sources covering this concept**

State which member pages address this concept and what each source says:

> "Concept: [name]
>
> [[member-a]] says: [direct paraphrase of what that page says about this concept, with its source citations]
> [[member-b]] says: [direct paraphrase, with citations]
> [[member-c]] says: [or 'does not address this concept']
>
> Agreement: [what they agree on]
> Disagreement: [what conflicts, or 'none']"

If no member page addresses the concept, drop it from the plan — do not invent coverage.

**ii. Wiki search**

```
wiki(q="[concept name — one sentence summary]", scope="all")
```

Note what the wiki already says about this concept. This surfaces:
- Existing pages to cross-link rather than repeat
- Source chunks that might add nuance not in the member pages
- Near-duplicate content that should be flagged rather than re-synthesised

**iii. Commit**

State out loud before writing:

> "Writing section: [heading]
> Claim type: established consensus | experimental result at [scale] | novel hypothesis | counter-consensus
> [[source-a.pdf]] says: [paraphrase]
> [[source-b.pdf]] says: [paraphrase — or disagreement]
> Wiki links I will include: [[concept-x]], [[concept-y]]
> Framing check: [confirm no encyclopedic voice — every claim has a named source]"

**Framing rules — apply before every sentence:**

| Claim type | Required framing |
|---|---|
| Established consensus | State as fact, cite inline: `"...claim. [[key.ext]]"` |
| Experimental result | Attribute + scope: `"[[key.ext]] demonstrates, on [N-parameter model / dataset X / organism Y], that..."` |
| Novel hypothesis | Hedge verb: `"[[key.ext]] hypothesises / proposes / suggests that..."` |
| Counter-consensus | Flag inline: `"Contrary to [view], [[key.ext]] argues that..."` |

**Framing gate:** Can you name a `[[source.pdf]]` for every claim in this section? If not, do not write the claim. Does any sentence read like a textbook without its citation? That is encyclopedic voice — rewrite it.

**iv. Write section**

Append the section to the file with Edit. One concept = one Edit = one `##` section.

**Slug casing rule:** slugs are always lowercase. Use pipe syntax for display: `[[slug|Display Text]]`. Never put a wikilink inside a `##` heading.

Mark todo `completed`. Move to next concept.

### c-iv. Append Excluded Members

Mark the excluded-members todo `in_progress`. Append as a final Edit:

```markdown
## Excluded members

| Page | Reason | Date |
|---|---|---|
| [[slug-x]] | Reagent, not a concept — d1-egfp is a reporter protein | 2026-04-15 |
| [[slug-y]] | Under 100 words — stub awaiting sources | 2026-04-15 |
```

Leave the table empty (headers only) if there are no noise members. Do not omit the section. Mark todo `completed`.

### d. Add Synthesised-Into Notice to Members

For each **confirmed** member page — not noise members, not the synthesis page itself — add one line directly below the frontmatter:

```
%% synthesised-into: [[slug]] %%
```

**Use the `path` field from the cluster detail to locate each file. Do not Glob, Grep, or Search
for the file. The path was already returned when you called `wiki(synthesise=N)`.**

Apply with Edit, one page at a time. Verify each edit was written before moving to the next.

The daemon detects this notice on next sync and sets `synthesised_into` in the DB. Once set, the page disappears from the sweep backlog and synthesis candidate pool. Do not add the notice to noise members — they remain eligible for future sweeps.

### e. Commit

```
wiki(synthesise=N, commit={"slug": "synthesis-slug"})
```

> "Synthesised cluster N: [[synthesis-slug]] written. N members noticed. Excluded members recorded. Next: cluster M."

Mark task completed.

---

## Step 2 — Done

> "Synthesis complete. N clusters synthesised, N pages written.
> Synthesis queue: now holds N pending clusters — run `lacuna synthesise` or schedule it.
> Remaining sweep backlog: N pages.
> Research gaps: N stubs, N ghost pages — visible in `lacuna status`."

---

## Decision Table

| Signal | Action |
|---|---|
| Member page < 100 words or < 2 sections | Noise — exclude; record in Excluded members table; do not add notice |
| Member page already synthesised into a different page | Noise — note the conflict in Excluded members; do not add a second notice |
| Member is a reagent / tool rather than a concept | Noise — exclude; record reason |
| Single-source cluster | Proceed; add single-source callout at top of synthesis page |
| Revision run (existing synthesis page) | Read existing page first; edit in place; add revision callout |
| Cluster has > 10 members | Synthesise the highest-coverage members; record the rest as overflow in Excluded members table |
| Proposed slug conflicts with an existing page | Append a disambiguating suffix: `nav-channel-pain-pharmacology-synthesis` |
