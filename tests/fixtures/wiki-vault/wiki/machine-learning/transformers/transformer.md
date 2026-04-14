---
created: 2026-04-14
updated: 2026-04-14
---
# transformer

The Transformer is a sequence-to-sequence architecture that relies entirely on [[attention-mechanism|attention mechanisms]], dispensing with recurrence and convolution. [[vaswani2017.pdf]] It consists of an encoder stack and a decoder stack, each built from repeated identical layers of attention and feed-forward computation.

## Encoder

The encoder maps an input token sequence to a sequence of continuous representations. It is composed of N = 6 identical layers. Each layer has two sublayers:

1. **Multi-head self-attention** — every token attends to every other token in the same sequence. See [[attention-mechanism]].
2. **Position-wise feed-forward network** — a two-layer FFN applied independently and identically to each token position (described below).

A residual connection wraps each sublayer, followed by layer normalisation:

```
output = LayerNorm(x + Sublayer(x))
```

All sublayers and the embedding layer produce outputs of dimension d_model = 512, enabling the residual additions. [[vaswani2017.pdf]]

## Decoder

The decoder generates the output sequence one token at a time (autoregressive). It is also composed of N = 6 identical layers, each with three sublayers:

1. **Masked multi-head self-attention** — each position attends only to earlier positions. Future positions are masked out (set to −∞ before softmax) to prevent information leakage.
2. **Encoder-decoder attention** — queries come from the previous decoder layer; keys and values come from the encoder output. This lets every decoder position attend over the full input sequence.
3. **Position-wise feed-forward network** — same structure as in the encoder.

Residual connections and layer norm are applied after each sublayer, as in the encoder. [[vaswani2017.pdf]]

## Embeddings and position

Input and output tokens are converted to d_model = 512 dimensional vectors via learned embeddings. The same weight matrix is shared between the two embedding layers and the pre-softmax linear projection. [[vaswani2017.pdf]]

Because the architecture contains no recurrence, token order is supplied by [[positional-encoding]], added to the embeddings at the bottom of both stacks before any computation.

## Position-wise feed-forward network

Each encoder and decoder layer contains a fully connected feed-forward network applied to each position separately and identically:

```
FFN(x) = max(0, xW₁ + b₁)W₂ + b₂
```

The input and output dimension is d_model = 512; the inner dimension is d_ff = 2048. Parameters differ across layers but are shared across positions within a layer. [[vaswani2017.pdf]]

## Scale

The base Transformer has 65M parameters (N = 6, d_model = 512, d_ff = 2048, h = 8 heads, d_k = d_v = 64). The big model has 213M parameters (N = 6, d_model = 1024, d_ff = 4096, h = 16 heads). [[vaswani2017.pdf]]

## Results

[[vaswani2017.pdf]] demonstrates, on the WMT 2014 English-to-German translation task, that the big Transformer achieves 28.4 BLEU — more than 2 BLEU above the previous state-of-the-art including ensembles — trained in 3.5 days on 8 P100 GPUs. On WMT 2014 English-to-French it achieves 41.8 BLEU, also state-of-the-art, at less than a quarter of the training cost of the prior best model.

See also: [[attention-mechanism]], [[positional-encoding]], [[kv-cache]], [[residual-stream]]
