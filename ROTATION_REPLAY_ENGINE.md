# Rotation Replay Engine

This build adds an evidence-first replay of the uploaded Condition Antiquary dagger benchmark.

## What it does

- Reconstructs all observed casts in chronological order.
- Rebuilds occupied cast time and compares it with Elite Insights cast uptime.
- Tracks verified initiative costs and reports the additional initiative income that remains unmodeled.
- Checks observed cast spacing against stored base recharge and exposes conflicts for later state modeling.
- Separates modeled direct-damage sources from aggregate condition output.
- Replays Antiquary artifact actions without inventing hidden random grant timestamps.

## Current benchmark result

- 42,040 observed DPS
- 3,952,297 observed total damage
- 173 casts replayed
- 100% of observed casts classified into a modeled core/artifact role
- 97.92% of observed power damage mapped to a modeled cast or artifact source
- Reconstructed cast uptime: 98.632% versus 98.25% reported by Elite Insights

## Deliberate blockers

This is not yet a free-form optimizer. Condition attribution, non-passive initiative gains, recharge resets/charges, and hidden artifact grants remain explicit blockers rather than assumptions.
