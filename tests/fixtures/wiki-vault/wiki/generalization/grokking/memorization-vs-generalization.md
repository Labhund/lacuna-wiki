---
created: 2026-04-14
updated: 2026-04-14
---
# memorization-vs-generalization

Training a neural network does not uniquely determine a single solution. There are many different functions a network could implement that all fit the training examples perfectly. [[compuflair2026theph.md]] frames this as a solution-selection problem: some of those functions are essentially elaborate lookup tables — memorisers that patch each training example individually and behave unpredictably on new inputs. Others implement a genuine rule that extends correctly to unseen data. Both score equally on the training set; only one generalises beyond it.

[[compuflair2026theph.md]] proposes that [[grokking]] is what happens when gradient descent first lands on a memorising solution and later migrates to a rule solution — not because the rule was unavailable, but because the memorisation basin is typically wider and easier to fall into during early training.

## Why Memorisation Comes First

Memorisation can reduce training loss quickly because it is flexible: the model can patch mistakes one by one. Rule learning often requires building the right internal machinery before it pays off, so the gradient does not point there first. [[compuflair2026theph.md]]

The volume of parameter configurations that implement memorisation is typically much larger than the volume that implements the correct rule. In physics terms this is an entropy difference: there are many more ways to be a memoriser than to be a rule follower. Early in training, the large memorisation basin wins by sheer size. [[compuflair2026theph.md]]

## The Migration

Once training loss is already low, the strong downhill gradient force is gone. The weaker forces — [[weight-decay]] and mini-batch noise — continue acting. Over time these can erode memorisation strategies that depend on large, sharp weight adjustments, and gradually shift the balance of stability towards the more economical rule solution. [[compuflair2026theph.md]]

The transition appears abrupt because it is a tipping point: the system hovers in the memorisation regime until the balance of pressures flips, then moves quickly. See [[phase-transition]] for the physics analogy.

## See also

- [[grokking]] — the observable phenomenon this model explains
- [[weight-decay]] — the regulariser that destabilises memorisation
- [[phase-transition]] — the physics lens on why the transition is abrupt
- [[energy-landscape]] — the geometric framing of memorisation vs rule basins
