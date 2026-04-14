---
name: llm-wiki-adversary
description: Evaluate wiki claims for fidelity and supersession. Falsification-first posture. Requires Plan 5 CLI tools (llm-wiki claims, llm-wiki adversary-commit).
---

# Adversary Skill — llm-wiki

Evaluate claims in the wiki for fidelity and supersession.

**Your posture for this entire session:** you are looking for what is wrong, not confirming what is right. Approach every claim as a prosecutor, not a defender. If a claim seems correct on first read, look harder — check whether the source actually hedges where the claim does not, check whether any newer source changes the picture. Only when you find no weakness does a claim earn SUPPORTS.

**Prerequisites:** `llm-wiki claims` and `llm-wiki adversary-commit` must be available (Plan 5). The daemon must be running.

---

## Targeting Modes

| Mode | When |
|---|---|
| `virgin` | After batch ingest — all claims never evaluated |
| `stale` | After adding new sources — claims not checked since last source registered |
| `page SLUG` | Before citing a specific page heavily |

Default: `virgin`.

---

## Step 1 — Target

List the claims to evaluate:

```bash
llm-wiki claims --mode virgin
# or
llm-wiki claims --mode stale
# or
llm-wiki claims --mode page attention-mechanism
```

Create one task per claim:
> "Evaluate claim [ID]: [first 60 chars of claim text]"

Report to the user:
> "Found N unevaluated claims across K pages. Starting evaluation."

---

## Step 2 — For Each Claim

Mark each task `in_progress` before starting it. Mark it `completed` when done.

### a. Commit

State out loud before acting — this generates your search framing:
> "Evaluating: '[full claim text]'
>  Source: [source_slug] ([published_date])
>  Page: [page_slug] › [section_name]"

### b. Search

```json
{"q": "[claim text without the [[citation]] marker]", "scope": "all"}
```

The claim's own source chunks surface first — fidelity check material. Other source chunks provide cross-source evidence. Both matter.

### c. Check — Work Through This in Order

1. **What would have to be true for this claim to be wrong?** Articulate the failure mode before reading the evidence.

2. **Fidelity:** Does the cited source actually assert this? Read the source chunks carefully. Does the source hedge, caveat, or say something subtly different from the claim? Compare word by word if needed.

3. **Scale of evidence:** What was the scale and scope of the experiment or demonstration? If the claim is written as a general truth but the source only ran a 270M-parameter model, a single benchmark, or one architecture — that is a FIDELITY FAILURE. The scale must appear in the claim. If it does not, fix the sentence to include it.

4. **Cross-source:** Does any other source — especially a more recent one — contradict this claim?

5. **Verdict:** One of the four below. No hedging. Pick the strongest verdict the evidence supports.

### d. Verdict and Action

**SUPPORTS** — the cited source confirms the claim, no contradictory evidence found:
- Accumulate: `claim_id=[ID] rel=supports`

**FIDELITY FAILURE** — the claim misrepresents its own source (overstates confidence, omits a key caveat, paraphrases imprecisely):
- Edit the page directly. Fix the sentence to match what the source actually says. The daemon picks up the change.
- Do not write a DB verdict — the edited claim becomes a new claim row after daemon sync.
- Note the fix in your running log: `FIDELITY FIX: [page › section] — [one sentence description of what was wrong]`

**GAP** — the source identifies this as a known unknown, open question, or explicit limitation:
- Accumulate: `claim_id=[ID] rel=gap`

**SUPERSEDED** — a newer source contradicts this claim:
- Pause. Surface to the user:
  > "Claim: [X] ([source_slug], [date])
  >  Superseded by: [newer_source] ([date]) — [one sentence]
  >  Proposed new claim: [Y]
  >  Approve / Skip / Override?"
- **If approved:**
  - Edit the page: add the new claim sentence with the new source citation.
  - Wait ~3s for daemon sync.
  - Run `llm-wiki claims --mode page [slug]` to find the new claim ID (it will have no `last_adversary_check`).
  - Accumulate: `claim_id=[old_ID] rel=refutes` and `supersede old=[old_ID] new=[new_ID]`
- **If skipped:** move on, no record.

### e. Accumulate

Keep a running list — do not commit to DB until the full loop is done:

```
VERDICTS:
  claim_id=42  rel=supports
  claim_id=17  rel=gap
  claim_id=99  rel=refutes

SUPERSESSIONS:
  old=99  new=107

FIDELITY FIXES:
  attention-mechanism › Scaled Dot-Product — claim said "proven" but source says "empirically observed"
```

### f. Tick

Mark the task `completed`. Move to the next claim.

---

## Step 3 — Commit + Report

When all tasks are ticked, batch-commit all verdicts in one CLI call:

```bash
llm-wiki adversary-commit \
  --verdict "claim_id=42,rel=supports" \
  --verdict "claim_id=17,rel=gap" \
  --verdict "claim_id=99,rel=refutes" \
  --supersede "old=99,new=107"
```

Report:
> "N claims evaluated.
>  K supported, J gaps, M fidelity fixes (edited directly), L supersessions.
>
>  Fidelity fixes:
>    [page › section] — [one sentence description]
>
>  Supersessions:
>    [old claim text] ([old source]) → [new claim text] ([new source])"

---

## Verdict Reference

| Verdict | Meaning | DB write | Page edit |
|---|---|---|---|
| SUPPORTS | Source confirms the claim | `rel=supports` | No |
| FIDELITY FAILURE | Claim misrepresents its source | None (new claim after edit) | Yes — fix the sentence |
| GAP | Source marks this as a known unknown | `rel=gap` | No |
| SUPERSEDED | Newer source contradicts — user approved | `rel=refutes` + `supersede` | Yes — add new claim |
