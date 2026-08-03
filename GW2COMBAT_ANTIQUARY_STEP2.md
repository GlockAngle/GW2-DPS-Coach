# gw2combat Antiquary Step 2

This build generates a complete 173-cast rotation from `data/benchmark_dagger.json` and creates a gw2combat encounter package at runtime.

Implemented:
- Thief and Antiquary enum support in bundled gw2combat source.
- Generated player build, golem build, and timestamped rotation.
- 17 of 18 unique benchmark skill names mapped from verified local Thief skill records.
- Strike coefficients and condition packets emitted for mapped skills.
- Superior Sigil of Force as a separate 1.05 strike multiplier.
- Superior Sigil of Earth, Relic of the Fractal, and Potent Poison definitions.
- Simulation page button: `Run Antiquary benchmark simulation`.

Current explicit placeholder:
- Metal Legion Guitar (Smash)

This is an integration subtotal, not yet a claim of final 42,040 DPS accuracy. Initiative legality, artifact inventory state, venom charge timing, and exact child-event timestamps still require dedicated gw2combat definitions.
