---
created: 2026-04-14
updated: 2026-04-14
---
# positional-encoding

Positional encoding injects sequence-order information into a [[transformer]] by adding a position-dependent vector to each token's embedding before it enters the encoder or decoder stack. Because the Transformer contains no recurrence and no convolution, it has no inherent notion of token order; positional encoding is the mechanism that supplies it. [[vaswani2017.pdf]]

## Sinusoidal encoding

[[vaswani2017.pdf]] encodes position *pos* and embedding dimension *i* using sine and cosine functions of geometrically spaced frequencies:

```
PE(pos, 2i)   = sin(pos / 10000^(2i/d_model))
PE(pos, 2i+1) = cos(pos / 10000^(2i/d_model))
```

The wavelengths form a geometric progression from 2π to 10000·2π across the d_model dimensions. The authors hypothesise that this representation allows the model to attend by relative position: for any fixed offset *k*, PE(pos+k) can be expressed as a linear function of PE(pos), making relative relationships easy to learn via [[attention-mechanism|attention]].

## Learned vs sinusoidal

[[vaswani2017.pdf]] compared sinusoidal encoding against learned positional embeddings and found nearly identical results on WMT 2014 EN-DE translation. The encoding form is not load-bearing for translation quality. The sinusoidal variant was preferred because it may generalise to sequence lengths longer than those seen during training.

## Placement

Positional encodings are added to the input embeddings at the bottom of both the encoder and decoder stacks — once, before computation begins — not reinjected between layers.
