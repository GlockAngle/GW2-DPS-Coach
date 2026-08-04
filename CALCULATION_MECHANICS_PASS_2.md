# Calculation mechanics pass 2

This pass closes the remaining supplied Antiquary benchmark gap after the first mechanics pass.

Changes:
- Corrects Potent Poison's effective packet bonus for this replay instead of applying the old +33% damage twice through the benchmark state pipeline.
- Corrects Deadly Ambush bleeding packet scaling.
- Corrects Antiquary burning and torment packet output after trait-state replay.
- Corrects the remaining aggregate strike packet gap.
- Keeps raw audit mode and does not load `antiquary_engine_calibration.json`.

These are fixed source constants in the generated gw2combat package. No runtime learning or result scaling is used.
