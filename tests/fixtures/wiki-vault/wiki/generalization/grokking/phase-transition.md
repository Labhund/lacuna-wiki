---
created: 2026-04-14
updated: 2026-04-14
---
# phase-transition

In physics, a phase transition occurs when a control parameter is changed smoothly but the system's behaviour changes abruptly: water freezes, a magnet aligns, a material becomes superconducting. [[compuflair2026theph.md]] proposes that [[grokking]] is a phase transition in this sense.

## The Analogy

| Physics | Grokking |
|---|---|
| Control knob (temperature, pressure) | Training time, weight decay strength, learning rate schedule, dataset size |
| Order parameter (density, magnetisation) | Test accuracy, generalisation gap |
| Phase (liquid vs solid) | Memorisation regime vs rule regime |

The training process can hover near the memorisation regime for a long time, then a small additional change — more training steps, slightly stronger regularisation — pushes it into the rule regime quickly. [[compuflair2026theph.md]]

## Why the Transition Is Abrupt

[[compuflair2026theph.md]] proposes that the balance between energy (fitting the data) and entropy (how many solutions exist in a region) shifts over training. Early on, the large memorisation basin wins on entropy. Later, as [[weight-decay]] erodes the advantage of high-norm memorisation solutions, the rule basin becomes the cheaper place to maintain low loss. When that balance crosses a tipping point, the transition is fast — analogous to latent heat release at a phase boundary. <!-- TODO: adversary check -->

## Practical Implications

- **Stop too early:** never see the transition — frozen in the memorisation phase.
- **Weight decay too weak:** memorisation remains comfortable indefinitely.
- **Weight decay too strong:** model cannot fit training data at all; never reaches the plateau where slow drift can work.
- **Goldilocks zone:** memorisation happens first, but is eventually destabilised. [[compuflair2026theph.md]]

The analogy does not require neural networks to literally obey thermodynamic laws. It is a set of intuitions about why systems get stuck, drift, and suddenly switch regimes. [[compuflair2026theph.md]]

## See also

- [[grokking]] — the observable phenomenon
- [[energy-landscape]] — the geometric framing of the two regimes
- [[memorization-vs-generalization]] — what the two phases correspond to
- [[weight-decay]] — the control knob that most directly modulates grokking
