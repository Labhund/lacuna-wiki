# Ingest + Adversary Skill Rewrite — Epistemics Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the ingest and adversary skills to enforce claim attribution, surface secondary insights, record evidence scope, and name the scale-of-evidence prosecution angle.

**Architecture:** Pure skill-file changes — no Python, no tests. Two files: `src/lacuna_wiki/skills/ingest.md` and `src/lacuna_wiki/skills/adversary.md`. The ingest skill gets a new Step 0 (register first), a structured Step 1 output format, claim-type declaration in Step 3a, framing rules in Step 3e, and a strengthened Step 4c. The adversary skill gets one new named check in Step 2c.

**Tech Stack:** Markdown skill files read by Claude Code / Hermes harness.

---

### Background — why these changes

Three failures from live ingest of a YouTube source (tygcrpcafhe):

1. **Encyclopedic voice**: "The residual stream satisfies the Markov property" — written as textbook fact. The source ran a 270M/18-layer experiment and asserted a hypothesis. Completely different epistemic status.

2. **Missing secondary insights**: The agent executed the main narrative and suppressed everything else. A valuable insight (vector walk through concept space) was never written because it wasn't the thesis.

3. **Evidence scope dropped**: "270M 18-layer model" should appear in the claim, not just in the source chunk. Future sessions reading the wiki page have no way to know this was a small-model experiment.

The adversary skill also needs a named prosecution angle for scale-of-evidence mismatch.

---

### Task 1: Rewrite ingest.md Step 1 — Structured Source Analysis

**Files:**
- Modify: `src/lacuna_wiki/skills/ingest.md`

- [ ] **Step 1: Replace the Step 1 section**

Replace the current Step 1 body (which ends at "Build a mental map before touching any wiki page.") with (outer fence is 4 backticks to survive nested inner fences):

````markdown
## Step 1 — Structured Source Analysis

Read the source in full. For local files: use the Read tool. For URLs: fetch the page.

After reading, produce this structured output before creating any todos:

```
## Main thesis: [one sentence — what is the source's central claim?]
## Supporting evidence: [what they actually measured or demonstrated, at what scale — be specific: "270M 18-layer model", "benchmark X on dataset Y"]
## Secondary insights: [things said in passing that are independently interesting — not supporting the thesis, just valuable]
## Surprising / counter-consensus claims: [anything that flies against established knowledge — flag these explicitly]
## Not worth a concept: [conscious exclusions — source-intrinsic reasons only: "too speculative", "assertion without evidence", "too tangential", "out of scope for this domain"]
```

The "Not worth a concept" row captures only source-quality exclusions — reasons that come from the source itself, not from wiki state. Wiki-coverage exclusions ("already well covered") cannot be known here; they are handled in Step 3d (DECIDE: "Same point → add citation to existing sentence"), after the agent has actually searched.

The row is not optional — making non-inclusion an explicit act prevents the summarisation instinct from silently suppressing surprising asides. Secondary insights belong in todos, not in the margins.
````

- [ ] **Step 2: Verify**

Open `src/lacuna_wiki/skills/ingest.md` and confirm Step 1 now contains the five-row structured output block with "Not worth a concept" (source-intrinsic reasons, no wiki-coverage exclusions) and no redundant source-chunk search.

- [ ] **Step 3: Commit**

```bash
git add src/lacuna_wiki/skills/ingest.md
git commit -m "skill: structured source analysis output in Step 1"
```

---

### Task 2: Add Step 0 — Register First

**Files:**
- Modify: `src/lacuna_wiki/skills/ingest.md`

The current skill has "Prerequisite: source must be registered" as a pre-check at the top. This lets the agent ingest a fixture source (like vaswani2017) that was never properly registered — no source chunks exist, and the adversary catches it as a GAP later. The fix: make `add-source` the first executable step, not a prerequisite.

- [ ] **Step 1: Insert Step 0 before the current Step 1**

Insert the following section before "## Step 1":

```markdown
## Step 0 — Register the Source

```bash
lacuna add-source path/or/url   # no --concept yet
```

**Capture both lines of output:**
```
Read:    raw/path/to/key.md        ← your source file for Step 1
Cite as: [[key.ext]]               ← the only citation you will use in Step 3e
```

The cite key is fixed here. You may not invent or change it later in the session.

**After reading the source (Step 1), assign its concept:**
```bash
lacuna move-source KEY --concept domain/subdomain
```

This atomically moves all source files and updates the DB. The daemon is not involved.

If the concept is obvious from the title or URL before reading (common for blog posts and arxiv papers), passing `--concept` upfront to `add-source` is a valid shortcut — but it is a shortcut, not the default. When in doubt, register first, read, then move.

**Never ingest a source you did not just register or explicitly verify exists:**
```bash
lacuna status   # lists all registered sources with their slugs
```
```

- [ ] **Step 2: Remove the old prerequisite block**

Find and remove the lines at the top of the current skill that say:
```
**Prerequisite:** the source must be registered. If it isn't:

```bash
lacuna add-source raw/path/to/file.pdf
```

Wait for the daemon to sync before proceeding.
```

- [ ] **Step 3: Remove the Citation Format Rules section at the bottom**

The citation format rules (currently at the bottom of the skill under "## Citation Format Rules") are now redundant — the cite key is established at Step 0 and the rules are embedded in the write step. Remove the entire section.

- [ ] **Step 4: Verify**

Read `src/lacuna_wiki/skills/ingest.md` and confirm:
- Step 0 is present before Step 1
- No "Prerequisite" block at the top
- No standalone "Citation Format Rules" section at the bottom

- [ ] **Step 5: Commit**

```bash
git add src/lacuna_wiki/skills/ingest.md
git commit -m "skill: Step 0 register-first, cite key as binding contract"
```

---

### Task 3: Claim-Type Declaration in Step 3a

**Files:**
- Modify: `src/lacuna_wiki/skills/ingest.md`

The current Step 3a commit says to declare slugs. Add claim-type declaration alongside.

- [ ] **Step 1: Replace the Step 3a commit block**

The current Step 3a reads:
```markdown
### a. Commit

State out loud before acting:
> "I am going to write about [X]: [one sentence].
>  Concepts I will link: [[slug-a]], [[slug-b]], [[slug-c]].
>  But first I will search the wiki for similar content."
```

Replace with:

```markdown
### a. Commit

State out loud before acting:
> "I am going to write about [X]: [one sentence].
>  Claim type: [established consensus | experimental result at [scale] | novel hypothesis | counter-consensus]
>  Concepts I will link: [[slug-a]], [[slug-b]], [[slug-c]].
>  But first I will search the wiki for similar content."

Claim types:
- **Established consensus** — widely accepted, cite as fact: "Attention computes a weighted sum of values. [[vaswani2017.pdf]]"
- **Experimental result** — source demonstrated this at a specific scale: "[[hay2026wedon.md]] demonstrates, on a 270M-parameter 18-layer model, that..."
- **Novel hypothesis** — source proposes but has not proven: "[[hay2026wedon.md]] hypothesises that the residual stream satisfies the Markov property..."
- **Counter-consensus** — flies against established knowledge: "Contrary to the standard view, [[hay2026wedon.md]] argues that..."

Claim type declared here determines framing in Step 3e.
```

- [ ] **Step 2: Verify**

Read the modified Step 3a and confirm it has the four claim types with examples.

- [ ] **Step 3: Commit**

```bash
git add src/lacuna_wiki/skills/ingest.md
git commit -m "skill: claim-type declaration in Step 3a commit"
```

---

### Task 4: Framing Rules in Step 3e Write

**Files:**
- Modify: `src/lacuna_wiki/skills/ingest.md`

The current Step 3e write section has link verification but no framing rules. Add a pre-write check that enforces the claim type declared in Step 3a.

- [ ] **Step 1: Add framing rules to Step 3e**

After the current "### e. Write" header and before the "**Citation format:**" line, insert:

```markdown
**Framing check — apply before writing:**

| Claim type declared in 3a | Required framing |
|---|---|
| Established consensus | State as fact, cite inline: `"...claim text. [[key.ext]]"` |
| Experimental result | Attribute + scope inline: `"[[key.ext]] demonstrates, on [N-parameter M-layer model / benchmark X], that..."` |
| Novel hypothesis | Hedge verb: `"[[key.ext]] hypothesises / proposes / suggests that..."` |
| Counter-consensus | Flag inline: `"Contrary to [established view], [[key.ext]] argues that..."` |

**Never write source-specific claims in encyclopedic voice.** "The residual stream satisfies the Markov property" is encyclopedic. "[[hay2026wedon.md]] hypothesises that the residual stream satisfies the Markov property" is attributed. When in doubt: if removing the citation would make the sentence sound like a textbook, the framing is wrong.

**Experimental scope is part of the claim.** "[[key.md]] demonstrates on a 270M-parameter model that X" is different from "X has been demonstrated." The scope signals what a future ingest should add: "[[later-paper.md]] extends this to 7B models." Never drop the scale.
```

- [ ] **Step 2: Verify**

Read Step 3e and confirm the framing table is present with all four claim types.

- [ ] **Step 3: Commit**

```bash
git add src/lacuna_wiki/skills/ingest.md
git commit -m "skill: claim framing rules in Step 3e write"
```

---

### Task 5: Strengthen Step 4c Flag

**Files:**
- Modify: `src/lacuna_wiki/skills/ingest.md`

The current Step 4c says "for any sentence where the written text and the source intent feel misaligned." This is too vague. Add a named check for assertion-strength mismatch.

- [ ] **Step 1: Replace the Step 4c body**

Current Step 4c:
```markdown
### c. Flag for Adversary

For any sentence where the written text and the source intent feel misaligned — or where you are uncertain whether the claim is fully supported — add an inline comment:

```markdown
The residual stream encodes full conversation history. <!-- TODO: adversary check -->
```

Do not rewrite or second-guess. Flag and move on. The adversary resolves these.
```

Replace with:

```markdown
### c. Flag for Adversary

For any sentence where the written text and the source intent feel misaligned, add:

```markdown
Claim sentence here. [[key.ext]] <!-- TODO: adversary check -->
```

Named checks — flag if any of these apply:
1. **Assertion strength**: is this claim making a stronger statement than the evidence supports? (e.g. "proves" when source says "suggests", or no model-scale qualifier on an experimental result)
2. **Scope creep**: does the claim generalise beyond what was measured? (e.g. source demonstrated on one architecture, claim implies universal)
3. **Hedging omitted**: did the source caveat something that the wiki text does not reflect?

Do not rewrite or re-search. Flag and move on. The adversary resolves these.

**Boundary:** if you find yourself wanting to re-read the source to resolve a doubt, that is adversary work. Flag it instead.
```

- [ ] **Step 2: Verify**

Read Step 4c and confirm the three named checks are present.

- [ ] **Step 3: Commit**

```bash
git add src/lacuna_wiki/skills/ingest.md
git commit -m "skill: named assertion-strength check in Step 4c"
```

---

### Task 6: Scale-of-Evidence Prosecution Angle in Adversary Skill

**Files:**
- Modify: `src/lacuna_wiki/skills/adversary.md`

The current Step 2c has three checks: "What would have to be true for this claim to be wrong?", fidelity check, and cross-source check. Add a fourth named check for scale-of-evidence mismatch.

- [ ] **Step 1: Update Step 2c in adversary.md**

Current Step 2c:
```markdown
### c. Check — Work Through This in Order

1. **What would have to be true for this claim to be wrong?** Articulate the failure mode before reading the evidence.

2. **Fidelity:** Does the cited source actually assert this? Read the source chunks carefully. Does the source hedge, caveat, or say something subtly different from the claim? Compare word by word if needed.

3. **Cross-source:** Does any other source — especially a more recent one — contradict this claim?

4. **Verdict:** One of the four below. No hedging. Pick the strongest verdict the evidence supports.
```

Replace with:

```markdown
### c. Check — Work Through This in Order

1. **What would have to be true for this claim to be wrong?** Articulate the failure mode before reading the evidence.

2. **Fidelity:** Does the cited source actually assert this? Read the source chunks carefully. Does the source hedge, caveat, or say something subtly different from the claim? Compare word by word if needed.

3. **Scale of evidence:** What was the scale and scope of the evidence? A claim written as a general truth that was only demonstrated on a 270M-parameter model, a single benchmark, or one architecture is a fidelity failure. The scale must appear in the claim. If it does not, this is a FIDELITY FAILURE — fix the sentence to include the scope.

4. **Cross-source:** Does any other source — especially a more recent one — contradict this claim?

5. **Verdict:** One of the four below. No hedging. Pick the strongest verdict the evidence supports.
```

- [ ] **Step 2: Verify**

Read Step 2c and confirm the scale-of-evidence check is check 3, and cross-source has moved to check 4.

- [ ] **Step 3: Commit**

```bash
git add src/lacuna_wiki/skills/adversary.md
git commit -m "skill: scale-of-evidence named prosecution angle in adversary Step 2c"
```

---

### Task 7: Update install-skills to push changes

The skill files are installed into the harness skills directory. After rewriting them, reinstall.

- [ ] **Step 1: Run install-skills**

```bash
lacuna install-skills
```

Expected output: confirms ingest and adversary skills copied to `~/.claude/skills/`.

- [ ] **Step 2: Verify installed files match source**

```bash
diff src/lacuna_wiki/skills/ingest.md ~/.claude/skills/lacuna-ingest/SKILL.md
diff src/lacuna_wiki/skills/adversary.md ~/.claude/skills/lacuna-adversary/SKILL.md
```

Expected: no diff.

- [ ] **Step 3: Commit**

No additional commit needed — the source files were already committed in Tasks 1–6.
