# Benchmark Verification Gate

This build adds a strict readiness gate to **Antiquary Benchmark → Rotation Replay**.

The gate distinguishes:

- observed log values;
- reconstructed timeline facts;
- packet-weighted attribution estimates;
- independently predicted damage.

Current benchmark result:

- 5 of 9 verification categories fully verified;
- 80.5% weighted verification progress;
- 3 blocking categories remain;
- observed DPS is 42,040 and is explicitly not labeled as predicted DPS.

The remaining blocking work is shown directly in the site. The gate cannot turn green until cooldown/state legality, all condition-source packets, and independent damage formulas are complete.
