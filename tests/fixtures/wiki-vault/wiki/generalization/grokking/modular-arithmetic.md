---
created: 2026-04-14
updated: 2026-04-14
---
# modular-arithmetic

Modular arithmetic is arithmetic on a fixed-size ring of integers, where numbers wrap around after reaching a modulus. On a clock with modulus 12, 9 + 5 = 2 rather than 14. [[compuflair2026theph.md]]

Modular addition tasks have become the canonical benchmark for studying [[grokking]]. A model is trained on a subset of all input pairs (a, b) → (a + b) mod N and tested on the remainder. Because the pairs withheld at training time cannot be solved by surface similarity alone, the task cleanly separates memorisation from rule learning. [[220102177b.pdf]] [[compuflair2026theph.md]]

## See also

- [[grokking]] — the phenomenon this task is used to study
- [[algorithmic-datasets]] — the broader class of controlled datasets modular arithmetic belongs to
- [[generalization-diagnostic]] — the general principle the task instantiates
