---
created: 2026-04-14
updated: 2026-04-14
---
# kv-cache

The KV cache stores the pre-computed key and value tensors for every attention layer and every token in the current context, so that autoregressive decoding does not recompute them on each new token. [[tygcrpcafhe.md]]

## Memory Scaling Problem

KV cache size grows with context length. For Gemma 3 12B running a 20-turn conversation, the unbounded KV cache grows from 48 MB at turn 1 to ~978 MB by turn 20 — nearly 1 GB for a single session. [[tygcrpcafhe.md]]

The cache tensors represent the full K and V projections across all layers for all prior tokens. The residual stream state that underlies them is far smaller — approximately 8 KB per token — yet the KV expansion is stored redundantly even though it can be recomputed from the residual stream at any time. [[tygcrpcafhe.md]]

## Latency Bottleneck

Growing cache size degrades inference speed. In the Gemma 3 12B benchmark, per-turn wall-clock time rises from ~3 s at turn 1 to ~13 s at turn 20 under standard unbounded caching. [[tygcrpcafhe.md]]

The KV cache, originally introduced as an optimisation to avoid recomputation, becomes the dominant cost at long contexts.

## See also

- [[attention-mechanism]] — the Q/K/V computation the cache accelerates
- [[residual-stream]] — the compact state from which KV tensors can be recomputed
- [[kv-direct]] — bounded cache approach that evicts and recomputes on demand
