RELIC MODEL SYSTEM
==================

Each relic available in the imported workbook selector has its own JSON file:

    data/relics/<relic_name>.json

The JSON file records whether the relic is implemented, its effect type,
modifiers, uptime rules, verification date, and notes.

Implemented combat model
------------------------
Relic of the Thief:
- +1% outgoing strike damage per stack
- maximum 5 stacks
- stacks last 6 seconds
- each eligible trigger adds one stack and refreshes every active stack
- the Relic analysis tab calculates average stacks, any-stack uptime,
  five-stack uptime, and average strike-damage modifier

Other relics
------------
Every imported relic has a file, but unsupported relics are explicitly marked
"implemented": false. This prevents the simulator from silently applying an
incorrect or guessed effect. Add a dedicated calculation to gear_simulator.py
when a relic is implemented.

Important
---------
Relic of the Thief affects strike damage only. It does not increase Spider
Venom damage because Spider Venom is condition damage.
