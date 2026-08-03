# Thief trait data

The Traits page uses the official Guild Wars 2 API as its update source and links every trait to the Guild Wars 2 Wiki.

- `thief_traits_api.json` is created/refreshed from the live API by the **Refresh official trait data** button.
- `trait_presets.json` stores user-created trait presets.
- `thief_effect_overrides.json` is the intentionally small, human-editable implementation layer.

The API cache contains names, icons, in-game descriptions and fact records for all Thief core and elite specialization traits. A trait does not alter calculator output until its unconditional/static effect is explicitly verified and added to `thief_effect_overrides.json`, or a future custom Python handler is written for stateful mechanics.
