"""Benchmark reference-window helpers.

Keeps the Elite Insights fight-window DPS separate from the in-game golem DPS
shown to the player. Both can be valid because they may divide the same damage
by slightly different timing windows.
"""
from __future__ import annotations

from typing import Any


def build_benchmark_reference(
    report: dict[str, Any],
    *,
    ingame_displayed_dps: float | None = None,
) -> dict[str, Any]:
    player = report["players"][0]
    damage = int(player.get("dpsAll", [{}])[0].get("damage", 0) or 0)
    duration_ms = int(report.get("durationMS", 0) or 0)
    ei_duration_s = duration_ms / 1000.0 if duration_ms else 0.0
    ei_dps = damage / ei_duration_s if ei_duration_s else 0.0

    ingame_duration_s = None
    window_difference_s = None
    dps_difference = None
    dps_difference_pct = None
    if ingame_displayed_dps and ingame_displayed_dps > 0 and damage > 0:
        ingame_duration_s = damage / float(ingame_displayed_dps)
        window_difference_s = ei_duration_s - ingame_duration_s
        dps_difference = float(ingame_displayed_dps) - ei_dps
        dps_difference_pct = dps_difference / ei_dps * 100.0 if ei_dps else None

    return {
        "damage": damage,
        "elite_insights": {
            "dps": round(ei_dps),
            "raw_dps": ei_dps,
            "duration_s": ei_duration_s,
            "label": "Elite Insights fight-window DPS",
            "source": "Uploaded Elite Insights JSON",
        },
        "ingame": {
            "dps": round(float(ingame_displayed_dps)) if ingame_displayed_dps else None,
            "duration_s_implied": ingame_duration_s,
            "label": "In-game golem DPS",
            "source": "Player-reported in-game benchmark display",
        },
        "comparison": {
            "window_difference_s": window_difference_s,
            "dps_difference": dps_difference,
            "dps_difference_pct": dps_difference_pct,
            "same_damage_basis": True,
            "interpretation": (
                "The values use the same player damage total but different effective timing windows. "
                "Use Elite Insights for JSON replay validation and retain the in-game value as the player's benchmark score."
            ),
        },
    }
