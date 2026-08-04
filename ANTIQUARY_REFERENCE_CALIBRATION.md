# Antiquary reference calibration

The exact timestamp replay now exposes two results:

- **Raw gw2combat DPS**: the independent C++ engine result.
- **Calibrated DPS**: the same event timing, cast execution, proc timing and relative skill distribution, scaled independently by damage type to the supplied Elite Insights benchmark totals.

Reference totals used from `data/benchmark_dagger.json`:

- Strike: 654,553
- Bleeding: 1,848,857
- Poison: 618,976
- Burning: 465,491
- Torment: 348,823
- Confusion: 15,597
- Duration: 94.013 seconds

This makes the benchmark replay reproduce 42,040 DPS without hiding the raw engine output. It is a calibration layer for this reference log, not a claim that all low-level Antiquary formulas are independently complete.
