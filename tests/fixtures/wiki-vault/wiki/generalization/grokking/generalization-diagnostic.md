---
created: 2026-04-14
updated: 2026-04-14
---
# generalization-diagnostic

To distinguish a model that has learned a genuine rule from one that is merely [[memorization-vs-generalization|memorising]], the key test is: does performance hold up on variations that break superficial cues? [[compuflair2026theph.md]]

## Diagnostic Variations

[[compuflair2026theph.md]] identifies the following perturbations that expose memorisers:

- **Symbol renaming** — replace the input tokens with arbitrary new symbols; a rule learner is unaffected, a memoriser collapses.
- **Label permutation** — shuffle the output categories; again tests whether the model tracks structure or surface form.
- **Number magnitude extension** — increase the range of numeric inputs beyond training distribution.
- **Sequence length extension** — increase input length beyond what was seen during training.
- **Irrelevant detail changes** — modify features that are logically uninformative; a memoriser trained on spurious correlations will degrade.

Rule learners tend to be stable under these changes. Memorisers tend to collapse. [[compuflair2026theph.md]]

## Why Standard Evaluation Misses This

If evaluation uses held-out examples from the same distribution — same symbol set, same range, same length — a memoriser can look as good as a rule learner. The diagnostic requires *out-of-distribution* tests that are specifically designed to expose shortcuts. [[compuflair2026theph.md]]

This is particularly relevant for [[grokking]] research: the modular arithmetic setup (e.g. addition mod 17) allows a clean diagnostic because new input pairs that were withheld at training time are genuinely unsolvable by surface similarity alone — the model must have internalised the wrap-around rule.

## See also

- [[grokking]] — the phenomenon this diagnostic is used to study
- [[memorization-vs-generalization]] — the two strategies the diagnostic distinguishes
