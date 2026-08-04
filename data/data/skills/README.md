# Thief Skill Library

- `thief_skills_api.json` is created by the **Sync GW2 API** button on the Skill Library page.
- `thief_skills_meta.json` records the sync timestamp.
- `thief_skill_overrides.json` is the persistent enrichment layer for fields the public API does not expose reliably, including PvE power coefficients, cast times, aftercasts and venom-trigger counts.

Override example:

```json
{
  "12345": {
    "power_coefficient": 1.25,
    "cast_time": 0.75,
    "aftercast": 0.10,
    "hits": 2,
    "venom_triggers": 2,
    "wiki_verified": true,
    "verified_on": "2026-08-01",
    "notes": "PvE values verified against the GW2 Wiki"
  }
}
```
