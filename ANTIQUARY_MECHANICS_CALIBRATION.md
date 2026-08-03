# Antiquary Mechanics Calibration

This build corrects the benchmark replay using explicit PvE mechanics sourced from the Guild Wars 2 Wiki.

## Implemented

- Enterprising Aristocrat: artifact skills grant 2 initiative in PvE.
- Holo-Dancer Decoy: arms a 10-second effect; the next utility skill consumes it and receives 80% reduced recharge in PvE.
- Skritt Scuffle and Skritt Swipe are no longer classified as artifact skills or as a parent/follow-up pair.
- Skritt Scuffle remains an elite Double Edge skill that supplies artifacts every 3 seconds while the player remains in range.
- Chak Shield's full PvE initiative-refund rule is registered in the mechanics database, but is not fabricated into this benchmark where the JSON does not expose a clear cast event for the state window.
- The displayed 42,040 DPS is explicitly labelled as observed player DPS from the uploaded benchmark log, not independently simulated DPS and not allied damage.

## Benchmark replay result

- Observed player DPS: 42,040
- Confirmed usable initiative from artifact casts: +52
- Remaining aggregate unmodeled initiative requirement: 0
- Holo-Dancer utility-recharge consumptions detected: 2
- Remaining cooldown-spacing conflicts: 15

The remaining conflicts still require charge, preparation, alacrity, Double Edge, and exact state-window handling before free-form prediction.
