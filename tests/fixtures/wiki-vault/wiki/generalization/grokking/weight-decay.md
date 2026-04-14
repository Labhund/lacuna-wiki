---
created: 2026-04-14
updated: 2026-04-14
---
# weight-decay

Weight decay is a regularisation technique that adds a penalty proportional to the L2 norm of the weights to the training objective. In practice it applies a constant multiplicative shrinkage to every weight at each optimisation step, gently pushing parameter values toward zero. [[compuflair2026theph.md]]

## Mechanism During the Grokking Plateau

Weight decay keeps acting even after training loss is already near-zero. The model can sit at near-perfect training accuracy, yet weights continue to be nudged toward smaller norms step after step. [[compuflair2026theph.md]]

[[compuflair2026theph.md]] proposes that this creates an asymmetry between memorisation and rule-following solutions over time:

- **Memorisation** strategies often rely on many large, sharp weight adjustments to nail individual training examples. These high-norm configurations are penalised more heavily and are gradually eroded.
- **Rule-following** strategies may be more economical — implementing the underlying algorithm with a smaller, more structured set of weights. They are cheaper to maintain under weight decay.

As training continues, the rule basin becomes the more stable place to live. When that balance tips, the model migrates — producing the abrupt generalisation jump characteristic of [[grokking]]. [[compuflair2026theph.md]] <!-- TODO: adversary check -->

## Weight Decay Strength and the Goldilocks Zone

[[compuflair2026theph.md]] notes that grokking is sensitive to weight decay strength:

- **Too weak:** memorisation remains comfortable indefinitely; the model never migrates.
- **Too strong:** the model cannot fit the training data at all; the plateau never forms.
- **Goldilocks zone:** memorisation happens first, but is eventually destabilised, allowing the slow drift to do its work.

## Empirical Effect on Data Efficiency

[[220102177b.pdf]] demonstrates, on the S5 composition objective with a 2-layer transformer and a budget of 10⁵ optimisation steps, that AdamW with weight decay 1 more than halves the fraction of training data required to reach 99% validation accuracy, compared to most other interventions tested — including full-batch gradient descent, vanilla Adam, residual dropout, and varying learning rates. Among the regularisers evaluated, weight decay had the largest single effect on data efficiency. [[220102177b.pdf]] also tests weight decay toward the network initialisation rather than the origin and finds it effective but slightly weaker, suggesting that the prior that approximately-zero weights suit small algorithmic tasks explains part but not all of weight decay's benefit.

## Interaction with Mini-Batch Noise

Mini-batch training adds a jitter to the optimisation trajectory — analogous to thermal noise in a physical system. Weight decay provides the directional pressure; the noise provides the exploration. Together they drive the slow drift during the grokking plateau that eventually crosses the [[phase-transition]] tipping point. [[compuflair2026theph.md]]

## See also

- [[grokking]] — the phenomenon weight decay's slow action enables
- [[phase-transition]] — why the transition is abrupt once the balance tips
- [[energy-landscape]] — the geometric framing of the memorisation and rule basins
- [[memorization-vs-generalization]] — what the two basins correspond to
