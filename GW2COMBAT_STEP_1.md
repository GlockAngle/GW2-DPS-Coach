# gw2combat integration — Step 1

This build establishes and verifies the backend bridge before Thief definitions are added.

## Included
- Bundled upstream gw2combat source and MIT license.
- Windows CMake build script with an automatic smoke test.
- Python adapter with reference validation and safer binary execution.
- A clean Simulation page with a one-click backend test.
- Manual encounter/build/rotation runner for development.
- No observed benchmark value is presented as predicted DPS.

## One-time Windows setup
From the project directory:

```powershell
.\scripts\build_gw2combat.ps1
```

Then start Streamlit normally:

```powershell
python -m streamlit run app.py
```

## Next step
Implement the reusable Thief resource layer and Dagger/Dagger skill definitions in gw2combat format.
