---
created: 2026-04-14
updated: 2026-04-14
---
# residual-stream

The residual stream is the main data highway through a transformer — a single vector per token that flows through every layer, is read by each layer's attention and MLP sub-blocks, and is written back to after each computation. For Gemma 3 12B the residual vector is 3,840 floats (~8 KB per token). [[tygcrpcafhe.md]]

## Markov Property

The residual stream satisfies the Markov property: the current residual vector at any layer is the complete computational state. The next computation depends only on it, not on any earlier token or layer explicitly. [[tygcrpcafhe.md]]

This means the residual stream carries the full conversation history — every fact, entity, and relationship from every prior turn — compressed into the geometry of its vectors. Older tokens are not discarded; they are encoded inside the surviving residuals of the current context window. [[tygcrpcafhe.md]]

## KV Tensors Are Derived State

The key and value tensors stored in the [[kv-cache]] are a precomputed expansion of the residual stream. All KV values at a given position can be recomputed from its residual vector with a single matrix multiply per attention head — one cheap linear projection. [[tygcrpcafhe.md]]

This makes the ~978 MB KV cache for a 20-turn conversation redundant in principle: the same information is already encoded in a residual stream that is a fraction of the size.

## Recomputation Cost

Recomputing KV from a residual vector at a single position is cheap (one linear projection per head). Recomputing the residual itself for a position that has been fully evicted requires running the full forward pass up to that layer, which is expensive. [[tygcrpcafhe.md]]

This asymmetry is the design principle behind [[kv-direct]]: keep residuals, evict KV tensors, recompute KV cheaply on demand.

## See also

- [[kv-cache]] — the cache the residual stream makes redundant
- [[kv-direct]] — bounded caching that exploits residual Markov property
- [[attention-mechanism]] — the attention computation that reads and writes the residual stream
