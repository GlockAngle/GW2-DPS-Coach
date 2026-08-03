GEAR SIMULATOR ADDED

The existing GW2 DPS Coach project now includes a new sidebar page:
    Gear Simulator

New files:
    data/gear_data.json
    utils/gear_simulator.py

Modified file:
    app.py

Run the project as before from this folder:
    streamlit run app.py

The page currently provides:
- Selectable prefixes for weapons, armour and trinkets.
- Food, utility, sigils and infusions.
- Core stat totals and derived stat metrics.
- Spider Venom damage-per-cast and DPS using the selected Condition Damage.

Current limitation:
- Rune and relic names are selectable, but conditional/special effects are not yet included in totals.
- The DPS result is Spider Venom contribution, not full rotation DPS.
