# Calculation mechanics pass 1

This pass fixes concrete missing or misread PvE mechanics in the raw gw2combat replay:

- Replays Lead Attacks and Combat High from their Elite Insights state timelines as time-weighted damage-state modifiers.
- Adds Deadly Ambush's +25% bleeding damage.
- Adds Deadly Ambush's 3 stacks of bleeding for 10 seconds to Skritt Swipe.
- Treats Mistburn Mortar's 0.5 coefficient as a per-pulse coefficient rather than dividing it across five pulses.
- Adds the four observed Forged Surfer additional bomb strikes at 1.2 coefficient each.

These are mechanics/state corrections. No reference-total scaling or damage-type calibration is enabled.
