---
created: 2026-04-14
updated: 2026-04-14
---
# attention-mechanism

The attention mechanism computes a weighted sum of values, where weights are determined by compatibility between a query and a set of keys.

## Scaled Dot-Product

Attention scores are computed as dot products between query and key vectors, scaled by √d_k to prevent gradient saturation. [[vaswani2017.pdf]]

The formula is: Attention(Q, K, V) = softmax(QK^T / √d_k) V

During autoregressive inference the computed K and V tensors are stored across decode steps as the [[kv-cache]], avoiding recomputation at the cost of memory that grows linearly with context length. [[tygcrpcafhe.md]]

## Multi-Head Attention

Multiple attention heads run in parallel, each attending to different subspaces. Outputs are concatenated and projected. [[vaswani2017.pdf]]

## Path length and long-range dependencies

A key motivation for self-attention over recurrent layers is the maximum signal path length between any two positions in the sequence. In a self-attention layer, any two positions are connected in O(1) sequential operations, because every position attends to every other position directly. In a recurrent layer, the path grows as O(n) — information must propagate token by token. Convolutional layers require O(log_k(n)) layers of dilated convolutions to connect distant positions. [[vaswani2017.pdf]]

Shorter paths make it easier to learn long-range dependencies during training, because gradients travel fewer steps to reach any pair of positions. Self-attention in the [[transformer]] reduces this to a constant, at the cost of O(n²·d) per-layer compute — which is faster than recurrent O(n·d²) when sequence length n is smaller than representation dimension d, the typical regime for sentence-length NLP. [[vaswani2017.pdf]]

See also: [[transformer]]
