# Cooldown + Condition Source Completion

This pass closes the two benchmark verification blockers that can be proven without an independent damage formula.

## Cooldown legality
- 100% benchmark Alacrity uses a 0.8 recharge-time factor.
- Holo-Dancer Decoy applies its PvE 80% recharge reduction to the next utility within 10 seconds.
- Repeat Ransacker removes 2 seconds from the remaining Skritt Swipe recharge on every artifact use.
- Skritt Scuffle's 50-second base recharge becomes 40 seconds under Alacrity.

## Condition packets
- Mistburn Mortar: 5 field pulses of 1.5s Burning plus the next 5 strikes at 1s Burning.
- Forged Surfer Dash: initial 6s Burning; benchmark observed 4 additional child bombs per cast at 3.5s Burning.
- Kryptis Turret: up to 8 shots, each 1 Torment for 4s.
- Metal Legion Guitar Rockout: 3 pulses, each 1 Confusion for 8s.
- Zephyrite Sun Crystal: base PvE packet of 1 Burning for 4s; trait variants remain build-selectable.

These packets support source attribution only. Predicted DPS remains blocked until the exact stat and modifier timeline is frozen and damage is calculated independently.
