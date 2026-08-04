from __future__ import annotations

from typing import Any

CONDITION_DURATION_KEY_BY_FAMILY = {
    "bleeding": "Bleeding Duration",
    "burning": "Burning Duration",
    "confusion": "Confusion Duration",
    "poison": "Poison Duration",
    "torment": "Torment Duration",
}

CONDITION_FAMILY_ALIASES = {
    "bleed": "bleeding",
    "bleeding": "bleeding",
    "burn": "burning",
    "burning": "burning",
    "confusion": "confusion",
    "poison": "poison",
    "poisoned": "poison",
    "torment": "torment",
}


def condition_family(name: str) -> str:
    """Return the canonical condition family used by damage and duration registries."""
    normalized = str(name or "").strip().lower()
    return CONDITION_FAMILY_ALIASES.get(normalized, normalized)


def resolve_condition_duration_bonus(
    condition_name: str,
    generic_duration: float,
    specific_durations: dict[str, Any] | None,
    additional_specific_bonus: float = 0.0,
) -> float:
    """Resolve the full condition-duration bonus from canonical or legacy keys.

    Gear Simulator stores condition-specific totals under names such as
    ``Poison Duration``. The Skill Library previously asked for ``Poison``,
    which silently discarded specific bonuses such as Potent Poison. This
    resolver accepts all supported representations for every damaging
    condition and applies the normal 100% duration cap.
    """
    family = condition_family(condition_name)
    duration_key = CONDITION_DURATION_KEY_BY_FAMILY.get(family)
    values = specific_durations or {}
    candidates = (
        duration_key,
        str(condition_name),
        str(condition_name).title(),
        family,
        family.title(),
    )
    resolved = float(generic_duration or 0.0)
    for key in candidates:
        if not key or key not in values:
            continue
        try:
            resolved = max(resolved, float(values[key]))
        except (TypeError, ValueError):
            continue
    # The runtime metrics object is only created while Gear Simulator is
    # rendered. Other pages may therefore have an older or empty metrics
    # snapshot after navigation/restart. Merge the currently resolved trait
    # duration effect as a fallback, but use max() rather than adding it to an
    # already-complete specific total. This avoids double-counting when Gear
    # Simulator has already included the same trait.
    try:
        trait_resolved = float(generic_duration or 0.0) + float(additional_specific_bonus or 0.0)
        resolved = max(resolved, trait_resolved)
    except (TypeError, ValueError):
        pass
    return max(0.0, min(1.0, resolved))
