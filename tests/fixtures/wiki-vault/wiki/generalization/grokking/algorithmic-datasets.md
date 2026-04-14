---
created: 2026-04-14
updated: 2026-04-14
---
# algorithmic-datasets

Algorithmic datasets are training sets generated from mathematical rules rather than collected from natural data. The distinguishing feature is that the ground truth rule is known exactly, and the full input–output space can be enumerated — making it possible to construct training and validation splits with precise coverage guarantees and to study generalization in a fully controlled setting.

[[220102177b.pdf]] introduces binary operation tables as the canonical form: datasets of equations `a ◦ b = c` where `a`, `b`, `c` are discrete abstract symbols with no internal structure visible to the network. The operator `◦` can be modular addition, modular division, permutation composition, or polynomial operations. Because operands are presented as unstructured tokens (not numbers in decimal notation), the network must infer all structure purely from co-occurrence patterns.

Training on a subset of a binary operation table amounts to filling in missing cells — analogous to solving a Sudoku puzzle. [[220102177b.pdf]] demonstrates this setup enables single-GPU experiments that reliably exhibit [[grokking]] and other generalization phenomena in a pronounced and reproducible form, in contrast to natural-data benchmarks where such effects are much weaker.

## Why Abstract Symbols Matter

Representing operands as unrelated abstract symbols prevents the network from exploiting any pre-existing structure (e.g. numerical magnitude, positional notation). Any structure the network uses to generalise must be discovered from scratch through training, making the learned representations a clean signal of what was actually learned. [[220102177b.pdf]]

## Task Difficulty and Symmetry

[[220102177b.pdf]] demonstrates, across a range of binary operations, that task difficulty — measured by the minimum training data fraction needed for generalisation — tracks the algebraic complexity of the operation. Symmetric operations (where `a ◦ b = b ◦ a`) require less training data than asymmetric ones; more complex polynomial expressions require more data and in some cases fail to generalise entirely within the optimisation budget. [[220102177b.pdf]] suggests the symmetry effect may be partially architecture-dependent, since a transformer can exploit symmetry by ignoring positional embeddings.

## See also

- [[grokking]] — the generalisation phenomenon these datasets are used to study
- [[modular-arithmetic]] — the most-studied instance of an algorithmic dataset
- [[memorization-vs-generalization]] — the distinction these datasets isolate cleanly
