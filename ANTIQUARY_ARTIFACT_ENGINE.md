# Antiquary Artifact Engine — benchmark validation pass

This build adds an explicit state model for Antiquary artifacts used in the uploaded dagger benchmark.

## Separations enforced

- Root artifact rolls are separate from follow-up skills.
- Forged Surfer Dash is separate from `Forged Surfer Dash (Additional Bombs)`.
- Holo-Dancer Decoy is separate from its decoy damage row.
- Metal Legion Guitar `Rockout` is separate from `Smash`.
- Skritt Scuffle creates up to two Skritt Swipe follow-up charges; Swipe is not treated as another random artifact.
- Zephyrite Sun Crystal and the observed Chak Shield damage row remain separate.

## Benchmark-observed validation

The uploaded 94.013-second log contains 30 root artifact uses, 6 follow-up uses, and 7 observed artifact families. The reconstructed follow-up timeline has zero invalid transitions.

The Elite Insights JSON exposes casts and damage, but not the hidden random-roll/grant timestamp. The engine therefore requires artifact generation as an explicit external event and never invents it from a later cast.
