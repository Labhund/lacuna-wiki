---
created: 2026-04-14
updated: 2026-04-14
---
# energy-landscape

The energy landscape is a geometric metaphor for the loss surface a neural network navigates during training. The "height" at any point in parameter space is the training objective — loss plus any regularisation penalties. Gradient descent is a ball rolling downhill: it quickly falls into some valley, but which valley depends on the terrain shape, friction (learning rate), and noise (batch size / optimisation stochasticity). [[compuflair2026theph.md]]

## Valleys, Width, and Entropy

Not all valleys are equal. A wide, flat valley corresponds to many different parameter configurations that all achieve roughly the same loss — high entropy in physics terms. A narrow valley corresponds to fewer configurations — lower entropy. [[compuflair2026theph.md]]

In the context of [[grokking]], [[compuflair2026theph.md]] proposes that the memorisation region of parameter space is typically wide (many ways to be a memoriser) while the rule-following region is narrower (more coordinated internal structure required). This entropy difference explains why gradient descent preferentially lands in the memorisation basin early in training.

## Drift Under Regularisation

Once a model has settled into a valley and training loss is low, the strong gradient force disappears. Weaker forces take over: [[weight-decay]] exerts a steady pull towards smaller norms, and mini-batch noise introduces a jitter analogous to thermal fluctuation in a physical system. Over long training runs these forces cause the model to drift within and between basins. [[compuflair2026theph.md]]

## Sharpness and Grokking: Empirical Correlation

[[220102177b.pdf]] demonstrates, on the S5 composition objective with a 2-layer transformer, that sharpness of the loss minimum — measured using the φ approximation of Keskar et al. (2016) — is predictive of whether a network generalises. Multiple networks trained with different random seeds for a fixed number of steps (until roughly half had achieved high validation accuracy) show a Spearman correlation of −0.795 (p < 0.000014) between validation accuracy and φ: networks in flatter regions of the loss landscape are far more likely to have grokked. [[220102177b.pdf]] interprets this as evidence that [[grokking]] happens only after the network's parameters enter relatively flat loss-landscape regions, consistent with the view that [[weight-decay]] and optimisation noise together drive the network away from sharp memorisation minima.

## See also

- [[phase-transition]] — what happens when the drift crosses a tipping point
- [[grokking]] — the observable phenomenon this landscape view explains
- [[memorization-vs-generalization]] — the two broad regions of the landscape
- [[weight-decay]] — the regulariser that drives drift toward narrower, more economical basins
