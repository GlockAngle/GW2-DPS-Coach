GW2 DPS Coach - neutral damage engine

Implemented in this build:
- Real selectable weapon-strength ranges and Minimum/Midpoint/Maximum roll
- Neutral strike formula with coefficient, armor, critical chance, critical damage and vulnerability
- Separate additive and multiplicative strike modifier buckets
- Level-80 PvE condition damage formulas for bleeding, burning, poison, torment and confusion
- Weighted torment from enemy movement uptime
- Confusion activation DPS from enemy attacks per second
- Global and condition-specific modifier inputs
- Neutral ProcEffect data contract for future sigils, relics and traits
- All new settings are stored in saved builds

Intentionally not implemented yet:
- Thief traits, initiative, skills, coefficients and animation times
- Rotation DPS or timeline graph
- Automatic relic/sigil proc simulation unless individually modelled
- Skill-specific condition duration/application counts

The Damage details values are damage per selected hit/coefficient and damage per condition stack,
not full DPS. Full DPS becomes valid after Thief skills and rotations are connected.
