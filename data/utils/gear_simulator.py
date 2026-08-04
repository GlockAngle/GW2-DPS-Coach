from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st
from utils.thief_traits import (
    apply_trait_selection,
    calculate_selected_trait_effects,
    current_trait_effect_registry,
    current_trait_selection,
    render_trait_assumptions,
    _derived_unique_boons_from_buff_state,
    selected_trait_ids,
    load_presets,
)

from utils.user_storage import load_json_dict, persistent_json_path, write_json_dict

from utils.damage_engine import (
    CONDITION_FORMULAS,
    WEAPON_STRENGTHS,
    DamageModifiers,
    ModifierSource,
    calculate_condition_damage,
    calculate_strike_damage,
    get_weapon_strength,
)


DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "gear_data.json"
CONSTANTS_FILE = Path(__file__).resolve().parents[1] / "data" / "combat_constants.json"
RELIC_DIR = Path(__file__).resolve().parents[1] / "data" / "relics"
BUNDLED_SAVED_BUILDS_FILE = Path(__file__).resolve().parents[1] / "data" / "saved_builds.json"
SAVED_BUILDS_FILE = persistent_json_path("saved_builds.json", BUNDLED_SAVED_BUILDS_FILE)
CURRENT_BUILD_FILE = persistent_json_path("current_build.json")
_CURRENT_BUILD_SESSION_KEY = "_thief_lab_current_build"
_CURRENT_BUILD_INITIALIZED_KEY = "_thief_lab_current_build_initialized"

CORE_STATS = (
    "Power", "Toughness", "Vitality", "Precision", "Ferocity",
    "Condition Damage", "Expertise", "Concentration", "Defense", "Healing Power",
)

THIEF_BASE_HEALTH = 1645.0

BUFF_PROFILE_FULL = "Full Benchmark Boons"
BUFF_PROFILE_CUSTOM = "Custom"
BUFF_PROFILE_OPTIONS = (BUFF_PROFILE_FULL, BUFF_PROFILE_CUSTOM)
FULL_BENCHMARK_BOONS = {
    "gear_might_enabled": True,
    "gear_might_stacks": 25,
    "gear_alacrity": True,
    "gear_alacrity_uptime": 100,
    "gear_quickness": True,
    "gear_quickness_uptime": 100,
    "gear_fury": True,
    "gear_fury_uptime": 100,
    "gear_protection": True,
    "gear_protection_uptime": 100,
    "gear_regeneration": True,
    "gear_regeneration_uptime": 100,
    "gear_resolution": False,
    "gear_resolution_uptime": 0,
    "gear_swiftness": True,
    "gear_swiftness_uptime": 100,
    "gear_vigor": True,
    "gear_vigor_uptime": 100,
    "gear_stability": False,
    "gear_stability_uptime": 0,
    "gear_resistance": True,
    "gear_resistance_uptime": 100,
    "gear_aegis": True,
    "gear_aegis_uptime": 100,
}

BASE_STATS = {
    "Power": 1000.0, "Toughness": 1000.0, "Vitality": 1000.0,
    "Precision": 1000.0, "Ferocity": 0.0, "Condition Damage": 0.0,
    "Expertise": 0.0, "Concentration": 0.0, "Defense": 0.0,
    "Healing Power": 0.0,
}

CONDITION_DURATION_KEYS = (
    "Bleeding Duration", "Burning Duration", "Confusion Duration",
    "Poison Duration", "Torment Duration",
)

JADE_CORE_VITALITY = {
    "None": 0.0,
    "Jade Bot Core: Tier 1": 100.0,
    "Jade Bot Core: Tier 2": 115.0,
    "Jade Bot Core: Tier 3": 130.0,
    "Jade Bot Core: Tier 4": 145.0,
    "Jade Bot Core: Tier 5": 160.0,
    "Jade Bot Core: Tier 6": 175.0,
    "Jade Bot Core: Tier 7": 190.0,
    "Jade Bot Core: Tier 8": 205.0,
    "Jade Bot Core: Tier 9": 220.0,
    "Jade Bot Core: Tier 10": 235.0,
}





def _current_build_disk_state() -> dict[str, Any]:
    state = st.session_state.get(_CURRENT_BUILD_SESSION_KEY)
    if isinstance(state, dict):
        return state
    loaded = load_json_dict(CURRENT_BUILD_FILE)
    state = loaded if isinstance(loaded, dict) else {}
    state.setdefault("build", {})
    state.setdefault("active_gear_preset", "")
    state.setdefault("active_trait_preset", "None")
    st.session_state[_CURRENT_BUILD_SESSION_KEY] = state
    return state


def _write_current_build_disk_state(state: dict[str, Any]) -> None:
    st.session_state[_CURRENT_BUILD_SESSION_KEY] = state
    write_json_dict(CURRENT_BUILD_FILE, state)


def _known_build_widget_keys(data: dict[str, Any]) -> set[str]:
    keys = {
        "gear_quick_preset", "gear_weapon_mode", "gear_food", "gear_utility",
        "gear_sigil_1", "gear_sigil_2", "gear_infusion", "gear_infusion_count",
        "gear_rune", "gear_relic", "gear_jade_core", "gear_might_stacks",
        "gear_might_enabled", "gear_fight_duration", "gear_twohand_weapon",
        "gear_mainhand_weapon", "gear_offhand_weapon", "gear_damage_weapon_slot",
        "gear_weapon_strength_mode", "gear_skill_coefficient", "gear_slow_uptime",
        "gear_reinforced_armor", "gear_enemy_armor", "gear_enemy_vulnerability",
        "gear_enemy_movement", "gear_enemy_interruptible", "gear_enemy_attack_speed",
        "gear_active_sigil_stacks", "gear_active_sigil_uptime",
        "gear_spider_venom_nearby_allies", "gear_spider_venom_effective_casts",
        "gear_trait_preset_selection", "gear_buff_profile",
        "trait_player_health_pct", "trait_target_health_pct", "trait_unique_conditions",
        "trait_flanking_or_defiant", "trait_revealed_uptime", "trait_stealth_uptime",
        "trait_barrier_uptime", "trait_combat_high_stacks", "trait_lead_attacks_bonus_pct",
        "trait_weakened_target_uptime", "trait_nearby_foe_uptime",
        "trait_endurance_not_full_uptime", "trait_marked_target_uptime",
        "trait_unique_boons", "trait_distracting_throw_uptime", "trait_distracting_throw_stacks",
        "trait_lotus_training_uptime", "trait_fluid_strikes_uptime",
        "trait_unhindered_combatant_uptime", "trait_bounding_dodger_uptime",
        "trait_exhilarating_ephemera_uptime",
    }
    for boon in ("alacrity", "quickness", "fury", "protection", "regeneration", "resolution", "swiftness", "vigor", "stability", "resistance", "aegis"):
        keys.add(f"gear_{boon}")
        keys.add(f"gear_{boon}_uptime")
    keys.update(f"gear_slot_{slot}" for slot in data["slots"])
    return keys


def initialize_persistent_build_state() -> None:
    """Restore the active build/preset from disk without losing live edits.

    On the first run of a Streamlit session the disk snapshot is authoritative.
    On later reruns, values still present in session state are authoritative and the
    disk snapshot only restores widget keys removed because another page was shown.
    """
    data = load_gear_data()
    state = _current_build_disk_state()
    build = state.get("build")
    first_session_run = not bool(st.session_state.get(_CURRENT_BUILD_INITIALIZED_KEY))

    if first_session_run:
        _ensure_gear_widget_defaults(data)
        if isinstance(build, dict) and build:
            _apply_saved_build(data, build)
        else:
            state["build"] = _current_build_from_state(data)
            _write_current_build_disk_state(state)
        active_gear = str(state.get("active_gear_preset", "") or "")
        if active_gear:
            st.session_state["gear_saved_build_selection"] = active_gear
        active_trait = str(state.get("active_trait_preset", "None") or "None")
        st.session_state["active_trait_preset"] = active_trait
        st.session_state["trait_preset_choice"] = active_trait
        st.session_state[_CURRENT_BUILD_INITIALIZED_KEY] = True
        return

    if not isinstance(build, dict) or not build:
        _ensure_gear_widget_defaults(data)
        return

    # Capture only keys that genuinely survived from the current session before
    # restoring the disk snapshot. Missing keys were removed by Streamlit and must
    # therefore be taken from disk rather than recreated from defaults.
    existing = {key: st.session_state[key] for key in _known_build_widget_keys(data) if key in st.session_state}
    existing_prefixes = dict(st.session_state.get("gear_prefixes", {}))
    live_traits = st.session_state.get("persistent_trait_selection")
    live_active_gear = st.session_state.get("gear_saved_build_selection")
    live_active_trait = st.session_state.get("active_trait_preset")
    live_trait_choice = st.session_state.get("trait_preset_choice")

    st.session_state.setdefault("gear_prefixes", {slot: "Viper" for slot in data["slots"]})
    _apply_saved_build(data, build)

    # Current interaction wins; disk only fills keys that Streamlit removed.
    for key, value in existing.items():
        st.session_state[key] = value
    if existing_prefixes:
        st.session_state["gear_prefixes"] = existing_prefixes
    if isinstance(live_traits, dict):
        apply_trait_selection(live_traits)

    active_gear = str(state.get("active_gear_preset", "") or "")
    if live_active_gear is not None:
        st.session_state["gear_saved_build_selection"] = live_active_gear
    elif active_gear:
        st.session_state["gear_saved_build_selection"] = active_gear

    active_trait = str(state.get("active_trait_preset", "None") or "None")
    st.session_state["active_trait_preset"] = live_active_trait if live_active_trait is not None else active_trait
    st.session_state["trait_preset_choice"] = live_trait_choice if live_trait_choice is not None else st.session_state["active_trait_preset"]

def autosave_current_build() -> None:
    """Persist the complete currently active build and selected preset names."""
    data = load_gear_data()
    _ensure_gear_widget_defaults(data)
    state = _current_build_disk_state()
    state["build"] = _current_build_from_state(data)
    state["active_gear_preset"] = str(st.session_state.get("gear_saved_build_selection", "") or "")
    state["active_trait_preset"] = str(st.session_state.get("active_trait_preset", "None") or "None")
    _write_current_build_disk_state(state)


def autosave_trait_state() -> None:
    """Update only traits/preset in the active build when the Traits page is used."""
    state = _current_build_disk_state()
    build = state.get("build")
    if not isinstance(build, dict):
        build = {}
    build["traits"] = current_trait_selection()
    state["build"] = build
    state["active_trait_preset"] = str(st.session_state.get("active_trait_preset", "None") or "None")
    _write_current_build_disk_state(state)


def _load_saved_builds() -> dict[str, dict[str, Any]]:
    return load_json_dict(SAVED_BUILDS_FILE)


def _write_saved_builds(builds: dict[str, dict[str, Any]]) -> None:
    write_json_dict(SAVED_BUILDS_FILE, builds)


def _ensure_gear_widget_defaults(data: dict[str, Any]) -> None:
    defaults = {
        "gear_quick_preset": "Custom",
        "gear_weapon_mode": "Two-handed weapon",
        "gear_food": "None",
        "gear_utility": "Toxic Focusing Crystal",
        "gear_sigil_1": "Bursting",
        "gear_sigil_2": "None",
        "gear_infusion": "Malign",
        "gear_infusion_count": 18,
        "gear_rune": sorted(data["runes"])[0],
        "gear_relic": sorted(data["relics"])[0],
        "gear_jade_core": "Jade Bot Core: Tier 10",
        "gear_buff_profile": BUFF_PROFILE_FULL,
        "gear_might_stacks": 25,
        "gear_might_enabled": True,
        "gear_alacrity": True,
        "gear_alacrity_uptime": 100,
        "gear_quickness": True,
        "gear_quickness_uptime": 100,
        "gear_fury": True,
        "gear_fury_uptime": 100,
        "gear_protection": True,
        "gear_protection_uptime": 100,
        "gear_regeneration": True,
        "gear_regeneration_uptime": 100,
        "gear_resolution": False,
        "gear_resolution_uptime": 0,
        "gear_swiftness": True,
        "gear_swiftness_uptime": 100,
        "gear_vigor": True,
        "gear_vigor_uptime": 100,
        "gear_stability": False,
        "gear_stability_uptime": 0,
        "gear_resistance": True,
        "gear_resistance_uptime": 100,
        "gear_aegis": True,
        "gear_aegis_uptime": 100,
        "gear_build_name": "",
        "gear_fight_duration": 90.0,
        "gear_twohand_weapon": "Spear",
        "gear_mainhand_weapon": "Dagger",
        "gear_offhand_weapon": "Pistol",
        "gear_damage_weapon_slot": "Main hand",
        "gear_weapon_strength_mode": "Midpoint",
        "gear_skill_coefficient": 1.0,
        "gear_slow_uptime": 0,
        "gear_reinforced_armor": False,
        "gear_enemy_armor": 2597,
        "gear_enemy_vulnerability": 25,
        "gear_enemy_movement": 0,
        "gear_enemy_interruptible": False,
        "gear_enemy_attack_speed": 1.0,
        "gear_active_sigil_stacks": 25,
        "gear_active_sigil_uptime": 100,
        "trait_unique_conditions": 10.0,
        "trait_unhindered_combatant_uptime": 0.0,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)
    st.session_state.setdefault(
        "gear_prefixes", {slot: "Viper" for slot in data["slots"]}
    )
    for slot in data["slots"]:
        st.session_state.setdefault(
            f"gear_slot_{slot}", st.session_state["gear_prefixes"].get(slot, "Viper")
        )


def _current_build_from_state(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 2,
        "quick_preset": st.session_state.get("gear_quick_preset", "Custom"),
        "weapon_mode": st.session_state.get("gear_weapon_mode", "Two-handed weapon"),
        "gear": {
            slot: st.session_state.get(f"gear_slot_{slot}", "Viper")
            for slot in data["slots"]
        },
        "food": st.session_state.get("gear_food", "None"),
        "utility": st.session_state.get("gear_utility", "Toxic Focusing Crystal"),
        "sigil_1": st.session_state.get("gear_sigil_1", "Bursting"),
        "sigil_2": st.session_state.get("gear_sigil_2", "None"),
        "infusion": st.session_state.get("gear_infusion", "Malign"),
        "infusion_count": int(st.session_state.get("gear_infusion_count", 18)),
        "rune": st.session_state.get("gear_rune", sorted(data["runes"])[0]),
        "relic": st.session_state.get("gear_relic", sorted(data["relics"])[0]),
        "jade_core": st.session_state.get("gear_jade_core", "Jade Bot Core: Tier 10"),
        "buff_profile": st.session_state.get("gear_buff_profile", BUFF_PROFILE_FULL),
        "custom_buffs": dict(st.session_state.get("gear_custom_buff_state", {})),
        "might_stacks": int(st.session_state.get("gear_might_stacks", 0)),
        "alacrity": bool(st.session_state.get("gear_alacrity", False)),
        "alacrity_uptime": int(st.session_state.get("gear_alacrity_uptime", 100)),
        "quickness": bool(st.session_state.get("gear_quickness", False)),
        "quickness_uptime": int(st.session_state.get("gear_quickness_uptime", 100)),
        "fury": bool(st.session_state.get("gear_fury", False)),
        "fury_uptime": int(st.session_state.get("gear_fury_uptime", 100)),
        "protection": bool(st.session_state.get("gear_protection", False)),
        "protection_uptime": int(st.session_state.get("gear_protection_uptime", 100)),
        "regeneration": bool(st.session_state.get("gear_regeneration", False)),
        "regeneration_uptime": int(st.session_state.get("gear_regeneration_uptime", 100)),
        "resolution": bool(st.session_state.get("gear_resolution", False)),
        "resolution_uptime": int(st.session_state.get("gear_resolution_uptime", 100)),
        "swiftness": bool(st.session_state.get("gear_swiftness", False)),
        "swiftness_uptime": int(st.session_state.get("gear_swiftness_uptime", 100)),
        "vigor": bool(st.session_state.get("gear_vigor", False)),
        "vigor_uptime": int(st.session_state.get("gear_vigor_uptime", 100)),
        "stability": bool(st.session_state.get("gear_stability", False)),
        "stability_uptime": int(st.session_state.get("gear_stability_uptime", 100)),
        "resistance": bool(st.session_state.get("gear_resistance", False)),
        "resistance_uptime": int(st.session_state.get("gear_resistance_uptime", 100)),
        "aegis": bool(st.session_state.get("gear_aegis", False)),
        "aegis_uptime": int(st.session_state.get("gear_aegis_uptime", 100)),
        "fight_duration": float(st.session_state.get("gear_fight_duration", 90.0)),
        "twohand_weapon": st.session_state.get("gear_twohand_weapon", "Spear"),
        "mainhand_weapon": st.session_state.get("gear_mainhand_weapon", "Dagger"),
        "offhand_weapon": st.session_state.get("gear_offhand_weapon", "Pistol"),
        "damage_weapon_slot": st.session_state.get("gear_damage_weapon_slot", "Main hand"),
        "weapon_strength_mode": st.session_state.get("gear_weapon_strength_mode", "Midpoint"),
        "skill_coefficient": float(st.session_state.get("gear_skill_coefficient", 1.0)),
        "slow_uptime": int(st.session_state.get("gear_slow_uptime", 0)),
        "reinforced_armor": bool(st.session_state.get("gear_reinforced_armor", False)),
        "enemy_armor": int(st.session_state.get("gear_enemy_armor", 2597)),
        "enemy_vulnerability": int(st.session_state.get("gear_enemy_vulnerability", 25)),
        "enemy_movement": int(st.session_state.get("gear_enemy_movement", 0)),
        "enemy_interruptible": bool(st.session_state.get("gear_enemy_interruptible", False)),
        "enemy_attack_speed": float(st.session_state.get("gear_enemy_attack_speed", 1.0)),
        "active_sigil_stacks": int(st.session_state.get("gear_active_sigil_stacks", 25)),
        "active_sigil_uptime": int(st.session_state.get("gear_active_sigil_uptime", 100)),
        "spider_venom": {
            "nearby_allies": int(st.session_state.get("gear_spider_venom_nearby_allies", 4)),
            "effective_casts": float(st.session_state.get("gear_spider_venom_effective_casts", 4.0)),
        },
        "traits": current_trait_selection(),
        "trait_preset": str(st.session_state.get("active_trait_preset", "None") or "None"),
        "trait_assumptions": {
            "player_health_pct": float(st.session_state.get("trait_player_health_pct", 100.0)),
            "target_health_pct": float(st.session_state.get("trait_target_health_pct", 100.0)),
            "unique_conditions": float(st.session_state.get("trait_unique_conditions", 10.0)),
            "flanking_or_defiant": bool(st.session_state.get("trait_flanking_or_defiant", True)),
            "revealed_uptime": float(st.session_state.get("trait_revealed_uptime", 0.0)),
            "stealth_uptime": float(st.session_state.get("trait_stealth_uptime", 0.0)),
            "barrier_uptime": float(st.session_state.get("trait_barrier_uptime", 0.0)),
            "combat_high_stacks": float(st.session_state.get("trait_combat_high_stacks", 0.0)),
            "lead_attacks_bonus_pct": float(st.session_state.get("trait_lead_attacks_bonus_pct", 0.0)),
            "weakened_target_uptime": float(st.session_state.get("trait_weakened_target_uptime", 0.0)),
            "nearby_foe_uptime": float(st.session_state.get("trait_nearby_foe_uptime", 0.0)),
            "endurance_not_full_uptime": float(st.session_state.get("trait_endurance_not_full_uptime", 0.0)),
            "marked_target_uptime": float(st.session_state.get("trait_marked_target_uptime", 0.0)),
            "unique_boons": float(_derived_unique_boons_from_buff_state()),
            "distracting_throw_uptime": float(st.session_state.get("trait_distracting_throw_uptime", 0.0)),
            "lotus_training_uptime": float(st.session_state.get("trait_lotus_training_uptime", 0.0)),
            "fluid_strikes_uptime": float(st.session_state.get("trait_fluid_strikes_uptime", 0.0)),
            "unhindered_combatant_uptime": float(st.session_state.get("trait_unhindered_combatant_uptime", 0.0)),
            "bounding_dodger_uptime": float(st.session_state.get("trait_bounding_dodger_uptime", 0.0)),
            "exhilarating_ephemera_uptime": float(st.session_state.get("trait_exhilarating_ephemera_uptime", 0.0)),
        },
    }


def _apply_saved_build(data: dict[str, Any], build: dict[str, Any]) -> None:
    st.session_state["gear_quick_preset"] = build.get("quick_preset", "Custom")
    st.session_state["gear_weapon_mode"] = build.get("weapon_mode", "Two-handed weapon")
    saved_gear = build.get("gear", {})
    for slot, sheet in data["slots"].items():
        options = data["prefix_tables"][sheet]
        value = saved_gear.get(slot, "Viper")
        if value not in options:
            value = "Viper" if "Viper" in options else sorted(options)[0]
        st.session_state[f"gear_slot_{slot}"] = value
        st.session_state["gear_prefixes"][slot] = value

    mappings = {
        "gear_food": ("food", data["food"], "None"),
        "gear_utility": ("utility", data["utility"], "Toxic Focusing Crystal"),
        "gear_sigil_1": ("sigil_1", data["sigils"], "Bursting"),
        "gear_sigil_2": ("sigil_2", data["sigils"], "None"),
        "gear_infusion": ("infusion", data["infusions"], "Malign"),
        "gear_rune": ("rune", data["runes"], sorted(data["runes"])[0]),
        "gear_relic": ("relic", data["relics"], sorted(data["relics"])[0]),
    }
    for state_key, (build_key, options, fallback) in mappings.items():
        value = build.get(build_key, fallback)
        st.session_state[state_key] = value if value in options else fallback

    jade = build.get("jade_core", "Jade Bot Core: Tier 10")
    st.session_state["gear_jade_core"] = jade if jade in JADE_CORE_VITALITY else "Jade Bot Core: Tier 10"
    st.session_state["gear_infusion_count"] = max(0, min(18, int(build.get("infusion_count", 18))))
    st.session_state["gear_might_stacks"] = max(0, min(25, int(build.get("might_stacks", 0))))
    st.session_state["gear_might_enabled"] = st.session_state["gear_might_stacks"] > 0
    for boon in ("alacrity", "quickness", "fury", "protection", "regeneration", "resolution", "swiftness", "vigor", "stability", "resistance", "aegis"):
        st.session_state[f"gear_{boon}"] = bool(build.get(boon, False))
        st.session_state[f"gear_{boon}_uptime"] = max(0, min(100, int(build.get(f"{boon}_uptime", 100))))
    saved_buff_profile = str(build.get("buff_profile", "") or "")
    if saved_buff_profile not in BUFF_PROFILE_OPTIONS:
        saved_buff_profile = (
            BUFF_PROFILE_FULL
            if all(st.session_state.get(key) == value for key, value in FULL_BENCHMARK_BOONS.items())
            else BUFF_PROFILE_CUSTOM
        )
    st.session_state["gear_buff_profile"] = saved_buff_profile
    saved_custom_buffs = build.get("custom_buffs", {})
    st.session_state["gear_custom_buff_state"] = dict(saved_custom_buffs) if isinstance(saved_custom_buffs, dict) else {}
    st.session_state["gear_fight_duration"] = max(1.0, float(build.get("fight_duration", 90.0)))
    # New weapon-loadout fields. Fall back to the legacy single weapon field for older saves.
    legacy_weapon = build.get("weapon_type", "Spear")
    twohand = build.get("twohand_weapon", legacy_weapon)
    mainhand = build.get("mainhand_weapon", "Dagger")
    offhand = build.get("offhand_weapon", "Pistol")
    st.session_state["gear_twohand_weapon"] = twohand if twohand in WEAPON_STRENGTHS else "Spear"
    st.session_state["gear_mainhand_weapon"] = mainhand if mainhand in WEAPON_STRENGTHS else "Dagger"
    st.session_state["gear_offhand_weapon"] = offhand if offhand in WEAPON_STRENGTHS else "Pistol"
    damage_slot = build.get("damage_weapon_slot", "Main hand")
    st.session_state["gear_damage_weapon_slot"] = damage_slot if damage_slot in ("Main hand", "Off hand") else "Main hand"
    mode = build.get("weapon_strength_mode", "Midpoint")
    st.session_state["gear_weapon_strength_mode"] = mode if mode in ("Minimum", "Midpoint", "Maximum") else "Midpoint"
    st.session_state["gear_skill_coefficient"] = max(0.0, float(build.get("skill_coefficient", 1.0)))
    st.session_state["gear_slow_uptime"] = max(0, min(100, int(build.get("slow_uptime", 0))))
    st.session_state["gear_reinforced_armor"] = bool(build.get("reinforced_armor", False))
    st.session_state["gear_enemy_armor"] = max(1, int(build.get("enemy_armor", 2597)))
    st.session_state["gear_enemy_vulnerability"] = max(0, min(25, int(build.get("enemy_vulnerability", 25))))
    st.session_state["gear_enemy_movement"] = max(0, min(100, int(build.get("enemy_movement", 0))))
    st.session_state["gear_enemy_interruptible"] = bool(build.get("enemy_interruptible", False))
    st.session_state["gear_enemy_attack_speed"] = max(0.0, float(build.get("enemy_attack_speed", 1.0)))
    st.session_state["gear_active_sigil_stacks"] = max(0, min(25, int(build.get("active_sigil_stacks", 25))))
    st.session_state["gear_active_sigil_uptime"] = max(0, min(100, int(build.get("active_sigil_uptime", 100))))

    venom_setup = build.get("spider_venom", {})
    # Backward compatible: old builds had no Spider Venom section.
    st.session_state["gear_spider_venom_nearby_allies"] = max(
        0, min(4, int(venom_setup.get("nearby_allies", 4)))
    )
    st.session_state["gear_spider_venom_effective_casts"] = max(
        0.0, float(venom_setup.get("effective_casts", 4.0))
    )

    apply_trait_selection(build.get("traits"))
    saved_trait_preset = str(build.get("trait_preset", "None") or "None")
    st.session_state["active_trait_preset"] = saved_trait_preset
    st.session_state["trait_preset_choice"] = saved_trait_preset
    st.session_state["gear_trait_preset_selection"] = saved_trait_preset
    assumptions = build.get("trait_assumptions", {})
    st.session_state["trait_player_health_pct"] = max(0.0, min(100.0, float(assumptions.get("player_health_pct", 100.0))))
    st.session_state["trait_target_health_pct"] = max(0.0, min(100.0, float(assumptions.get("target_health_pct", 100.0))))
    st.session_state["trait_unique_conditions"] = max(0.0, min(14.0, float(assumptions.get("unique_conditions", 10.0))))
    st.session_state["trait_flanking_or_defiant"] = bool(assumptions.get("flanking_or_defiant", True))
    st.session_state["trait_revealed_uptime"] = max(0.0, min(100.0, float(assumptions.get("revealed_uptime", 0.0))))
    st.session_state["trait_stealth_uptime"] = max(0.0, min(100.0, float(assumptions.get("stealth_uptime", 0.0))))
    st.session_state["trait_barrier_uptime"] = max(0.0, min(100.0, float(assumptions.get("barrier_uptime", 0.0))))
    st.session_state["trait_combat_high_stacks"] = max(0.0, min(10.0, float(assumptions.get("combat_high_stacks", 0.0))))
    st.session_state["trait_lead_attacks_bonus_pct"] = max(0.0, min(15.0, float(assumptions.get("lead_attacks_bonus_pct", 0.0))))
    st.session_state["trait_weakened_target_uptime"] = max(0.0, min(100.0, float(assumptions.get("weakened_target_uptime", 0.0))))
    st.session_state["trait_nearby_foe_uptime"] = max(0.0, min(100.0, float(assumptions.get("nearby_foe_uptime", 0.0))))
    st.session_state["trait_endurance_not_full_uptime"] = max(0.0, min(100.0, float(assumptions.get("endurance_not_full_uptime", 0.0))))
    st.session_state["trait_marked_target_uptime"] = max(0.0, min(100.0, float(assumptions.get("marked_target_uptime", 0.0))))
    # Unique boons are derived from the restored Buff profile; legacy saved values are ignored.
    st.session_state["trait_unique_boons"] = float(_derived_unique_boons_from_buff_state())
    legacy_distracting = float(assumptions.get("distracting_throw_stacks", 0.0))
    distracting_uptime = assumptions.get("distracting_throw_uptime", 100.0 if legacy_distracting > 0 else 0.0)
    st.session_state["trait_distracting_throw_uptime"] = max(0.0, min(100.0, float(distracting_uptime)))
    st.session_state["trait_lotus_training_uptime"] = max(0.0, min(100.0, float(assumptions.get("lotus_training_uptime", 0.0))))
    st.session_state["trait_fluid_strikes_uptime"] = max(0.0, min(100.0, float(assumptions.get("fluid_strikes_uptime", 0.0))))
    st.session_state["trait_unhindered_combatant_uptime"] = max(0.0, min(100.0, float(assumptions.get("unhindered_combatant_uptime", 0.0))))
    st.session_state["trait_bounding_dodger_uptime"] = max(0.0, min(100.0, float(assumptions.get("bounding_dodger_uptime", 0.0))))
    st.session_state["trait_exhilarating_ephemera_uptime"] = max(0.0, min(100.0, float(assumptions.get("exhilarating_ephemera_uptime", 0.0))))


def _save_new_build(data: dict[str, Any]) -> None:
    name = st.session_state.get("gear_build_name", "").strip()
    if not name:
        st.session_state["gear_build_message"] = ("error", "Enter a build name first.")
        return
    builds = _load_saved_builds()
    if name in builds:
        st.session_state["gear_build_message"] = ("error", f'"{name}" already exists. Use Overwrite.')
        return
    builds[name] = _current_build_from_state(data)
    _write_saved_builds(builds)
    st.session_state["gear_saved_build_selection"] = name
    st.session_state["gear_build_message"] = ("success", f'Saved build "{name}".')


def _overwrite_build(data: dict[str, Any]) -> None:
    name = st.session_state.get("gear_saved_build_selection")
    builds = _load_saved_builds()
    if not name or name not in builds:
        st.session_state["gear_build_message"] = ("error", "Select a saved build to overwrite.")
        return
    builds[name] = _current_build_from_state(data)
    _write_saved_builds(builds)
    st.session_state["gear_build_message"] = ("success", f'Overwrote build "{name}".')


def _load_selected_build(data: dict[str, Any]) -> None:
    name = st.session_state.get("gear_saved_build_selection")
    builds = _load_saved_builds()
    if not name or name not in builds:
        st.session_state["gear_build_message"] = ("error", "Select a saved build to load.")
        return

    # The trait preset selector is an independent user choice. Older gear builds
    # often contain ``trait_preset: None``; loading one of those must not erase a
    # preset the user just selected in the Gear Simulator. Capture the visible
    # choice before applying the saved build, because _apply_saved_build restores
    # the build's historical trait link as part of its full state snapshot.
    selected_trait_before_load = str(
        st.session_state.get(
            "gear_trait_preset_selection",
            st.session_state.get("active_trait_preset", "None"),
        )
        or "None"
    )

    build = builds[name]
    _apply_saved_build(data, build)

    trait_presets = load_presets()
    linked_trait = str(build.get("trait_preset", "None") or "None")

    # A currently selected valid trait preset takes priority over an old saved
    # value of None. Otherwise use the build's linked preset when it still exists.
    if selected_trait_before_load in trait_presets:
        effective_trait = selected_trait_before_load
    elif linked_trait in trait_presets:
        effective_trait = linked_trait
    else:
        effective_trait = "None"

    if effective_trait != "None":
        apply_trait_selection(trait_presets[effective_trait])
    st.session_state["active_trait_preset"] = effective_trait
    st.session_state["trait_preset_choice"] = effective_trait
    st.session_state["gear_trait_preset_selection"] = effective_trait

    st.session_state["gear_build_name"] = name
    st.session_state["gear_saved_build_selection"] = name
    suffix = f' with trait preset "{effective_trait}"' if effective_trait != "None" else ""
    st.session_state["gear_build_message"] = ("success", f'Loaded build "{name}"{suffix}.')
    autosave_current_build()


def _delete_selected_build() -> None:
    name = st.session_state.get("gear_saved_build_selection")
    builds = _load_saved_builds()
    if not name or name not in builds:
        st.session_state["gear_build_message"] = ("error", "Select a saved build to delete.")
        return
    del builds[name]
    _write_saved_builds(builds)
    remaining = sorted(builds)
    st.session_state["gear_saved_build_selection"] = remaining[0] if remaining else None
    st.session_state["gear_build_message"] = ("success", f'Deleted build "{name}".')




def _load_trait_preset_from_gear() -> None:
    """Apply the trait preset selected inside Gear Simulator."""
    chosen = str(st.session_state.get("gear_trait_preset_selection", "None") or "None")
    presets = load_presets()
    if chosen == "None":
        st.session_state["active_trait_preset"] = "None"
        st.session_state["trait_preset_choice"] = "None"
        autosave_trait_state()
        autosave_current_build()
        st.session_state["gear_build_message"] = ("info", "Trait preset link cleared. Current trait selections were kept.")
        return
    selection = presets.get(chosen)
    if not isinstance(selection, dict):
        st.session_state["gear_build_message"] = ("error", f'Trait preset "{chosen}" could not be loaded.')
        return
    apply_trait_selection(selection)
    st.session_state["active_trait_preset"] = chosen
    st.session_state["trait_preset_choice"] = chosen
    autosave_trait_state()
    autosave_current_build()
    st.session_state["gear_build_message"] = ("success", f'Loaded trait preset "{chosen}".')

def _render_build_manager(data: dict[str, Any]) -> None:
    builds = _load_saved_builds()
    names = sorted(builds)
    selected = st.session_state.get("gear_saved_build_selection")
    summary = selected if selected in names else (f"{len(names)} saved build{'s' if len(names) != 1 else ''}" if names else "No saved builds")

    with st.expander(f"💾 Saved builds · {summary}", expanded=False):
        top = st.columns([1.15, 1.0, 1.0])
        with top[0]:
            st.text_input(
                "New build name", key="gear_build_name",
                placeholder="Example: Condi Spear Benchmark",
            )
        with top[1]:
            if names:
                current = st.session_state.get("gear_saved_build_selection")
                if current not in names:
                    st.session_state["gear_saved_build_selection"] = names[0]
                st.selectbox("Saved build", names, key="gear_saved_build_selection")
            else:
                st.selectbox("Saved build", ["No saved builds yet"], disabled=True)
                st.session_state["gear_saved_build_selection"] = None
        with top[2]:
            trait_presets = load_presets()
            trait_options = ["None"] + sorted(trait_presets)
            active_trait = str(st.session_state.get("active_trait_preset", "None") or "None")
            if active_trait not in trait_options:
                active_trait = "None"
            if st.session_state.get("gear_trait_preset_selection") not in trait_options:
                st.session_state["gear_trait_preset_selection"] = active_trait
            st.selectbox(
                "Trait preset",
                trait_options,
                key="gear_trait_preset_selection",
                on_change=_load_trait_preset_from_gear,
                help="Select a preset to apply it immediately. Trait presets are created and edited on the Traits page.",
            )

        buttons = st.columns(5)
        buttons[0].button(
            "Save new", use_container_width=True, type="primary",
            on_click=_save_new_build, args=(data,),
        )
        buttons[1].button(
            "Load", use_container_width=True, disabled=not names,
            on_click=_load_selected_build, args=(data,),
        )
        buttons[2].button(
            "Overwrite", use_container_width=True, disabled=not names,
            on_click=_overwrite_build, args=(data,),
        )
        buttons[3].button(
            "Delete", use_container_width=True, disabled=not names,
            on_click=_delete_selected_build,
        )
        buttons[4].button(
            "Reload traits", use_container_width=True,
            on_click=_load_trait_preset_from_gear,
            help="Reapply the selected trait preset without changing gear.",
        )

        message = st.session_state.pop("gear_build_message", None)
        if message:
            level, text = message
            getattr(st, level)(text)
        active_trait = str(st.session_state.get("active_trait_preset", "None") or "None")
        active_buffs = str(st.session_state.get("gear_buff_profile", BUFF_PROFILE_FULL) or BUFF_PROFILE_FULL)
        st.caption(
            f"Active trait preset: {active_trait} · Buff profile: {active_buffs}. "
            "Saved builds store both links under %LOCALAPPDATA%\\ThiefLab."
        )

def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


@st.cache_data(show_spinner=False)
def load_relic_model(relic_name: str) -> dict[str, Any]:
    path = RELIC_DIR / f"{_slugify(relic_name)}.json"
    if not path.exists():
        return {
            "name": f"Relic of the {relic_name}",
            "short_name": relic_name,
            "model": "missing",
            "implemented": False,
            "description": "No relic data file exists for this selection.",
            "static_stats": {},
            "damage_modifiers": {},
            "uptime_model": None,
        }
    return json.loads(path.read_text(encoding="utf-8"))


def calculate_thief_relic_uptime(
    fight_duration: float,
    trigger_interval: float,
    first_trigger: float = 0.0,
    trigger_times: list[float] | None = None,
    stack_duration: float = 6.0,
    max_stacks: int = 5,
) -> dict[str, float | list[float]]:
    """Time-weighted Relic of the Thief stacks for an assumed trigger timeline.

    Each eligible trigger adds one stack, up to the cap, and refreshes the
    expiration time of every active stack. Integration uses exact event
    boundaries, so short fights and delayed openings are handled correctly.
    """
    duration = max(0.0, float(fight_duration))
    if duration <= 0:
        return {
            "trigger_times": [], "average_stacks": 0.0, "any_uptime": 0.0,
            "max_stack_uptime": 0.0, "average_strike_modifier": 0.0,
            "final_stacks": 0.0,
        }

    if trigger_times is None:
        interval = max(0.01, float(trigger_interval))
        t = max(0.0, float(first_trigger))
        triggers: list[float] = []
        while t < duration:
            triggers.append(t)
            t += interval
    else:
        triggers = sorted({float(t) for t in trigger_times if 0.0 <= float(t) < duration})

    events = sorted(set([0.0, duration] + triggers + [min(duration, t + stack_duration) for t in triggers]))
    active_stacks = 0
    expiry = -1.0
    weighted_stacks = 0.0
    any_time = 0.0
    max_time = 0.0
    trigger_set = set(triggers)

    for index, event_time in enumerate(events[:-1]):
        if active_stacks and event_time >= expiry - 1e-9:
            active_stacks = 0
        if event_time in trigger_set:
            active_stacks = min(max_stacks, active_stacks + 1)
            expiry = min(duration, event_time + stack_duration)
        next_time = events[index + 1]
        segment = max(0.0, next_time - event_time)
        weighted_stacks += active_stacks * segment
        if active_stacks > 0:
            any_time += segment
        if active_stacks >= max_stacks:
            max_time += segment

    average_stacks = weighted_stacks / duration
    return {
        "trigger_times": triggers,
        "average_stacks": average_stacks,
        "any_uptime": any_time / duration,
        "max_stack_uptime": max_time / duration,
        "average_strike_modifier": average_stacks * 0.01,
        "final_stacks": float(active_stacks),
    }


@st.cache_data(show_spinner=False)
def load_gear_data() -> dict[str, Any]:
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


@st.cache_data(show_spinner=False)
def load_constants() -> dict[str, Any]:
    return json.loads(CONSTANTS_FILE.read_text(encoding="utf-8"))


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _add_item_stats(total: dict[str, float], item: dict[str, Any], factor: float = 1.0) -> None:
    for stat in CORE_STATS:
        total[stat] += _number(item.get(stat)) * factor


def _rune_formula_value(formula: str, equipped_count: int = 6) -> float:
    """Evaluate the simple COUNT/IFS formulas used by the imported rune sheet."""
    if not formula:
        return 0.0
    cleaned = formula.replace("$", "").replace(" ", "")
    # Ordered IFS conditions: M3>=5,175 or M3=6,125.
    pairs = re.findall(r"M\d*(>=|=)(\d+),(-?\d+(?:\.\d+)?)", cleaned)
    for operator, threshold_text, value_text in pairs:
        threshold = int(threshold_text)
        matches = equipped_count >= threshold if operator == ">=" else equipped_count == threshold
        if matches:
            return float(value_text)
    return 0.0


def calculate_rune_bonus(rune_data: dict[str, Any], equipped_count: int = 6) -> tuple[dict[str, float], dict[str, float]]:
    stats = {stat: 0.0 for stat in CORE_STATS}
    modifiers = {"Boon Duration": 0.0, "Condition Duration": 0.0, "Critical Chance": 0.0}

    formulas = rune_data.get("_formulas", {}) if isinstance(rune_data, dict) else {}
    for key in (*CORE_STATS, *modifiers):
        value = _number(rune_data.get(key))
        formula_value = _rune_formula_value(str(formulas.get(key, "")), equipped_count)
        final_value = formula_value if formula_value else value
        if key in stats:
            stats[key] += final_value
        else:
            modifiers[key] += final_value
    return stats, modifiers


def _apply_utility(stats_before_utility: dict[str, float], utility_name: str, utility_data: dict[str, Any]) -> dict[str, float]:
    result = {stat: 0.0 for stat in CORE_STATS}
    _add_item_stats(result, utility_data)

    power = stats_before_utility["Power"]
    precision = stats_before_utility["Precision"]
    ferocity = stats_before_utility["Ferocity"]
    condition_damage = stats_before_utility["Condition Damage"]
    expertise = stats_before_utility["Expertise"]

    if utility_name == "Master Tuning Crystal":
        result["Condition Damage"] = precision * 0.03 + expertise * 0.08
    elif utility_name == "Toxic Focusing Crystal":
        result["Condition Damage"] = power * 0.03 + precision * 0.03
    elif utility_name == "Toxic Maintenance Oil":
        result["Concentration"] = power * 0.03 + condition_damage * 0.06
    elif utility_name == "Potent Lucent Oil":
        result["Concentration"] = power * 0.03 + precision * 0.03
    elif utility_name == "Furious Sharpening Stone":
        result["Power"] = precision * 0.03
        result["Ferocity"] = precision * 0.03
    elif utility_name == "Superior Sharpening Stone":
        result["Power"] = precision * 0.03 + ferocity * 0.06
    return result


def calculate_selected_stats(
    data: dict[str, Any], selections: dict[str, str], weapon_mode: str,
    food_name: str, utility_name: str, sigil_names: list[str],
    infusion_name: str, infusion_count: int, rune_name: str,
    jade_core_name: str = "None", might_stacks: int = 0,
    active_sigil_stacks: int = 25, active_sigil_uptime: float = 1.0,
) -> tuple[dict[str, float], dict[str, float], dict[str, float], dict[str, dict[str, float]]]:
    gear_only = {stat: 0.0 for stat in CORE_STATS}

    for slot, prefix in selections.items():
        if weapon_mode == "Two-handed weapon" and slot == "Weapon 2":
            continue
        sheet_name = data["slots"][slot]
        prefix_data = data["prefix_tables"][sheet_name].get(prefix, {})
        factor = 2.0 if weapon_mode == "Two-handed weapon" and slot == "Weapon 1" else 1.0
        _add_item_stats(gear_only, prefix_data, factor)

    sources = {
        "Base attributes": dict(BASE_STATS),
        "Equipment": dict(gear_only),
        "Food": {stat: 0.0 for stat in CORE_STATS},
        "Infusions": {stat: 0.0 for stat in CORE_STATS},
        "Sigils (static stats)": {stat: 0.0 for stat in CORE_STATS},
        "Rune set": {stat: 0.0 for stat in CORE_STATS},
        "Utility": {stat: 0.0 for stat in CORE_STATS},
        "Jade Bot Core": {stat: 0.0 for stat in CORE_STATS},
        "Might": {stat: 0.0 for stat in CORE_STATS},
        "Selected traits": {stat: 0.0 for stat in CORE_STATS},
    }

    total = {stat: BASE_STATS[stat] + gear_only[stat] for stat in CORE_STATS}

    food_data = data["food"].get(food_name, {})
    _add_item_stats(sources["Food"], food_data)
    _add_item_stats(total, food_data)

    infusion = data["infusions"].get(infusion_name, {})
    for stat in CORE_STATS:
        bonus = _number(infusion.get(stat)) * infusion_count
        sources["Infusions"][stat] = bonus
        total[stat] += bonus

    for sigil_name in sigil_names:
        sigil_data = data["sigils"].get(sigil_name, {})
        sigil_stats = dict(sigil_data)
        if sigil_name == "Bloodlust":
            sigil_stats["Power"] = 10.0 * max(0, min(25, int(active_sigil_stacks)))
        elif sigil_name == "Cruelty":
            sigil_stats["Ferocity"] = 10.0 * max(0, min(25, int(active_sigil_stacks)))
        elif sigil_name == "Severance":
            uptime = max(0.0, min(1.0, float(active_sigil_uptime)))
            sigil_stats["Precision"] = 250.0 * uptime
            sigil_stats["Ferocity"] = 250.0 * uptime
        _add_item_stats(sources["Sigils (static stats)"], sigil_stats)
        _add_item_stats(total, sigil_stats)

    rune_stats, rune_modifiers = calculate_rune_bonus(data["runes"].get(rune_name, {}), 6)
    for stat in CORE_STATS:
        sources["Rune set"][stat] = rune_stats[stat]
        total[stat] += rune_stats[stat]

    utility_bonus = _apply_utility(total, utility_name, data["utility"].get(utility_name, {}))
    for stat in CORE_STATS:
        sources["Utility"][stat] = utility_bonus[stat]
        total[stat] += utility_bonus[stat]

    jade_vitality = JADE_CORE_VITALITY.get(jade_core_name, 0.0)
    sources["Jade Bot Core"]["Vitality"] = jade_vitality
    total["Vitality"] += jade_vitality

    might_bonus = max(0, min(25, int(might_stacks))) * 30.0
    sources["Might"]["Power"] = might_bonus
    sources["Might"]["Condition Damage"] = might_bonus
    total["Power"] += might_bonus
    total["Condition Damage"] += might_bonus

    trait_stats, trait_modifiers, _trait_sources = calculate_selected_trait_effects()
    for stat, amount in trait_stats.items():
        if stat in total:
            sources["Selected traits"][stat] += float(amount)
            total[stat] += float(amount)
    # Resolve stat conversions after all direct stat sources have been applied.
    precision_to_ferocity = float(trait_modifiers.get("precision_to_ferocity", 0.0))
    if precision_to_ferocity:
        converted = total["Precision"] * precision_to_ferocity
        sources["Selected traits"]["Ferocity"] += converted
        total["Ferocity"] += converted
    power_to_vitality = float(trait_modifiers.get("power_to_vitality", 0.0))
    if power_to_vitality:
        converted = total["Power"] * power_to_vitality
        sources["Selected traits"]["Vitality"] += converted
        total["Vitality"] += converted
    vitality_to_expertise = float(trait_modifiers.get("vitality_to_expertise", 0.0))
    if vitality_to_expertise:
        converted = total["Vitality"] * vitality_to_expertise
        sources["Selected traits"]["Expertise"] += converted
        total["Expertise"] += converted
    condition_to_healing_power = float(trait_modifiers.get("condition_to_healing_power", 0.0))
    if condition_to_healing_power:
        converted = total["Condition Damage"] * condition_to_healing_power
        sources["Selected traits"]["Healing Power"] += converted
        total["Healing Power"] += converted
    conversion_keys = {"precision_to_ferocity", "power_to_vitality", "vitality_to_expertise", "condition_to_healing_power"}
    for key, amount in trait_modifiers.items():
        if key not in conversion_keys:
            rune_modifiers[key] = rune_modifiers.get(key, 0.0) + float(amount)

    return total, gear_only, rune_modifiers, sources


def calculate_metrics(
    stats: dict[str, float], rune_modifiers: dict[str, float],
    sigil_data: list[dict[str, Any]], food_data: dict[str, Any] | None = None,
    fury_uptime: float = 0.0,
) -> dict[str, float | dict[str, float]]:
    food_data = food_data or {}
    extra_crit = rune_modifiers.get("Critical Chance", 0.0) + sum(
        _number(x.get("Critical Chance")) for x in sigil_data
    )
    extra_crit += 0.25 * max(0.0, min(1.0, float(fury_uptime)))
    critical_chance = min(1.0, max(0.0, 0.05 + (stats["Precision"] - 1000.0) / 2100.0 + extra_crit))
    critical_damage = 1.5 + stats["Ferocity"] / 1500.0 + rune_modifiers.get("Critical Damage", 0.0)
    sigil_condition_duration = sum(_number(x.get("Condition Duration")) for x in sigil_data)
    sigil_boon_duration = sum(_number(x.get("Boon Duration")) for x in sigil_data)
    generic_condition_duration = min(1.0, max(0.0, stats["Expertise"] / 1500.0 + rune_modifiers.get("Condition Duration", 0.0) + sigil_condition_duration))
    boon_duration = min(1.0, max(0.0, stats["Concentration"] / 1500.0 + rune_modifiers.get("Boon Duration", 0.0) + sigil_boon_duration))
    specific_durations = {}
    for key in CONDITION_DURATION_KEYS:
        sigil_specific = sum(_number(x.get(key)) for x in sigil_data)
        specific_durations[key] = min(
            1.0,
            generic_condition_duration
            + rune_modifiers.get(key, 0.0)
            + _number(food_data.get(key))
            + sigil_specific,
        )
    effective_power = stats["Power"] * (1.0 + critical_chance * (critical_damage - 1.0))
    return {
        "critical_chance": critical_chance, "critical_damage": critical_damage,
        "condition_duration": generic_condition_duration, "boon_duration": boon_duration,
        "specific_condition_durations": specific_durations,
        "effective_power": effective_power,
    }


def calculate_spider_venom(condition_damage: float, lead_attacks: float, combat_high: float,
                            distracting_throw: float, lotus_training: float,
                            condition_modifier: float, recipient_count: int,
                            vulnerability_stacks: int, effective_casts: float,
                            constants: dict[str, Any], *, power: float = 0.0,
                            healing_power: float = 0.0,
                            leeching_venoms: bool = False) -> dict[str, float]:
    venom = constants["spider_venom"]
    vulnerability_multiplier = 1.0 + min(max(vulnerability_stacks, 0), 25) * venom["vulnerability_per_stack"]
    poison_tick = venom["condition_coefficient"] * condition_damage + venom["base_damage"]
    base_per_cast = (
        poison_tick * venom["ticks"] * venom["applications_per_recipient"]
        * float(recipient_count) * venom["poison_master_multiplier"] * vulnerability_multiplier
    )
    traits = constants["traits"]
    multiplier = (
        1.0 + lead_attacks * traits["lead_attacks_per_stack"]
        + combat_high * traits["combat_high_per_stack"]
        + distracting_throw * traits["distracting_throw_per_stack"]
        + lotus_training * traits["lotus_training"] + condition_modifier
    )
    poison_damage_per_cast = base_per_cast * multiplier
    # Leeching Venoms triggers once per consumed venom strike, not once per poison tick.
    venom_strikes_per_cast = venom["applications_per_recipient"] * float(recipient_count)
    siphon_damage_per_strike = (320.0 + 0.033 * max(0.0, power)) if leeching_venoms else 0.0
    siphon_healing_per_strike = (325.0 + 0.20 * max(0.0, healing_power)) if leeching_venoms else 0.0
    siphon_damage_per_cast = siphon_damage_per_strike * venom_strikes_per_cast
    siphon_healing_per_cast = siphon_healing_per_strike * venom_strikes_per_cast
    damage_per_cast = poison_damage_per_cast + siphon_damage_per_cast
    total_damage = damage_per_cast * effective_casts
    applications_per_cast = (
        venom["ticks"] * venom["applications_per_recipient"] * float(recipient_count)
    )
    return {
        "poison_tick": poison_tick,
        "applications_per_cast": applications_per_cast,
        "vulnerability_multiplier": vulnerability_multiplier,
        "base_per_cast": base_per_cast,
        "multiplier": multiplier,
        "poison_damage_per_cast": poison_damage_per_cast,
        "venom_strikes_per_cast": venom_strikes_per_cast,
        "siphon_damage_per_strike": siphon_damage_per_strike,
        "siphon_damage_per_cast": siphon_damage_per_cast,
        "siphon_healing_per_cast": siphon_healing_per_cast,
        "damage_per_cast": damage_per_cast,
        "effective_casts": effective_casts,
        "total_damage": total_damage,
    }


def _apply_prefix_preset(data: dict[str, Any]) -> None:
    preset = st.session_state.get("gear_quick_preset", "Custom")
    preset_map = {"Full Viper": "Viper", "Full Ritualist": "Ritualist", "Full Sinister": "Sinister"}
    prefix = preset_map.get(preset)
    if not prefix:
        return
    for slot, sheet in data["slots"].items():
        options = data["prefix_tables"][sheet]
        if prefix in options:
            st.session_state[f"gear_slot_{slot}"] = prefix
            st.session_state.setdefault("gear_prefixes", {})[slot] = prefix


def _mark_preset_custom() -> None:
    st.session_state["gear_quick_preset"] = "Custom"


def _select_prefixes(data: dict[str, Any], weapon_mode: str) -> dict[str, str]:
    if "gear_prefixes" not in st.session_state:
        st.session_state["gear_prefixes"] = {slot: "Viper" for slot in data["slots"]}

    selected: dict[str, str] = {}
    with st.expander("Equipment", expanded=False):
        columns = st.columns(2, gap="small")
        visible_index = 0
        for slot in data["slots"]:
            if weapon_mode == "Two-handed weapon" and slot == "Weapon 2":
                selected[slot] = st.session_state["gear_prefixes"].get(slot, "Viper")
                continue
            sheet = data["slots"][slot]
            options = sorted(data["prefix_tables"][sheet])
            key = f"gear_slot_{slot}"
            current = st.session_state.get(key, st.session_state["gear_prefixes"].get(slot, "Viper"))
            if current not in options:
                current = "Viper" if "Viper" in options else options[0]
                st.session_state[key] = current
            label = "2H weapon" if weapon_mode == "Two-handed weapon" and slot == "Weapon 1" else slot
            with columns[visible_index % 2]:
                value = st.selectbox(
                    label, options, index=options.index(current), key=key,
                    on_change=_mark_preset_custom,
                )
                selected[slot] = value
                st.session_state["gear_prefixes"][slot] = value
            visible_index += 1
    return selected

def _capture_custom_buff_state() -> dict[str, Any]:
    """Capture only the editable player-boon controls for the Custom profile."""
    keys = tuple(FULL_BENCHMARK_BOONS)
    return {key: st.session_state.get(key, value) for key, value in FULL_BENCHMARK_BOONS.items()}


def _restore_custom_buff_state() -> None:
    snapshot = st.session_state.get("gear_custom_buff_state")
    if not isinstance(snapshot, dict) or not snapshot:
        # First use of Custom starts from the values that were active before the
        # benchmark profile was chosen, rather than from an empty profile.
        snapshot = {key: st.session_state.get(key, value) for key, value in FULL_BENCHMARK_BOONS.items()}
        st.session_state["gear_custom_buff_state"] = dict(snapshot)
    for key, default in FULL_BENCHMARK_BOONS.items():
        st.session_state[key] = snapshot.get(key, default)


def _mark_buff_profile_custom() -> None:
    """Manual player-boon edits update and persist the separate Custom profile."""
    st.session_state["gear_buff_profile"] = BUFF_PROFILE_CUSTOM
    st.session_state["gear_custom_buff_state"] = _capture_custom_buff_state()
    autosave_current_build()


def _apply_selected_buff_profile() -> None:
    profile = str(st.session_state.get("gear_buff_profile", BUFF_PROFILE_FULL) or BUFF_PROFILE_FULL)
    if profile == BUFF_PROFILE_FULL:
        # Preserve the previous Custom setup before temporarily showing benchmark boons.
        current = {key: st.session_state.get(key) for key in FULL_BENCHMARK_BOONS}
        if current and not all(current.get(key) == value for key, value in FULL_BENCHMARK_BOONS.items()):
            st.session_state["gear_custom_buff_state"] = {
                key: current.get(key, default) for key, default in FULL_BENCHMARK_BOONS.items()
            }
        for key, value in FULL_BENCHMARK_BOONS.items():
            st.session_state[key] = value
    else:
        _restore_custom_buff_state()
    autosave_current_build()


def _uptime_input(boon: str, label: str, help_text: str) -> tuple[bool, float]:
    row = st.columns([1.5, 0.85], gap="small")
    with row[0]:
        enabled = st.checkbox(
            label, key=f"gear_{boon}", help=help_text,
            on_change=_mark_buff_profile_custom,
        )
    with row[1]:
        uptime = st.number_input(
            f"{label} uptime", min_value=0, max_value=100, step=1,
            key=f"gear_{boon}_uptime", disabled=not enabled,
            label_visibility="collapsed", on_change=_mark_buff_profile_custom,
        )
    return enabled, (float(uptime) / 100.0 if enabled else 0.0)


def _render_buffs_panel() -> dict[str, float | bool | int]:
    st.markdown("#### Buffs")
    st.selectbox(
        "Buff profile", list(BUFF_PROFILE_OPTIONS), key="gear_buff_profile",
        on_change=_apply_selected_buff_profile,
        help="Full Benchmark Boons applies 25 Might and 100% uptime for the standard benchmark boons. Any manual edit switches the profile to Custom.",
    )
    if st.session_state.get("gear_buff_profile") == BUFF_PROFILE_FULL:
        for key, value in FULL_BENCHMARK_BOONS.items():
            st.session_state[key] = value
        st.caption("25 Might · 100% Alacrity, Quickness, Fury, Protection, Regeneration, Swiftness, Vigor, Resistance and Aegis · Resolution and Stability off")
    else:
        st.caption("Custom boon setup")

    alacrity, alacrity_uptime = _uptime_input(
        "alacrity", "Alacrity ◐", "Recharge math is implemented. It becomes fully actionable when cooldown-based skills and rotations are added."
    )
    quickness, quickness_uptime = _uptime_input(
        "quickness", "Quickness ◐", "Action-speed math is implemented. It is not yet connected to skill cast times or rotation DPS."
    )
    fury, fury_uptime = _uptime_input(
        "fury", "Fury", "+25 percentage points of critical chance in PvE while active."
    )

    row = st.columns([1.5, 0.85], gap="small")
    with row[0]:
        st.checkbox(
            "Might", key="gear_might_enabled",
            help="Each stack at level 80 adds 30 Power and 30 Condition Damage.",
            on_change=_mark_buff_profile_custom,
        )
    with row[1]:
        might_stacks = st.number_input(
            "Might stacks", min_value=0, max_value=25, step=1, key="gear_might_stacks",
            disabled=not st.session_state.get("gear_might_enabled", False),
            label_visibility="collapsed", on_change=_mark_buff_profile_custom,
        )
    if not st.session_state.get("gear_might_enabled", False):
        might_stacks = 0

    protection, protection_uptime = _uptime_input(
        "protection", "Protection", "Reduces incoming strike damage by 33% while active; the fight-average multiplier is calculated."
    )
    regeneration, regeneration_uptime = _uptime_input(
        "regeneration", "Regeneration", "Calculates average level-80 regeneration healing per second from Healing Power and uptime."
    )
    resolution, resolution_uptime = _uptime_input(
        "resolution", "Resolution", "Reduces incoming condition damage by 33% while active; the fight-average multiplier is calculated."
    )
    swiftness, swiftness_uptime = _uptime_input(
        "swiftness", "Swiftness", "Adds 33% movement speed while active; the fight-average bonus is displayed."
    )
    vigor, vigor_uptime = _uptime_input(
        "vigor", "Vigor", "Adds 50% endurance regeneration while active; the fight-average bonus is displayed."
    )
    stability, stability_uptime = _uptime_input(
        "stability", "Stability", "Player boon. Currently contributes to the unique-boon count; stack-specific combat effects can be added when needed."
    )
    resistance, resistance_uptime = _uptime_input(
        "resistance", "Resistance", "Player boon. Currently contributes to the unique-boon count and indicates immunity to non-damaging condition effects while active."
    )
    aegis, aegis_uptime = _uptime_input(
        "aegis", "Aegis", "Player boon. Counts toward the average unique-boon total; block consumption is not simulated yet."
    )

    return {
        "might_stacks": int(might_stacks),
        "alacrity": alacrity, "alacrity_uptime": alacrity_uptime,
        "quickness": quickness, "quickness_uptime": quickness_uptime,
        "fury": fury, "fury_uptime": fury_uptime,
        "protection": protection, "protection_uptime": protection_uptime,
        "regeneration": regeneration, "regeneration_uptime": regeneration_uptime,
        "resolution": resolution, "resolution_uptime": resolution_uptime,
        "swiftness": swiftness, "swiftness_uptime": swiftness_uptime,
        "vigor": vigor, "vigor_uptime": vigor_uptime,
        "stability": stability, "stability_uptime": stability_uptime,
        "resistance": resistance, "resistance_uptime": resistance_uptime,
        "aegis": aegis, "aegis_uptime": aegis_uptime,
    }

def _calculate_boon_effects(stats: dict[str, float], buffs: dict[str, float | bool | int]) -> dict[str, float]:
    alacrity_uptime = float(buffs["alacrity_uptime"])
    quickness_uptime = float(buffs.get("quickness_uptime", 0.0))
    protection_uptime = float(buffs["protection_uptime"])
    regeneration_uptime = float(buffs["regeneration_uptime"])
    resolution_uptime = float(buffs["resolution_uptime"])
    swiftness_uptime = float(buffs["swiftness_uptime"])
    vigor_uptime = float(buffs["vigor_uptime"])
    # Recharge progresses at 1.25x while Alacrity is active. This is the fight-average recharge multiplier.
    cooldown_multiplier = 1.0 / (1.0 + 0.25 * alacrity_uptime)
    regeneration_hps_active = 130.0 + 0.125 * stats.get("Healing Power", 0.0)
    return {
        "cooldown_multiplier": cooldown_multiplier,
        "recharge_speed_bonus": 0.25 * alacrity_uptime,
        "action_speed_bonus": 0.50 * quickness_uptime,
        "action_time_multiplier": 1.0 / (1.0 + 0.50 * quickness_uptime),
        "strike_damage_taken_multiplier": 1.0 - 0.33 * protection_uptime,
        "condition_damage_taken_multiplier": 1.0 - 0.33 * resolution_uptime,
        "regeneration_hps": regeneration_hps_active * regeneration_uptime,
        "movement_speed_bonus": 0.33 * swiftness_uptime,
        "endurance_regen_bonus": 0.50 * vigor_uptime,
    }


def _apply_reinforced_armor(stats: dict[str, float], gear_only: dict[str, float], enabled: bool) -> dict[str, float]:
    """Apply the PvE Reinforced Armor effect without mutating the base calculation."""
    adjusted = dict(stats)
    if enabled:
        adjusted["Vitality"] *= 1.05
        adjusted["Defense"] += gear_only.get("Defense", 0.0) * 0.05
    return adjusted


def _render_combat_panels(
    stats: dict[str, float],
    metrics: dict[str, float | dict[str, float]],
    rune_modifiers: dict[str, float],
    food_data: dict[str, Any],
    food_name: str,
    selected_sigils: list[str],
    sigil_data: dict[str, Any],
    *,
    show_modifier_audit: bool = False,
) -> dict[str, Any]:
    st.markdown("### Damage engine")
    st.caption("Status: ◐ = partially connected · 🧪 = deliberate test input · ❓ = currently unused. Hover labels for details.")
    settings_col, enemy_col = st.columns([1.12, 1.0], gap="small")

    with settings_col:
        with st.container(border=True):
            st.markdown("#### Settings")
            fight_duration = st.number_input(
                "Fight duration (s) ❓", min_value=1.0, step=1.0, key="gear_fight_duration",
                help="Stored with the build, but not used by the neutral hit or condition calculations yet. It will drive proc counts, condition buildup, and rotation DPS later."
            )
            weapon_configuration = st.session_state.get("gear_weapon_mode", "Two-handed weapon")
            weapon_options = sorted(WEAPON_STRENGTHS)

            if weapon_configuration == "Two-handed weapon":
                weapon_type = st.selectbox(
                    "Weapon", weapon_options, key="gear_twohand_weapon",
                    help="Used correctly for the neutral weapon-strength test. Later, equipped Thief skills will choose their own weapon source automatically."
                )
                damage_weapon_slot = "Two-handed"
                st.caption(f"Damage source: {weapon_type} (two-handed)")
            else:
                weapon_cols = st.columns(2, gap="small")
                with weapon_cols[0]:
                    mainhand_weapon = st.selectbox(
                        "Main hand", weapon_options, key="gear_mainhand_weapon",
                        help="Used for the neutral weapon-strength test. Skill availability and automatic skill-to-weapon mapping are not implemented yet."
                    )
                with weapon_cols[1]:
                    offhand_weapon = st.selectbox(
                        "Off hand", weapon_options, key="gear_offhand_weapon",
                        help="Used for the neutral weapon-strength test. Dual skills and automatic skill-to-weapon mapping are not implemented yet."
                    )
                damage_weapon_slot = st.radio(
                    "Damage source for this neutral hit 🧪",
                    ["Main hand", "Off hand"],
                    horizontal=True,
                    key="gear_damage_weapon_slot",
                    help="Until skills are implemented, choose which equipped weapon supplies weapon strength for the test hit.",
                )
                weapon_type = mainhand_weapon if damage_weapon_slot == "Main hand" else offhand_weapon

            weapon_mode = st.selectbox("Weapon strength roll", ["Minimum", "Midpoint", "Maximum"], key="gear_weapon_strength_mode")
            coefficient = st.number_input(
                "Skill coefficient 🧪", min_value=0.0, step=0.05, format="%.3f", key="gear_skill_coefficient",
                help="Temporary manual test value. It affects the neutral strike calculation, but real Thief skills will supply their coefficients automatically."
            )
            slow_uptime = st.number_input(
                "Slow uptime (%) ❓", min_value=0, max_value=100, step=1, key="gear_slow_uptime",
                help="Currently stored only and does not affect any calculation. It is reserved for future traits, relics, and enemy-state conditions."
            )
            reinforced = st.checkbox("Reinforced Armor", key="gear_reinforced_armor", help="Applies +5% total Vitality and +5% Defense from worn equipment in PvE.")
            with st.expander("Sigil stack assumptions", expanded=False):
                st.number_input(
                    "Active sigil stacks", min_value=0, max_value=25, step=1,
                    key="gear_active_sigil_stacks",
                    help="Used by stacking sigils such as Bloodlust and Cruelty. No longer assumes maximum stacks silently.",
                )
                st.number_input(
                    "Triggered sigil uptime (%) ◐", min_value=0, max_value=100, step=1,
                    key="gear_active_sigil_uptime",
                    help="Currently used by Severance's temporary Precision/Ferocity. Other triggered sigils still require individual proc models.",
                )

    with enemy_col:
        with st.container(border=True):
            st.markdown("#### Enemy")
            enemy_armor = st.number_input("Armor", min_value=1, step=1, key="gear_enemy_armor")
            vulnerability = st.number_input("Vulnerability", min_value=0, max_value=25, step=1, key="gear_enemy_vulnerability")
            movement = st.number_input(
                "Moving uptime (%) ◐", min_value=0, max_value=100, step=1, key="gear_enemy_movement",
                help="Currently affects only the weighted Torment damage row. It does not yet affect skills, traits, positioning, or rotation timing."
            )
            interruptible = st.checkbox(
                "Currently interruptible ❓", key="gear_enemy_interruptible",
                help="Currently stored only and has no effect. It will be used by interrupt-triggered Thief traits, skills, sigils, or relics later."
            )
            attack_speed = st.number_input(
                "Attacks per second ◐", min_value=0.0, step=0.05, format="%.2f", key="gear_enemy_attack_speed",
                help="Partially implemented: used only for the Confusion activation comparison. It is not connected to a full enemy attack or rotation simulation."
            )

    # Damage modifiers are engine output, not user-entered values. Each selected
    # source contributes to an auditable bucket. Bursting is the first fully
    # implemented generic condition-damage sigil.
    global_condition_sources: list[ModifierSource] = []
    additive_strike_sources: list[ModifierSource] = []
    multiplicative_strike_sources: list[tuple[str, float]] = []
    condition_specific_sources: dict[str, list[ModifierSource]] = {}
    for sigil_name in selected_sigils:
        row = sigil_data.get(sigil_name, {})
        condition_bonus = float(_number(row.get("Condition Modifier")))
        strike_bonus = float(_number(row.get("Add. Strike Modifier")))
        if condition_bonus:
            global_condition_sources.append(ModifierSource(f"Sigil of {sigil_name}", condition_bonus))
        if strike_bonus:
            additive_strike_sources.append(ModifierSource(f"Sigil of {sigil_name}", strike_bonus))

    trait_stats, trait_modifier_values, trait_sources = calculate_selected_trait_effects()
    trait_registry = current_trait_effect_registry()
    for effect in trait_registry.for_target("global_condition"):
        global_condition_sources.append(ModifierSource(effect.source, effect.value))
    for effect in trait_registry.for_target("additive_strike"):
        additive_strike_sources.append(ModifierSource(effect.source, effect.value))
    for effect in trait_registry.for_target("multiplicative_strike"):
        multiplicative_strike_sources.append((effect.source, 1.0 + effect.value))
    for condition in ("bleeding", "burning", "poison", "torment", "confusion"):
        for effect in trait_registry.for_target(condition):
            condition_specific_sources.setdefault(condition, []).append(ModifierSource(effect.source, effect.value))

    modifiers = DamageModifiers(
        additive_strike_sources=tuple(additive_strike_sources),
        multiplicative_strike_sources=tuple(multiplicative_strike_sources),
        global_condition_sources=tuple(global_condition_sources),
        condition_specific_sources={key: tuple(value) for key, value in condition_specific_sources.items()},
    )
    selected_strength = get_weapon_strength(weapon_type, weapon_mode)
    strike = calculate_strike_damage(
        power=stats["Power"],
        weapon_strength=selected_strength,
        coefficient=float(coefficient),
        enemy_armor=float(enemy_armor),
        critical_chance=float(metrics["critical_chance"]),
        critical_damage=float(metrics["critical_damage"]),
        vulnerability_stacks=int(vulnerability),
        modifiers=modifiers,
    )
    conditions = calculate_condition_damage(
        condition_damage=stats["Condition Damage"],
        vulnerability_stacks=int(vulnerability),
        modifiers=modifiers,
        enemy_movement_uptime=float(movement) / 100.0,
        enemy_attack_speed=float(attack_speed),
    )

    if show_modifier_audit:
        with st.expander("Calculated damage modifiers", expanded=False):
            st.caption(
                "Read-only engine output. Equipment, sigils, relics and future traits add their own source lines automatically."
            )

            outgoing_condition = 1.0 + modifiers.global_condition
            incoming_damage = strike["vulnerability_factor"]
            final_condition = outgoing_condition * incoming_damage

            summary_cols = st.columns(3)
            summary_cols[0].metric(
                "Outgoing condition",
                f"{outgoing_condition:.2%}",
                help="Your outgoing condition-damage multiplier before enemy effects. Sigil of Bursting adds +5%."
            )
            summary_cols[1].metric(
                "Incoming damage",
                f"{incoming_damage:.2%}",
                help="The enemy-side damage-taken multiplier. Vulnerability adds 1% per stack."
            )
            summary_cols[2].metric(
                "Final condition",
                f"{final_condition:.2%}",
                help="Outgoing condition multiplier multiplied by the enemy incoming-damage multiplier."
            )

            condition_rows = [{
                "Bucket": "Outgoing condition",
                "Source": "Base",
                "Bonus": 0.0,
                "Running factor": 1.0,
            }]
            running = 1.0
            for source in modifiers.global_condition_sources:
                running += source.bonus
                condition_rows.append({
                    "Bucket": "Outgoing condition",
                    "Source": source.name,
                    "Bonus": source.bonus,
                    "Running factor": running,
                })
            condition_rows.append({
                "Bucket": "Incoming damage",
                "Source": f"Vulnerability ({int(vulnerability)} stacks)",
                "Bonus": float(vulnerability) / 100.0,
                "Running factor": incoming_damage,
            })
            condition_rows.append({
                "Bucket": "Final condition",
                "Source": "Outgoing × incoming",
                "Bonus": final_condition - 1.0,
                "Running factor": final_condition,
            })
            st.dataframe(
                pd.DataFrame(condition_rows),
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Bonus": st.column_config.NumberColumn(format="percent"),
                    "Running factor": st.column_config.NumberColumn(format="percent"),
                },
            )

            if modifiers.additive_strike_sources:
                st.markdown("**Strike modifier sources**")
                st.dataframe(
                    pd.DataFrame([
                        {"Source": source.name, "Bonus": source.bonus}
                        for source in modifiers.additive_strike_sources
                    ]),
                    hide_index=True,
                    use_container_width=True,
                    column_config={"Bonus": st.column_config.NumberColumn(format="percent")},
                )
            else:
                st.caption("No outgoing strike-damage modifier sources are active.")
    st.markdown("#### Damage details")
    strike_col, condition_col = st.columns([1.0, 1.35], gap="small")
    with strike_col:
        with st.container(border=True):
            st.markdown("##### Strike")
            st.caption(f"Using {weapon_type} from {damage_weapon_slot.lower()} at the {weapon_mode.lower()} strength roll.")
            row1 = st.columns(3)
            row1[0].metric("Weapon strength", f"{selected_strength:,.1f}")
            row1[1].metric("Normal hit", f'{strike["normal_hit"]:,.1f}')
            row1[2].metric("Critical hit", f'{strike["critical_hit"]:,.1f}')
            row2 = st.columns(3)
            row2[0].metric("Expected hit", f'{strike["expected_hit"]:,.1f}')
            row2[1].metric("Effective Power", f'{strike["effective_power"]:,.0f}')
            row2[2].metric("Total modifier", f'×{strike["total_factor"]:.4f}')
            st.caption("Damage for the selected coefficient. This is damage per hit, not DPS.")
            with st.expander("Strike formula audit"):
                st.dataframe(pd.DataFrame([
                    {"Input": "Power", "Value": stats["Power"]},
                    {"Input": "Weapon", "Value": weapon_type},
                    {"Input": "Weapon strength", "Value": selected_strength},
                    {"Input": "Coefficient", "Value": coefficient},
                    {"Input": "Enemy armor", "Value": enemy_armor},
                    {"Input": "Additive factor", "Value": strike["additive_factor"]},
                    {"Input": "Multiplicative factor", "Value": strike["multiplicative_factor"]},
                    {"Input": "Vulnerability factor", "Value": strike["vulnerability_factor"]},
                ]), hide_index=True, use_container_width=True)

    with condition_col:
        with st.container(border=True):
            st.markdown("##### Conditions")
            st.caption(
                "Compact output first. Open a condition audit only when you want to verify where its damage and duration come from."
            )

            generic_duration = float(metrics["condition_duration"])
            specific_durations = metrics["specific_condition_durations"]
            condition_duration_map = {
                "Bleeding": float(specific_durations.get("Bleeding Duration", generic_duration)),
                "Burning": float(specific_durations.get("Burning Duration", generic_duration)),
                "Poison": float(specific_durations.get("Poison Duration", generic_duration)),
                "Torment": float(specific_durations.get("Torment Duration", generic_duration)),
                "Confusion": float(specific_durations.get("Confusion Duration", generic_duration)),
            }

            summary_names = [
                "Bleeding", "Burning", "Poison", "Torment (weighted)",
                "Confusion (tick)", "Confusion (activation)",
            ]
            summary_rows = []
            for name in summary_names:
                row = conditions[name]
                family = name.split(" (")[0]
                duration_bonus = condition_duration_map.get(family, generic_duration)
                is_activation = name == "Confusion (activation)"
                final_seconds = None if is_activation else 1.0 + duration_bonus
                summary_rows.append({
                    "Condition": name,
                    "Tick damage": row["final_damage"],
                    "Duration": "—" if is_activation else f"+{duration_bonus * 100:.1f}% → {final_seconds:.3f}s",
                    "Total from 1s base": None if is_activation else row["final_damage"] * final_seconds,
                })

            st.dataframe(
                pd.DataFrame(summary_rows),
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Condition": st.column_config.TextColumn(
                        "Condition",
                        help="The damaging condition. Torment weighted uses the selected enemy-movement uptime."
                    ),
                    "Tick damage": st.column_config.NumberColumn(
                        "Tick damage",
                        format="%.2f",
                        help="Damage dealt by one condition stack per second after Condition Damage, condition modifiers, and Vulnerability."
                    ),
                    "Duration": st.column_config.TextColumn(
                        "Duration",
                        help="The outgoing duration bonus and the resulting duration for a hypothetical 1.0-second base application. Example: +72.2% becomes 1.722 seconds."
                    ),
                    "Total from 1s base": st.column_config.NumberColumn(
                        "Total from 1s base",
                        format="%.2f",
                        help="Tick damage multiplied by the resulting duration of a hypothetical 1.0-second base application. This is a comparison aid, not DPS."
                    ),
                },
            )
            st.caption(
                "Hover the column headers for definitions. “Total from 1s base” is a neutral comparison aid, not rotation DPS. "
                "Real skill durations, stacks and application frequency come later with the Thief skill engine."
            )

            expertise_duration = max(0.0, float(stats.get("Expertise", 0.0)) / 1500.0)
            rune_duration = float(rune_modifiers.get("Condition Duration", 0.0))

            audit_names = [
                "Bleeding", "Burning", "Poison", "Torment (stationary)",
                "Torment (moving)", "Torment (weighted)",
                "Confusion (tick)", "Confusion (activation)",
            ]
            for name in audit_names:
                row = conditions[name]
                family = name.split(" (")[0]
                specific_key = f"{family} Duration"
                food_specific = float(_number(food_data.get(specific_key)))
                total_duration = condition_duration_map.get(family, generic_duration)
                is_activation = name == "Confusion (activation)"

                with st.expander(f"{name} audit", expanded=False):
                    if row.get("base") is None:
                        st.write(
                            f"Weighted from stationary and moving Torment using "
                            f"**{float(movement):.0f}% moving uptime**."
                        )
                        st.dataframe(
                            pd.DataFrame([
                                {"State": "Stationary", "Weight": 1.0 - float(movement) / 100.0, "Damage": conditions["Torment (stationary)"]["final_damage"]},
                                {"State": "Moving", "Weight": float(movement) / 100.0, "Damage": conditions["Torment (moving)"]["final_damage"]},
                                {"State": "Weighted result", "Weight": 1.0, "Damage": row["final_damage"]},
                            ]),
                            hide_index=True, use_container_width=True,
                            column_config={
                                "Weight": st.column_config.NumberColumn(format="percent"),
                                "Damage": st.column_config.NumberColumn(format="%.2f"),
                            },
                        )
                    else:
                        formula_rows = [
                            {"Step": "Base damage", "Value": float(row["base"])},
                            {"Step": f'Coefficient × Condition Damage ({float(row["coefficient"]):.4f} × {stats["Condition Damage"]:,.0f})', "Value": float(row["coefficient"]) * stats["Condition Damage"]},
                            {"Step": "Raw damage", "Value": float(row["raw_damage"])},
                            {"Step": "Condition modifier factor", "Value": float(row["modifier_factor"])},
                            {"Step": f'Vulnerability ({int(vulnerability)} stacks)', "Value": float(row["vulnerability_factor"])},
                            {"Step": "Final damage", "Value": float(row["final_damage"])},
                        ]
                        st.dataframe(
                            pd.DataFrame(formula_rows), hide_index=True, use_container_width=True,
                            column_config={"Value": st.column_config.NumberColumn(format="%.4f")},
                        )

                    if not is_activation:
                        st.markdown("**Duration sources**")
                        duration_rows = [
                            {"Source": f'Expertise ({stats.get("Expertise", 0.0):,.0f})', "Bonus": expertise_duration},
                            {"Source": "Rune/global duration", "Bonus": rune_duration},
                        ]
                        if food_specific:
                            duration_rows.append({"Source": food_name, "Bonus": food_specific})
                        duration_rows.append({"Source": "Final duration bonus", "Bonus": total_duration})
                        st.dataframe(
                            pd.DataFrame(duration_rows), hide_index=True, use_container_width=True,
                            column_config={"Bonus": st.column_config.NumberColumn(format="percent")},
                        )
                        st.info(
                            f"A skill with a 1.0-second base {family.lower()} duration lasts "
                            f"**{1.0 + total_duration:.3f} seconds** and deals approximately "
                            f"**{row['final_damage'] * (1.0 + total_duration):,.2f} total damage per stack**."
                        )
                    else:
                        st.info(
                            "Confusion activation damage occurs when the enemy activates a skill. "
                            "Condition duration affects how long the stack can trigger, not the damage of one activation."
                        )

                    st.markdown("**Affected by**")
                    st.write(
                        "Condition Damage · Vulnerability · Global condition modifiers · "
                        f"{family}-specific modifiers"
                        + (" · Condition duration" if not is_activation else "")
                    )

    return {
        "fight_duration": float(fight_duration),
        "weapon_configuration": weapon_configuration,
        "weapon_type": weapon_type,
        "twohand_weapon": st.session_state.get("gear_twohand_weapon", "Spear"),
        "mainhand_weapon": st.session_state.get("gear_mainhand_weapon", "Dagger"),
        "offhand_weapon": st.session_state.get("gear_offhand_weapon", "Pistol"),
        "damage_weapon_slot": damage_weapon_slot,
        "weapon_strength_mode": weapon_mode,
        "weapon_strength": selected_strength,
        "skill_coefficient": float(coefficient),
        "slow_uptime": float(slow_uptime) / 100.0,
        "reinforced_armor": bool(reinforced),
        "enemy_armor": float(enemy_armor),
        "vulnerability_stacks": int(vulnerability),
        "enemy_movement": float(movement) / 100.0,
        "enemy_interruptible": bool(interruptible),
        "enemy_attack_speed": float(attack_speed),
        "modifiers": modifiers,
        "strike": strike,
        "conditions": conditions,
    }


def _render_damage_modifier_audit(combat: dict[str, Any]) -> None:
    """Render the shared modifier buckets once, in Developer tools."""
    modifiers = combat.get("modifiers")
    strike = combat.get("strike", {})
    vulnerability = int(combat.get("vulnerability_stacks", 0))
    if modifiers is None:
        return
    with st.expander("Damage modifier buckets", expanded=False):
        st.caption("Shared outgoing and enemy-side modifier groups used by the neutral strike and condition reference calculations.")
        outgoing_condition = 1.0 + modifiers.global_condition
        incoming_damage = float(strike.get("vulnerability_factor", 1.0))
        final_condition = outgoing_condition * incoming_damage
        summary_cols = st.columns(3)
        summary_cols[0].metric("Outgoing condition modifier", f"{outgoing_condition:.2%}")
        summary_cols[1].metric("Enemy damage-taken modifier", f"{incoming_damage:.2%}")
        summary_cols[2].metric("Final condition multiplier", f"{final_condition:.2%}")
        rows = [{"Bucket": "Outgoing condition", "Source": "Base", "Bonus": 0.0, "Running factor": 1.0}]
        running = 1.0
        for source in modifiers.global_condition_sources:
            running += source.bonus
            rows.append({"Bucket": "Outgoing condition", "Source": source.name, "Bonus": source.bonus, "Running factor": running})
        rows.append({"Bucket": "Enemy damage taken", "Source": f"Vulnerability ({vulnerability} stacks)", "Bonus": vulnerability / 100.0, "Running factor": incoming_damage})
        rows.append({"Bucket": "Final condition", "Source": "Outgoing × enemy", "Bonus": final_condition - 1.0, "Running factor": final_condition})
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True, column_config={
            "Bonus": st.column_config.NumberColumn(format="percent"),
            "Running factor": st.column_config.NumberColumn(format="percent"),
        })
        st.markdown("**Outgoing strike modifier sources**")
        strike_rows = [{"Source": x.name, "Bonus": x.bonus, "Group": "Additive"} for x in modifiers.additive_strike_sources]
        strike_rows += [{"Source": name, "Bonus": factor - 1.0, "Group": "Multiplicative"} for name, factor in modifiers.multiplicative_strike_sources]
        if strike_rows:
            st.dataframe(pd.DataFrame(strike_rows), hide_index=True, use_container_width=True, column_config={"Bonus": st.column_config.NumberColumn(format="percent")})
        else:
            st.caption("No outgoing strike modifiers are active.")


def _render_trait_validation_checks() -> None:
    """Keep representative regression checks out of the normal results view."""
    registry = current_trait_effect_registry()
    selected_ids = selected_trait_ids()
    with st.expander("Trait integration validation", expanded=False):
        effect_index = {(effect.source_id, effect.target): effect.value for effect in registry.effects}
        checks = [
            (1164, "Deadly Ambition", "Condition Damage", 180.0, "+180 Condition Damage"),
            (1291, "Potent Poison", "poison", 0.33, "+33% poison damage"),
            (1291, "Potent Poison", "Poison Duration", 0.33, "+33% poison duration"),
            (1157, "Lead Attacks", "additive_strike", None, "configured strike bonus"),
            (1157, "Lead Attacks", "global_condition", None, "configured condition bonus"),
            (2348, "Combat High", "additive_strike", None, "3% strike damage per configured stack"),
            (2348, "Combat High", "global_condition", None, "2% condition damage per configured stack"),
            (1269, "Executioner", "multiplicative_strike", 0.20, "+20% strike damage below 50% target health"),
            (2136, "One in the Chamber", "stolen_skill_damage", 0.25, "+25% matching stolen-skill damage"),
        ]
        rows = []
        selected_set = set(selected_ids)
        for trait_id, name, target, expected, description in checks:
            if trait_id not in selected_set:
                state, actual = "Not selected", "—"
            elif (trait_id, target) in effect_index:
                value = float(effect_index[(trait_id, target)])
                state = "PASS" if expected is None or abs(value - expected) < 1e-9 else "CHECK"
                actual = _format_trait_effect_value(target, value, "modifier_add")
            else:
                state, actual = "Inactive condition / missing", "0"
            rows.append({"Trait": name, "Expected behavior": description, "Current result": actual, "Status": state})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption("Executioner requires target health below 50%. Lead Attacks and Combat High require non-zero assumptions.")


def _format_trait_effect_value(target: str, value: float, kind: str) -> str:
    """Format a resolved trait effect for the user-facing audit."""
    stat_like = {
        "Power", "Precision", "Ferocity", "Condition Damage", "Expertise",
        "Concentration", "Vitality", "Toughness", "Defense", "Healing Power",
    }
    if target in stat_like:
        return f"{value:+,.0f}"
    if kind == "conversion" or target.endswith("_to_ferocity") or target.endswith("_to_expertise"):
        return f"{value:+.1%}"
    return f"{value:+.1%}"


def _render_active_trait_effects_panel(*, include_validation: bool = False) -> None:
    """Show exactly which selected trait effects are active and which still need events."""
    _stats, _modifiers, trait_sources = calculate_selected_trait_effects()
    registry = current_trait_effect_registry()
    selected_ids = selected_trait_ids()

    with st.container(border=True):
        st.markdown("### Active trait effects")
        st.caption(
            "This is the live bridge between Traits and Gear Simulator. Every row below is currently affecting the shared build. "
            "Event-only parts stay visible separately so they are not forgotten."
        )

        applied_rows: list[dict[str, Any]] = []
        for effect in registry.effects:
            applied_rows.append({
                "Trait": effect.source,
                "Effect": effect.target.replace("_", " "),
                "Amount": _format_trait_effect_value(effect.target, effect.value, effect.kind.value),
                "Condition": effect.condition or "Always",
                "Used by": effect.destination or "Shared calculator",
            })

        pending_rows: list[dict[str, Any]] = []
        for source in trait_sources:
            for pending in source.get("pending", []):
                pending_rows.append({
                    "Trait": source.get("trait_name", "Unknown"),
                    "Waiting for": str(pending),
                })

        summary = st.columns(4, gap="small")
        summary[0].metric("Selected traits", len(selected_ids))
        summary[1].metric("Applied effects", len(applied_rows))
        summary[2].metric("Event / pending parts", len(pending_rows))
        summary[3].metric("Link status", "Connected" if applied_rows or not selected_ids else "Needs mapping")

        if applied_rows:
            st.dataframe(pd.DataFrame(applied_rows), use_container_width=True, hide_index=True)
        elif selected_ids:
            st.warning("Traits are selected, but no resolved effect is currently reaching the calculator.")
        else:
            st.info("Select a build on the Traits page to populate this audit.")

        with st.expander("Event-based and conditional parts still waiting", expanded=False):
            if pending_rows:
                st.dataframe(pd.DataFrame(pending_rows), use_container_width=True, hide_index=True)
            else:
                st.success("No pending trait parts for the current selection.")

        if include_validation:
            with st.expander("Representative validation checks", expanded=False):
                effect_index = {(effect.source_id, effect.target): effect.value for effect in registry.effects}
                checks = [
                    (1164, "Deadly Ambition", "Condition Damage", 180.0, "+180 Condition Damage"),
                    (1291, "Potent Poison", "poison", 0.33, "+33% poison damage"),
                    (1291, "Potent Poison", "Poison Duration", 0.33, "+33% poison duration"),
                    (1157, "Lead Attacks", "additive_strike", None, "configured strike bonus"),
                    (1157, "Lead Attacks", "global_condition", None, "configured condition bonus"),
                    (2348, "Combat High", "additive_strike", None, "3% strike damage per configured stack"),
                    (2348, "Combat High", "global_condition", None, "2% condition damage per configured stack"),
                    (1269, "Executioner", "multiplicative_strike", 0.20, "+20% strike damage below 50% target health"),
                    (2136, "One in the Chamber", "stolen_skill_damage", 0.25, "+25% matching stolen-skill damage"),
                ]
                validation_rows = []
                selected_set = set(selected_ids)
                for trait_id, trait_name, target, expected, description in checks:
                    if trait_id not in selected_set:
                        state = "Not selected"
                        actual = "—"
                    elif (trait_id, target) in effect_index:
                        value = float(effect_index[(trait_id, target)])
                        tolerance_ok = expected is None or abs(value - expected) < 1e-9
                        state = "PASS" if tolerance_ok else "CHECK"
                        actual = _format_trait_effect_value(target, value, "modifier_add")
                    else:
                        state = "Inactive condition / missing"
                        actual = "0"
                    validation_rows.append({
                        "Trait": trait_name,
                        "Expected behavior": description,
                        "Current result": actual,
                        "Status": state,
                    })
                st.dataframe(pd.DataFrame(validation_rows), use_container_width=True, hide_index=True)
                st.caption("Executioner only passes below 50% target health. Lead Attacks and Combat High only pass when their assumption values are above zero.")


def render_gear_simulator_page() -> None:
    data, constants = load_gear_data(), load_constants()
    _ensure_gear_widget_defaults(data)
    st.title("Gear Simulator")
    st.caption("Build static equipment stats, then use those stats in separate combat estimates.")
    st.markdown(
        """
        <style>
        .block-container { max-width: min(1920px, calc(100vw - 245px)) !important; width: calc(100vw - 275px) !important; padding-left: 1.15rem; padding-right: 1.15rem; }
        div[data-testid="stVerticalBlock"] { gap: 0.42rem; }
        div[data-testid="stExpander"] details summary { padding-top: .48rem; padding-bottom: .48rem; }
        div[data-testid="stMetric"] { padding: .48rem .62rem; }
        div[data-testid="stMetric"] label { font-size: .78rem; }
        div[data-testid="stMetricValue"] { font-size: 1.35rem; }
        .stSelectbox label, .stNumberInput label, .stTextInput label { font-size: .78rem; }

        /* Gear Simulator tab navigation */
        div[data-testid="stTabs"] > div[data-baseweb="tab-list"] {
            display: flex !important;
            align-items: center !important;
            gap: .42rem !important;
            width: 100% !important;
            padding: .38rem !important;
            margin: .45rem 0 .72rem 0 !important;
            background: #15171d !important;
            border: 1px solid rgba(255,255,255,.10) !important;
            border-radius: 10px !important;
            box-shadow: inset 0 1px 0 rgba(255,255,255,.025) !important;
            overflow-x: auto !important;
        }
        div[data-testid="stTabs"] > div[data-baseweb="tab-list"] button[data-baseweb="tab"] {
            flex: 0 0 auto !important;
            min-height: 2.35rem !important;
            padding: .54rem .86rem !important;
            margin: 0 !important;
            border: 1px solid transparent !important;
            border-radius: 7px !important;
            background: transparent !important;
            color: #aeb3be !important;
            font-weight: 650 !important;
            font-size: .82rem !important;
            letter-spacing: .005em !important;
            transition: background .14s ease, border-color .14s ease, color .14s ease !important;
        }
        div[data-testid="stTabs"] > div[data-baseweb="tab-list"] button[data-baseweb="tab"]:hover {
            background: #24272f !important;
            border-color: rgba(255,255,255,.08) !important;
            color: #f4f5f7 !important;
        }
        div[data-testid="stTabs"] > div[data-baseweb="tab-list"] button[data-baseweb="tab"][aria-selected="true"] {
            background: linear-gradient(180deg, #48252c 0%, #372027 100%) !important;
            border-color: #d64a58 !important;
            color: #ffffff !important;
            box-shadow: 0 0 0 1px rgba(214,74,88,.12), 0 4px 12px rgba(0,0,0,.18) !important;
        }
        div[data-testid="stTabs"] > div[data-baseweb="tab-list"] div[data-baseweb="tab-highlight"] {
            display: none !important;
        }

        /* Nested tab row: quieter than the main section tabs */
        div[data-testid="stTabs"] div[data-testid="stTabs"] > div[data-baseweb="tab-list"] {
            padding: .24rem .30rem !important;
            margin: .18rem 0 .70rem 0 !important;
            gap: .22rem !important;
            background: #111318 !important;
            border-color: rgba(255,255,255,.075) !important;
            border-radius: 8px !important;
        }
        div[data-testid="stTabs"] div[data-testid="stTabs"] > div[data-baseweb="tab-list"] button[data-baseweb="tab"] {
            min-height: 2.02rem !important;
            padding: .42rem .72rem !important;
            font-size: .76rem !important;
            font-weight: 600 !important;
            border-radius: 6px !important;
        }
        div[data-testid="stTabs"] div[data-testid="stTabs"] > div[data-baseweb="tab-list"] button[data-baseweb="tab"][aria-selected="true"] {
            background: rgba(214,74,88,.13) !important;
            border-color: rgba(214,74,88,.58) !important;
            color: #ffffff !important;
            box-shadow: inset 0 -2px 0 #e04f5d !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    gear_tab, venom_tab, relic_tab, data_tab = st.tabs(["Gear & stats", "Spider Venom", "Relic analysis", "Data & assumptions"])

    with gear_tab:
        _render_build_manager(data)

        setup_tab, simulation_tab, audits_tab = st.tabs([
            "Build setup", "Results", "Developer tools"
        ])

        with setup_tab:
            gear_col, upgrades_col, buffs_col = st.columns([1.55, 1.15, 0.9], gap="medium")

            with gear_col:
                with st.container(border=True):
                    st.markdown("#### Equipment")
                    controls = st.columns([1.0, 1.0], gap="small")
                    with controls[0]:
                        st.selectbox(
                            "Equipment preset", ["Custom", "Full Viper", "Full Ritualist", "Full Sinister"],
                            key="gear_quick_preset", on_change=_apply_prefix_preset, args=(data,),
                        )
                    with controls[1]:
                        weapon_mode = st.selectbox(
                            "Weapon configuration", ["Two-handed weapon", "Main hand + off hand"], key="gear_weapon_mode"
                        )
                    st.caption("Spear: choose Two-handed weapon; its stats count as two one-handed weapon blocks.")
                    selected_prefixes = _select_prefixes(data, weapon_mode)

            with upgrades_col:
                with st.container(border=True):
                    st.markdown("#### Upgrades & consumables")
                    food_options = sorted(data["food"])
                    food = st.selectbox("Food", food_options, key="gear_food")
                    utility_options = sorted(data["utility"])
                    utility = st.selectbox("Utility", utility_options, key="gear_utility")
                    selected_rune = st.selectbox("Rune set", sorted(data["runes"]), key="gear_rune")
                    selected_relic = st.selectbox(
                        "Relic ❓", sorted(data["relics"]), key="gear_relic",
                        help="Most relics are selectable by name only. Only relics with a dedicated model affect combat calculations."
                    )
                    sigil_cols = st.columns(2, gap="small")
                    sigil_options = sorted(data["sigils"])
                    with sigil_cols[0]:
                        sigil_1 = st.selectbox(
                            "Sigil 1 ❓", sigil_options, key="gear_sigil_1",
                            help="Static stats and supported modifiers work. Most triggered/proc sigils are not yet simulated."
                        )
                    with sigil_cols[1]:
                        sigil_2 = st.selectbox(
                            "Sigil 2 ❓", sigil_options, key="gear_sigil_2",
                            help="Static stats and supported modifiers work. Most triggered/proc sigils are not yet simulated."
                        )
                    jade_core = st.selectbox("Jade Bot Core", list(JADE_CORE_VITALITY), key="gear_jade_core")
                    inf_cols = st.columns([1.45, .75], gap="small")
                    with inf_cols[0]:
                        infusion_options = sorted(data["infusions"])
                        infusion = st.selectbox("Infusion", infusion_options, key="gear_infusion")
                    with inf_cols[1]:
                        infusion_count = st.number_input("Count", 0, 18, step=1, key="gear_infusion_count")

                    supported_sigils = {"None", "Accuracy", "Agony", "Bloodlust", "Bursting", "Concentration", "Cruelty", "Demons", "Force", "Malice", "Ruby Orb", "Severance", "Smoldering", "Venom"}
                    unsupported = [name for name in [sigil_1, sigil_2] if name not in supported_sigils]
                    if unsupported:
                        st.caption("⚠ Not fully simulated: " + ", ".join(sorted(set(unsupported))))

            with buffs_col:
                with st.container(border=True):
                    buffs = _render_buffs_panel()
            render_trait_assumptions(expanded=False, popover=False)

        might_stacks = int(buffs["might_stacks"])
        total_stats, gear_only, rune_modifiers, stat_sources = calculate_selected_stats(
            data, selected_prefixes, weapon_mode, food, utility, [sigil_1, sigil_2],
            infusion, int(infusion_count), selected_rune, jade_core, int(might_stacks),
            int(st.session_state.get("gear_active_sigil_stacks", 25)),
            float(st.session_state.get("gear_active_sigil_uptime", 100)) / 100.0,
        )
        pre_reinforced_stats = dict(total_stats)
        total_stats = _apply_reinforced_armor(
            total_stats, gear_only, bool(st.session_state.get("gear_reinforced_armor", False))
        )
        reinforced_source = {stat: 0.0 for stat in CORE_STATS}
        reinforced_source["Vitality"] = total_stats["Vitality"] - pre_reinforced_stats["Vitality"]
        reinforced_source["Defense"] = total_stats["Defense"] - pre_reinforced_stats["Defense"]
        if reinforced_source["Vitality"] or reinforced_source["Defense"]:
            stat_sources["Reinforced Armor"] = reinforced_source
        sigil_rows = [data["sigils"].get(sigil_1, {}), data["sigils"].get(sigil_2, {})]
        metrics = calculate_metrics(
            total_stats, rune_modifiers, sigil_rows, data["food"].get(food, {}), float(buffs["fury_uptime"])
        )
        boon_effects = _calculate_boon_effects(total_stats, buffs)

        st.session_state["gear_sim_total_stats"] = total_stats
        st.session_state["gear_sim_metrics"] = metrics
        st.session_state["gear_sim_selected_sigils"] = [sigil_1, sigil_2]
        st.session_state["gear_sim_selected_relic"] = selected_relic
        st.session_state["gear_sim_buffs"] = {**buffs, **boon_effects}
        st.session_state["shared_selected_trait_ids"] = selected_trait_ids()
        st.session_state["shared_trait_effects"] = current_trait_effect_registry().serialize()

        health = THIEF_BASE_HEALTH + 10.0 * total_stats["Vitality"]
        armor = total_stats["Defense"] + total_stats["Toughness"]

        with simulation_tab:
            selected_ids = selected_trait_ids()
            active_registry = current_trait_effect_registry()
            active_effect_count = len(active_registry.effects)
            status_cols = st.columns([1.2, 1.2, 2.6], gap="small")
            status_cols[0].metric("Selected traits", len(selected_ids))
            status_cols[1].metric("Active trait effects", active_effect_count)
            if selected_ids and active_effect_count:
                status_cols[2].success("Traits are linked to this calculation. Open Developer tools to inspect modifier sources and validation checks.")
            elif selected_ids:
                status_cols[2].warning("Traits are selected, but none of the selected effects is currently calculator-ready. Check Trait Progress / the trait audit.")
            else:
                status_cols[2].info("No traits selected yet. Choose them on the Traits page; this result updates automatically.")

            _render_active_trait_effects_panel(include_validation=False)

            st.markdown("### Key stats")
            key_metrics = [
                ("Power", f'{total_stats["Power"]:,.0f}'),
                ("Precision", f'{total_stats["Precision"]:,.0f}'),
                ("Ferocity", f'{total_stats["Ferocity"]:,.0f}'),
                ("Condition Damage", f'{total_stats["Condition Damage"]:,.0f}'),
                ("Expertise", f'{total_stats["Expertise"]:,.0f}'),
                ("Critical chance", f'{metrics["critical_chance"]:.2%}'),
                ("Critical damage", f'{metrics["critical_damage"]:.2%}'),
                ("Condition duration", f'{metrics["condition_duration"]:.2%}'),
            ]
            stat_cols = st.columns(len(key_metrics), gap="small")
            for col, (label, value) in zip(stat_cols, key_metrics):
                col.metric(label, value)

            with st.expander("Secondary & defensive stats", expanded=False):
                secondary = [
                    ("Vitality", f'{total_stats["Vitality"]:,.0f}'),
                    ("Health", f'{health:,.0f}'),
                    ("Toughness", f'{total_stats["Toughness"]:,.0f}'),
                    ("Defense", f'{total_stats["Defense"]:,.0f}'),
                    ("Armor", f'{armor:,.0f}'),
                    ("Boon duration", f'{metrics["boon_duration"]:.2%}'),
                    ("Effective power", f'{metrics["effective_power"]:,.0f}'),
                ]
                cols = st.columns(len(secondary), gap="small")
                for col, (label, value) in zip(cols, secondary):
                    col.metric(label, value)

            st.markdown("### Simulation")
            combat_assumptions = _render_combat_panels(
                total_stats, metrics, rune_modifiers, data["food"].get(food, {}), food,
                [sigil_1, sigil_2], data["sigils"]
            )
            st.session_state["gear_sim_combat_assumptions"] = combat_assumptions

            with st.expander("Active build effects", expanded=False):
                buff_cards = st.columns(7, gap="small")
                values = [
                    ("Cooldown", f'{boon_effects["cooldown_multiplier"]:.1%}'),
                    ("Strike taken", f'{boon_effects["strike_damage_taken_multiplier"]:.1%}'),
                    ("Condition taken", f'{boon_effects["condition_damage_taken_multiplier"]:.1%}'),
                    ("Regeneration", f'{boon_effects["regeneration_hps"]:,.1f} HP/s'),
                    ("Move speed", f'+{boon_effects["movement_speed_bonus"]:.1%}'),
                    ("Endurance regen", f'+{boon_effects["endurance_regen_bonus"]:.1%}'),
                    ("Fury crit", f'+{0.25 * float(buffs["fury_uptime"]):.1%}'),
                ]
                for col, (label, value) in zip(buff_cards, values):
                    col.metric(label, value)

                rune_stats, _ = calculate_rune_bonus(data["runes"].get(selected_rune, {}), 6)
                rune_text = ", ".join(f"+{v:g} {k}" for k, v in rune_stats.items() if v) or "No static attribute bonus"
                st.success(f"Rune of the {selected_rune}: {rune_text}.")
                relic_model = load_relic_model(selected_relic)
                if relic_model.get("implemented"):
                    st.info(f"{relic_model.get('name', selected_relic)}: {relic_model.get('description', '')}")
                else:
                    st.warning(f"{relic_model.get('name', selected_relic)}: {relic_model.get('description', 'Dedicated model not implemented.')}")

        with audits_tab:
            st.caption("Technical diagnostics live here. User-facing results and per-skill formulas stay beside the result they explain.")
            if combat_assumptions:
                _render_damage_modifier_audit(combat_assumptions)
            _render_trait_validation_checks()

            with st.expander("Engine status", expanded=False):
                st.markdown("""
- **Complete now:** gear, runes, food, utility, infusions, Jade Core, Might, Fury, supported sigil effects, weapon strength, strike reference math, condition tick math, duration math, Vulnerability and survivability stats.
- **Partially connected:** Alacrity, Quickness, moving-target uptime, enemy attacks per second and triggered-sigil uptime.
- **Not used yet:** fight duration, Slow uptime and interruptible state.
- **Still individual work:** unsupported proc sigils and most relic effects.
""")

            with st.expander("Stat source audit", expanded=False):
                source_rows = []
                for source_name, source_values in stat_sources.items():
                    row = {"Source": source_name}
                    row.update({stat: source_values.get(stat, 0.0) for stat in CORE_STATS})
                    source_rows.append(row)
                total_row = {"Source": "FINAL TOTAL"}
                total_row.update(total_stats)
                source_rows.append(total_row)
                st.dataframe(
                    pd.DataFrame(source_rows), hide_index=True, use_container_width=True,
                    column_config={stat: st.column_config.NumberColumn(format="%.0f") for stat in CORE_STATS},
                )

            with st.expander("Vitality, Health & Armor audit", expanded=False):
                survivability_rows = [{
                    "Source": "Thief profession base health", "Vitality": 0.0,
                    "Health contribution": THIEF_BASE_HEALTH, "Toughness": 0.0,
                    "Defense": 0.0, "Armor contribution": 0.0,
                }]
                for source_name, source_values in stat_sources.items():
                    vitality_value = source_values.get("Vitality", 0.0)
                    toughness_value = source_values.get("Toughness", 0.0)
                    defense_value = source_values.get("Defense", 0.0)
                    survivability_rows.append({
                        "Source": source_name,
                        "Vitality": vitality_value,
                        "Health contribution": vitality_value * 10.0,
                        "Toughness": toughness_value,
                        "Defense": defense_value,
                        "Armor contribution": toughness_value + defense_value,
                    })
                survivability_rows.append({
                    "Source": "FINAL TOTAL", "Vitality": total_stats["Vitality"],
                    "Health contribution": health, "Toughness": total_stats["Toughness"],
                    "Defense": total_stats["Defense"], "Armor contribution": armor,
                })
                st.dataframe(pd.DataFrame(survivability_rows), hide_index=True, use_container_width=True)
                st.caption("Health = 1,645 Thief base health + 10 × Vitality. Armor = Toughness + Defense.")

            with st.expander("Duration audit", expanded=False):
                duration_rows = [
                    {"Duration": "Generic condition duration", "Value": f'{metrics["condition_duration"]:.1%}'},
                    *[
                        {"Duration": name, "Value": f'{value:.1%}'}
                        for name, value in metrics["specific_condition_durations"].items()
                        if value > metrics["condition_duration"]
                    ],
                    {"Duration": "Boon duration", "Value": f'{metrics["boon_duration"]:.1%}'},
                ]
                st.dataframe(pd.DataFrame(duration_rows), hide_index=True, use_container_width=True)

    with venom_tab:
        stats = st.session_state.get("gear_sim_total_stats")
        if not stats:
            st.info("Open **Gear & stats** once so the selected build can be calculated.")
        else:
            st.subheader("Spider Venom contribution")
            st.caption("Estimates the total ally Spider Venom damage contributed by the selected build. This is one damage source, not complete personal DPS.")

            condition_modifier = sum(
                _number(data["sigils"].get(x, {}).get("Condition Modifier"))
                for x in st.session_state.get("gear_sim_selected_sigils", [])
            )
            relic = st.session_state.get("gear_sim_selected_relic", "")
            condition_modifier += _number(
                load_relic_model(relic).get("damage_modifiers", {}).get("condition_damage")
            )

            active_trait_ids = selected_trait_ids()
            lead_bonus_pct = (
                float(st.session_state.get("trait_lead_attacks_bonus_pct", 0.0))
                if 1157 in active_trait_ids else 0.0
            )
            combat_high_stacks = (
                float(st.session_state.get("trait_combat_high_stacks", 0.0))
                if 2348 in active_trait_ids else 0.0
            )
            distracting_throw_uptime = float(st.session_state.get("trait_distracting_throw_uptime", 0.0))
            lotus_training_uptime = (
                float(st.session_state.get("trait_lotus_training_uptime", 0.0))
                if 1833 in active_trait_ids else 0.0
            )
            vulnerability = int(st.session_state.get("gear_enemy_vulnerability", 25))
            st.markdown("#### Build inputs")
            input_cards = st.columns(3, gap="small")
            input_cards[0].metric("Condition Damage", f'{stats["Condition Damage"]:,.0f}')
            input_cards[1].metric("Generic condition modifier", f'+{condition_modifier:.1%}')
            input_cards[2].metric("Vulnerability", f"{vulnerability} stacks")

            st.markdown("#### Shared trait assumptions")
            assumption_cards = st.columns(4, gap="small")
            assumption_cards[0].metric("Lead Attacks", f"+{lead_bonus_pct:.1f}%")
            assumption_cards[1].metric("Combat High", f"{combat_high_stacks:.1f} stacks")
            assumption_cards[2].metric("Distracting Throw", f"{distracting_throw_uptime:.1f}% uptime")
            assumption_cards[3].metric("Lotus Training", f"{lotus_training_uptime:.1f}% uptime")
            st.caption("Edit these values in **Gear & stats → Build setup → Combat & trait assumptions**.")

            st.markdown("#### Venom setup")
            setup_cols = st.columns(2, gap="medium")
            with setup_cols[0]:
                nearby_allies = st.number_input(
                    "Nearby allies receiving venom",
                    min_value=0,
                    max_value=4,
                    value=int(st.session_state.get("gear_spider_venom_nearby_allies", 4)),
                    step=1,
                    key="gear_spider_venom_nearby_allies",
                    help=(
                        "Spider Venom always applies to you and can additionally be shared "
                        "to up to four nearby allies."
                    ),
                )
            with setup_cols[1]:
                effective_casts = st.number_input(
                    "Effective Spider Venom casts",
                    min_value=0.0,
                    value=float(st.session_state.get("gear_spider_venom_effective_casts", 4.0)),
                    step=0.1,
                    format="%.2f",
                    key="gear_spider_venom_effective_casts",
                    help="Use fractional casts when the final cast is cut short.",
                )

            total_recipients = 1 + int(nearby_allies)  # caster + nearby allies
            st.caption(
                f"Calculating **{total_recipients} total venom recipients**: "
                f"you + {int(nearby_allies)} nearby all{'y' if int(nearby_allies) == 1 else 'ies'}."
            )

            result = calculate_spider_venom(
                stats["Condition Damage"],
                lead_bonus_pct,
                combat_high_stacks,
                distracting_throw_uptime / 100.0,
                lotus_training_uptime / 100.0,
                condition_modifier,
                total_recipients,
                vulnerability,
                effective_casts,
                constants,
                power=stats["Power"],
                healing_power=stats.get("Healing Power", 0.0),
                leeching_venoms=1130 in selected_trait_ids(),
            )

            st.markdown("#### Spider Venom contribution")
            cards = st.columns(4, gap="small")
            cards[0].metric("Contribution / full cast", f'{result["damage_per_cast"]:,.0f}')
            cards[1].metric("Total recipients", f"{total_recipients}")
            cards[2].metric("Effective casts", f"{effective_casts:.2f}")
            cards[3].metric("Total contribution", f'{result["total_damage"]:,.0f}')

            with st.expander("Calculation audit"):
                st.markdown("##### Base contribution")
                base_rows = [
                    {
                        "Step": "Poison damage per tick",
                        "Value": f'{result["poison_tick"]:,.2f}',
                        "Source": f'Base poison formula using {stats["Condition Damage"]:,.0f} Condition Damage',
                    },
                    {
                        "Step": "Poison applications per full cast",
                        "Value": f'{result["applications_per_cast"]:,.0f}',
                        "Source": f'{total_recipients} total recipients (self + {int(nearby_allies)} allies) × venom applications',
                    },
                    {
                        "Step": "Vulnerability",
                        "Value": f'×{result["vulnerability_multiplier"]:.4f}',
                        "Source": f'{vulnerability} stacks from shared enemy settings',
                    },
                    {
                        "Step": "Base contribution / full cast",
                        "Value": f'{result["base_per_cast"]:,.0f}',
                        "Source": "Poison damage × applications × poison-master factor × Vulnerability",
                    },
                ]
                if result["siphon_damage_per_cast"] > 0:
                    base_rows.extend([
                        {
                            "Step": "Leeching Venoms siphon / strike",
                            "Value": f'{result["siphon_damage_per_strike"]:,.2f}',
                            "Source": f'320 + 0.033 × {stats["Power"]:,.0f} Power',
                        },
                        {
                            "Step": "Leeching Venoms siphon / full cast",
                            "Value": f'{result["siphon_damage_per_cast"]:,.0f}',
                            "Source": f'{result["venom_strikes_per_cast"]:,.0f} consumed venom strikes; not poison ticks',
                        },
                        {
                            "Step": "Leeching Venoms healing / full cast",
                            "Value": f'{result["siphon_healing_per_cast"]:,.0f}',
                            "Source": f'325 + 0.20 × {stats.get("Healing Power", 0.0):,.0f} Healing Power per strike',
                        },
                    ])
                st.dataframe(pd.DataFrame(base_rows), hide_index=True, use_container_width=True)

                st.markdown("##### Outgoing condition-damage modifiers")
                trait_constants = constants["traits"]
                modifier_rows = []

                selected_sigils = st.session_state.get("gear_sim_selected_sigils", [])
                for sigil_name in selected_sigils:
                    value = _number(data["sigils"].get(sigil_name, {}).get("Condition Modifier"))
                    if value:
                        modifier_rows.append({
                            "Modifier": sigil_name,
                            "Input": "Selected",
                            "Affects": "Condition damage",
                            "Bonus": f'+{value:.1%}',
                            "Multiplier": f'×{1.0 + value:.4f}',
                            "Status": "Applied",
                            "Source": "Gear Simulator → Sigils",
                        })

                relic_condition_modifier = _number(
                    load_relic_model(relic).get("damage_modifiers", {}).get("condition_damage")
                )
                if relic_condition_modifier:
                    modifier_rows.append({
                        "Modifier": f"Relic of the {relic}",
                        "Input": "Selected",
                        "Affects": "Condition damage",
                        "Bonus": f'+{relic_condition_modifier:.1%}',
                        "Multiplier": f'×{1.0 + relic_condition_modifier:.4f}',
                        "Status": "Applied",
                        "Source": "Gear Simulator → Relic",
                    })

                lead_contribution = lead_bonus_pct * trait_constants["lead_attacks_per_stack"]
                combat_high_contribution = combat_high_stacks * trait_constants["combat_high_per_stack"]
                distracting_throw_contribution = (distracting_throw_uptime / 100.0) * trait_constants["distracting_throw_per_stack"]
                lotus_training_contribution = (lotus_training_uptime / 100.0) * trait_constants["lotus_training"]

                modifier_rows.extend([
                    {
                        "Modifier": "Lead Attacks",
                        "Input": f'{lead_bonus_pct:.1f}% average bonus',
                        "Affects": "Strike & condition damage",
                        "Bonus": f'+{lead_contribution:.1%}',
                        "Multiplier": f'×{1.0 + lead_contribution:.4f}',
                        "Status": "Applied" if lead_contribution else "Neutral",
                        "Source": "Selected Lead Attacks trait + shared rotation assumption",
                    },
                    {
                        "Modifier": "Combat High",
                        "Input": f'{combat_high_stacks:.1f} average stacks',
                        "Affects": "Condition damage",
                        "Bonus": f'+{combat_high_contribution:.1%}',
                        "Multiplier": f'×{1.0 + combat_high_contribution:.4f}',
                        "Status": "Applied" if combat_high_contribution else "Neutral",
                        "Source": f'Selected Combat High trait · {trait_constants["combat_high_per_stack"]:.0%} condition damage per stack',
                    },
                    {
                        "Modifier": "Distracting Throw",
                        "Input": f'{distracting_throw_uptime:.1f}% uptime',
                        "Affects": "Condition damage",
                        "Bonus": f'+{distracting_throw_contribution:.1%}',
                        "Multiplier": f'×{1.0 + distracting_throw_contribution:.4f}',
                        "Status": "Applied" if distracting_throw_contribution else "Neutral",
                        "Source": f'{trait_constants["distracting_throw_per_stack"]:.0%} while active',
                    },
                    {
                        "Modifier": "Lotus Training",
                        "Input": f'{lotus_training_uptime:.1f}% uptime',
                        "Affects": "Condition damage",
                        "Bonus": f'+{lotus_training_contribution:.1%}',
                        "Multiplier": f'×{1.0 + lotus_training_contribution:.4f}',
                        "Status": "Applied" if lotus_training_contribution else "Neutral",
                        "Source": f'Selected Lotus Training trait · {trait_constants["lotus_training"]:.0%} at full uptime',
                    },
                ])

                if not modifier_rows:
                    modifier_rows.append({
                        "Modifier": "No outgoing modifiers",
                        "Input": "—",
                        "Affects": "Condition damage",
                        "Bonus": "+0.0%",
                        "Multiplier": "×1.0000",
                        "Status": "Neutral",
                        "Source": "No supported source is active",
                    })

                modifier_df = pd.DataFrame(modifier_rows)
                preferred_columns = [
                    "Modifier", "Affects", "Input", "Bonus", "Multiplier", "Status", "Source"
                ]
                modifier_df = modifier_df[[c for c in preferred_columns if c in modifier_df.columns]]
                st.dataframe(modifier_df, hide_index=True, use_container_width=True)

                summary_rows = [
                    {"Effect": "Outgoing condition damage", "Total": f'+{(result["multiplier"] - 1.0):.1%}', "Multiplier": f'×{result["multiplier"]:.4f}'},
                    {"Effect": "Vulnerability", "Total": f'+{(result["vulnerability_multiplier"] - 1.0):.1%}', "Multiplier": f'×{result["vulnerability_multiplier"]:.4f}'},
                    {"Effect": "Final combined damage factor", "Total": "—", "Multiplier": f'×{(result["vulnerability_multiplier"] * result["multiplier"]):.4f}'},
                ]
                st.markdown("###### Modifier summary")
                st.dataframe(pd.DataFrame(summary_rows), hide_index=True, use_container_width=True)

                st.markdown("##### Final contribution")
                final_rows = [
                    {
                        "Metric": "Final contribution / full cast",
                        "Value": f'{result["damage_per_cast"]:,.0f}',
                    },
                    {"Metric": "Effective casts", "Value": f'{effective_casts:.2f}'},
                    {
                        "Metric": "Total Spider Venom contribution",
                        "Value": f'{result["total_damage"]:,.0f}',
                    },
                ]
                st.dataframe(pd.DataFrame(final_rows), hide_index=True, use_container_width=True)

    with relic_tab:
        selected_relic = st.session_state.get("gear_sim_selected_relic", "Thief")
        relic_model = load_relic_model(selected_relic)
        st.subheader(relic_model.get("name", f"Relic of the {selected_relic}"))

        status = relic_model.get("source_status", "unverified")
        verified = bool(relic_model.get("last_verified"))
        implemented = bool(relic_model.get("implemented"))

        if verified:
            st.success(f"Mechanics verified for PvE on {relic_model['last_verified']}.")
        else:
            st.warning("This relic has not yet been verified against a current PvE source.")

        st.write(relic_model.get("description", "No verified description is available."))

        c1, c2, c3 = st.columns(3)
        c1.metric("Data status", "Verified" if verified else "Unverified")
        c2.metric("Damage model", "Active" if implemented else "Not active")
        c3.metric("Static stats", "None" if not relic_model.get("static_stats") else "Present")

        if selected_relic == "Thief" and verified:
            st.markdown("""**Verified PvE mechanics**

- Eligible weapon-skill hits grant **1 stack**.
- Each stack grants **+1% outgoing strike damage**.
- Maximum: **5 stacks**.
- Duration: **6 seconds**.
- A new eligible hit refreshes the duration of all stacks.
- It does **not** increase condition damage.""")
            st.info(
                "The relic is deliberately not applied to final damage yet. Accurate average stacks require "
                "real skill events from the future Thief rotation engine; no guessed hit interval is used."
            )
        elif implemented:
            st.info("This relic has a dedicated model and is applied by the damage engine.")
        else:
            st.info(
                "Selection is stored, but the effect is not applied. A relic only becomes active after its "
                "PvE trigger, duration, cooldown, stacking rules, and damage scope are individually verified."
            )

        with st.expander("Technical status"):
            st.write({
                "game_mode": relic_model.get("game_mode", "PvE"),
                "effect_type": relic_model.get("effect_type", "unknown"),
                "source_status": status,
                "last_verified": relic_model.get("last_verified"),
                "implemented": implemented,
                "notes": relic_model.get("notes", []),
            })


    with data_tab:
        st.subheader("Data & assumptions")
        st.caption("Generic engine rules only. No character, account, player, target, or build names are stored here.")

        rows = [
            {"System": "Equipment attributes", "Status": "Implemented", "Assumption": "Level-80 ascended-equivalent attribute values from the imported workbook; audited in the stat source tables."},
            {"System": "Runes", "Status": "Implemented", "Assumption": "All six superior-rune bonuses are combined. Individual rune data still requires spot checks after balance changes."},
            {"System": "Infusions", "Status": "Implemented", "Assumption": "+5 selected attribute per stat infusion."},
            {"System": "Might", "Status": "Implemented", "Assumption": "+30 Power and +30 Condition Damage per stack at level 80."},
            {"System": "Fury", "Status": "Implemented", "Assumption": "PvE critical-chance increase is applied through the boon engine."},
            {"System": "Weapon strength", "Status": "Implemented / verify per weapon", "Assumption": "Minimum, midpoint, or maximum value from the selected weapon profile."},
            {"System": "Enemy armor", "Status": "Implemented", "Assumption": "Strike damage divides by the entered armor value."},
            {"System": "Vulnerability", "Status": "Implemented", "Assumption": "+1% incoming strike and condition damage per stack."},
            {"System": "Condition formulas", "Status": "Implemented", "Assumption": "Level-80 PvE base and scaling coefficients; shown in condition audits."},
            {"System": "Relics", "Status": "Per-relic", "Assumption": "No generic uptime. Unsupported relics contribute nothing until individually verified and modeled."},
            {"System": "Proc sigils", "Status": "Not implemented", "Assumption": "No proc damage, conditions, cooldowns, or trigger rates are guessed."},
            {"System": "Fight duration", "Status": "Stored only", "Assumption": "Will become active when rotation and proc timelines exist."},
            {"System": "Thief traits and skills", "Status": "Not implemented", "Assumption": "No profession-specific modifiers are included in the neutral engine."},
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)

        st.markdown("""**Relic policy**

1. The selector may contain relic names imported from the workbook.
2. A name alone is not treated as effect data.
3. Each relic must be checked for PvE-specific wording, trigger, internal cooldown, duration, stacking, refresh behavior, and affected damage type.
4. Until that check is complete, the relic is displayed as **not active** and contributes exactly zero.
5. Rotation-dependent uptime is never guessed from a personal build or example enemy.

""")

        st.info(
            "Primary verification targets are the current GW2 Wiki PvE pages and ArenaNet API descriptions where available. "
            "Balance-sensitive records include a last-verified date in their relic JSON file."
        )

    # Save the active setup after every Gear Simulator render. This is the durable
    # source used when changing pages or restarting Streamlit.
    autosave_current_build()
