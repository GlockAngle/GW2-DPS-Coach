"""Wiki-sourced Antiquary mechanics used by the replay engine.

Values in this file are PvE values unless noted otherwise.  Each mechanic keeps
its source URL and evidence note so the UI can distinguish verified rules from
assumptions.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Mechanic:
    key: str
    name: str
    value: float | int | str
    unit: str
    trigger: str
    effect: str
    source_url: str
    evidence: str = "wiki_verified"


MECHANICS: dict[str, Mechanic] = {
    "benchmark_alacrity_recharge_factor": Mechanic(
        key="benchmark_alacrity_recharge_factor",
        name="Benchmark alacrity recharge factor",
        value=0.8,
        unit="multiplier",
        trigger="Benchmark profile has 100% alacrity",
        effect="Skills with recharge complete in 80% of their listed base recharge.",
        source_url="https://wiki.guildwars2.com/wiki/Alacrity",
    ),
    "repeat_ransacker_recharge_reduction": Mechanic(
        key="repeat_ransacker_recharge_reduction",
        name="Repeat Ransacker Skritt Swipe reduction",
        value=2,
        unit="seconds",
        trigger="Use an artifact while Repeat Ransacker is selected",
        effect="Reduce the remaining recharge of Skritt Swipe by 2 seconds.",
        source_url="https://wiki.guildwars2.com/wiki/Repeat_Ransacker",
    ),
    "artifact_initiative_gain": Mechanic(
        key="artifact_initiative_gain",
        name="Enterprising Aristocrat initiative gain",
        value=2,
        unit="initiative",
        trigger="Use an artifact skill",
        effect="Gain 2 initiative in PvE.",
        source_url="https://wiki.guildwars2.com/wiki/Enterprising_Aristocrat",
    ),
    "holo_utility_recharge_reduction": Mechanic(
        key="holo_utility_recharge_reduction",
        name="Holo-Dancer Decoy utility recharge reduction",
        value=80,
        unit="percent",
        trigger="Use Holo-Dancer Decoy, then use the next utility skill within 10 seconds",
        effect="The next utility skill has 80% reduced recharge in PvE.",
        source_url="https://wiki.guildwars2.com/wiki/Holo-Dancer_Decoy",
    ),
    "holo_effect_duration": Mechanic(
        key="holo_effect_duration",
        name="Holo-Dancer Decoy effect duration",
        value=10,
        unit="seconds",
        trigger="Use Holo-Dancer Decoy",
        effect="The utility-recharge modifier remains available for 10 seconds or until consumed.",
        source_url="https://wiki.guildwars2.com/wiki/Holo-Dancer_Decoy",
    ),
    "chak_initiative_refund": Mechanic(
        key="chak_initiative_refund",
        name="Chak Shield initiative refund",
        value=100,
        unit="percent",
        trigger="Use Chak Shield, then use weapon skills that cost initiative during its effect",
        effect="Qualifying weapon skills refund all initiative spent in PvE.",
        source_url="https://wiki.guildwars2.com/wiki/Chak_Shield",
    ),
    "skritt_scuffle_interval": Mechanic(
        key="skritt_scuffle_interval",
        name="Skritt Scuffle artifact interval",
        value=3,
        unit="seconds",
        trigger="Remain in range of the summoned skritt",
        effect="The elite grants an artifact every interval for its duration.",
        source_url="https://wiki.guildwars2.com/wiki/Skritt_Scuffle",
    ),
}

ARTIFACT_SKILL_IDS = {
    76633,  # Forged Surfer Dash
    77277,  # Mistburn Mortar
    77192,  # Summon Kryptis Turret
    76674,  # Holo-Dancer Decoy
    76582,  # Metal Legion Guitar (Rockout)
    76596,  # Metal Legion Guitar (Smash / sequence action)
    76895,  # Zephyrite Sun Crystal
}

# Utility actions used by the benchmark. Prepare/activate are separate actions;
# only the next utility cast consumes the Holo-Dancer effect.
BENCHMARK_UTILITY_IDS = {13026, 13028, 13037, 56898}
HOLO_DANCER_ID = 76674
SKRITT_SCUFFLE_ID = 77255
SKRITT_SWIPE_ID = 77397


def mechanics_rows() -> list[dict[str, object]]:
    return [
        {
            "key": m.key,
            "name": m.name,
            "value": m.value,
            "unit": m.unit,
            "trigger": m.trigger,
            "effect": m.effect,
            "source_url": m.source_url,
            "evidence": m.evidence,
        }
        for m in MECHANICS.values()
    ]
