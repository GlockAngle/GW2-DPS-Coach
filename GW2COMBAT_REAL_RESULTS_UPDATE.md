# gw2combat real-results integration

This pass replaces the raw-audit placeholder on the Simulation page with a real parser for gw2combat's `tick_events` schema.

## Included

- Runs the generated 173-cast Antiquary package through `bin/gw2combat.exe`.
- Parses player damage events, cast events, combat duration and AFK ticks.
- Displays simulated DPS, total damage, combat time and event count.
- Adds skill/damage-type breakdowns, a cumulative-DPS timeline and cast audit.
- Adds an audit JSON download and keeps raw output under collapsed diagnostics.
- Gives all Simulation buttons stable Streamlit keys to prevent duplicate-element errors.
- Improves timeout and process-error diagnostics.

## Current limitation

The engine result is now real, but the generated Antiquary model is still incomplete. Missing artifact inventory, initiative legality, venom recipient/timing and child-event timing can still create a large gap from the 42,040-DPS reference log.
