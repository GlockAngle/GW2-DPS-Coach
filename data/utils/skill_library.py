from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import pandas as pd
import streamlit as st

from utils.damage_engine import get_weapon_strength, calculate_condition_damage
from utils.damage_engine.modifiers import DamageModifiers, ModifierSource
from utils.wiki_skill_sync import sync_all_thief_wiki_data

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "data" / "skills"
SKILL_FILE = SKILL_DIR / "thief_skills_api.json"
OVERRIDE_FILE = SKILL_DIR / "thief_skill_overrides.json"
META_FILE = SKILL_DIR / "thief_skills_meta.json"
API_URL = "https://api.guildwars2.com/v2/skills"


from utils.condition_utils import condition_family, resolve_condition_duration_bonus


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return default


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _request_json(url: str) -> tuple[Any, dict[str, str]]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "GW2-DPS-Coach/SkillLibrary (+local Streamlit app)",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
        headers = {k.lower(): v for k, v in response.headers.items()}
    return payload, headers


def sync_thief_skills_from_api() -> tuple[int, str]:
    """Download current public skill metadata and retain Thief-relevant records."""
    all_skills: list[dict[str, Any]] = []
    page = 0
    while True:
        query = urllib.parse.urlencode({"page": page, "page_size": 200, "lang": "en"})
        payload, headers = _request_json(f"{API_URL}?{query}")
        if not isinstance(payload, list) or not payload:
            break
        all_skills.extend(item for item in payload if isinstance(item, dict))
        total_pages = int(headers.get("x-page-total", "0") or 0)
        page += 1
        if total_pages and page >= total_pages:
            break

    thief_skills: list[dict[str, Any]] = []
    for raw in all_skills:
        professions = raw.get("professions") or []
        if "Thief" not in professions:
            continue
        skill = dict(raw)
        skill["shared_profession_skill"] = len(professions) > 1
        skill["wiki_url"] = "https://wiki.guildwars2.com/wiki/" + urllib.parse.quote(
            str(skill.get("name", "")).replace(" ", "_"), safe="_()'"
        )
        thief_skills.append(skill)

    thief_skills.sort(
        key=lambda s: (
            str(s.get("type", "")),
            str(s.get("weapon_type", "")),
            str(s.get("slot", "")),
            str(s.get("name", "")),
        )
    )
    _write_json(SKILL_FILE, thief_skills)
    synced = datetime.now(timezone.utc).isoformat()
    _write_json(META_FILE, {"synced_at": synced, "source": API_URL, "count": len(thief_skills)})
    if not OVERRIDE_FILE.exists():
        _write_json(OVERRIDE_FILE, {})
    return len(thief_skills), synced


@st.cache_data(show_spinner=False)
def load_skill_data(file_mtime: float, override_mtime: float) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    del file_mtime, override_mtime
    skills = _read_json(SKILL_FILE, [])
    overrides = _read_json(OVERRIDE_FILE, {})
    meta = _read_json(META_FILE, {})
    return (
        skills if isinstance(skills, list) else [],
        overrides if isinstance(overrides, dict) else {},
        meta if isinstance(meta, dict) else {},
    )


def _load() -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    return load_skill_data(
        SKILL_FILE.stat().st_mtime if SKILL_FILE.exists() else 0.0,
        OVERRIDE_FILE.stat().st_mtime if OVERRIDE_FILE.exists() else 0.0,
    )


def _fact_value(skill: dict[str, Any], fact_type: str, text_contains: str | None = None) -> Any:
    for fact in skill.get("facts") or []:
        if fact.get("type") != fact_type:
            continue
        if text_contains and text_contains.lower() not in str(fact.get("text", "")).lower():
            continue
        for key in ("value", "duration", "distance", "hit_count", "percent"):
            if key in fact:
                return fact[key]
    return None


def _api_conditions(skill: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    allowed = {"Bleeding", "Burning", "Confusion", "Poison", "Torment", "Vulnerability", "Weakness", "Cripple", "Immobilize"}
    for fact in skill.get("facts") or []:
        if fact.get("type") not in {"Buff", "PrefixedBuff"}:
            continue
        status = str(fact.get("status", ""))
        if status not in allowed:
            continue
        result.append(
            {
                "condition": status,
                "stacks": int(fact.get("apply_count", 1) or 1),
                "duration": float(fact.get("duration", 0) or 0),
            }
        )
    return result


def _conditions(skill: dict[str, Any], override: dict[str, Any]) -> list[dict[str, Any]]:
    value = override.get("conditions")
    return value if isinstance(value, list) else _api_conditions(skill)


def _recharge(skill: dict[str, Any], override: dict[str, Any] | None = None) -> float | None:
    override = override or {}
    value = override.get("recharge_override")
    if value is None:
        value = _fact_value(skill, "Recharge")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _initiative(skill: dict[str, Any], override: dict[str, Any]) -> int | float | None:
    value = override.get("initiative_cost", skill.get("initiative"))
    try:
        return int(value) if float(value).is_integer() else float(value)
    except (TypeError, ValueError, AttributeError):
        return None


def _hit_count(skill: dict[str, Any], override: dict[str, Any]) -> int | None:
    if override.get("hits") is not None:
        try:
            return int(override["hits"])
        except (TypeError, ValueError):
            return None
    counts = [fact.get("hit_count") for fact in skill.get("facts") or [] if fact.get("type") == "Damage"]
    counts = [int(c) for c in counts if isinstance(c, (int, float))]
    return max(counts) if counts else None


def _skill_validation(skill: dict[str, Any], override: dict[str, Any], classification: dict[str, str]) -> list[str]:
    """Return explicit V1 issues. Aftercast is intentionally excluded."""
    issues: list[str] = []
    category = str(classification.get("category") or "").strip()
    weapon = str(classification.get("weapon") or "").strip()
    slot = str(classification.get("slot") or "").strip()
    specialization = str(classification.get("specialization") or "").strip()

    if not category or category in {"Unknown", "Unclassified"}:
        issues.append("Missing category")
    if not slot or slot == "Unknown":
        issues.append("Missing slot")
    if category in {"Weapon", "Stealth Attack"} and (not weapon or weapon in {"Unknown", "None"}):
        issues.append("Missing weapon")
    if not specialization or specialization == "Unclassified":
        issues.append("Missing specialization")

    coefficient = override.get("power_coefficient")
    hits = _hit_count(skill, override)
    conditions = _conditions(skill, override)
    has_damage_fact = any(f.get("type") == "Damage" for f in skill.get("facts") or [])
    damage_skill = coefficient is not None or hits is not None or has_damage_fact or bool(conditions)

    if damage_skill and coefficient is None and not conditions:
        issues.append("Missing damage coefficient")
    if coefficient is not None and not hits:
        issues.append("Missing hit count")
    if coefficient is not None and not isinstance(override.get("hit_model"), list):
        # A deterministic equal-hit model can be generated from total coefficient + hits.
        if hits:
            issues.append("Hit model generated at runtime")
        else:
            issues.append("Missing hit model")
    if override.get("review_flags"):
        issues.append("Needs manual review")
    return issues


def _slot_order(slot: str) -> int:
    order = {
        "Weapon_1": 1, "Weapon_2": 2, "Weapon_3": 3, "Weapon_4": 4, "Weapon_5": 5,
        "Profession_1": 11, "Profession_2": 12, "Profession_3": 13, "Profession_4": 14, "Profession_5": 15,
        "Heal": 20, "Utility": 21, "Elite": 22,
        "Downed_1": 31, "Downed_2": 32, "Downed_3": 33, "Downed_4": 34,
    }
    return order.get(slot, 99)


def _normalize_classification(skill: dict[str, Any], c: dict[str, str], override: dict[str, Any]) -> dict[str, str]:
    """Correct API/Wiki classifications that describe transformed skill bars as weapons."""
    out = dict(c)
    page = str(override.get("wiki_page") or "")
    name = str(skill.get("name") or "")
    description = str(skill.get("description") or "")
    api_slot = str(skill.get("slot") or out.get("slot") or "Unknown")
    api_type = str(skill.get("type") or "")
    wiki_blob = f"{page} {description} {override.get('notes', '')}".lower()

    # The API exposes Specter Shadow Shroud slots with weapon_type=Staff. They are
    # transformed profession skills, not Daredevil staff weapon skills.
    shadow_shroud_ids = {"63362", "63107", "63167", "63220", "63227", "63160", "63249"}
    if str(skill.get("id")) in shadow_shroud_ids or "shadow shroud" in wiki_blob or (out.get("specialization", "").lower() == "specter" and name in {"Haunt Shot", "Grasping Shadows", "Dawn's Repose", "Eternal Night", "Mind Shock"}):
        slot_num = api_slot.replace("Weapon_", "") if api_slot.startswith("Weapon_") else out.get("slot", "").replace("Weapon_", "")
        out.update({
            "specialization": "Specter",
            "category": "Shroud",
            "weapon": "Shadow Shroud",
            "slot": f"Shroud_{slot_num}" if slot_num else "Shroud",
            "environment": "Aquatic" if "underwater" in page.lower() else "Land",
        })

    # Antiquary F2/F3 records are artifact skills granted by Skritt Swipe.
    artifact_names = {
        "Exalted Hammer", "Holo-Dancer Decoy", "Metal Legion Guitar", "Zephyrite Sun Crystal",
        "Chak Shield", "Forged Surfer Dash", "Mistburn Mortar", "Summon Kryptis Turret",
        "Unstable Skritt Bomb",
    }
    if (out.get("specialization", "").lower() == "antiquary" and api_slot.startswith("Profession_") and api_slot != "Profession_1") or name in artifact_names:
        out["specialization"] = "Antiquary"
        out["category"] = "Artifact"
        out["weapon"] = "Artifact"
        out["environment"] = "Land"

    # Norn transformation subskills are valid records, but not normal Thief weapon skills.
    if name in {"Swipe", "Maul", "Charge"} and api_type == "Bundle":
        out.update({"specialization": "Core", "category": "Transform", "weapon": "Transformation"})
    if name.startswith("Release the ") and api_type == "Elite":
        out.update({"specialization": "Core", "category": "Racial Elite", "weapon": "None"})
    if not name.strip():
        out.update({"specialization": "Internal", "category": "Internal", "weapon": "None"})

    # Normalize capitalization from wiki properties.
    spec = str(out.get("specialization") or "Unclassified")
    canonical = {"daredevil": "Daredevil", "deadeye": "Deadeye", "specter": "Specter", "antiquary": "Antiquary", "core": "Core"}
    out["specialization"] = canonical.get(spec.lower(), spec)
    return out


def _classification(skill: dict[str, Any], override: dict[str, Any]) -> dict[str, str]:
    explicit = override.get("classification")
    if isinstance(explicit, dict):
        return _normalize_classification(skill, {
            "specialization": str(explicit.get("specialization") or "Core"),
            "category": str(explicit.get("category") or skill.get("type") or "Other"),
            "weapon": str(explicit.get("weapon") or skill.get("weapon_type") or "None"),
            "environment": str(explicit.get("environment") or "Land"),
            "slot": str(explicit.get("slot") or skill.get("slot") or "Unknown"),
            "chain_role": str(explicit.get("chain_role") or "—"),
        }, override)

    slot = str(skill.get("slot") or "Unknown")
    categories = {str(x) for x in skill.get("categories") or []}
    category = str(skill.get("type") or "Other")
    if slot.startswith("Weapon_"):
        category = "Stealth Attack" if "StealthAttack" in categories else "Weapon"
    elif slot.startswith("Profession_"):
        category = "Profession"
    elif slot.startswith("Downed_"):
        category = "Downed"

    environment = "Aquatic" if str(skill.get("weapon_type") or "") in {"Harpoon", "Speargun", "Trident"} else "Land"
    return _normalize_classification(skill, {
        "specialization": "Unclassified",
        "category": category,
        "weapon": str(skill.get("weapon_type") or "None"),
        "environment": environment,
        "slot": slot,
        "chain_role": "—",
    }, override)


def _is_usable_default(skill: dict[str, Any], override: dict[str, Any]) -> bool:
    c = _classification(skill, override)
    if skill.get("shared_profession_skill"):
        return False
    if c["category"] in {"Downed", "Bundle", "Transform", "Pet", "Internal"}:
        return False
    if c["environment"] == "Aquatic":
        return False
    if c["slot"].startswith("Downed_"):
        return False
    return c["category"] in {"Weapon", "Stealth Attack", "Profession", "Shroud", "Artifact", "Heal", "Utility", "Elite", "Racial Elite"}


def _format_conditions(items: Iterable[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for item in items:
        name = str(item.get("condition", "Unknown"))
        stacks = int(item.get("stacks", 1) or 1)
        duration = float(item.get("duration", 0) or 0)
        chunks.append(f"{name} {stacks}× / {duration:g}s")
    return " · ".join(chunks) if chunks else "—"


def _status(override: dict[str, Any]) -> str:
    explicit = str(override.get("data_status") or "")
    if explicit:
        return explicit
    if override.get("wiki_verified") or (override.get("wiki_synced") and not override.get("review_flags")):
        return "Wiki verified"
    if override.get("wiki_synced") or override:
        return "Partial"
    return "API only"


def _simulation_readiness(skill: dict[str, Any], override: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    """Return strict rotation-readiness and component checks.

    Wiki enrichment is provenance, not proof of an executable combat model.
    Condition-bearing skills require explicit event mapping; dynamic skills remain
    state-dependent even when their source payloads are verified.
    """
    classification = _classification(skill, override)
    coefficient = override.get("power_coefficient")
    hits = _hit_count(skill, override)
    cast_time = override.get("cast_time")
    conditions = _conditions(skill, override)
    condition_events = override.get("condition_events")
    dynamic_recall = override.get("dynamic_recall")
    flags = [str(x) for x in (override.get("review_flags") or [])]

    class_ok = all(
        str(classification.get(key) or "").strip() not in {"", "Unknown", "Unclassified"}
        for key in ("specialization", "category", "slot")
    )
    if classification.get("category") in {"Weapon", "Stealth Attack"}:
        class_ok = class_ok and str(classification.get("weapon") or "").strip() not in {"", "Unknown", "None"}

    strike_needed = coefficient is not None
    hit_ok = (not strike_needed) or bool(hits)
    cast_ok = cast_time is not None
    conditions_ok = (not conditions) or isinstance(condition_events, list) and bool(condition_events)
    event_review_flags = [f for f in flags if f.startswith("condition audit:")]
    review_ok = not event_review_flags

    checks = [
        {"Component": "Classification", "Status": "Verified" if class_ok else "Blocked", "Details": f"{classification.get('specialization')} · {classification.get('category')} · {classification.get('weapon')} · {classification.get('slot')}"},
        {"Component": "Strike coefficient", "Status": "Verified" if coefficient is not None else "Not applicable", "Details": f"{float(coefficient):g}" if coefficient is not None else "No stored strike coefficient"},
        {"Component": "Hit count", "Status": "Verified" if hit_ok and hits else ("Not applicable" if not strike_needed else "Blocked"), "Details": str(hits or "—")},
        {"Component": "Cast time", "Status": "Verified" if cast_ok else "Blocked", "Details": f"{float(cast_time):g}s" if cast_ok else "Required for rotations"},
        {"Component": "Condition packets", "Status": "Verified" if conditions else "None", "Details": _format_conditions(conditions)},
        {"Component": "Condition event mapping", "Status": "Verified" if conditions_ok and review_ok else ("Not applicable" if not conditions else "Blocked"), "Details": "Explicit per-hit/per-cast events stored" if conditions_ok and review_ok else ("No conditions" if not conditions else "Manual event mapping required")},
        {"Component": "Aftercast / animation lock", "Status": "Blocked", "Details": "Not stored yet; mandatory before exact rotation timing"},
    ]

    if dynamic_recall:
        return "State-dependent", checks
    hard_block = not all((class_ok, hit_ok, cast_ok, conditions_ok, review_ok))
    if hard_block:
        return "Needs review", checks
    # Exact rotations remain blocked globally until aftercast is available.
    return "Skill model ready", checks


def _current_damage(skill: dict[str, Any], override: dict[str, Any], stats: dict[str, Any]) -> dict[str, Any]:
    coefficient = override.get("power_coefficient")
    try:
        coefficient = float(coefficient) if coefficient is not None else None
    except (TypeError, ValueError):
        coefficient = None
    if coefficient is None or coefficient <= 0:
        return {"normal": None, "critical": None, "expected": None, "weapon": None, "strength": None}

    c = _classification(skill, override)
    weapon = c["weapon"].title()
    # Transformed/profession bars use the currently selected build weapon strength.
    if c["category"] in {"Shroud", "Profession", "Artifact"} or weapon in {"None", "Unknown", "Aquatic", "Shadow Shroud", "Artifact"}:
        if st.session_state.get("gear_weapon_mode", "Two-handed weapon") == "Two-handed weapon":
            weapon = str(st.session_state.get("gear_twohand_weapon", "Spear"))
        else:
            selected_slot = st.session_state.get("gear_damage_weapon_slot", "Main hand")
            weapon = str(st.session_state.get("gear_offhand_weapon" if selected_slot == "Off hand" else "gear_mainhand_weapon", "Dagger"))
    roll = str(st.session_state.get("gear_weapon_strength_mode", "Midpoint")).lower()
    try:
        strength = get_weapon_strength(weapon, roll)
    except Exception:
        strength = 1000.0

    power = float(stats.get("Power", 1000.0) or 1000.0)
    precision = float(stats.get("Precision", 1000.0) or 1000.0)
    ferocity = float(stats.get("Ferocity", 0.0) or 0.0)
    # Direct critical modifiers and outgoing damage modifiers are not always
    # represented as raw Precision/Ferocity, so read them from the shared trait
    # registry as well. This keeps Skill Library results consistent with Gear Simulator.
    modifier_effects: dict[str, list[Any]] = {
        "critical_chance": [],
        "critical_damage": [],
        "additive_strike": [],
        "multiplicative_strike": [],
        "stolen_skill_damage": [],
    }
    try:
        from utils.thief_traits import current_trait_effect_registry
        trait_registry = current_trait_effect_registry()
        modifier_effects["critical_chance"] = list(trait_registry.for_target("Critical Chance"))
        modifier_effects["critical_damage"] = list(trait_registry.for_target("Critical Damage"))
        modifier_effects["additive_strike"] = list(trait_registry.for_target("additive_strike"))
        modifier_effects["multiplicative_strike"] = list(trait_registry.for_target("multiplicative_strike"))
        modifier_effects["stolen_skill_damage"] = list(trait_registry.for_target("stolen_skill_damage"))
        direct_crit_chance = sum(effect.value for effect in modifier_effects["critical_chance"])
        direct_crit_damage = sum(effect.value for effect in modifier_effects["critical_damage"])
        additive_strike = sum(effect.value for effect in modifier_effects["additive_strike"])
        multiplicative_strike = sum(effect.value for effect in modifier_effects["multiplicative_strike"])
        stolen_skill_damage = sum(effect.value for effect in modifier_effects["stolen_skill_damage"])
    except Exception:
        direct_crit_chance = direct_crit_damage = additive_strike = multiplicative_strike = stolen_skill_damage = 0.0

    # Equipment modifiers must be read from the shared active-build state too.
    # This makes Skill Inspector react immediately to sigil/relic changes.
    try:
        from utils.gear_simulator import load_gear_data, load_relic_model
        gear_data = load_gear_data()
        for sigil_name in st.session_state.get("gear_sim_selected_sigils", []):
            row = gear_data.get("sigils", {}).get(sigil_name, {})
            value = float(row.get("Add. Strike Modifier", 0.0) or 0.0)
            if value:
                modifier_effects["additive_strike"].append(ModifierSource(f"Sigil of {sigil_name}", value))
                additive_strike += value

        relic_name = str(st.session_state.get("gear_sim_selected_relic", "") or "")
        relic_model = load_relic_model(relic_name) if relic_name else {}
        relic_modifiers = relic_model.get("damage_modifiers", {}) if isinstance(relic_model, dict) else {}
        relic_add = float(relic_modifiers.get("additive_strike", relic_modifiers.get("strike_damage", 0.0)) or 0.0)
        relic_mult = float(relic_modifiers.get("multiplicative_strike", 0.0) or 0.0)
        if relic_add:
            modifier_effects["additive_strike"].append(ModifierSource(f"Relic of the {relic_name}", relic_add))
            additive_strike += relic_add
        if relic_mult:
            modifier_effects["multiplicative_strike"].append(ModifierSource(f"Relic of the {relic_name}", relic_mult))
            multiplicative_strike += relic_mult
    except Exception:
        pass

    crit_chance = max(0.0, min(1.0, (precision - 1000.0) / 2100.0 + 0.05 + direct_crit_chance))
    crit_multiplier = 1.5 + ferocity / 1500.0 + direct_crit_damage
    armor = float(st.session_state.get("gear_enemy_armor", 2597.0) or 2597.0)
    vulnerability = float(st.session_state.get("gear_enemy_vulnerability", 25.0) or 25.0)
    incoming = 1.0 + vulnerability / 100.0
    outgoing = (1.0 + additive_strike) * (1.0 + multiplicative_strike)
    is_deadeye_stolen_skill = (
        c["specialization"].lower() == "deadeye"
        and c["category"] == "Profession"
        and c["slot"] == "Profession_2"
    )
    if is_deadeye_stolen_skill:
        outgoing *= 1.0 + stolen_skill_damage
    normal = strength * power * coefficient / max(1.0, armor) * incoming * outgoing
    critical = normal * crit_multiplier
    expected = normal * (1.0 + crit_chance * (crit_multiplier - 1.0))
    return {
        "normal": normal, "critical": critical, "expected": expected,
        "weapon": weapon, "strength": strength, "power": power,
        "precision": precision, "ferocity": ferocity,
        "crit_chance": crit_chance, "crit_multiplier": crit_multiplier,
        "armor": armor, "vulnerability": vulnerability,
        "outgoing_modifier": outgoing,
        "additive_strike_total": additive_strike,
        "multiplicative_strike_total": multiplicative_strike,
        "stolen_skill_damage_total": stolen_skill_damage if is_deadeye_stolen_skill else 0.0,
        "is_deadeye_stolen_skill": is_deadeye_stolen_skill,
        "modifier_effects": modifier_effects,
    }


def calculate_live_skill_damage(
    skill: dict[str, Any],
    override: dict[str, Any],
    stats: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Single authoritative live-build strike calculation used by Skills and Simulation."""
    active_stats = stats if stats is not None else (st.session_state.get("gear_sim_total_stats", {}) or {})
    return _current_damage(skill, override, active_stats)


def _ensure_data() -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    skills, overrides, meta = _load()
    if not skills:
        st.info("The local Thief skill database has not been synced yet. Use **Sync GW2 API** once; verified overrides are already included and merge by skill ID after sync.")
    return skills, overrides, meta


def _coverage(skills: list[dict[str, Any]], overrides: dict[str, Any]) -> dict[str, int]:
    statuses = [_status(overrides.get(str(s.get("id")), {}) if isinstance(overrides.get(str(s.get("id")), {}), dict) else {}) for s in skills]
    classifications = [
        _classification(s, overrides.get(str(s.get("id")), {}) if isinstance(overrides.get(str(s.get("id")), {}), dict) else {})
        for s in skills
    ]
    return {
        "total": len(skills),
        "classified": sum(c["specialization"] not in {"Unclassified", "Internal"} for c in classifications),
        "unresolved": sum(c["specialization"] == "Unclassified" for c in classifications),
        "damage_ready": sum(
            (overrides.get(str(s.get("id")), {}) or {}).get("power_coefficient") is not None
            for s in skills
        ),
        "wiki": sum(x == "Wiki verified" for x in statuses),
        "partial": sum(x == "Partial" for x in statuses),
        "api": sum(x == "API only" for x in statuses),
        "review_status": sum(x == "Needs review" for x in statuses),
        "review": sum(bool((overrides.get(str(s.get("id")), {}) or {}).get("review_flags")) for s in skills),
    }


def render_skill_library_page() -> None:
    st.title("Skills")
    st.caption("Authoritative skill view. Strike values use the same live-build calculation pipeline as Simulation; proc-only effects remain separate events.")

    skills, overrides, meta = _ensure_data()
    coverage = _coverage(skills, overrides)
    top = st.columns([1.5, 0.7, 0.7, 0.7, 0.7, 0.7, 1.9])
    with top[0]:
        if st.button("↻ Sync complete Thief skill database", use_container_width=True, type="primary"):
            try:
                with st.spinner("Downloading API metadata, resolving exact Wiki pages by game ID, then parsing structured PvE data…"):
                    count, _ = sync_thief_skills_from_api()
                    load_skill_data.clear()
                    current_skills, _, _ = _load()
                    result = sync_all_thief_wiki_data(current_skills, OVERRIDE_FILE, preserve_manual=True)
                load_skill_data.clear()
                st.success(
                    f"Stored {count} API records. Wiki mapped {result['mapped']} records: "
                    f"{result['wiki_verified']} verified, {result['partial']} partial, "
                    f"{result['review']} review, {result['resolved_by_search']} rescued by title search, {result['missing_page']} unresolved."
                )
                st.rerun()
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError) as exc:
                st.error(f"Could not complete the skill sync: {exc}")
    top[1].metric("API records", coverage["total"])
    top[2].metric("Classified", coverage["classified"])
    top[3].metric("Damage-ready", coverage["damage_ready"])
    top[4].metric("Partial", coverage["partial"])
    top[5].metric("Unresolved", coverage["unresolved"])
    with top[6]:
        if meta.get("synced_at"):
            st.caption(f"Official GW2 API sync: {str(meta['synced_at'])[:19].replace('T', ' ')} UTC")
        st.caption("The complete sync imports stable API metadata and structured PvE Wiki infobox/skill-fact values. Existing hand-verified fields always take precedence.")

    with st.expander("Developer tools · data sync", expanded=False):
        a, b = st.columns(2)
        with a:
            if st.button("API metadata only", use_container_width=True):
                try:
                    count, _ = sync_thief_skills_from_api()
                    load_skill_data.clear()
                    st.success(f"Stored {count} Thief-relevant API records.")
                    st.rerun()
                except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                    st.error(f"Could not sync the GW2 API: {exc}")
        with b:
            if st.button("Wiki enrichment only", use_container_width=True):
                try:
                    current_skills, _, _ = _load()
                    result = sync_all_thief_wiki_data(current_skills, OVERRIDE_FILE, preserve_manual=True)
                    load_skill_data.clear()
                    st.success(f"Wiki mapped {result['mapped']} skill IDs; {result['resolved_by_search']} were rescued by exact-ID title search.")
                    st.rerun()
                except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError) as exc:
                    st.error(f"Could not enrich from the GW2 Wiki: {exc}")

    if not skills:
        st.warning("Sync the API to populate the table. The included Spear overrides will automatically attach to matching skill IDs.")
        return

    classifications = {
        str(s.get("id")): _classification(s, overrides.get(str(s.get("id")), {}) if isinstance(overrides.get(str(s.get("id")), {}), dict) else {})
        for s in skills
    }
    categories = sorted({v["category"] for v in classifications.values()})
    weapons = sorted({v["weapon"] for v in classifications.values()})
    specs = sorted({v["specialization"] for v in classifications.values()})
    statuses = ["Wiki verified", "Partial", "Needs review", "API only"]

    f1, f2, f3, f4, f5, f6 = st.columns([1.15, 1.15, 1.15, 1.15, 1.35, 2.1])
    with f1:
        scope = st.selectbox("Scope", ["Usable PvE skills", "All stored skills"], key="skill_lib_scope")
    with f2:
        selected_category = st.selectbox("Category", ["All"] + categories, key="skill_lib_category")
    with f3:
        selected_weapon = st.selectbox("Weapon", ["All"] + weapons, key="skill_lib_weapon")
    with f4:
        selected_spec = st.selectbox("Specialization", ["All"] + specs, key="skill_lib_spec")
    with f5:
        selected_status = st.selectbox("Data status", ["All"] + statuses, key="skill_lib_status")
    with f6:
        query = st.text_input("Search", placeholder="Skill name or description", key="skill_lib_search")

    only_equipped = st.checkbox("Show only skills for the currently equipped weapon(s), plus profession, shroud and artifact skills", value=False, key="skill_lib_equipped_only")
    equipped = set()
    if st.session_state.get("gear_weapon_mode", "Two-handed weapon") == "Two-handed weapon":
        equipped.add(str(st.session_state.get("gear_twohand_weapon", "Spear")))
    else:
        equipped.update({str(st.session_state.get("gear_mainhand_weapon", "Dagger")), str(st.session_state.get("gear_offhand_weapon", "Pistol"))})

    filtered: list[dict[str, Any]] = []
    for skill in skills:
        sid = str(skill.get("id"))
        override = overrides.get(sid, {}) if isinstance(overrides.get(sid, {}), dict) else {}
        c = classifications[sid]
        if scope == "Usable PvE skills" and not _is_usable_default(skill, override):
            continue
        if selected_category != "All" and c["category"] != selected_category:
            continue
        if selected_weapon != "All" and c["weapon"] != selected_weapon:
            continue
        if selected_spec != "All" and c["specialization"] != selected_spec:
            continue
        if selected_status != "All" and _status(override) != selected_status:
            continue
        if only_equipped and c["category"] in {"Weapon", "Stealth Attack"} and c["weapon"] not in equipped:
            continue
        haystack = f"{skill.get('name', '')} {skill.get('description', '')} {c['weapon']} {c['category']}".lower()
        if query.strip() and query.strip().lower() not in haystack:
            continue
        filtered.append(skill)

    stats = st.session_state.get("gear_sim_total_stats", {}) or {}
    build_loaded = bool(stats)
    with st.container(border=True):
        b1, b2, b3, b4, b5 = st.columns([1.35, 1, 1, 1, 1.2])
        b1.markdown("**Live Gear Simulator link**")
        b1.caption("Skill strike values recalculate immediately when gear, traits, buffs, enemy armor or Vulnerability change.")
        b2.metric("Power", f"{float(stats.get('Power', 1000)):,.0f}")
        b3.metric("Precision", f"{float(stats.get('Precision', 1000)):,.0f}")
        b4.metric("Ferocity", f"{float(stats.get('Ferocity', 0)):,.0f}")
        b5.metric("Enemy", f"{float(st.session_state.get('gear_enemy_armor', 2597)):,.0f} armor", f"{float(st.session_state.get('gear_enemy_vulnerability', 25)):g} vuln")
        if not build_loaded:
            st.info("Open Gear Simulator once to load your current build. Until then, the library uses level-80 base offensive stats.")
    rows: list[dict[str, Any]] = []
    for skill in filtered:
        sid = str(skill.get("id"))
        override = overrides.get(sid, {}) if isinstance(overrides.get(sid, {}), dict) else {}
        c = classifications[sid]
        damage = calculate_live_skill_damage(skill, override, stats)
        cast_time = override.get("cast_time")
        aftercast = override.get("aftercast")
        rows.append(
            {
                "Skill": skill.get("name", "Unknown"),
                "Spec": c["specialization"],
                "Category": c["category"],
                "Weapon": c["weapon"],
                "Slot": c["slot"].replace("Weapon_", "W").replace("Profession_", "F"),
                "Chain": c["chain_role"],
                "Power coeff.": override.get("coefficient_display", override.get("power_coefficient", "—")),
                "Hits": _hit_count(skill, override) if _hit_count(skill, override) is not None else "—",
                "Cast": f"{float(cast_time):.2f}s" if cast_time is not None else "—",
                "Aftercast": f"{float(aftercast):.2f}s" if aftercast is not None else "—",
                "Recharge": f"{_recharge(skill, override):g}s" if _recharge(skill, override) is not None else "—",
                "Initiative": _initiative(skill, override) if _initiative(skill, override) is not None else "—",
                "Non-crit strike": f"{damage['normal']:,.0f}" if damage["normal"] is not None else "—",
                "Crit strike": f"{damage['critical']:,.0f}" if damage["critical"] is not None else "—",
                "Expected strike": f"{damage['expected']:,.0f}" if damage["expected"] is not None else "—",
                "Conditions": _format_conditions(_conditions(skill, override)),
                "Status": _status(override),
                "ID": skill.get("id"),
            }
        )

    st.caption(f"Showing {len(rows)} of {len(skills)} stored records. Run **Wiki enrichment only** after the API sync; strike damage is calculated live from the current Gear Simulator build whenever a verified PvE coefficient exists. Conditions are listed separately and are not included in the strike columns.")
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=min(680, 80 + max(1, len(rows)) * 35))

    if not filtered:
        return

    st.subheader("Skill inspector")
    names = [f"{s.get('name', 'Unknown')} · {s.get('id')}" for s in filtered]
    selected_label = st.selectbox("Inspect skill", names, key="skill_lib_inspect")
    selected_skill = filtered[names.index(selected_label)]
    sid = str(selected_skill.get("id"))
    override = overrides.get(sid, {}) if isinstance(overrides.get(sid, {}), dict) else {}
    c = classifications[sid]

    left, right = st.columns([1.0, 3.0])
    with left:
        if selected_skill.get("icon"):
            st.image(selected_skill["icon"], width=72)
        st.markdown(f"### {selected_skill.get('name', 'Unknown')}")
        st.caption(f"ID {sid} · {c['specialization']} · {c['category']} · {c['weapon']} · {c['environment']}")
        st.link_button("GW2 Wiki", override.get("wiki_url") or selected_skill.get("wiki_url", "https://wiki.guildwars2.com"), use_container_width=True)
        status = _status(override)
        if status == "Wiki verified":
            st.success(status)
        elif status == "Partial":
            st.warning(status)
        else:
            st.info(status)
    with right:
        st.write(selected_skill.get("description") or "No description returned by the API.")
        hit_count = _hit_count(selected_skill, override)
        total_coefficient = override.get("power_coefficient")
        average_per_hit = None
        if total_coefficient is not None and hit_count:
            average_per_hit = float(total_coefficient) / max(1, int(hit_count))
        metrics = st.columns(8)
        metrics[0].metric("Initiative", _initiative(selected_skill, override) or "—")
        metrics[1].metric("Recharge", f"{_recharge(selected_skill, override):g}s" if _recharge(selected_skill, override) is not None else "—")
        metrics[2].metric("Hits", hit_count or "—")
        metrics[3].metric("Total coefficient", f"{float(total_coefficient):g}" if total_coefficient is not None else "—", help="Total coefficient for the complete cast, not per hit.")
        metrics[4].metric("Average / hit", f"{average_per_hit:g}" if average_per_hit is not None else "—", help="Total coefficient divided by hit count. Split-hit skills can have unequal individual coefficients; see Combat data.")
        metrics[5].metric("Cast time", f"{override.get('cast_time')}s" if override.get("cast_time") is not None else "—")
        metrics[6].metric("Aftercast", "Planned" if override.get("aftercast") is None else f"{override.get('aftercast')}s", help="Aftercast is excluded from Skill Library v1 readiness and remains on the rotation-engine to-do list.")
        metrics[7].metric("Venom triggers", override.get("venom_triggers", "—"))

        damage = calculate_live_skill_damage(selected_skill, override, stats)
        st.markdown("**Current build damage**")
        d1, d2, d3, d4, d5 = st.columns(5)
        d1.metric("Non-crit / cast", f"{damage['normal']:,.0f}" if damage["normal"] is not None else "—")
        d2.metric("Critical / cast", f"{damage['critical']:,.0f}" if damage["critical"] is not None else "—")
        d3.metric("Expected / cast", f"{damage['expected']:,.0f}" if damage["expected"] is not None else "—")
        d4.metric("Total coefficient", f"{float(total_coefficient):g}" if total_coefficient is not None else "—", help="Total coefficient for the complete cast. The display breakdown is shown in Combat data.")
        d5.metric("Weapon strength", f"{damage['strength']:,.1f}" if damage["strength"] is not None else "—", damage.get("weapon") or "")

        baseline_key = f"skill_compare_baseline_{sid}"
        baseline = st.session_state.get(baseline_key)
        compare_cols = st.columns([1.2, 3.8])
        with compare_cols[0]:
            if st.button("Save current result", key=f"save_skill_baseline_{sid}", use_container_width=True, disabled=damage["expected"] is None):
                st.session_state[baseline_key] = {
                    "normal": damage["normal"],
                    "critical": damage["critical"],
                    "expected": damage["expected"],
                    "power": damage.get("power"),
                    "precision": damage.get("precision"),
                    "ferocity": damage.get("ferocity"),
                }
                st.rerun()
        with compare_cols[1]:
            if isinstance(baseline, dict) and damage["expected"] is not None:
                previous = float(baseline.get("expected") or 0.0)
                delta = float(damage["expected"]) - previous
                pct = (delta / previous * 100.0) if previous else 0.0
                st.info(f"Saved result: {previous:,.0f} expected → {damage['expected']:,.0f} current ({delta:+,.0f}, {pct:+.2f}%).")
            else:
                st.caption("Save the current result, change gear or traits, then return here to see the skill-level difference.")

        st.caption("Strike-only output. Conditions are shown separately until the event engine can model exact application timing, duration and target state.")

        detail_tabs = st.tabs(["Combat data", "Damage calculation", "Conditions & state", "Events", "Validation", "Sources", "API data"])
        with detail_tabs[0]:
            combat_rows = []
            if total_coefficient is not None:
                combat_rows.append({"Field": "Stored total coefficient", "Value": f"{float(total_coefficient):g}"})
                combat_rows.append({"Field": "Display breakdown", "Value": override.get("coefficient_display", "—")})
                combat_rows.append({"Field": "Hit count", "Value": hit_count or "—"})
                combat_rows.append({"Field": "Average coefficient per hit", "Value": f"{average_per_hit:g}" if average_per_hit is not None else "—"})
            for key, label in [
                ("range", "Range"),
                ("melee_range", "Melee range"),
                ("stealth_duration", "Stealth duration"),
                ("evade_duration", "Evade duration"),
                ("block_duration", "Block duration"),
                ("boons_removed", "Boons removed"),
            ]:
                if key in override:
                    combat_rows.append({"Field": label, "Value": override[key]})
            if override.get("healing"):
                combat_rows.append({"Field": "Healing model", "Value": json.dumps(override["healing"])})
            if override.get("life_siphon"):
                combat_rows.append({"Field": "Life siphon model", "Value": json.dumps(override["life_siphon"])})
            st.dataframe(pd.DataFrame(combat_rows), hide_index=True, use_container_width=True) if combat_rows else st.caption("No enriched combat fields yet.")
        with detail_tabs[1]:
            if damage["normal"] is None:
                st.caption("A verified power coefficient is required before strike damage can be calculated.")
            else:
                coefficient = float(override.get("power_coefficient"))
                base_numerator = damage["strength"] * damage["power"] * coefficient
                armor_result = base_numerator / max(1.0, damage["armor"])
                vulnerability_factor = 1.0 + min(25.0, max(0.0, damage["vulnerability"])) / 100.0
                expected_factor = 1.0 + damage["crit_chance"] * (damage["crit_multiplier"] - 1.0)
                additive_factor = 1.0 + float(damage.get("additive_strike_total", 0.0) or 0.0)
                multiplicative_factor = 1.0 + float(damage.get("multiplicative_strike_total", 0.0) or 0.0)
                stolen_factor = 1.0 + float(damage.get("stolen_skill_damage_total", 0.0) or 0.0)
                after_vulnerability = armor_result * vulnerability_factor
                after_additive = after_vulnerability * additive_factor
                after_multiplicative = after_additive * multiplicative_factor
                after_stolen = after_multiplicative * stolen_factor

                st.markdown("**Active effects used by this strike calculation**")
                modifier_rows: list[dict[str, Any]] = []
                effect_groups = damage.get("modifier_effects", {}) if isinstance(damage.get("modifier_effects"), dict) else {}
                for group_key, group_label in [
                    ("additive_strike", "Additive strike group"),
                    ("multiplicative_strike", "Multiplicative strike group"),
                    ("stolen_skill_damage", "Deadeye stolen-skill group"),
                    ("critical_chance", "Critical chance"),
                    ("critical_damage", "Critical damage"),
                ]:
                    if group_key == "stolen_skill_damage" and not damage.get("is_deadeye_stolen_skill"):
                        continue
                    for effect in effect_groups.get(group_key, []):
                        modifier_rows.append({
                            "Source": getattr(effect, "source", "Unknown"),
                            "Group": group_label,
                            "Amount": f"{float(getattr(effect, 'value', 0.0)):+.2%}",
                            "Condition": getattr(effect, "condition", "Always"),
                            "Note": getattr(effect, "note", ""),
                        })
                if modifier_rows:
                    st.dataframe(pd.DataFrame(modifier_rows), hide_index=True, use_container_width=True)
                else:
                    st.caption("No selected trait effects modify this strike calculation.")

                st.markdown("**Formula audit**")
                audit_rows = [
                    {"Step": "1. Weapon strength", "Input / factor": f"{damage['strength']:,.2f}", "Result after step": f"{damage['strength']:,.2f}", "Explanation": f"Selected {damage['weapon']} strength roll"},
                    {"Step": "2. Power", "Input / factor": f"× {damage['power']:,.0f}", "Result after step": f"{damage['strength'] * damage['power']:,.2f}", "Explanation": "Resulting Power from the active build"},
                    {"Step": "3. Total coefficient", "Input / factor": f"× {coefficient:g}", "Result after step": f"{base_numerator:,.2f}", "Explanation": "Verified coefficient for the complete cast"},
                    {"Step": "4. Enemy armor", "Input / factor": f"÷ {damage['armor']:,.0f}", "Result after step": f"{armor_result:,.2f}", "Explanation": "Base strike damage before incoming/outgoing modifiers"},
                    {"Step": "5. Vulnerability", "Input / factor": f"× {vulnerability_factor:.4f}", "Result after step": f"{after_vulnerability:,.2f}", "Explanation": f"{damage['vulnerability']:g} stacks on the target"},
                    {"Step": "6. Additive strike group", "Input / factor": f"× {additive_factor:.4f}", "Result after step": f"{after_additive:,.2f}", "Explanation": f"1 + summed additive modifiers ({damage.get('additive_strike_total', 0.0):+.2%})"},
                    {"Step": "7. Multiplicative strike group", "Input / factor": f"× {multiplicative_factor:.4f}", "Result after step": f"{after_multiplicative:,.2f}", "Explanation": f"1 + summed multiplicative modifiers ({damage.get('multiplicative_strike_total', 0.0):+.2%})"},
                ]
                if damage.get("is_deadeye_stolen_skill"):
                    audit_rows.append({"Step": "8. Deadeye stolen-skill group", "Input / factor": f"× {stolen_factor:.4f}", "Result after step": f"{after_stolen:,.2f}", "Explanation": "Only applies to matching Deadeye stolen skills"})
                audit_rows.extend([
                    {"Step": "9. Non-crit / cast", "Input / factor": f"× {damage.get('outgoing_modifier', 1.0):.4f} total outgoing", "Result after step": f"{damage['normal']:,.2f}", "Explanation": "Final non-critical strike result"},
                    {"Step": "10. Critical multiplier", "Input / factor": f"× {damage['crit_multiplier']:.4f}", "Result after step": f"{damage['critical']:,.2f}", "Explanation": f"1.5 + Ferocity {damage['ferocity']:,.0f} ÷ 1500 + direct critical-damage effects"},
                    {"Step": "11. Critical chance", "Input / factor": f"{damage['crit_chance']:.2%}", "Result after step": f"× {expected_factor:.4f} expected factor", "Explanation": f"Precision {damage['precision']:,.0f} plus direct critical-chance effects"},
                    {"Step": "12. Expected / cast", "Input / factor": "Non-crit × expected factor", "Result after step": f"{damage['expected']:,.2f}", "Explanation": "Critical-chance-weighted strike result"},
                ])
                st.dataframe(pd.DataFrame(audit_rows), hide_index=True, use_container_width=True)
                st.code(
                    f"Base = {damage['strength']:.2f} × {damage['power']:.0f} × {coefficient:g} ÷ {damage['armor']:.0f} = {armor_result:.2f}\n"
                    f"Non-crit = {armor_result:.2f} × {vulnerability_factor:.4f} vulnerability "
                    f"× {additive_factor:.4f} additive group × {multiplicative_factor:.4f} multiplicative group "
                    f"× {stolen_factor:.4f} stolen-skill group = {damage['normal']:.2f}\n"
                    f"Expected = {damage['normal']:.2f} × (1 + {damage['crit_chance']:.4f} × ({damage['crit_multiplier']:.4f} − 1)) "
                    f"= {damage['expected']:.2f}",
                    language="text",
                )
        with detail_tabs[2]:
            conds = _conditions(selected_skill, override)
            condition_audit_flags = [
                str(flag) for flag in (override.get("review_flags") or [])
                if str(flag).startswith("condition audit:")
            ]
            condition_mapping_verified = not condition_audit_flags
            if condition_audit_flags:
                st.error(
                    "Exact condition totals are blocked for this skill because its applications are not yet mapped "
                    "to explicit combat events. " + " | ".join(flag.replace("condition audit: ", "") for flag in condition_audit_flags)
                )
            if override.get("dynamic_recall"):
                recall = override.get("dynamic_recall") or {}
                st.info(
                    f"State-dependent recall skill: up to {recall.get('max_axes_recalled', '?')} existing axes are recalled. "
                    "Their effects depend on which earlier skills created those axes, so inherited conditions are resolved only in a rotation state."
                )
                payload_rows = []
                for payload in recall.get("source_payloads", []):
                    for event in payload.get("condition_events_per_recalled_axe", []):
                        payload_rows.append({
                            "Axe source": payload.get("source_skill", payload.get("source_skill_id", "Unknown")),
                            "Maximum axes from source": payload.get("max_axes_from_source", "—"),
                            "Inherited condition per recalled axe": event.get("condition", "Unknown"),
                            "Stacks": event.get("stacks", 1),
                            "Base duration": f"{float(event.get('base_duration', 0) or 0):g}s",
                        })
                if payload_rows:
                    st.markdown("**Inherited recalled-axe payloads**")
                    st.dataframe(pd.DataFrame(payload_rows), hide_index=True, use_container_width=True)
            if conds:
                # Condition previews intentionally calculate the full potential value of the
                # stored applications. Exact application timestamps, cleanses, phase cut-offs
                # and target-state changes remain responsibilities of the future event engine.
                condition_damage_stat = float(stats.get("Condition Damage", 0.0) or 0.0)
                vulnerability_stacks = int(float(st.session_state.get("gear_enemy_vulnerability", 25.0) or 25.0))
                metrics_state = st.session_state.get("gear_sim_metrics", {}) or {}
                generic_duration = float(metrics_state.get("condition_duration", max(0.0, min(1.0, float(stats.get("Expertise", 0.0) or 0.0) / 1500.0))) or 0.0)
                specific_durations = metrics_state.get("specific_condition_durations", {}) or {}

                global_sources: list[ModifierSource] = []
                condition_sources: dict[str, list[ModifierSource]] = {}
                duration_sources: dict[str, list[tuple[str, float]]] = {}
                try:
                    from utils.thief_traits import (
                        calculate_selected_trait_effects,
                        current_trait_effect_registry,
                    )
                    # Re-resolve selected trait effects on this page. The Gear
                    # Simulator creates its metrics snapshot only while that
                    # page is rendered, so relying solely on the old snapshot
                    # can lose effects such as Potent Poison after navigation
                    # or an app restart.
                    calculate_selected_trait_effects()
                    registry = current_trait_effect_registry()
                    for effect in registry.for_target("global_condition"):
                        global_sources.append(ModifierSource(effect.source, effect.value))
                    for family in ("bleeding", "burning", "poison", "torment", "confusion"):
                        for effect in registry.for_target(family):
                            condition_sources.setdefault(family, []).append(ModifierSource(effect.source, effect.value))
                        for effect in registry.for_target(f"{family.title()} Duration"):
                            duration_sources.setdefault(family, []).append((effect.source, float(effect.value)))
                except Exception:
                    pass

                modifiers = DamageModifiers(
                    global_condition_sources=tuple(global_sources),
                    condition_specific_sources={key: tuple(value) for key, value in condition_sources.items()},
                )
                condition_values = calculate_condition_damage(
                    condition_damage=condition_damage_stat,
                    vulnerability_stacks=vulnerability_stacks,
                    modifiers=modifiers,
                    enemy_movement_uptime=float(st.session_state.get("gear_enemy_movement", 0.0) or 0.0) / 100.0,
                    enemy_attack_speed=float(st.session_state.get("gear_enemy_attack_speed", 1.0) or 1.0),
                )

                summary_rows: list[dict[str, Any]] = []
                duration_rows: list[dict[str, Any]] = []
                interaction_rows: list[dict[str, Any]] = []
                total_applications = 0.0
                total_base_stack_seconds = 0.0
                total_modified_stack_seconds = 0.0
                estimated_total_damage = 0.0
                damaging_rows = 0

                for index, cond in enumerate(conds, start=1):
                    name = str(cond.get("condition", cond.get("name", "Unknown")))
                    family = condition_family(name)
                    applications = float(cond.get("stacks", cond.get("apply_count", 1)) or 1)
                    base_duration = float(cond.get("duration", 0) or 0)
                    active_specific_duration = sum(
                        value for _source, value in duration_sources.get(family, [])
                    )
                    duration_bonus = resolve_condition_duration_bonus(
                        name,
                        generic_duration,
                        specific_durations,
                        additional_specific_bonus=active_specific_duration,
                    )
                    # Gear Simulator metrics already include condition-specific trait, food, rune and sigil bonuses.
                    modified_duration = base_duration * (1.0 + duration_bonus)
                    base_stack_seconds = applications * base_duration
                    modified_stack_seconds = applications * modified_duration

                    formula_key = name
                    if name == "Torment":
                        formula_key = "Torment (weighted)"
                    elif name == "Confusion":
                        formula_key = "Confusion (tick)"
                    damage_row = condition_values.get(formula_key)
                    estimate = None
                    if condition_mapping_verified and isinstance(damage_row, dict) and base_duration > 0:
                        estimate = float(damage_row.get("final_damage", 0.0) or 0.0) * modified_stack_seconds
                        estimated_total_damage += estimate
                        damaging_rows += 1

                    total_applications += applications
                    total_base_stack_seconds += base_stack_seconds
                    total_modified_stack_seconds += modified_stack_seconds
                    summary_rows.append({
                        "Condition": name,
                        "Applications / cast": f"{applications:g}",
                        "Base duration": f"{base_duration:g}s",
                        "Duration bonus": f"+{duration_bonus:.1%}",
                        "Modified duration": f"{modified_duration:.2f}s",
                        "Total condition duration (stack-seconds)": f"{modified_stack_seconds:.2f}",
                        "Estimated maximum condition damage": (
                            f"{estimate:,.0f}" if estimate is not None else
                            ("Unverified event mapping" if not condition_mapping_verified else "State/control only")
                        ),
                    })
                    duration_rows.append({
                        "Condition": f"{name} #{index}",
                        "Base": f"{base_duration:g}s",
                        "Generic duration": f"+{generic_duration:.1%}",
                        "Specific total": f"+{duration_bonus:.1%}",
                        "Final / application": f"{modified_duration:.2f}s",
                    })

                    for source in global_sources:
                        interaction_rows.append({"Condition": name, "Source": source.name, "Effect": f"Global condition damage {source.bonus:+.1%}", "Applied": "Yes"})
                    for source in condition_sources.get(family, []):
                        interaction_rows.append({"Condition": name, "Source": source.name, "Effect": f"{name} damage {source.bonus:+.1%}", "Applied": "Yes"})
                    for source, value in duration_sources.get(family, []):
                        interaction_rows.append({"Condition": name, "Source": source, "Effect": f"{name} duration {value:+.1%}", "Applied": "Included in duration"})

                unique_conditions = len({str(c.get("condition", c.get("name", "Unknown"))) for c in conds})
                longest_modified_duration = max(
                    (float(row["Modified duration"].rstrip("s")) for row in summary_rows),
                    default=0.0,
                )
                decay_window_dps = (
                    estimated_total_damage / longest_modified_duration
                    if damaging_rows and longest_modified_duration > 0
                    else None
                )

                cards = st.columns(5)
                cards[0].metric("Applications / cast", f"{total_applications:g}")
                cards[1].metric("Unique conditions", unique_conditions)
                cards[2].metric(
                    "Total condition duration",
                    f"{total_modified_stack_seconds:.2f}",
                    help="Stack-seconds: applications × modified duration, summed across all stored condition packets.",
                )
                cards[3].metric(
                    "Estimated maximum damage",
                    f"{estimated_total_damage:,.0f}" if damaging_rows else "—",
                    help="Maximum condition damage if every stored application lands and lasts for its complete modified duration.",
                )
                cards[4].metric(
                    "Average DPS over decay",
                    f"{decay_window_dps:,.0f}" if decay_window_dps is not None else "—",
                    help="Estimated maximum condition damage divided by the longest modified condition duration. This is not rotation DPS.",
                )

                st.markdown("**Condition summary**")
                st.dataframe(pd.DataFrame(summary_rows), hide_index=True, use_container_width=True)
                st.caption(
                    "Estimated maximum damage assumes every stored application lands and runs for its complete modified duration. "
                    "It includes current Condition Damage, Vulnerability and active condition modifiers, but not cleanses, phase endings, target invulnerability or verified per-hit timing."
                )

                with st.expander("Duration breakdown", expanded=False):
                    st.dataframe(pd.DataFrame(duration_rows), hide_index=True, use_container_width=True)
                    st.caption(f"Generic condition duration from the current build: {generic_duration:.2%}. Condition duration is capped by the Gear Simulator before it reaches this page.")

                with st.expander("Trait and modifier interactions", expanded=False):
                    if interaction_rows:
                        interactions_df = pd.DataFrame(interaction_rows).drop_duplicates()
                        interactions_df.insert(1, "Source type", "Trait")
                        st.dataframe(interactions_df, hide_index=True, use_container_width=True)
                    else:
                        st.caption("No active trait condition-damage or condition-duration effects were found for these conditions.")

                with st.expander("Future event sequence", expanded=False):
                    preview_rows = []
                    hit_total = _hit_count(selected_skill, override) or 0
                    cast_seconds = float(override.get("cast_time") or 0.0)
                    for hit_index in range(1, hit_total + 1):
                        preview_time = cast_seconds * hit_index / hit_total if hit_total and cast_seconds > 0 else 0.0
                        preview_rows.append({"Preview time": f"{preview_time:.2f}s", "Event": "skill_hit", "Detail": f"Hit {hit_index} of {hit_total}"})
                    for cond in conds:
                        preview_rows.append({"Preview time": "On linked hit", "Event": "condition_applied", "Detail": f"{cond.get('condition', cond.get('name', 'Unknown'))} ×{cond.get('stacks', cond.get('apply_count', 1))} for {float(cond.get('duration', 0) or 0):g}s base"})
                    st.dataframe(pd.DataFrame(preview_rows), hide_index=True, use_container_width=True)
                    st.caption("The condition packets are verified; their exact hit assignment and timestamps remain preview data until the event engine is implemented.")

                st.markdown("**Runtime status**")
                status_rows = [
                    {"Capability": "Stored applications and base duration", "Status": "Ready"},
                    {"Capability": "Current-build duration modifiers", "Status": "Ready"},
                    {"Capability": "Current-build condition damage estimate", "Status": "Preview"},
                    {"Capability": "Exact per-hit application timing", "Status": "Event engine required"},
                    {"Capability": "Rotation DPS, cleanses and phase cut-offs", "Status": "Event engine required"},
                ]
                st.dataframe(pd.DataFrame(status_rows), hide_index=True, use_container_width=True)
            else:
                st.caption("No damaging or control conditions are stored for this skill.")
            conditional = override.get("conditional_effects")
            if isinstance(conditional, list) and conditional:
                st.markdown("**Conditional effects**")
                st.dataframe(pd.DataFrame(conditional), hide_index=True, use_container_width=True)
        with detail_tabs[3]:
            hooks = override.get("event_tags")
            if not isinstance(hooks, list):
                hooks = ["skill_cast"]
                if _hit_count(selected_skill, override):
                    hooks += ["skill_hit", "critical_hit"]
                if _initiative(selected_skill, override):
                    hooks.append("initiative_spent")
                if _conditions(selected_skill, override):
                    hooks.append("condition_applied")
            hooks = list(dict.fromkeys(str(x) for x in hooks))

            explicit_events = override.get("condition_events")
            if isinstance(explicit_events, list) and explicit_events:
                st.markdown("**Verified condition events**")
                explicit_rows = []
                for event in explicit_events:
                    repeats = int(event.get("hits", event.get("repeats", 1)) or 1)
                    applications_per_hit = int(event.get("applications_per_hit", 1) or 1)
                    stacks_per_application = int(event.get("stacks_per_application", 1) or 1)
                    explicit_rows.append({
                        "Phase": event.get("phase", "cast"),
                        "Repeats / hits": repeats,
                        "Condition": event.get("condition", "Unknown"),
                        "Applications per repeat": applications_per_hit,
                        "Stacks per application": stacks_per_application,
                        "Base duration": f"{float(event.get('base_duration', 0) or 0):g}s",
                        "Total applications": repeats * applications_per_hit * stacks_per_application,
                        "Creates persistent state": event.get("creates_recallable_axes", "—"),
                    })
                st.dataframe(pd.DataFrame(explicit_rows), hide_index=True, use_container_width=True)
                st.caption("These rows are the executable combat model. They are kept separate from tooltip/API facts and from other skills such as Recall Axes.")
            elif _conditions(selected_skill, override):
                st.error("This skill has stored conditions but no explicit condition-event mapping. It is blocked from exact simulation.")

            if override.get("dynamic_recall"):
                st.markdown("**State-dependent event rule**")
                recall = override.get("dynamic_recall") or {}
                st.info(str(recall.get("payload_rule") or "Payload depends on earlier rotation state."))

            hit_count = _hit_count(selected_skill, override) or 0
            cast_time = float(override.get("cast_time") or 0.0)
            event_rows = [{"Time": "0.00s", "Event": "skill_cast", "Details": selected_skill.get("name", "Skill")}]
            initiative = _initiative(selected_skill, override)
            if initiative:
                event_rows.append({"Time": "0.00s", "Event": "initiative_spent", "Details": f"{initiative:g} initiative"})
            if hit_count:
                for hit_index in range(1, hit_count + 1):
                    event_time = cast_time * hit_index / hit_count if cast_time > 0 else 0.0
                    event_rows.append({"Time": f"{event_time:.2f}s", "Event": "skill_hit", "Details": f"Hit {hit_index} of {hit_count} (preview timing)"})
            if cast_time > 0:
                event_rows.append({"Time": f"{cast_time:.2f}s", "Event": "cast_complete", "Details": "Aftercast not included"})
            st.markdown("**Preview timeline**")
            st.dataframe(pd.DataFrame(event_rows), hide_index=True, use_container_width=True)
            st.caption("Timeline positions for individual hits are preview-only unless exact per-hit timestamps are stored. Supported event tags:")
            st.code("\n".join(hooks), language="text")
        with detail_tabs[4]:
            classification = _classification(selected_skill, override)
            issues = _skill_validation(selected_skill, override, classification)
            readiness, readiness_rows = _simulation_readiness(selected_skill, override)
            if readiness == "Skill model ready":
                st.success("Skill model ready — combat fields are structurally usable. Exact rotations remain blocked until aftercast/timing is verified.")
            elif readiness == "State-dependent":
                st.info("State-dependent skill — its payload is verified, but the result requires prior rotation state.")
            else:
                st.warning("Needs review — this skill is blocked from exact simulation.")
            st.dataframe(pd.DataFrame(readiness_rows), hide_index=True, use_container_width=True)
            if issues:
                st.markdown("**Open items**")
                for issue in issues:
                    if issue == "Hit model generated at runtime":
                        st.info(issue)
                    else:
                        st.write(f"- {issue}")
            else:
                st.caption("No v1 validation issues detected.")
        with detail_tabs[5]:
            provenance = [
                {"Field": "Name / ID", "Value": f"{selected_skill.get('name', 'Unknown')} · {sid}", "Source": "Official GW2 API"},
                {"Field": "Description and icon", "Value": "Loaded", "Source": "Official GW2 API"},
                {"Field": "Classification", "Value": f"{c['specialization']} · {c['category']} · {c['weapon']} · {c['slot']}", "Source": "API + local resolver"},
                {"Field": "Total coefficient", "Value": override.get("coefficient_display", override.get("power_coefficient", "—")), "Source": "GW2 Wiki enrichment" if override.get("power_coefficient") is not None else "Unavailable"},
                {"Field": "Hit count", "Value": _hit_count(selected_skill, override) or "—", "Source": "GW2 Wiki enrichment / API facts"},
                {"Field": "Cast time", "Value": f"{override.get('cast_time')}s" if override.get("cast_time") is not None else "—", "Source": "GW2 Wiki enrichment"},
                {"Field": "Recharge", "Value": f"{_recharge(selected_skill, override):g}s" if _recharge(selected_skill, override) is not None else "—", "Source": "GW2 API / Wiki override"},
                {"Field": "Initiative", "Value": _initiative(selected_skill, override) or "—", "Source": "GW2 API / Wiki override"},
                {"Field": "Conditions", "Value": _format_conditions(_conditions(selected_skill, override)), "Source": "GW2 Wiki enrichment / API facts"},
                {"Field": "Calculated damage", "Value": "Live from current build", "Source": "GW2 DPS Coach"},
                {"Field": "Data status", "Value": _status(override), "Source": "Completeness rules"},
                {"Field": "Verified mode", "Value": override.get("verified_mode", "—"), "Source": "Enrichment metadata"},
                {"Field": "Verified on", "Value": override.get("verified_on", "—"), "Source": "Enrichment metadata"},
                {"Field": "Wiki revision", "Value": override.get("wiki_revision", "—"), "Source": "GW2 Wiki"},
                {"Field": "Notes", "Value": override.get("notes", "—"), "Source": "Local review"},
            ]
            st.dataframe(pd.DataFrame(provenance), hide_index=True, use_container_width=True)
            flags = override.get("review_flags")
            if isinstance(flags, list) and flags:
                st.warning("Manual review still required:\n\n- " + "\n- ".join(str(x) for x in flags))
        with detail_tabs[6]:
            facts = selected_skill.get("facts") or []
            if facts:
                fact_rows = []
                for fact in facts:
                    fact_rows.append(
                        {
                            "Text": fact.get("text", ""),
                            "Type": fact.get("type", ""),
                            "Value": fact.get("value", fact.get("duration", fact.get("distance", fact.get("hit_count", fact.get("percent", ""))))),
                            "Status": fact.get("status", ""),
                            "Stacks": fact.get("apply_count", ""),
                        }
                    )
                st.dataframe(pd.DataFrame(fact_rows), hide_index=True, use_container_width=True)
            else:
                st.caption("The API returned no facts for this skill.")

    with st.expander("Developer tools · review queue", expanded=False):
        review_rows = []
        for skill in skills:
            ov = overrides.get(str(skill.get("id")), {}) if isinstance(overrides.get(str(skill.get("id")), {}), dict) else {}
            flags = ov.get("review_flags")
            if isinstance(flags, list):
                for flag in flags:
                    review_rows.append({"Skill": skill.get("name"), "ID": skill.get("id"), "Issue": flag})
        if review_rows:
            st.dataframe(pd.DataFrame(review_rows), hide_index=True, use_container_width=True)
        else:
            st.success("No enriched skills are currently flagged for manual review.")
        st.caption("API-only records are not considered errors; they simply remain excluded from final skill-damage simulation until enriched.")


def live_damage_ready_skills() -> list[str]:
    """Names of skills that can be used by the live build sensitivity tester."""
    skills, overrides, _ = _load()
    result = []
    for skill in skills:
        override = overrides.get(str(skill.get("id")), {}) if isinstance(overrides.get(str(skill.get("id")), {}), dict) else {}
        try:
            if float(override.get("power_coefficient", 0.0) or 0.0) > 0:
                result.append(f"{skill.get('name', 'Unknown')} · {skill.get('id')}")
        except (TypeError, ValueError):
            continue
    return sorted(result)


def simulate_live_skill(label: str, casts: float = 1.0) -> dict[str, Any]:
    """Calculate one skill from the current shared build state for UI testing."""
    skills, overrides, _ = _load()
    try:
        skill_id = str(label.rsplit(" · ", 1)[1])
    except (IndexError, AttributeError):
        raise ValueError("Invalid skill selection")
    skill = next((row for row in skills if str(row.get("id")) == skill_id), None)
    if skill is None:
        raise ValueError(f"Skill {skill_id} was not found")
    override = overrides.get(skill_id, {}) if isinstance(overrides.get(skill_id, {}), dict) else {}
    stats = st.session_state.get("gear_sim_total_stats", {}) or {}
    damage = calculate_live_skill_damage(skill, override, stats)
    expected = float(damage.get("expected") or 0.0)
    normal = float(damage.get("normal") or 0.0)
    critical = float(damage.get("critical") or 0.0)
    return {
        "skill": skill.get("name", "Unknown"),
        "skill_id": skill_id,
        "casts": float(casts),
        "normal_per_cast": normal,
        "critical_per_cast": critical,
        "expected_per_cast": expected,
        "expected_total": expected * float(casts),
        "outgoing_modifier": float(damage.get("outgoing_modifier", 1.0) or 1.0),
        "modifier_effects": damage.get("modifier_effects", {}),
        "power": float(damage.get("power", 0.0) or 0.0),
        "precision": float(damage.get("precision", 0.0) or 0.0),
        "ferocity": float(damage.get("ferocity", 0.0) or 0.0),
    }
