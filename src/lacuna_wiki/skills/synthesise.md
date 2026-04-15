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

### c. Plan the Synthesis Page

**Derive the cluster path from the member page paths shown in the cluster detail.**
Each member line includes `path: wiki/{cluster-path}/{slug}.md`. Take the directory
of any confirmed member — that is your cluster path.

> Example: if a member path is `wiki/neuroscience/pain-biology/nav17-pain-signaling.md`,
> the synthesis page goes at `wiki/neuroscience/pain-biology/{slug}.md`.

**Do NOT search the filesystem with Glob, Find, or Search to locate page files.**
**Do NOT use the Read or Edit tools on wiki files to find paths.**
Everything goes through `wiki()`.

**Before writing a single word of the page, produce an outline out loud:**

```
Synthesis plan for [[slug]]:

Section 1 — [heading]: [one sentence — the point this section makes]
  Claim type: established consensus | experimental result at [scale] | novel hypothesis | counter-consensus
  Sources: [[source-a.pdf]], [[source-b.pdf]]
  Wiki links: [[concept-x]], [[concept-y]]

Section 2 — [heading]: ...
  Claim type: ...
  Sources: ...
  Wiki links: ...

[repeat per section]

Disagreements to surface: [list any conflicts between member pages]
Single-source limitation: yes/no
```

**Framing gate — check each section before writing it:**
- Can you name a specific `[[source.pdf]]` for every claim? If not, do not write the claim.
- Is the claim type `experimental result`? Then the scope (model size, dataset, organism) must be in the sentence.
- Does the sentence read like a textbook without the citation? That is encyclopedic voice — rewrite.

**Claim-type framing rules (identical to `lacuna-ingest`):**

| Claim type | Required framing |
|---|---|
| Established consensus | State as fact, cite inline: `"...claim. [[key.ext]]"` |
| Experimental result | Attribute + scope: `"[[key.ext]] demonstrates, on [scale/context], that..."` |
| Novel hypothesis | Hedge verb: `"[[key.ext]] hypothesises / proposes / suggests that..."` |
| Counter-consensus | Flag inline: `"Contrary to [view], [[key.ext]] argues that..."` |

**Slug casing rule:** slugs are always lowercase. Use pipe syntax for display: `[[slug|Display Text]]`. Never put a wikilink inside a `##` heading.

### c-ii. Write the Synthesis Page — One Section at a Time

Create the file with frontmatter and the title heading only:

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

**Then write each section from the plan as a separate Edit.** Before each section Edit, state out loud:

> "Writing section [N] — [heading]: [claim]. Claim type: [type]. Source: [[key.ext]]."

Do not write a section you did not plan. Do not combine multiple sections into one Edit.

**After all planned sections**, append the Excluded members section as a final Edit:

```markdown
## Excluded members

| Page | Reason | Date |
|---|---|---|
| [[slug-x]] | Reagent, not a concept — d1-egfp is a reporter protein | 2026-04-15 |
| [[slug-y]] | Under 100 words — stub awaiting sources | 2026-04-15 |
```

Leave this table empty (headers only) if there are no noise members. Do not omit the section — it is the persistent record of agent judgments for future reviewers.

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
