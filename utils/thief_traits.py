from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import streamlit as st

from utils.effect_engine import EffectKind, EffectRegistry
from utils.user_storage import load_json_dict, persistent_json_path, write_json_dict
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parents[1]
TRAIT_DIR = ROOT / "data" / "traits"
CACHE_PATH = TRAIT_DIR / "thief_traits_api.json"
OVERRIDES_PATH = TRAIT_DIR / "thief_effect_overrides.json"
BUNDLED_PRESETS_PATH = TRAIT_DIR / "trait_presets.json"
PRESETS_PATH = persistent_json_path("trait_presets.json", BUNDLED_PRESETS_PATH)
TRAIT_CHANGELOG_PATH = TRAIT_DIR / "TRAIT_PROGRESS_CHANGELOG.md"

# Official GW2 API specialization IDs. This small index is deliberately kept in
# code so the cache can always be rebuilt from the live API without hand-editing
# all trait names/descriptions.
THIEF_SPECIALIZATIONS: dict[int, dict[str, Any]] = {
    28: {"name": "Deadly Arts", "elite": False, "minor": [1279, 1280, 1257], "major": [1245, 1276, 1164, 1169, 1292, 1704, 1291, 1167, 1269]},
    35: {"name": "Critical Strikes", "elite": False, "minor": [1281, 1210, 1282], "major": [1209, 1267, 1268, 1170, 1272, 1299, 1904, 1215, 1702]},
    20: {"name": "Shadow Arts", "elite": False, "minor": [1294, 1136, 1705], "major": [1160, 1293, 1284, 1297, 1130, 1300, 1134, 1135, 1162]},
    54: {"name": "Acrobatics", "elite": False, "minor": [1240, 1234, 1242], "major": [1112, 1289, 1237, 1241, 1192, 1290, 1238, 1295, 1703]},
    44: {"name": "Trickery", "elite": False, "minor": [1137, 1232, 1157], "major": [1159, 1252, 1163, 1277, 1286, 1190, 1187, 1158, 1706]},
    7: {"name": "Daredevil", "elite": True, "minor": [1994, 1887, 1837], "major": [1933, 2023, 1949, 1884, 1893, 1975, 1833, 1964, 2047]},
    58: {"name": "Deadeye", "elite": True, "minor": [2171, 2172, 2084], "major": [2145, 2173, 2136, 2118, 2078, 2160, 2111, 2093, 2146]},
    71: {"name": "Specter", "elite": True, "minor": [2184, 2272, 2280], "major": [2284, 2299, 2275, 2290, 2288, 2285, 2264, 2300, 2289]},
    77: {"name": "Antiquary", "elite": True, "minor": [2403, 2337, 2362], "major": [2423, 2365, 2346, 2400, 2431, 2350, 2409, 2393, 2348]},
}

ALL_TRAIT_IDS = sorted({trait_id for spec in THIEF_SPECIALIZATIONS.values() for trait_id in spec["minor"] + spec["major"]})


def _request_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "GW2-DPS-Coach/trait-sync"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def sync_trait_cache() -> dict[str, Any]:
    """Fetch current official API records and store an editable local snapshot."""
    TRAIT_DIR.mkdir(parents=True, exist_ok=True)
    traits: list[dict[str, Any]] = []
    # The API supports comma-separated IDs. Keep batches modest for reliability.
    for start in range(0, len(ALL_TRAIT_IDS), 50):
        batch = ALL_TRAIT_IDS[start:start + 50]
        traits.extend(_request_json("https://api.guildwars2.com/v2/traits?ids=" + ",".join(map(str, batch))))

    specs: list[dict[str, Any]] = []
    for spec_id in THIEF_SPECIALIZATIONS:
        specs.append(_request_json(f"https://api.guildwars2.com/v2/specializations/{spec_id}"))

    payload = {
        "source": "Official Guild Wars 2 API",
        "api": "https://api.guildwars2.com/v2/traits",
        "wiki": "https://wiki.guildwars2.com/wiki/List_of_thief_traits",
        "specializations": specs,
        "traits": traits,
    }
    CACHE_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def _fallback_payload() -> dict[str, Any]:
    traits = []
    for spec_id, spec in THIEF_SPECIALIZATIONS.items():
        for trait_id in spec["minor"] + spec["major"]:
            traits.append({
                "id": trait_id,
                "name": f"Trait {trait_id}",
                "description": "Official details have not been synchronized on this PC yet.",
                "icon": "",
                "facts": [],
                "traited_facts": [],
                "specialization": spec_id,
                "tier": 0,
                "slot": "Minor" if trait_id in spec["minor"] else "Major",
            })
    specs = [
        {"id": spec_id, "name": spec["name"], "elite": spec["elite"], "minor_traits": spec["minor"], "major_traits": spec["major"]}
        for spec_id, spec in THIEF_SPECIALIZATIONS.items()
    ]
    return {"source": "Bundled ID index (sync required)", "specializations": specs, "traits": traits}


def load_trait_data(auto_sync: bool = True) -> tuple[dict[str, Any], str | None]:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8")), None
        except (json.JSONDecodeError, OSError):
            pass
    if auto_sync:
        try:
            return sync_trait_cache(), None
        except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            return _fallback_payload(), str(exc)
    return _fallback_payload(), "Trait cache has not been synchronized."


def load_effect_overrides() -> dict[str, Any]:
    if not OVERRIDES_PATH.exists():
        return {}
    try:
        return json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def load_presets() -> dict[str, Any]:
    return load_json_dict(PRESETS_PATH)


def save_presets(presets: dict[str, Any]) -> None:
    write_json_dict(PRESETS_PATH, presets)


def _trait_map(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {int(item["id"]): item for item in payload.get("traits", []) if "id" in item}


def _spec_map(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {int(item["id"]): item for item in payload.get("specializations", []) if "id" in item}


def _wiki_url(name: str) -> str:
    return "https://wiki.guildwars2.com/wiki/" + name.replace(" ", "_")


def _clean_text(text: str) -> str:
    """Remove API/wiki presentation markup while preserving readable text."""
    value = html.unescape(text or "")
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"c=@[a-zA-Z_]+", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _trait_effect_parts(trait_id: int, overrides: dict[str, Any]) -> list[dict[str, Any]]:
    """Return effect-level implementation records for one trait.

    Existing override data remains the source of truth. Static stats/modifiers are
    represented separately from trigger/event packets so mixed traits are never
    incorrectly labelled as wholly implemented or wholly waiting.
    """
    record = overrides.get(str(trait_id), {})
    parts: list[dict[str, Any]] = []

    state_map = {
        "applied_now": "applied",
        "event_engine": "event",
        "needs_implementation": "needs_code",
    }
    for item in record.get("effects", []) or []:
        if not isinstance(item, dict):
            continue
        raw_state = str(item.get("state", "needs_implementation"))
        state = state_map.get(raw_state, raw_state)
        effect_type = str(item.get("type", "effect"))
        if effect_type == "attribute_bonus":
            text = f"{item.get('attribute', 'Attribute')} {float(item.get('value', 0)):+g}"
        elif effect_type == "modifier":
            text = f"{item.get('target', 'Modifier')} {float(item.get('value', 0)):+.1%}"
        elif effect_type == "apply_condition":
            duration = item.get("duration_s")
            duration_text = f" ({duration:g}s)" if isinstance(duration, (int, float)) else ""
            text = f"Apply {item.get('condition', 'condition')}{duration_text} on {item.get('trigger', 'trigger')}"
        elif effect_type == "event_packet":
            text = str(item.get("trigger") or "Triggered effect packet")
        elif effect_type == "calculator_handler":
            text = f"Calculator handler: {item.get('handler', 'mapped effect')}"
        elif effect_type == "life_siphon":
            text = f"Life siphon on {item.get('trigger', 'trigger')}"
        elif effect_type == "gain_venom_stacks":
            text = f"Gain venom stacks on {item.get('trigger', 'trigger')}"
        elif effect_type == "unimplemented":
            text = str(item.get("description") or "Known effect needs implementation")
        else:
            text = str(item.get("description") or item.get("handler") or effect_type.replace("_", " ").title())
        parts.append({"effect": text, "state": state, "kind": effect_type.replace("_", " ").title()})

    for name, amount in record.get("stats", {}).items():
        parts.append({"effect": f"{name} {float(amount):+g}", "state": "applied", "kind": "Static stat"})
    for name, amount in record.get("modifiers", {}).items():
        label = record.get("labels", {}).get(name, name)
        parts.append({"effect": f"{label} {float(amount):+.1%}", "state": "applied", "kind": "Static modifier"})

    # Handler-specific effects that are already connected but may not be duplicated
    # in the generic stats/modifiers dictionaries.
    handler_parts = {
        "dagger_training": [("Power +80; another +80 while a dagger is equipped", "applied", "Conditional stat")],
        "deadly_ambition": [
            ("Condition Damage +180", "applied", "Static stat"),
            ("Apply Poison on a qualifying dual-wield attack", "event", "Triggered condition"),
        ],
        "revealed_training": [("Power bonus scaled by Revealed uptime", "applied", "Assumption-driven stat")],
        "exposed_weakness": [("Strike damage per unique condition on target", "applied", "Assumption-driven modifier")],
        "executioner": [("Strike damage while target is below 50% health", "applied", "Target-state modifier")],
        "keen_observer": [("Critical chance, including the high-health bonus", "applied", "Player-state modifier")],
        "twin_fangs": [("Critical damage and flanking/defiant critical chance", "applied", "State modifier")],
        "practiced_tolerance": [("Convert 10% of Precision into Ferocity", "applied", "Stat conversion")],
        "deadly_aim": [("Weapon-specific strike damage", "applied", "Weapon modifier")],
        "ferocious_strikes": [("Critical damage while target is above 50% health", "applied", "Target-state modifier")],
        "no_quarter": [
            ("Average Ferocity while Fury is active", "applied", "Boon-uptime stat"),
            ("Extend Fury after critical hits", "event", "Critical-hit event"),
        ],
        "leeching_venoms": [
            ("Life-siphon damage and healing on consumed venom strikes", "applied", "Venom calculation"),
            ("Gain extra venom stacks when entering or leaving stealth", "event", "Stealth event"),
        ],
        "one_in_the_chamber": [("Damage bonus to matching stolen skills", "applied", "Skill-specific modifier")],
        "unhindered_combatant": [("Average incoming damage reduction from configured uptime", "applied", "Assumption-driven defense")],
        "invigorating_precision": [("Healing from critical-hit damage", "applied", "Critical-hit calculation")],
    }
    for effect_text, state, kind in handler_parts.get(record.get("handler"), []):
        if not any(part["effect"] == effect_text for part in parts):
            parts.append({"effect": effect_text, "state": state, "kind": kind})

    event_trigger = record.get("event_trigger")
    event_packet = record.get("event_packet") or []
    if event_trigger or event_packet:
        packet_text = " · ".join(
            str(item.get("effect") or item.get("type") or item.get("name") or "Event effect")
            for item in event_packet[:4] if isinstance(item, dict)
        )
        label = str(event_trigger or packet_text or "Triggered effect")
        if packet_text and packet_text.lower() not in label.lower():
            label = f"{label} ({packet_text})"
        if not any(part["state"] == "event" and part["effect"] == label for part in parts):
            parts.append({"effect": label, "state": "event", "kind": "Event packet"})

    notes = record.get("notes")
    status = record.get("status", "data_only")
    if not parts:
        if status == "data_only":
            parts.append({"effect": str(notes or "Calculator effect still needs implementation"), "state": "needs_code", "kind": "Unimplemented"})
        elif status in {"event_ready", "partial"}:
            parts.append({"effect": str(notes or "Requires combat-event timing"), "state": "event", "kind": "Event packet"})
        else:
            parts.append({"effect": str(notes or "Effect is mapped through a calculator handler"), "state": "applied", "kind": "Calculator handler"})
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for part in parts:
        key = (str(part.get("effect", "")), str(part.get("state", "")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(part)
    return deduped


def _effect_status(trait_id: int, overrides: dict[str, Any]) -> tuple[str, str]:
    parts = _trait_effect_parts(trait_id, overrides)
    states = {part["state"] for part in parts}
    if states == {"applied"}:
        return "✅", "Applied now: every currently modelled effect feeds the calculator."
    if "applied" in states and "event" in states:
        return "🟡", "Mixed trait: passive/assumption effects are applied now; triggered effects are preserved for the event engine."
    if states <= {"event"}:
        return "⏳", "Waiting for event engine: the trigger and effect packet are preserved, but encounter frequency/timing is not simulated yet."
    if "needs_code" in states:
        return "⚪", "Needs implementation: official information exists, but at least one effect is not connected yet."
    return "🟡", "Partially connected. Open Trait details for the effect-level status."


_PERSISTENT_TRAIT_SELECTION_KEY = "persistent_trait_selection"


def _selection_from_widget_state() -> dict[str, Any]:
    """Snapshot rendered trait widgets into ordinary session state."""
    result: dict[str, Any] = {"lines": []}
    for line in range(1, 4):
        result["lines"].append({
            "specialization": st.session_state.get(f"trait_line_{line}_spec", "None"),
            "major_traits": [
                st.session_state.get(f"trait_line_{line}_tier_{tier}")
                for tier in range(3)
            ],
        })
    return result


def _persist_trait_selection() -> None:
    """Copy rendered widget values into durable, non-widget session state."""
    st.session_state[_PERSISTENT_TRAIT_SELECTION_KEY] = _selection_from_widget_state()


def _specialization_changed(line: int) -> None:
    """Normalize a changed specialization before persisting the selection."""
    raw = st.session_state.get(f"trait_line_{line}_spec", "None")
    if raw not in {None, "None"}:
        try:
            _ensure_line_trait_defaults(line, int(raw))
        except (KeyError, TypeError, ValueError):
            st.session_state[f"trait_line_{line}_spec"] = "None"
            for tier in range(3):
                st.session_state[f"trait_line_{line}_tier_{tier}"] = None
    else:
        for tier in range(3):
            st.session_state[f"trait_line_{line}_tier_{tier}"] = None
    _persist_trait_selection()


def _restore_trait_widget_state() -> None:
    """Restore widget keys from the durable selection snapshot.

    Streamlit deletes widget-owned keys when their page is not rendered. A key
    can also survive briefly with a stale value during page navigation, so the
    durable snapshot must be authoritative and is copied unconditionally before
    any Traits widgets are created.
    """
    selection = st.session_state.get(_PERSISTENT_TRAIT_SELECTION_KEY)
    if not isinstance(selection, dict):
        return
    raw_lines = selection.get("lines", [])
    for line in range(1, 4):
        line_data = raw_lines[line - 1] if line - 1 < len(raw_lines) and isinstance(raw_lines[line - 1], dict) else {}
        spec = str(line_data.get("specialization", "None"))
        st.session_state[f"trait_line_{line}_spec"] = spec
        majors = list(line_data.get("major_traits", []) or [])[:3]
        majors += [None] * (3 - len(majors))
        for tier, trait_id in enumerate(majors):
            st.session_state[f"trait_line_{line}_tier_{tier}"] = trait_id


def selected_trait_ids() -> list[int]:
    selection = _current_selection() if "_current_selection" in globals() else None
    if isinstance(selection, dict):
        selected: list[int] = []
        for line_data in selection.get("lines", []):
            if not isinstance(line_data, dict):
                continue
            spec_id = line_data.get("specialization")
            if not spec_id or spec_id == "None":
                continue
            spec_id_int = int(spec_id)
            selected.extend(THIEF_SPECIALIZATIONS[spec_id_int]["minor"])
            for value in line_data.get("major_traits", []):
                if value:
                    selected.append(int(value))
        return selected

    # Startup fallback before helper definitions are available.
    selected = []
    for line in range(1, 4):
        spec_id = st.session_state.get(f"trait_line_{line}_spec")
        if not spec_id or spec_id == "None":
            continue
        spec_id_int = int(spec_id)
        selected.extend(THIEF_SPECIALIZATIONS[spec_id_int]["minor"])
        for tier in range(3):
            value = st.session_state.get(f"trait_line_{line}_tier_{tier}")
            if value:
                selected.append(int(value))
    return selected


def _equipped_weapon_names() -> set[str]:
    """Return the weapon types currently selected in the neutral combat panel."""
    mode = st.session_state.get("gear_weapon_mode", "Two-handed weapon")
    if mode == "Two-handed weapon":
        return {str(st.session_state.get("gear_twohand_weapon", ""))}
    return {
        str(st.session_state.get("gear_mainhand_weapon", "")),
        str(st.session_state.get("gear_offhand_weapon", "")),
    }


def _official_fact_summary(trait: dict[str, Any]) -> list[str]:
    """Convert API facts into concise human-readable value lines."""
    rows: list[str] = []
    for fact in trait.get("facts", []) or []:
        fact_type = fact.get("type")
        label = str(fact.get("text") or fact.get("target") or fact.get("status") or "Effect")
        if fact_type == "AttributeAdjust":
            rows.append(f"{label}: +{fact.get('value', 0):g}")
        elif fact_type == "Percent":
            rows.append(f"{label}: +{fact.get('percent', 0):g}%")
        elif fact_type == "Number":
            rows.append(f"{label}: {fact.get('value', 0):g}")
        elif fact_type == "Recharge":
            rows.append(f"Recharge: {fact.get('value', 0):g}s")
        elif fact_type == "Buff":
            status = fact.get("status", "Effect")
            duration = fact.get("duration", 0)
            count = fact.get("apply_count", 1)
            count_text = f" x{count}" if count not in {None, 1} else ""
            duration_text = f" ({duration:g}s)" if duration else ""
            rows.append(f"{status}{count_text}{duration_text}")
    # API records can contain multiple game-mode variants. Keep the values visible,
    # but remove exact duplicates so the UI remains compact.
    return list(dict.fromkeys(rows))


def calculate_selected_trait_effects() -> tuple[dict[str, float], dict[str, float], list[dict[str, Any]]]:
    """Calculate verified trait effects and return a transparent source audit.

    Effects are only applied when their condition can be resolved from current
    calculator state. Every selected trait still receives an audit row, even when
    it is waiting for a future skill/state/rotation system.
    """
    overrides = load_effect_overrides()
    payload, _ = load_trait_data(auto_sync=False)
    traits = _trait_map(payload)
    stats: dict[str, float] = {}
    modifiers: dict[str, float] = {}
    sources: list[dict[str, Any]] = []
    registry = EffectRegistry()
    weapons = _equipped_weapon_names()
    fury_uptime = (
        max(0.0, min(1.0, float(st.session_state.get("gear_fury_uptime", 100)) / 100.0))
        if st.session_state.get("gear_fury", False) else 0.0
    )
    player_health = max(0.0, min(100.0, float(st.session_state.get("trait_player_health_pct", 100.0))))
    target_health = max(0.0, min(100.0, float(st.session_state.get("trait_target_health_pct", 100.0))))
    unique_conditions = max(0.0, min(14.0, float(st.session_state.get("trait_unique_conditions", 10.0))))
    flanking_or_defiant = bool(st.session_state.get("trait_flanking_or_defiant", True))
    revealed_uptime = max(0.0, min(1.0, float(st.session_state.get("trait_revealed_uptime", 0.0)) / 100.0))
    stealth_uptime = max(0.0, min(1.0, float(st.session_state.get("trait_stealth_uptime", 0.0)) / 100.0))
    barrier_uptime = max(0.0, min(1.0, float(st.session_state.get("trait_barrier_uptime", 0.0)) / 100.0))
    combat_high_stacks = max(0.0, min(10.0, float(st.session_state.get("trait_combat_high_stacks", 0.0))))
    lead_attacks_bonus = max(0.0, min(0.15, float(st.session_state.get("trait_lead_attacks_bonus_pct", 0.0)) / 100.0))
    weakened_target_uptime = max(0.0, min(1.0, float(st.session_state.get("trait_weakened_target_uptime", 0.0)) / 100.0))
    nearby_foe_uptime = max(0.0, min(1.0, float(st.session_state.get("trait_nearby_foe_uptime", 0.0)) / 100.0))
    endurance_not_full_uptime = max(0.0, min(1.0, float(st.session_state.get("trait_endurance_not_full_uptime", 0.0)) / 100.0))
    marked_target_uptime = max(0.0, min(1.0, float(st.session_state.get("trait_marked_target_uptime", 0.0)) / 100.0))
    unique_boons = max(0.0, min(12.0, float(st.session_state.get("trait_unique_boons", 0.0))))
    quickness_uptime = (
        max(0.0, min(1.0, float(st.session_state.get("gear_quickness_uptime", 100)) / 100.0))
        if st.session_state.get("gear_quickness", False) else 0.0
    )
    fluid_strikes_uptime = max(0.0, min(1.0, float(st.session_state.get("trait_fluid_strikes_uptime", 0.0)) / 100.0))
    bounding_dodger_uptime = max(0.0, min(1.0, float(st.session_state.get("trait_bounding_dodger_uptime", 0.0)) / 100.0))
    exhilarating_ephemera_uptime = max(0.0, min(1.0, float(st.session_state.get("trait_exhilarating_ephemera_uptime", 0.0)) / 100.0))
    lotus_training_uptime = max(0.0, min(1.0, float(st.session_state.get("trait_lotus_training_uptime", 0.0)) / 100.0))
    unhindered_combatant_uptime = max(0.0, min(1.0, float(st.session_state.get("trait_unhindered_combatant_uptime", 0.0)) / 100.0))

    for trait_id in selected_trait_ids():
        trait = traits.get(trait_id, {"name": f"Trait {trait_id}", "facts": []})
        record = overrides.get(str(trait_id), {})
        status = record.get("status", "data_only")
        stats_before = dict(stats)
        modifiers_before = dict(modifiers)
        applied: list[str] = []
        pending: list[str] = []
        destinations: set[str] = set()

        # Straight data-driven effects.
        if status in {"implemented", "assumption", "partial"}:
            for name, amount in record.get("stats", {}).items():
                value = float(amount)
                stats[name] = stats.get(name, 0.0) + value
                applied.append(f"{name} {value:+g}")
                destinations.add("Resulting stats")
            for name, amount in record.get("modifiers", {}).items():
                value = float(amount)
                modifiers[name] = modifiers.get(name, 0.0) + value
                applied.append(f"{record.get('labels', {}).get(name, name)} {value:+.1%}")
                destinations.add(record.get("destinations", {}).get(name, "Damage / duration engine"))

        # Verified conditional handlers.
        handler = record.get("handler")
        if handler == "dagger_training":
            stats["Power"] = stats.get("Power", 0.0) + 80.0
            applied.append("Power +80")
            if "Dagger" in weapons:
                stats["Power"] += 80.0
                applied.append("Power +80 (dagger equipped)")
            else:
                pending.append("Additional +80 Power activates when a dagger is equipped")
            destinations.add("Resulting stats")
        elif handler == "deadly_ambition":
            stats["Condition Damage"] = stats.get("Condition Damage", 0.0) + 180.0
            applied.append("Condition Damage +180")
            destinations.add("Resulting stats")
            pending.append("Poison application on dual-wield attacks requires the skill-event engine")
        elif handler == "revealed_training":
            amount = 80.0 + 120.0 * revealed_uptime
            stats["Power"] = stats.get("Power", 0.0) + amount
            applied.append(f"Power +{amount:g} average ({revealed_uptime:.0%} Revealed uptime)")
            destinations.add("Resulting stats")
        elif handler == "exposed_weakness":
            amount = 0.02 * unique_conditions
            modifiers["additive_strike"] = modifiers.get("additive_strike", 0.0) + amount
            applied.append(f"Strike damage +{amount:.1%} ({unique_conditions} unique conditions)")
            destinations.add("Strike modifier engine")
        elif handler == "executioner":
            if target_health < 50.0:
                modifiers["multiplicative_strike"] = modifiers.get("multiplicative_strike", 0.0) + 0.20
                applied.append("Strike damage ×1.20 (target below 50% health)")
                destinations.add("Strike modifier engine")
            else:
                pending.append("+20% strike damage activates below 50% target health")
        elif handler == "keen_observer":
            amount = 0.05 + (0.05 if player_health > 90.0 else 0.0)
            modifiers["Critical Chance"] = modifiers.get("Critical Chance", 0.0) + amount
            applied.append(f"Critical chance +{amount:.1%}")
            destinations.add("Critical chance")
        elif handler == "twin_fangs":
            crit_damage = 0.05 + (0.02 if player_health > 50.0 else 0.0)
            modifiers["Critical Damage"] = modifiers.get("Critical Damage", 0.0) + crit_damage
            applied.append(f"Critical damage +{crit_damage:.1%}")
            if flanking_or_defiant:
                modifiers["Critical Chance"] = modifiers.get("Critical Chance", 0.0) + 0.07
                applied.append("Critical chance +7% (flanking/defiant)")
            else:
                pending.append("+7% critical chance requires flanking, side attacks, or a defiant target")
            destinations.update({"Critical chance", "Critical damage"})
        elif handler == "practiced_tolerance":
            # Precision is resolved after static gear/trait stats. Store a conversion ratio.
            modifiers["precision_to_ferocity"] = modifiers.get("precision_to_ferocity", 0.0) + 0.10
            applied.append("Ferocity = 10% of final Precision")
            destinations.add("Resulting stats / Critical damage")
        elif handler == "deadly_aim":
            if "Pistol" in weapons or "Harpoon Gun" in weapons:
                modifiers["additive_strike"] = modifiers.get("additive_strike", 0.0) + 0.10
                applied.append("Pistol/harpoon-gun strike damage +10%")
                destinations.add("Strike modifier engine")
            else:
                pending.append("+10% strike damage requires a pistol or harpoon gun")
        elif handler == "ferocious_strikes":
            if target_health > 50.0:
                modifiers["Critical Damage"] = modifiers.get("Critical Damage", 0.0) + 0.10
                applied.append("Critical damage +10% (target above 50% health)")
                destinations.add("Critical damage")
            else:
                pending.append("+10% critical damage requires target above 50% health")
        elif handler == "no_quarter":
            if fury_uptime > 0:
                amount = 250.0 * fury_uptime
                stats["Ferocity"] = stats.get("Ferocity", 0.0) + amount
                applied.append(f"Ferocity +{amount:g} average ({fury_uptime:.0%} Fury uptime)")
                destinations.add("Critical damage / Effective Power")
            else:
                pending.append("+250 Ferocity requires Fury")
            pending.append("Fury extension on critical hit requires the skill-event engine")
        elif handler == "hidden_killer":
            amount = stealth_uptime
            modifiers["Critical Chance"] = modifiers.get("Critical Chance", 0.0) + amount
            if amount > 0:
                applied.append(f"Critical chance +{amount:.1%} average ({stealth_uptime:.0%} stealth/linger uptime)")
                destinations.add("Critical chance")
            else:
                pending.append("+100% critical chance requires stealth/linger uptime")
        elif handler == "invigorating_precision":
            healing_ratio = 0.04 + 0.02 * fury_uptime
            modifiers["critical_damage_healing"] = modifiers.get("critical_damage_healing", 0.0) + healing_ratio
            applied.append(f"Healing = {healing_ratio:.1%} of outgoing critical-hit damage")
            destinations.add("Healing audit")
        elif handler == "preparedness":
            stats["Expertise"] = stats.get("Expertise", 0.0) + 150.0
            applied.append("Expertise +150")
            destinations.add("Resulting stats / Condition duration")
            pending.append("Maximum initiative +3 is stored for the future initiative engine")
        elif handler == "lead_attacks":
            if lead_attacks_bonus > 0:
                modifiers["additive_strike"] = modifiers.get("additive_strike", 0.0) + lead_attacks_bonus
                modifiers["global_condition"] = modifiers.get("global_condition", 0.0) + lead_attacks_bonus
                applied.append(f"All damage +{lead_attacks_bonus:.1%} average")
                destinations.update({"Strike modifier engine", "Condition modifier engine"})
            else:
                pending.append("Set average Lead Attacks bonus to activate up to +15% all damage")
            pending.append("Steal recharge reduction requires the skill-cooldown engine")
        elif handler == "deadly_ambush":
            modifiers["bleeding"] = modifiers.get("bleeding", 0.0) + 0.25
            applied.append("Bleeding damage +25%")
            destinations.add("Bleeding condition modifier")
            pending.append("Bleeding applied by Steal requires the skill-event engine")
        elif handler == "swindlers_equilibrium":
            stats["Power"] = stats.get("Power", 0.0) + 120.0
            applied.append("Power +120")
            if "Sword" in weapons or "Spear" in weapons:
                stats["Power"] += 120.0
                applied.append("Power +120 (sword/spear equipped)")
            else:
                pending.append("Additional +120 Power requires sword or underwater spear")
            destinations.add("Resulting stats")
            pending.append("Steal recharge on evade requires the skill-event engine")
        elif handler == "weakening_strikes":
            if weakened_target_uptime > 0:
                amount = 0.10 * weakened_target_uptime
                modifiers["additive_strike"] = modifiers.get("additive_strike", 0.0) + amount
                modifiers["incoming_strike_reduction"] = modifiers.get("incoming_strike_reduction", 0.0) + amount
                applied.append(f"Strike damage +{amount:.1%} average vs weakened target")
                applied.append(f"Incoming strike damage −{amount:.1%} average")
                destinations.update({"Strike modifier engine", "Survivability audit"})
            else:
                pending.append("Set weakened-target uptime to activate its damage effects")
            pending.append("Weakness application after dodge requires the skill-event engine")
        elif handler == "marauders_resilience":
            modifiers["power_to_vitality"] = modifiers.get("power_to_vitality", 0.0) + 0.07
            applied.append("Vitality = 7% of final Power")
            destinations.add("Resulting stats / Health")
            if nearby_foe_uptime > 0:
                reduction = 0.10 * nearby_foe_uptime
                modifiers["incoming_strike_reduction"] = modifiers.get("incoming_strike_reduction", 0.0) + reduction
                applied.append(f"Incoming strike damage −{reduction:.1%} average (nearby foe)")
                destinations.add("Survivability audit")
            else:
                pending.append("Set nearby-foe uptime to model the 10% damage reduction")
        elif handler == "staff_master":
            stats["Power"] = stats.get("Power", 0.0) + 120.0
            applied.append("Power +120")
            if "Staff" in weapons:
                stats["Power"] += 120.0
                applied.append("Power +120 (staff equipped)")
            else:
                pending.append("Additional +120 Power requires staff")
            destinations.add("Resulting stats")
            pending.append("Endurance per initiative spent requires initiative events")
        elif handler == "havoc_specialist":
            if endurance_not_full_uptime > 0:
                amount = 0.15 * endurance_not_full_uptime
                modifiers["additive_strike"] = modifiers.get("additive_strike", 0.0) + amount
                applied.append(f"Strike damage +{amount:.1%} average (endurance not full)")
                destinations.add("Strike modifier engine")
            else:
                pending.append("Set endurance-not-full uptime to activate up to +15% strike damage")
        elif handler == "fluid_strikes":
            amount = 0.10 * fluid_strikes_uptime
            if amount > 0:
                modifiers["additive_strike"] = modifiers.get("additive_strike", 0.0) + amount
                applied.append(f"Strike damage +{amount:.1%} average ({fluid_strikes_uptime:.0%} uptime)")
                destinations.add("Strike modifier engine")
            else:
                pending.append("Set Fluid Strikes uptime to model its +10% strike damage buff")
            pending.append("Automatic uptime requires movement-skill and shadowstep events")
        elif handler == "lotus_training":
            amount = 0.15 * lotus_training_uptime
            if amount > 0:
                modifiers["global_condition"] = modifiers.get("global_condition", 0.0) + amount
                applied.append(f"Condition damage +{amount:.1%} average ({lotus_training_uptime:.0%} uptime)")
                destinations.add("Condition modifier engine")
            else:
                pending.append("Set Lotus Training uptime to model its +15% condition damage buff")
            pending.append("Impaling Lotus damage and conditions require dodge/skill events")
        elif handler == "bounding_dodger":
            amount = 0.15 * bounding_dodger_uptime
            if amount > 0:
                modifiers["additive_strike"] = modifiers.get("additive_strike", 0.0) + amount
                applied.append(f"Strike damage +{amount:.1%} average ({bounding_dodger_uptime:.0%} uptime)")
                destinations.add("Strike modifier engine")
            else:
                pending.append("Set Bounding Dodger uptime to model its +15% strike damage buff")
            pending.append("Bound impact damage requires dodge/skill events")
        elif handler == "unhindered_combatant":
            if unhindered_combatant_uptime > 0:
                reduction = 0.10 * unhindered_combatant_uptime
                modifiers["incoming_strike_reduction"] = modifiers.get("incoming_strike_reduction", 0.0) + reduction
                modifiers["incoming_condition_reduction"] = modifiers.get("incoming_condition_reduction", 0.0) + reduction
                applied.append(f"Incoming strike/condition damage −{reduction:.1%} average ({unhindered_combatant_uptime:.0%} uptime)")
                destinations.add("Survivability audit")
            else:
                pending.append("Set Unhindered Combatant uptime to model its 10% damage reduction")
            pending.append("Dash, condition removal and exhaustion require dodge events")
        elif handler == "exhilarating_ephemera":
            amount = 0.10 * exhilarating_ephemera_uptime
            if amount > 0:
                modifiers["additive_strike"] = modifiers.get("additive_strike", 0.0) + amount
                applied.append(f"Strike damage +{amount:.1%} average ({exhilarating_ephemera_uptime:.0%} uptime)")
                destinations.add("Strike modifier engine")
            else:
                pending.append("Set Exhilarating Ephemera uptime to model its +10% strike damage buff")
            pending.append("Automatic uptime requires artifact-use events")
        elif handler == "leeching_venoms":
            modifiers["leeching_venoms"] = modifiers.get("leeching_venoms", 0.0) + 1.0
            applied.append("Spider Venom strikes siphon 320 + 0.033 × Power damage")
            applied.append("Spider Venom strikes heal 325 + 0.20 × Healing Power")
            destinations.add("Spider Venom calculation audit")
            pending.append("Three extra Spider Venom stacks per stealth enter/exit cycle require stealth events")
        elif handler == "dark_sentry":
            modifiers["outgoing_healing_to_others"] = modifiers.get("outgoing_healing_to_others", 0.0) + 0.20
            applied.append("Outgoing healing to allies +20%")
            destinations.add("Healing audit")
            pending.append("Rot Wallow Venom applications require barrier and ally-hit events")
        elif handler == "one_in_the_chamber":
            modifiers["stolen_skill_damage"] = modifiers.get("stolen_skill_damage", 0.0) + 0.25
            applied.append("Stolen-skill damage +25%")
            destinations.add("Skill Library / stolen skills")
            pending.append("Cantrip-generated stolen skills require cantrip and mark events")
        elif handler == "iron_sight":
            if marked_target_uptime > 0:
                bonus = 0.10 * marked_target_uptime
                reduction = 0.15 * marked_target_uptime
                modifiers["additive_strike"] = modifiers.get("additive_strike", 0.0) + bonus
                modifiers["incoming_strike_reduction"] = modifiers.get("incoming_strike_reduction", 0.0) + reduction
                applied.append(f"Strike damage +{bonus:.1%} average vs marked target")
                applied.append(f"Incoming strike damage −{reduction:.1%} average from marked target")
                destinations.update({"Strike modifier engine", "Survivability audit"})
            else:
                pending.append("Set marked-target uptime to activate Iron Sight")
        elif handler == "silent_scope":
            stats["Precision"] = stats.get("Precision", 0.0) + 120.0
            applied.append("Precision +120")
            destinations.add("Resulting stats / Critical chance")
            pending.append("Stealth-attack access after dodge requires malice and skill-state logic")
        elif handler == "premeditation":
            stats["Concentration"] = stats.get("Concentration", 0.0) + 180.0
            applied.append("Concentration +180")
            if unique_boons > 0:
                amount = 0.01 * unique_boons
                modifiers["additive_strike"] = modifiers.get("additive_strike", 0.0) + amount
                applied.append(f"Strike damage +{amount:.1%} ({unique_boons} unique boons)")
                destinations.add("Strike modifier engine")
            else:
                pending.append("Set unique boons to activate +1% strike damage per boon")
            destinations.add("Resulting stats / Boon duration")
        elif handler == "be_quick_or_be_killed":
            if quickness_uptime > 0:
                amount = 200.0 * quickness_uptime
                stats["Power"] = stats.get("Power", 0.0) + amount
                stats["Precision"] = stats.get("Precision", 0.0) + amount
                applied.append(f"Power +{amount:g} average ({quickness_uptime:.0%} Quickness uptime)")
                applied.append(f"Precision +{amount:g} average ({quickness_uptime:.0%} Quickness uptime)")
                destinations.add("Resulting stats")
            else:
                pending.append("+200 Power and Precision require Quickness")
            pending.append("Quickness granted on marking requires the mark/skill-event engine")
        elif handler == "second_opinion":
            stats["Condition Damage"] = stats.get("Condition Damage", 0.0) + 90.0
            applied.append("Condition Damage +90")
            if "Scepter" in weapons:
                stats["Condition Damage"] += 90.0
                applied.append("Condition Damage +90 (scepter equipped)")
            else:
                pending.append("Additional +90 Condition Damage requires scepter")
            modifiers["condition_to_healing_power"] = modifiers.get("condition_to_healing_power", 0.0) + 0.07
            applied.append("Healing Power = 7% of final Condition Damage")
            destinations.update({"Resulting stats", "Healing Power"})
        elif handler == "strength_of_shadows":
            modifiers["vitality_to_expertise"] = modifiers.get("vitality_to_expertise", 0.0) + 0.13
            modifiers["torment"] = modifiers.get("torment", 0.0) + 0.20
            applied.append("Expertise = 13% of final Vitality")
            applied.append("Torment damage +20%")
            destinations.update({"Resulting stats / Condition duration", "Torment condition modifier"})
        elif handler == "enterprising_aristocrat":
            if barrier_uptime > 0:
                modifiers["incoming_strike_reduction"] = modifiers.get("incoming_strike_reduction", 0.0) + 0.10 * barrier_uptime
                modifiers["incoming_condition_reduction"] = modifiers.get("incoming_condition_reduction", 0.0) + 0.10 * barrier_uptime
                applied.append(f"Incoming strike/condition damage −{0.10 * barrier_uptime:.1%} average")
                destinations.add("Survivability audit")
            else:
                pending.append("Damage reduction requires barrier uptime")
            pending.append("Barrier and initiative on artifact use require the artifact-event engine")
        elif handler == "combat_high":
            strike_amount = 0.03 * combat_high_stacks
            condition_amount = 0.02 * combat_high_stacks
            if combat_high_stacks > 0:
                modifiers["additive_strike"] = modifiers.get("additive_strike", 0.0) + strike_amount
                modifiers["global_condition"] = modifiers.get("global_condition", 0.0) + condition_amount
                applied.append(f"Strike damage +{strike_amount:.1%} ({combat_high_stacks:g} stacks)")
                applied.append(f"Condition damage +{condition_amount:.1%} ({combat_high_stacks:g} stacks)")
                destinations.update({"Strike modifier engine", "Condition modifier engine"})
            else:
                pending.append("Set average Combat High stacks to activate its damage bonus")
        elif record.get("event_packet_ready"):
            applied.append("Verified event packet and PvE values registered")
            destinations.add("Future combat-event / rotation engine")

        event_packet = record.get("event_packet", [])
        if event_packet:
            trigger = str(record.get("event_trigger", "Combat event"))
            pending.append(f"Event-ready: {trigger}")
            destinations.add("Future combat-event / rotation engine")

        notes = record.get("notes", [])
        if isinstance(notes, str):
            notes = [notes]
        pending.extend(str(note) for note in notes if note)
        if not applied and not pending:
            pending.append("Official values loaded; calculator mapping not implemented yet")

        # Convert the resolved handler output into structured effects. This
        # registry is now the canonical source attribution layer; the legacy
        # dictionaries are generated from it for the existing damage formulas.
        trait_name = trait.get("name", f"Trait {trait_id}")
        destination_text = ", ".join(sorted(destinations))
        for target in set(stats_before) | set(stats):
            delta = float(stats.get(target, 0.0)) - float(stats_before.get(target, 0.0))
            if abs(delta) > 1e-12:
                registry.register_stat(
                    trait_name, target, delta, source_id=trait_id,
                    destination=destination_text or "Resulting stats",
                )
        conversion_targets = {
            "precision_to_ferocity", "power_to_vitality",
            "vitality_to_expertise", "condition_to_healing_power",
        }
        for target in set(modifiers_before) | set(modifiers):
            delta = float(modifiers.get(target, 0.0)) - float(modifiers_before.get(target, 0.0))
            if abs(delta) <= 1e-12:
                continue
            if target in conversion_targets:
                registry.register_conversion(
                    trait_name, target, delta, source_id=trait_id,
                    destination=destination_text or "Resulting stats",
                )
            else:
                registry.register_modifier(
                    trait_name, target, delta, source_id=trait_id,
                    destination=destination_text or "Damage engine",
                )

        sources.append({
            "trait_id": trait_id,
            "trait_name": trait.get("name", f"Trait {trait_id}"),
            "status": status,
            "applied": applied,
            "pending": list(dict.fromkeys(pending)),
            "destinations": sorted(destinations),
            "official_values": _official_fact_summary(trait),
        })
    canonical_stats, canonical_modifiers = registry.to_legacy()
    st.session_state["trait_effect_registry"] = registry.serialize()
    return canonical_stats, canonical_modifiers, sources


def current_trait_effect_registry() -> EffectRegistry:
    """Return the currently resolved structured trait effects."""
    return EffectRegistry.deserialize(st.session_state.get("trait_effect_registry", []))


def _current_selection() -> dict[str, Any]:
    # Never reconstruct shared state from widget keys here. On any page other
    # than Traits those keys may be absent, partially cleaned up, or stale.
    # Callbacks and the end of render_traits_page keep this durable snapshot
    # current, and every calculator reads only this snapshot.
    stored = st.session_state.get(_PERSISTENT_TRAIT_SELECTION_KEY)
    if isinstance(stored, dict):
        return stored
    return {
        "lines": [
            {"specialization": "None", "major_traits": [None, None, None]}
            for _ in range(3)
        ]
    }


def _apply_selection(selection: dict[str, Any]) -> None:
    normalized: dict[str, Any] = {"lines": []}
    for line in range(1, 4):
        raw_lines = selection.get("lines", []) if isinstance(selection, dict) else []
        line_data = raw_lines[line - 1] if line - 1 < len(raw_lines) and isinstance(raw_lines[line - 1], dict) else {}
        majors = list(line_data.get("major_traits", []) or [])[:3]
        majors += [None] * (3 - len(majors))
        normalized_line = {
            "specialization": str(line_data.get("specialization", "None")),
            "major_traits": majors,
        }
        normalized["lines"].append(normalized_line)
        st.session_state[f"trait_line_{line}_spec"] = normalized_line["specialization"]
        for tier, trait_id in enumerate(majors):
            st.session_state[f"trait_line_{line}_tier_{tier}"] = trait_id
    st.session_state[_PERSISTENT_TRAIT_SELECTION_KEY] = normalized


def current_trait_selection() -> dict[str, Any]:
    """Public shared-state snapshot used by saved builds and future rotation pages."""
    return _current_selection()


def apply_trait_selection(selection: dict[str, Any] | None) -> None:
    """Restore a shared trait selection from a saved build."""
    if isinstance(selection, dict):
        _apply_selection(selection)



def _render_selected_trait_detail(trait: dict[str, Any], status_icon: str, status_help: str) -> None:
    """Render one compact detail card for the currently selected major trait."""
    cols = st.columns([0.12, 0.88], vertical_alignment="center")
    with cols[0]:
        if trait.get("icon"):
            st.image(trait["icon"], width=40)
    with cols[1]:
        st.markdown(f"**{trait.get('name', 'Unknown')}** {status_icon}", help=status_help)
        description = _clean_text(trait.get("description", ""))
        if description:
            st.caption(description)
        st.markdown(f"[GW2 Wiki]({_wiki_url(trait.get('name', ''))})")


def _render_minor_strip(trait: dict[str, Any], status_icon: str, status_help: str) -> None:
    """Render an automatic minor trait as a narrow Snow Crows-style strip."""
    cols = st.columns([0.22, 0.78], vertical_alignment="center")
    with cols[0]:
        if trait.get("icon"):
            st.image(trait["icon"], width=34)
    with cols[1]:
        st.markdown(f"**{trait.get('name', 'Unknown')}** {status_icon}", help=status_help)


def _inject_trait_page_css() -> None:
    st.markdown(
        """
        <style>
        /* Compact, build-editor style trait page. */
        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 10px;
        }
        .trait-spec-label {
            font-size: 0.78rem;
            letter-spacing: .08em;
            text-transform: uppercase;
            opacity: .7;
            margin-bottom: .2rem;
        }
        .trait-tier-label {
            font-size: .78rem;
            font-weight: 700;
            opacity: .75;
            margin-bottom: .15rem;
        }
        .trait-minor-label {
            font-size: .72rem;
            opacity: .6;
            margin-bottom: .2rem;
        }
        .trait-minor-strip {
            display: flex;
            align-items: center;
            gap: .9rem;
            margin-top: .45rem;
            min-height: 34px;
        }
        .trait-minor-icon {
            width: 32px;
            height: 32px;
            object-fit: contain;
            display: block;
            cursor: help;
        }
        div[role="radiogroup"] {
            gap: .15rem !important;
        }
        div[role="radiogroup"] label {
            padding: .38rem .5rem !important;
            border: 1px solid rgba(128,128,128,.22);
            border-radius: 7px;
            margin: 0 !important;
            background: rgba(128,128,128,.035);
        }
        div[role="radiogroup"] label:hover {
            border-color: rgba(255,80,80,.7);
            background: rgba(255,80,80,.06);
        }
        div[role="radiogroup"] label:has(input:checked) {
            border-color: #ff4b4b;
            background: rgba(255,75,75,.12);
        }
        div[role="radiogroup"] p {
            font-size: .84rem !important;
        }
        .trait-selected-card {
            border-top: 1px solid rgba(128,128,128,.22);
            margin-top: .45rem;
            padding-top: .55rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )



def _process_visual_trait_click() -> None:
    """Apply a trait selected from the clickable visual strip."""
    raw = st.query_params.get("trait_click")
    if not raw:
        return
    try:
        line_raw, tier_raw, trait_raw = str(raw).split(":", 2)
        line = int(line_raw)
        tier = int(tier_raw)
        trait_id = int(trait_raw)
        spec_raw = st.session_state.get(f"trait_line_{line}_spec")
        if line not in {1, 2, 3} or tier not in {0, 1, 2} or spec_raw in {None, "None"}:
            raise ValueError("Invalid trait location")
        spec_id = int(spec_raw)
        valid = THIEF_SPECIALIZATIONS[spec_id]["major"][tier * 3:(tier + 1) * 3]
        if trait_id not in valid:
            raise ValueError("Trait does not belong to the selected tier")
        st.session_state[f"trait_line_{line}_tier_{tier}"] = trait_id
    except (ValueError, KeyError, TypeError):
        st.session_state["trait_visual_error"] = "The clicked trait could not be applied. Refresh official trait data and try again."
    st.query_params.clear()
    st.rerun()


def _ensure_line_trait_defaults(line: int, spec_id: int) -> None:
    major = THIEF_SPECIALIZATIONS[spec_id]["major"]
    for tier in range(3):
        key = f"trait_line_{line}_tier_{tier}"
        valid = major[tier * 3:(tier + 1) * 3]
        if st.session_state.get(key) not in valid:
            st.session_state[key] = valid[0]


def _trait_tooltip(trait: dict[str, Any], status_icon: str, status_help: str) -> str:
    name = html.escape(str(trait.get("name", "Unknown trait")))
    description = html.escape(_clean_text(str(trait.get("description", ""))))
    help_text = html.escape(status_help)
    return f"<strong>{name} {status_icon}</strong><span>{description}</span><small>{help_text}</small>"


def _render_clickable_trait_builder(
    traits: dict[int, dict[str, Any]],
    specs: dict[int, dict[str, Any]],
    overrides: dict[str, Any],
) -> None:
    """Render a Snow Crows/Armory-inspired editor whose icons are inputs."""
    blocks: list[str] = []
    active_lines = 0
    for line in range(1, 4):
        raw_spec = st.session_state.get(f"trait_line_{line}_spec")
        if raw_spec in {None, "None"}:
            continue
        active_lines += 1
        spec_id = int(raw_spec)
        _ensure_line_trait_defaults(line, spec_id)
        meta = specs.get(spec_id, {})
        name = html.escape(THIEF_SPECIALIZATIONS[spec_id]["name"])
        background = html.escape(str(meta.get("background", "")))
        profession_icon = html.escape(str(meta.get("profession_icon_big") or meta.get("icon", "")))

        minor_html: list[str] = []
        for trait_id in THIEF_SPECIALIZATIONS[spec_id]["minor"]:
            trait = traits.get(trait_id, {"name": f"Trait {trait_id}", "icon": "", "description": ""})
            status, status_help = _effect_status(trait_id, overrides)
            icon = html.escape(str(trait.get("icon", "")))
            minor_html.append(
                f'<div class="minor node"><img src="{icon}" alt=""><div class="tooltip">{_trait_tooltip(trait, status, status_help)}</div></div>'
            )

        tier_html: list[str] = []
        major = THIEF_SPECIALIZATIONS[spec_id]["major"]
        for tier in range(3):
            selected = int(st.session_state[f"trait_line_{line}_tier_{tier}"])
            choices: list[str] = []
            for trait_id in major[tier * 3:(tier + 1) * 3]:
                trait = traits.get(trait_id, {"name": f"Trait {trait_id}", "icon": "", "description": ""})
                status, status_help = _effect_status(trait_id, overrides)
                icon = html.escape(str(trait.get("icon", "")))
                selected_class = " selected" if trait_id == selected else ""
                choices.append(
                    f'<a class="major node{selected_class}" href="?trait_click={line}:{tier}:{trait_id}" target="_top" aria-label="Select {html.escape(str(trait.get("name", "Trait")))}">'
                    f'<img src="{icon}" alt=""><span class="status">{status}</span>'
                    f'<div class="tooltip">{_trait_tooltip(trait, status, status_help)}</div></a>'
                )
            tier_html.append('<div class="tier">' + ''.join(choices) + '</div>')

        bg_style = (
            f"background-image:linear-gradient(90deg,rgba(15,12,12,.10),rgba(15,12,12,.48)),url('{background}');"
            if background else ""
        )
        portrait = f'<img src="{profession_icon}" alt="">' if profession_icon else ''
        blocks.append(
            '<section class="spec" style="' + bg_style + '">' 
            '<div class="portrait">' + portrait + '<span>' + name + '</span></div>'
            '<div class="minor-slot">' + minor_html[0] + '</div>' + tier_html[0] +
            '<div class="minor-slot">' + minor_html[1] + '</div>' + tier_html[1] +
            '<div class="minor-slot">' + minor_html[2] + '</div>' + tier_html[2] +
            '</section>'
        )

    if not blocks:
        st.info("Choose at least one specialization above.")
        return

    height = active_lines * 184 + 10
    document = '''<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--accent:#ff4b4b;--panel:#17191f;--text:#f3f4f6;}
*{box-sizing:border-box} html,body{margin:0;background:transparent;color:var(--text);font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;overflow:visible}
.builder{display:grid;gap:12px;padding:1px}
.spec{position:relative;min-height:168px;display:grid;grid-template-columns:minmax(165px,1.25fr) 58px 74px 58px 74px 58px 74px;align-items:center;gap:12px;padding:14px 18px;border:1px solid rgba(255,255,255,.10);border-radius:11px;background-color:#21191a;background-size:cover;background-position:center;box-shadow:inset 0 0 55px rgba(0,0,0,.40)}
.portrait{height:136px;position:relative;display:flex;align-items:flex-end;overflow:hidden;border-right:1px solid rgba(255,255,255,.10)}
.portrait img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;object-position:left center;filter:drop-shadow(0 6px 10px #000)}
.portrait span{position:relative;z-index:2;font-size:17px;font-weight:750;padding:0 10px 5px 2px;text-shadow:0 2px 6px #000}
.minor-slot{display:flex;justify-content:center}
.tier{display:flex;flex-direction:column;gap:8px;align-items:center}
.node{position:relative;width:48px;height:48px;display:block;border-radius:6px}
.node img{width:48px;height:48px;object-fit:cover;border-radius:5px;display:block}
.minor img{clip-path:polygon(50% 0,92% 24%,92% 76%,50% 100%,8% 76%,8% 24%);filter:drop-shadow(0 0 2px rgba(255,111,65,.8))}
a.major{opacity:.28;filter:saturate(.65);transition:opacity .13s,transform .13s,filter .13s;text-decoration:none;outline:none}
a.major:hover{opacity:.82;transform:scale(1.05);filter:saturate(1)}
a.major.selected{opacity:1;filter:saturate(1) drop-shadow(0 0 5px rgba(255,75,75,.75))}
a.major.selected img{outline:2px solid var(--accent);outline-offset:2px}
.status{position:absolute;right:-9px;top:-9px;font-size:12px;filter:drop-shadow(0 1px 2px #000)}
.tooltip{display:none;position:absolute;z-index:50;left:50%;bottom:calc(100% + 10px);transform:translateX(-50%);width:285px;padding:10px 12px;border:1px solid rgba(255,255,255,.16);border-radius:8px;background:#11141a;box-shadow:0 10px 30px rgba(0,0,0,.55);text-align:left;pointer-events:none}
.tooltip strong,.tooltip span,.tooltip small{display:block}.tooltip strong{margin-bottom:5px}.tooltip span{font-size:12px;line-height:1.38;color:#d6d8df}.tooltip small{margin-top:7px;color:#aeb3bd}
.node:hover .tooltip{display:block}
@media(max-width:900px){.spec{grid-template-columns:110px 44px 62px 44px 62px 44px 62px;gap:5px;padding:10px}.node,.node img{width:42px;height:42px}.portrait span{font-size:13px}}
</style></head><body><main class="builder">''' + ''.join(blocks) + '''</main></body></html>'''
    components.html(document, height=height, scrolling=False)
    st.caption("Click the trait icons directly. Bright icons are selected; dim icons are alternatives. Hover an icon for its official description and implementation status.")

def _trait_label(trait_id: int, traits: dict[int, dict[str, Any]], overrides: dict[str, Any]) -> str:
    trait = traits.get(trait_id, {})
    status, _ = _effect_status(trait_id, overrides)
    return f"{status} {trait.get('name', f'Trait {trait_id}')}"


def _render_trait_summary(
    trait_id: int,
    traits: dict[int, dict[str, Any]],
    overrides: dict[str, Any],
    *,
    compact: bool = False,
) -> None:
    trait = traits.get(trait_id, {"name": f"Trait {trait_id}", "description": "", "icon": ""})
    status, status_help = _effect_status(trait_id, overrides)
    icon_col, text_col = st.columns([0.16 if compact else 0.12, 0.84 if compact else 0.88], vertical_alignment="center")
    with icon_col:
        if trait.get("icon"):
            st.image(trait["icon"], width=34 if compact else 42)
    with text_col:
        st.markdown(f"**{trait.get('name', f'Trait {trait_id}')}** {status}", help=status_help)
        description = _clean_text(trait.get("description", ""))
        if description:
            st.caption(description)


def _set_major_trait(line: int, tier: int, trait_id: int) -> None:
    st.session_state[f"trait_line_{line}_tier_{tier}"] = int(trait_id)
    st.session_state["focused_trait_id"] = int(trait_id)
    _persist_trait_selection()


def _focus_trait_from_key(key: str) -> None:
    value = st.session_state.get(key)
    if value:
        st.session_state["focused_trait_id"] = int(value)
    _persist_trait_selection()


def _render_minor_icons_compact(
    spec_id: int,
    traits: dict[int, dict[str, Any]],
    overrides: dict[str, Any],
) -> None:
    """Show the three automatic minors in a single compact row."""
    st.caption("Automatic minors")
    cols = st.columns(3, gap="small")
    for idx, trait_id in enumerate(THIEF_SPECIALIZATIONS[spec_id]["minor"]):
        trait = traits.get(trait_id, {"name": f"Trait {trait_id}", "icon": "", "description": ""})
        status, status_help = _effect_status(trait_id, overrides)
        tooltip = f"{trait.get('name', f'Trait {trait_id}')} {status}\n\n{_clean_text(trait.get('description', ''))}\n\n{status_help}"
        with cols[idx]:
            if trait.get("icon"):
                st.image(trait["icon"], width=34)
            st.markdown(
                f"<div title='{html.escape(tooltip)}' style='font-size:.66rem;line-height:1.05;min-height:2.1em'>"
                f"{html.escape(trait.get('name', f'Trait {trait_id}'))} {status}</div>",
                unsafe_allow_html=True,
            )


def _render_major_dropdowns_compact(
    line: int,
    spec_id: int,
    traits: dict[int, dict[str, Any]],
    overrides: dict[str, Any],
) -> None:
    """Use one small dropdown per tier instead of nine full-width buttons."""
    major = THIEF_SPECIALIZATIONS[spec_id]["major"]
    for tier in range(3):
        valid = major[tier * 3:(tier + 1) * 3]
        key = f"trait_line_{line}_tier_{tier}"
        if st.session_state.get(key) not in valid:
            st.session_state[key] = valid[0]

        selected = st.selectbox(
            f"Tier {tier + 1}",
            valid,
            key=key,
            format_func=lambda trait_id: _trait_label(int(trait_id), traits, overrides),
            on_change=_focus_trait_from_key,
            args=(key,),
            help="Select one major trait for this tier. The status icon shows whether its calculator effect is implemented.",
        )

        trait = traits.get(int(selected), {"name": f"Trait {selected}", "icon": "", "description": ""})
        status, status_help = _effect_status(int(selected), overrides)
        icon_col, text_col = st.columns([0.18, 0.82], vertical_alignment="center")
        with icon_col:
            if trait.get("icon"):
                st.image(trait["icon"], width=34)
        with text_col:
            st.caption(_clean_text(trait.get("description", "")) or status_help)


def _render_specialization_compact(
    line: int,
    spec_id: int,
    traits: dict[int, dict[str, Any]],
    specs: dict[int, dict[str, Any]],
    overrides: dict[str, Any],
) -> None:
    """Render one compact specialization row using only native Streamlit widgets.

    Minor traits are icons with hover help. Each major tier has one selector and
    one short, plain-text effect line. No raw HTML is rendered here.
    """
    _ensure_line_trait_defaults(line, spec_id)
    spec_meta = specs.get(spec_id, {})
    spec_name = THIEF_SPECIALIZATIONS[spec_id]["name"]
    elite_label = "Elite" if THIEF_SPECIALIZATIONS[spec_id]["elite"] else "Core"

    with st.container(border=True):
        identity, tier1_col, tier2_col, tier3_col = st.columns([1.05, 1.0, 1.0, 1.0], gap="small")

        with identity:
            icon_col, name_col = st.columns([0.20, 0.80], vertical_alignment="center")
            with icon_col:
                icon = spec_meta.get("profession_icon") or spec_meta.get("icon")
                if icon:
                    st.image(icon, width=34)
            with name_col:
                st.markdown(f"**{spec_name}**")

            # Option A: only the three automatic minor-trait icons.
            # Use native Streamlit rendering so HTML can never leak as text.
            minor_cols = st.columns(3, gap="small")
            for minor_col, trait_id in zip(minor_cols, THIEF_SPECIALIZATIONS[spec_id]["minor"]):
                trait = traits.get(trait_id, {"name": f"Trait {trait_id}", "icon": ""})
                with minor_col:
                    icon_url = str(trait.get("icon", ""))
                    if icon_url:
                        st.image(icon_url, width=34)

        major = THIEF_SPECIALIZATIONS[spec_id]["major"]
        for tier, col in enumerate((tier1_col, tier2_col, tier3_col)):
            valid = major[tier * 3:(tier + 1) * 3]
            key = f"trait_line_{line}_tier_{tier}"
            if st.session_state.get(key) not in valid:
                st.session_state[key] = valid[0]

            with col:
                selected = st.selectbox(
                    f"Tier {tier + 1}",
                    valid,
                    key=key,
                    format_func=lambda trait_id: _trait_label(int(trait_id), traits, overrides),
                    on_change=_focus_trait_from_key,
                    args=(key,),
                    help="Choose one major trait. The question mark means its calculator effect is not implemented yet.",
                )
                trait = traits.get(int(selected), {"name": f"Trait {selected}", "icon": "", "description": ""})
                status, status_help = _effect_status(int(selected), overrides)
                description = _clean_text(trait.get("description", ""))

                icon_col, text_col = st.columns([0.16, 0.84], vertical_alignment="center")
                with icon_col:
                    if trait.get("icon"):
                        st.image(trait["icon"], width=30)
                with text_col:
                    _, _, source_rows = calculate_selected_trait_effects()
                    source = next((row for row in source_rows if row["trait_id"] == int(selected)), None)
                    if source and source["applied"]:
                        st.caption(" · ".join(source["applied"]), help="Applied now to: " + ", ".join(source["destinations"]))
                    elif source and source["official_values"]:
                        values = " · ".join(source["official_values"][:2])
                        st.caption(f"Not applied yet — {values}", help=(description + "\n\n" + "\n".join(source["pending"])).strip())
                    else:
                        st.caption("No active calculator effect yet", help=(description + "\n\n" + status_help).strip())

def _render_focused_trait_panel(
    traits: dict[int, dict[str, Any]],
    overrides: dict[str, Any],
) -> None:
    selected_ids = selected_trait_ids()
    focused = st.session_state.get("focused_trait_id")
    if focused not in selected_ids:
        focused = next((trait_id for trait_id in selected_ids if trait_id in traits), None)
    if focused is None:
        return

    trait_id = int(focused)
    trait = traits.get(trait_id, {"name": f"Trait {trait_id}", "description": "", "icon": ""})
    status_icon, status_help = _effect_status(trait_id, overrides)
    effect = overrides.get(str(trait_id), {})

    st.subheader("Trait details")
    with st.container(border=True):
        icon_col, content_col = st.columns([0.08, 0.92], vertical_alignment="top")
        with icon_col:
            if trait.get("icon"):
                st.image(trait["icon"], width=56)
        with content_col:
            st.markdown(f"### {trait.get('name', f'Trait {trait_id}')} {status_icon}")
            st.caption(status_help)
            description = _clean_text(trait.get("description", ""))
            if description:
                st.write(description)
            st.markdown(f"[GW2 Wiki]({_wiki_url(trait.get('name', ''))})")

        st.divider()
        st.markdown("**Effect-level status**")
        effect_rows = []
        state_labels = {
            "applied": "✅ Applied now",
            "event": "⏳ Waiting for event engine",
            "needs_code": "⚪ Needs implementation",
        }
        for part in _trait_effect_parts(trait_id, overrides):
            effect_rows.append({
                "Effect": part["effect"],
                "Type": part["kind"],
                "Status": state_labels.get(part["state"], part["state"]),
            })
        st.dataframe(effect_rows, use_container_width=True, hide_index=True)
        notes = effect.get("notes")
        if notes:
            st.caption("Notes")
            if isinstance(notes, list):
                for note in notes:
                    st.write(f"• {note}")
            else:
                st.write(notes)


def _render_active_trait_effects(overrides: dict[str, Any]) -> None:
    """Render a compact, collapsible audit of selected trait calculations."""
    stats, modifiers, sources = calculate_selected_trait_effects()

    with st.expander("Active effect calculation", expanded=False):
        active_rows: list[dict[str, str]] = []
        waiting_rows: list[dict[str, str]] = []
        official_rows: list[dict[str, str]] = []

        for source in sources:
            trait_name = source["trait_name"]
            destinations = ", ".join(source["destinations"]) or "—"

            for applied in source["applied"]:
                active_rows.append({
                    "Trait": trait_name,
                    "Applied effect": applied,
                    "Feeds into": destinations,
                })

            pending = source["pending"] or ([] if source["applied"] else ["No calculator mapping yet"])
            for missing in pending:
                status = "Partial" if source["applied"] else "Waiting"
                waiting_rows.append({
                    "Trait": trait_name,
                    "Status": status,
                    "Missing mechanic": missing,
                })

            official_values = " · ".join(source["official_values"])
            if official_values:
                official_rows.append({
                    "Trait": trait_name,
                    "Official values": official_values,
                })

        st.markdown("**Active effects**")
        if active_rows:
            st.dataframe(
                active_rows,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Trait": st.column_config.TextColumn(width="medium"),
                    "Applied effect": st.column_config.TextColumn(width="large"),
                    "Feeds into": st.column_config.TextColumn(width="medium"),
                },
            )
        else:
            st.info("None of the selected traits currently changes the calculator.")

        st.markdown("**Selected but not yet fully simulated**")
        if waiting_rows:
            st.dataframe(
                waiting_rows,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Trait": st.column_config.TextColumn(width="medium"),
                    "Status": st.column_config.TextColumn(width="small"),
                    "Missing mechanic": st.column_config.TextColumn(width="large"),
                },
            )
        else:
            st.success("All selected trait effects are fully mapped.")

        st.markdown("**Combined active totals**")
        totals: list[dict[str, str]] = []
        totals.extend(
            {"Effect": key, "Total": f"{value:+g}", "Type": "Stat"}
            for key, value in sorted(stats.items())
        )
        totals.extend(
            {"Effect": key, "Total": f"{value:+.1%}", "Type": "Modifier"}
            for key, value in sorted(modifiers.items())
        )
        if totals:
            st.dataframe(
                totals,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Type": st.column_config.TextColumn(width="small"),
                    "Effect": st.column_config.TextColumn(width="medium"),
                    "Total": st.column_config.TextColumn(width="small"),
                },
            )
        else:
            st.caption("No verified active totals yet.")

        if official_rows:
            with st.expander("Official values for selected traits", expanded=False):
                st.dataframe(
                    official_rows,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Trait": st.column_config.TextColumn(width="medium"),
                        "Official values": st.column_config.TextColumn(width="large"),
                    },
                )

def _derived_unique_boons_from_buff_state() -> float:
    """Return the fight-average number of unique configured boons.

    Might counts as one unique boon whenever at least one stack is enabled. Other
    boons contribute their configured uptime fraction, so a 50% Fury profile
    contributes 0.5 to effects that scale with the average unique-boon count.
    """
    total = 0.0
    if bool(st.session_state.get("gear_might_enabled", False)) and float(st.session_state.get("gear_might_stacks", 0)) > 0:
        total += 1.0
    for boon in (
        "alacrity", "quickness", "fury", "protection", "regeneration",
        "resolution", "swiftness", "vigor", "stability", "resistance", "aegis",
    ):
        if bool(st.session_state.get(f"gear_{boon}", False)):
            uptime = max(0.0, min(100.0, float(st.session_state.get(f"gear_{boon}_uptime", 0.0))))
            total += uptime / 100.0
    return total


def render_trait_assumptions(*, expanded: bool = False, popover: bool = False) -> None:
    """Render the single shared set of combat-state assumptions.

    Inputs are grouped by their eventual source. Boon count is derived from the
    active Buff profile instead of being entered twice. Rotation-dependent values
    remain editable for now and are explicitly marked for future automation.
    """
    host = st.popover("⚙ Combat & trait assumptions", use_container_width=True) if popover else st.expander(
        "Combat & trait assumptions", expanded=expanded
    )
    with host:
        st.caption(
            "These values describe the combat situation around the active build. "
            "Gear, traits and buffs are read automatically; only encounter and rotation averages remain manual for now."
        )

        encounter_tab, rotation_tab, advanced_tab = st.tabs([
            "Encounter state", "Rotation averages", "Advanced uptimes"
        ])

        with encounter_tab:
            st.caption("MANUAL NOW · later these can be loaded from a combat log.")
            a, b = st.columns(2)
            a.number_input(
                "Player health (%)", 0.0, 100.0, 100.0, 0.01, format="%.3f",
                key="trait_player_health_pct",
                help="Used by traits with a player-health threshold."
            )
            b.number_input(
                "Target health (%)", 0.0, 100.0, 100.0, 0.01, format="%.3f",
                key="trait_target_health_pct",
                help="Used by target-health effects such as Executioner."
            )
            c, d = st.columns(2)
            c.number_input(
                "Unique conditions on target", 0.0, 14.0, 10.0, 0.1, format="%.3f",
                key="trait_unique_conditions",
                help="Average unique conditions on the target; used by effects such as Exposed Weakness."
            )
            d.checkbox(
                "Flanking / defiant target", value=True, key="trait_flanking_or_defiant",
                help="Shared target-state flag for flanking or defiant-foe bonuses."
            )
            e, f = st.columns(2)
            e.number_input(
                "Weakened target uptime (%)", 0.0, 100.0, 0.0, 0.01, format="%.3f",
                key="trait_weakened_target_uptime",
                help="Fight-average uptime for effects that require a weakened target."
            )
            f.info(
                "Nearby-foe uptime is only relevant to Marauder's Resilience and has been moved to Advanced uptimes. "
                "It is hidden there unless that trait is selected."
            )

            derived_boons = _derived_unique_boons_from_buff_state()
            st.session_state["trait_unique_boons"] = derived_boons
            st.markdown("##### Player boons — separate from target conditions")
            boon_cols = st.columns([1, 2])
            boon_cols[0].metric("Unique boons on player", f"{derived_boons:.2f}")
            boon_cols[1].caption(
                "Calculated only from the player Buff profile. This is never used as the target condition count. "
                "The target remains controlled separately by Unique conditions on target above."
            )

        with rotation_tab:
            st.caption("MANUAL NOW · the future event/rotation engine will calculate these values.")
            g, h = st.columns(2)
            g.number_input(
                "Average Lead Attacks bonus (%)", 0.0, 15.0, 0.0, 0.001, format="%.3f",
                key="trait_lead_attacks_bonus_pct",
                help="Average outgoing-damage bonus maintained through initiative spending."
            )
            h.number_input(
                "Average Combat High stacks", 0.0, 10.0, 0.0, 0.01, format="%.3f",
                key="trait_combat_high_stacks",
                help="Average Combat High stacks across the measured window."
            )
            i, j = st.columns(2)
            i.number_input(
                "Revealed uptime (%)", 0.0, 100.0, 0.0, 0.01, format="%.3f",
                key="trait_revealed_uptime",
                help="Average Revealed uptime for Revealed-dependent effects."
            )
            j.number_input(
                "Stealth / linger uptime (%)", 0.0, 100.0, 0.0, 0.01, format="%.3f",
                key="trait_stealth_uptime",
                help="Average stealth or post-stealth linger uptime."
            )
            k, l = st.columns(2)
            k.number_input(
                "Barrier uptime (%)", 0.0, 100.0, 0.0, 0.01, format="%.3f",
                key="trait_barrier_uptime",
                help="Average time the player has barrier."
            )
            l.number_input(
                "Marked target uptime (%)", 0.0, 100.0, 0.0, 0.01, format="%.3f",
                key="trait_marked_target_uptime",
                help="Average uptime of the relevant marked-target state."
            )
            m, n = st.columns(2)
            m.number_input(
                "Endurance not full uptime (%)", 0.0, 100.0, 0.0, 0.01, format="%.3f",
                key="trait_endurance_not_full_uptime",
                help="Average time below full endurance."
            )
            n.number_input(
                "Distracting Throw modifier uptime (%)", 0.0, 100.0, 0.0, 0.01, format="%.3f",
                key="trait_distracting_throw_uptime",
                help="Distracting Throw is a single +10% condition-damage modifier while active; it does not stack. Enter its fight-average uptime."
            )

        with advanced_tab:
            st.caption("ADVANCED MANUAL OVERRIDES · keep at zero unless the selected build uses the effect.")
            o, p = st.columns(2)
            o.number_input(
                "Lotus Training uptime (%)", 0.0, 100.0, 0.0, 0.01, format="%.3f",
                key="trait_lotus_training_uptime",
                help="Average uptime used by estimates that include Lotus Training."
            )
            p.number_input(
                "Fluid Strikes uptime (%)", 0.0, 100.0, 0.0, 0.01, format="%.3f",
                key="trait_fluid_strikes_uptime",
                help="Average uptime of the strike-damage buff after movement skills or shadowsteps."
            )
            q, r = st.columns(2)
            q.number_input(
                "Bounding Dodger uptime (%)", 0.0, 100.0, 0.0, 0.01, format="%.3f",
                key="trait_bounding_dodger_uptime",
                help="Average uptime of the strike-damage buff after Bound."
            )
            r.number_input(
                "Exhilarating Ephemera uptime (%)", 0.0, 100.0, 0.0, 0.01, format="%.3f",
                key="trait_exhilarating_ephemera_uptime",
                help="Average uptime of the strike-damage buff after artifact use."
            )
            s_col, t_col = st.columns(2)
            s_col.number_input(
                "Unhindered Combatant uptime (%)", 0.0, 100.0, 0.0, 0.01, format="%.3f",
                key="trait_unhindered_combatant_uptime",
                help="Average uptime of the incoming-damage reduction after Dash."
            )
            t_col.empty()

            if 1933 in selected_trait_ids():
                st.markdown("##### Marauder's Resilience")
                st.caption(
                    "Only for this selected trait: enter the percentage of the fight where at least one enemy is within 360 range. "
                    "At 100% uptime, the trait's 10% incoming strike-damage reduction is fully active. This never increases outgoing DPS."
                )
                st.number_input(
                    "Enemy within 360 range uptime (%)", 0.0, 100.0, 0.0, 0.01, format="%.3f",
                    key="trait_nearby_foe_uptime",
                    help="Marauder's Resilience only. Use 100% for melee-range uptime, 0% when no enemy stays within 360 range, or a fight-average value between them."
                )
            else:
                st.caption("Marauder's Resilience range uptime is hidden because that trait is not selected.")

        with st.expander("Which traits use these assumptions?", expanded=False):
            st.dataframe(
                [
                    {"Assumption": "Player / target health", "Used by": "Health-threshold traits such as Executioner, Keen Observer and Ferocious Strikes", "Future source": "Combat log"},
                    {"Assumption": "Conditions on target", "Used by": "Condition-count modifiers such as Exposed Weakness", "Future source": "Combat log"},
                    {"Assumption": "Flanking / defiant", "Used by": "Positional and defiant-target bonuses such as Twin Fangs", "Future source": "Combat log / encounter"},
                    {"Assumption": "Unique boons on player", "Used by": "Player boon-count effects such as Premeditation", "Future source": "Player Buff profile (already derived; never target conditions)"},
                    {"Assumption": "Lead Attacks / Combat High", "Used by": "Initiative and stack-based outgoing modifiers", "Future source": "Rotation engine"},
                    {"Assumption": "Nearby foe uptime", "Used by": "Marauder's Resilience incoming-damage reduction only", "Future source": "Encounter / combat log"},
                    {"Assumption": "Distracting Throw uptime", "Used by": "Single +10% condition modifier while active; non-stacking", "Future source": "Rotation engine"},
                    {"Assumption": "Revealed / stealth / barrier / mark", "Used by": "State-dependent trait effects", "Future source": "Event engine / combat log"},
                    {"Assumption": "Advanced uptimes", "Used by": "Specific dodge, movement and artifact buffs", "Future source": "Rotation engine"},
                ],
                hide_index=True,
                use_container_width=True,
            )


def render_trait_progress_page() -> None:
    """Effect-level development dashboard generated from live trait data."""
    st.title("Trait Progress")
    st.caption(
        "Progress is counted per effect, not only per trait. A mixed trait can have a passive effect applied now "
        "and a triggered effect preserved for the future event engine."
    )

    payload, sync_error = load_trait_data(auto_sync=True)
    traits = _trait_map(payload)
    overrides = load_effect_overrides()
    if sync_error:
        st.warning("Live trait synchronization failed; cached trait data is being used.")

    trait_rows: list[dict[str, Any]] = []
    effect_rows: list[dict[str, Any]] = []
    spec_rows: list[dict[str, Any]] = []
    state_label = {
        "applied": "Applied now",
        "event": "Waiting for event engine",
        "needs_code": "Needs implementation",
    }

    for spec_id, spec in THIEF_SPECIALIZATIONS.items():
        spec_counts = {"applied": 0, "event": 0, "needs_code": 0}
        ids = spec["minor"] + spec["major"]
        for trait_id in ids:
            trait = traits.get(trait_id, {})
            parts = _trait_effect_parts(trait_id, overrides)
            states = {part["state"] for part in parts}
            if states == {"applied"}:
                trait_state = "Applied now"
            elif "needs_code" in states:
                trait_state = "Needs implementation"
            elif "applied" in states and "event" in states:
                trait_state = "Mixed: applied + event"
            else:
                trait_state = "Waiting for event engine"
            trait_rows.append({
                "Specialization": spec["name"],
                "Type": "Minor" if trait_id in spec["minor"] else "Major",
                "Trait": trait.get("name", f"Trait {trait_id}"),
                "Trait status": trait_state,
                "Applied effects": sum(part["state"] == "applied" for part in parts),
                "Event effects": sum(part["state"] == "event" for part in parts),
                "Needs code": sum(part["state"] == "needs_code" for part in parts),
            })
            for part in parts:
                spec_counts[part["state"]] += 1
                effect_rows.append({
                    "Specialization": spec["name"],
                    "Trait": trait.get("name", f"Trait {trait_id}"),
                    "Effect": part["effect"],
                    "Effect type": part["kind"],
                    "Status": state_label.get(part["state"], part["state"]),
                })
        total_effects = sum(spec_counts.values())
        spec_rows.append({
            "Specialization": spec["name"],
            "Traits": len(ids),
            "Applied now": spec_counts["applied"],
            "Waiting for events": spec_counts["event"],
            "Needs implementation": spec_counts["needs_code"],
            "Effect coverage %": 100.0 * (spec_counts["applied"] + spec_counts["event"]) / max(1, total_effects),
        })

    applied = sum(row["Status"] == "Applied now" for row in effect_rows)
    events = sum(row["Status"] == "Waiting for event engine" for row in effect_rows)
    needs_code = sum(row["Status"] == "Needs implementation" for row in effect_rows)
    metrics = st.columns(4)
    metrics[0].metric("Traits", len(trait_rows))
    metrics[1].metric("Effects applied now", applied)
    metrics[2].metric("Effects waiting for events", events)
    metrics[3].metric("Effects needing code", needs_code)

    st.info(
        "Legend: ✅ Applied now changes current calculators. ⏳ Waiting for event engine is fully preserved as a trigger/effect packet, "
        "but needs combat timing. ⚪ Needs implementation means the known effect still has no calculator or event mapping."
    )

    st.subheader("By specialization")
    st.dataframe(spec_rows, use_container_width=True, hide_index=True)

    view = st.radio("Progress view", ["Effect checklist", "Trait summary"], horizontal=True)
    status_filter = st.multiselect(
        "Show statuses",
        ["Applied now", "Waiting for event engine", "Needs implementation"],
        default=["Applied now", "Waiting for event engine", "Needs implementation"],
        key="trait_progress_effect_status_filter",
    )
    spec_filter = st.selectbox(
        "Specialization", ["All"] + [spec["name"] for spec in THIEF_SPECIALIZATIONS.values()],
        key="trait_progress_spec_filter_v2",
    )

    if view == "Effect checklist":
        filtered = [row for row in effect_rows if row["Status"] in status_filter]
        if spec_filter != "All":
            filtered = [row for row in filtered if row["Specialization"] == spec_filter]
        st.dataframe(filtered, use_container_width=True, hide_index=True)
    else:
        filtered = trait_rows
        if spec_filter != "All":
            filtered = [row for row in filtered if row["Specialization"] == spec_filter]
        st.dataframe(filtered, use_container_width=True, hide_index=True)

    with st.expander("Development changelog", expanded=False):
        if TRAIT_CHANGELOG_PATH.exists():
            st.markdown(TRAIT_CHANGELOG_PATH.read_text(encoding="utf-8"))
        else:
            st.caption("No trait changelog has been created yet.")


def render_traits_page() -> None:
    _restore_trait_widget_state()
    _inject_trait_page_css()
    st.title("Thief Traits")
    st.caption(
        "Choose up to three specialization lines. Each selected major trait shows a short effect summary beneath its selector."
    )

    payload, sync_error = load_trait_data(auto_sync=True)
    traits = _trait_map(payload)
    specs = _spec_map(payload)
    overrides = load_effect_overrides()

    top = st.columns([1.35, 1.0, 0.65])
    with top[0]:
        st.caption(f"Data source: {payload.get('source', 'Unknown')}")
        if sync_error:
            st.warning("Live synchronization failed. Cached trait data is being used.")
    with top[1]:
        if st.button("Refresh official trait data", use_container_width=True):
            try:
                sync_trait_cache()
                st.success("Official trait cache refreshed.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not refresh trait data: {exc}")
    with top[2]:
        st.metric("Traits loaded", len(traits))

    with st.expander("Trait presets", expanded=False):
        presets = load_presets()
        a, b = st.columns([1.2, 1.0])
        with a:
            preset_name = st.text_input("New preset name", placeholder="Example: Condi Antiquary")
        with b:
            preset_options = ["None"] + sorted(presets)
            active_preset = st.session_state.get("active_trait_preset", "None")
            if active_preset not in preset_options:
                active_preset = "None"
            if "trait_preset_choice" not in st.session_state:
                st.session_state["trait_preset_choice"] = active_preset
            chosen = st.selectbox("Saved trait preset", preset_options, key="trait_preset_choice")
        buttons = st.columns(4)
        if buttons[0].button("Save as new", use_container_width=True, disabled=not preset_name.strip()):
            presets[preset_name.strip()] = _current_selection()
            save_presets(presets)
            st.success(f'Saved trait preset "{preset_name.strip()}".')
            st.rerun()
        if buttons[1].button("Load", use_container_width=True, disabled=chosen == "None"):
            _apply_selection(presets[chosen])
            st.session_state["active_trait_preset"] = chosen
            st.rerun()
        if buttons[2].button("Overwrite", use_container_width=True, disabled=chosen == "None"):
            presets[chosen] = _current_selection()
            save_presets(presets)
            st.success(f'Updated "{chosen}".')
        if buttons[3].button("Delete", use_container_width=True, disabled=chosen == "None"):
            presets.pop(chosen, None)
            save_presets(presets)
            if st.session_state.get("active_trait_preset") == chosen:
                st.session_state["active_trait_preset"] = "None"
            st.session_state["trait_preset_choice"] = "None"
            st.rerun()


    st.subheader("Specializations")
    spec_options = ["None"] + [str(spec_id) for spec_id in THIEF_SPECIALIZATIONS]
    spec_names = {"None": "None"} | {
        str(spec_id): THIEF_SPECIALIZATIONS[spec_id]["name"] for spec_id in THIEF_SPECIALIZATIONS
    }
    spec_cols = st.columns(3)
    for line in range(1, 4):
        with spec_cols[line - 1]:
            selected_spec = st.selectbox(
                f"Specialization {line}",
                spec_options,
                format_func=lambda value: spec_names[value],
                key=f"trait_line_{line}_spec",
                on_change=_specialization_changed,
                args=(line,),
            )
            if selected_spec != "None":
                _ensure_line_trait_defaults(line, int(selected_spec))

    selected_specs = [
        int(st.session_state[f"trait_line_{line}_spec"])
        for line in range(1, 4)
        if st.session_state.get(f"trait_line_{line}_spec") not in {None, "None"}
    ]
    duplicate_specs = len(selected_specs) != len(set(selected_specs))
    elite_count = sum(bool(THIEF_SPECIALIZATIONS[spec_id]["elite"]) for spec_id in selected_specs)
    if duplicate_specs:
        st.error("A specialization can only be selected once.")
    if elite_count > 1:
        st.error("A valid PvE build can contain at most one elite specialization.")

    active = []
    for line in range(1, 4):
        raw_spec = st.session_state.get(f"trait_line_{line}_spec")
        if raw_spec not in {None, "None"}:
            active.append((line, int(raw_spec)))

    if active:
        for line, spec_id in active:
            _render_specialization_compact(line, spec_id, traits, specs, overrides)
    else:
        st.info("Choose at least one specialization.")

    _render_active_trait_effects(overrides)
    _persist_trait_selection()

    chosen_ids = selected_trait_ids()
    chosen_parts = [part for trait_id in chosen_ids for part in _trait_effect_parts(trait_id, overrides)]
    applied_count = sum(part["state"] == "applied" for part in chosen_parts)
    event_count = sum(part["state"] == "event" for part in chosen_parts)
    needs_code_count = sum(part["state"] == "needs_code" for part in chosen_parts)

    st.subheader("Selected trait effect status")
    cols = st.columns(4)
    cols[0].metric("Selected traits", len(chosen_ids))
    cols[1].metric("Effects applied now", applied_count)
    cols[2].metric("Waiting for event engine", event_count)
    cols[3].metric("Needs implementation", needs_code_count)
    st.info(
        "Status is tracked per effect. Mixed traits keep their passive part active while their triggered part remains structured for the event engine."
    )

    with st.expander("Developer tools · selected official trait data"):
        rows = []
        for trait_id in chosen_ids:
            trait = traits.get(trait_id, {})
            icon, _ = _effect_status(trait_id, overrides)
            rows.append({
                "ID": trait_id,
                "Trait": trait.get("name", f"Trait {trait_id}"),
                "Status": icon,
                "Description": _clean_text(trait.get("description", "")),
                "Facts": json.dumps(trait.get("facts", []), ensure_ascii=False),
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)
