### 2026-08-01 — Shared assumptions and progress dashboard

- Added a temporary **Trait Progress** navigation page.
- Progress counts are generated from `thief_effect_overrides.json`; no separate manual count is maintained.
- Added specialization totals, full/partial/waiting counts, filters, and a detailed checklist.
- Moved conditional trait assumptions out of the Traits page.
- Added **Combat & trait assumptions** to the Gear Simulator damage section so gear, traits, enemy state, and runtime assumptions feed one shared calculation state.
- Preserved all existing session-state keys, so current trait calculations and saved selections remain compatible.

- Shared combat/trait assumptions are now stored and restored with saved Gear Simulator builds (build schema version 2).

### 2026-08-01 — Assumption-driven trait completion pass

- Added shared uptime models for Fluid Strikes, Lotus Training, Bounding Dodger, and Exhilarating Ephemera.
- Registered Dark Sentry's +20% outgoing healing to allies.
- Corrected Havoc Specialist to +15% strike damage in PvE.
- Corrected Strength of Shadows to +20% Torment damage in PvE.
- Corrected Combat High to +3% strike and +2% condition damage per stack in PvE.
- Remaining waiting traits now predominantly require skill, dodge, Steal/Mark, artifact, initiative, internal-cooldown, or ally-event simulation.
## 2026-08-02 — Trait implementation pass 3

- Connected Invigorating Precision's PvE critical-damage healing ratio (4%, 6% with Fury).
- Added an Unhindered Combatant uptime assumption and connected its PvE 10% incoming strike/condition reduction.
- Connected One in the Chamber's PvE +25% stolen-skill damage to matching Skill Library records.
- Skill Library strike results now consume shared direct critical chance, critical damage, additive strike and multiplicative strike trait effects.
- Added a damage-audit row showing the combined outgoing trait factor.
- Saved builds now preserve the Unhindered Combatant uptime assumption.


## Pass 4
- Connected Leeching Venoms to the Spider Venom damage/healing audit.
- Added verified event packets for 10 additional traits instead of leaving them unmapped.
- Kept trigger-frequency portions partial until the event/rotation engine exists.
