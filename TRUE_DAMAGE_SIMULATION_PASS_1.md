# True damage simulation — pass 1

This build adds an evidence-aware condition-source attribution layer to the Rotation Replay page.

## What it does

- Keeps **Observed DPS** separate from any future independent prediction.
- Reads explicit condition packets from the skill event library.
- Uses cast counts from the benchmark replay.
- Attributes each mapped aggregate condition total by relative base stack-seconds.
- Shows source rows, event phases, cast counts, attribution share, attributed damage, and attributed DPS.
- Exposes unmapped conditions and prediction blockers rather than inventing sources.

## Current benchmark result

- Observed condition damage: 3,297,744
- Packet-attributed condition damage: 2,467,833
- Coverage: 74.83%
- Poison and Bleeding are mapped through explicit benchmark skill packets.
- Burning, Confusion, and Torment remain unmapped in this pass because their trait/sigil/relic/artifact source packets are not yet complete.

## Important limitation

This is **attribution**, not independent prediction. It preserves the observed total for each condition that has at least one explicit packet source. A true predicted DPS value remains blocked until the remaining generated condition sources, stat snapshot, modifiers, event timings, ramp, and target-death truncation are modeled.
