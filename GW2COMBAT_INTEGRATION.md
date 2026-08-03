# gw2combat integration

The old experimental Python prediction engine has been removed from the main UI. `gw2combat` is bundled under `vendor/gw2combat` and remains licensed under its MIT license.

## One-time Windows build
Open PowerShell in the project folder and run:

```powershell
.\scripts\build_gw2combat.ps1
```

Then start the dashboard normally:

```powershell
python -m streamlit run app.py
```

The **Simulation** workspace reports whether the executable is available.

## Current integration boundary
The adapter can execute arbitrary gw2combat encounter/build/rotation files and parse the audit output. Complete live Antiquary definitions still have to be authored against gw2combat's configuration schema before the app can claim a full independent Antiquary DPS result. The UI never labels an incomplete result as a full prediction.
