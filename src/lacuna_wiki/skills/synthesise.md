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

### c. Write Synthesis Page

Write the synthesis page at `wiki/{cluster-path}/{slug}.md`.

**Frontmatter must open the file. Include `synthesis: true`:**

```markdown
---
tags: [tag1, tag2]
synthesis: true
---

# slug

[body]
```

Tag rules: include each segment of the cluster path (e.g. `sRNA`, `quantification`) plus 1–3 cross-cutting concept tags. Lowercase, hyphen-separated.

**Body structure:**
- Open with a one-paragraph synthesis of what all members agree on
- Separate section for disagreements or scope differences between sources
- Cite all contributing sources inline at the sentence level: `claim [[source-a.pdf]] [[source-b.pdf]]`
- For single-source clusters, add a note at the top: `> *This synthesis draws from a single source — [[source.pdf]].*`

**Framing rules (apply the same claim-type discipline as `lacuna-ingest`):**
- State weight of evidence across sources, not any single source's view
- Surface disagreements explicitly: "[[source-a.pdf]] argues X; [[source-b.pdf]] demonstrates Y at 270M parameters — the larger-scale result is more likely to generalise"
- Hedge unproven claims: "[[source.pdf]] hypothesises that..."
- Never write encyclopedic voice for experimental results

**Slug casing rule:** slugs are always lowercase. Use pipe syntax for display: `[[slug|Display Text]]`. Never put a wikilink inside a `##` heading.

**Revision run:** edit the synthesis page in place. Add new content from new members; do not erase prior synthesis. Add a revision callout directly below frontmatter:

```markdown
> *Revised [date]: added [[new-slug-a]], [[new-slug-b]].*
```

**Excluded members section:** at the bottom of every synthesis page, add:

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
