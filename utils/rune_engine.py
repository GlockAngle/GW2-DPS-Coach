"""Class-neutral rune stat calculation.

The workbook import stores many six-rune totals as Excel IFS formulas rather than
plain numbers.  This module evaluates those formulas without depending on
Streamlit, which makes the behavior testable and prevents rune bonuses from
silently disappearing in the UI layer.
"""
from __future__ import annotations

import re
from typing import Any, Iterable


_FORMULA_PAIR_RE = re.compile(
    r"[A-Z]+\d*(>=|=)(\d+),(-?\d+(?:\.\d+)?)",
    flags=re.IGNORECASE,
)


def number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def evaluate_count_formula(formula: str, equipped_count: int = 6) -> float:
    """Evaluate the ordered COUNT/IFS formulas used by the imported rune sheet.

    Example: ``IFS(M6>=6,225,M6>=4,100,M6>=2,35)`` returns 225 for six runes.
    The first matching condition wins, just like Excel IFS.
    """
    if not formula:
        return 0.0
    cleaned = formula.replace("$", "").replace(" ", "")
    for operator, threshold_text, value_text in _FORMULA_PAIR_RE.findall(cleaned):
        threshold = int(threshold_text)
        matches = equipped_count >= threshold if operator == ">=" else equipped_count == threshold
        if matches:
            return float(value_text)
    return 0.0


def calculate_rune_bonus(
    rune_data: dict[str, Any],
    core_stats: Iterable[str],
    equipped_count: int = 6,
) -> tuple[dict[str, float], dict[str, float]]:
    """Return static rune attributes and non-attribute modifiers."""
    core_stats = tuple(core_stats)
    stats = {stat: 0.0 for stat in core_stats}
    modifiers = {"Boon Duration": 0.0, "Condition Duration": 0.0, "Critical Chance": 0.0}

    formulas = rune_data.get("_formulas", {}) if isinstance(rune_data, dict) else {}
    for key in (*core_stats, *modifiers):
        direct_value = number(rune_data.get(key))
        formula = str(formulas.get(key, ""))
        # A present formula is authoritative, including a legitimate zero result.
        final_value = evaluate_count_formula(formula, equipped_count) if formula else direct_value
        if key in stats:
            stats[key] = final_value
        else:
            modifiers[key] = final_value
    return stats, modifiers
