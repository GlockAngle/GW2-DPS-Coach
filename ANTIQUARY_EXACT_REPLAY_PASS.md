# Antiquary exact replay pass

The generated gw2combat package now treats the Elite Insights cast timestamps as authoritative.

Previously, generated skills retained animation locks and cooldowns. gw2combat therefore delayed or skipped many logged casts (for example 26 of 39 Death Blossoms and 18 of 31 Double Strikes), causing a large artificial DPS deficit.

In exact replay mode:

- every benchmark skill has zero engine cast duration;
- every benchmark skill has zero engine cooldown;
- hit and condition packets remain scheduled at the logged cast-duration offset;
- instant utility/artifact casts may overlap weapon animations exactly as they did in the log;
- expected per-skill cast counts are included in package diagnostics.

This is intentionally a rotation replay mode. A later free-form optimizer mode can restore initiative, cooldown and animation legality checks independently.
