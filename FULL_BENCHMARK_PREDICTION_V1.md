# Full Benchmark Prediction v1

This build connects the exact uploaded benchmark cast timeline to Combat Engine v1.

## What is genuinely predicted
- Strike damage for skills with verified PvE coefficients.
- Condition damage for explicit condition packets.
- Condition duration from the bundled Condi Antiquary gear profile.
- Confirmed Potent Poison PvE poison damage and duration modifiers.
- Fight-end truncation of condition duration.

## What the result means
The UI labels the result **Predicted covered DPS**, not full predicted DPS. It is calculated from formulas and does not read observed damage totals. The current bundled benchmark produces about 18.7k predicted DPS from the covered packets.

The remaining gap is explicit: selected trait modifiers, Fractal relic procs, Earth sigil procs, and several artifact child effects are not yet independently generated. These remain listed under unsupported sources.
