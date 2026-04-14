---
created: 2026-04-14
updated: 2026-04-14
---
# kv-direct

KV Direct is an inference strategy that bounds the KV cache to a fixed memory budget and recomputes evicted KV tensors from the [[residual-stream]] on demand, achieving constant memory usage and stable per-turn latency at arbitrary context lengths. [[tygcrpcafhe.md]]

## Mechanism

Rather than growing the KV cache unboundedly, KV Direct enforces a hard memory cap (e.g. 150 MB). When the budget is exceeded, the oldest KV tensors are evicted. If an evicted position is needed during attention, its key and value tensors are recomputed from the stored residual vector at that position — one linear projection per attention head. [[tygcrpcafhe.md]]

The residual stream is preserved precisely because recomputing it from scratch is expensive (requires the full forward pass through all layers up to that position), while recomputing KV from a residual is cheap. [[tygcrpcafhe.md]]

## Performance

On Gemma 3 12B over a 20-turn conversation with a 150 MB KV budget (~400 tokens):

- Memory stays flat after turn 3, never exceeding the budget.
- Per-turn latency is ~3.8–4.2 s throughout, compared to 3 s → 13 s for unbounded caching.
- At turn 20, KV Direct is ~3× faster than standard KV caching by wall-clock time.

The bounded version running on a sixth of the memory outperforms the unbounded version at long contexts. [[tygcrpcafhe.md]]

## Correctness

Experimental verification showed that KV Direct produces identical outputs to unbounded caching on the same prompts — no context is lost. Older tokens are not discarded; they remain encoded in the residual stream and are accessible via recomputation. [[tygcrpcafhe.md]]

## See also

- [[kv-cache]] — the unbounded baseline KV Direct replaces
- [[residual-stream]] — the compact state KV Direct preserves and recomputes from
- [[attention-mechanism]] — the attention computation KV Direct accelerates
