from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

WIKI_API = "https://wiki.guildwars2.com/api.php"
USER_AGENT = "GW2-DPS-Coach/SkillLibrary (+local Streamlit app; wiki enrichment)"


def _request_json(params: dict[str, Any], timeout: int = 45) -> dict[str, Any]:
    query = urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(
        f"{WIKI_API}?{query}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(values), size):
        yield values[i : i + size]


def _balanced_templates(text: str, template_name: str | None = None) -> list[str]:
    """Return balanced {{...}} blocks, optionally only matching one template name."""
    out: list[str] = []
    stack: list[int] = []
    i = 0
    while i < len(text) - 1:
        pair = text[i : i + 2]
        if pair == "{{":
            stack.append(i)
            i += 2
            continue
        if pair == "}}" and stack:
            start = stack.pop()
            end = i + 2
            if not stack:
                block = text[start:end]
                if template_name is None:
                    out.append(block)
                else:
                    inner = block[2:-2].lstrip()
                    name = inner.split("|", 1)[0].strip().lower().replace("_", " ")
                    if name == template_name.lower().replace("_", " "):
                        out.append(block)
            i += 2
            continue
        i += 1
    return out


def _split_top_level(text: str, separator: str = "|") -> list[str]:
    parts: list[str] = []
    start = 0
    tpl_depth = 0
    link_depth = 0
    i = 0
    while i < len(text):
        pair = text[i : i + 2]
        if pair == "{{":
            tpl_depth += 1
            i += 2
            continue
        if pair == "}}" and tpl_depth:
            tpl_depth -= 1
            i += 2
            continue
        if pair == "[[":
            link_depth += 1
            i += 2
            continue
        if pair == "]]" and link_depth:
            link_depth -= 1
            i += 2
            continue
        if text[i] == separator and tpl_depth == 0 and link_depth == 0:
            parts.append(text[start:i])
            start = i + 1
        i += 1
    parts.append(text[start:])
    return parts


def _parse_template(block: str) -> tuple[str, dict[str, str], list[str]]:
    inner = block[2:-2]
    parts = _split_top_level(inner)
    name = parts[0].strip()
    params: dict[str, str] = {}
    positional: list[str] = []
    for raw in parts[1:]:
        eq_at = -1
        tpl_depth = link_depth = 0
        i = 0
        while i < len(raw):
            pair = raw[i : i + 2]
            if pair == "{{": tpl_depth += 1; i += 2; continue
            if pair == "}}" and tpl_depth: tpl_depth -= 1; i += 2; continue
            if pair == "[[": link_depth += 1; i += 2; continue
            if pair == "]]" and link_depth: link_depth -= 1; i += 2; continue
            if raw[i] == "=" and tpl_depth == 0 and link_depth == 0:
                eq_at = i; break
            i += 1
        if eq_at >= 0:
            params[raw[:eq_at].strip().lower().replace("_", " ")] = raw[eq_at + 1 :].strip()
        else:
            positional.append(raw.strip())
    return name, params, positional


def _strip_markup(value: str) -> str:
    value = re.sub(r"<!--.*?-->", "", value, flags=re.S)
    value = re.sub(r"<ref\b[^>]*>.*?</ref>|<ref\b[^>]*/>", "", value, flags=re.S | re.I)
    value = re.sub(r"\[\[(?:[^\]|]+\|)?([^\]]+)\]\]", r"\1", value)
    value = re.sub(r"''+", "", value)
    value = re.sub(r"<[^>]+>", "", value)
    return html.unescape(value).strip()


def _num(value: Any) -> float | None:
    if value is None:
        return None
    text = _strip_markup(str(value)).strip()
    text = text.replace("½", ".5").replace("¼", ".25").replace("¾", ".75")
    text = text.replace("−", "-")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def _integerish(value: float | None) -> int | float | None:
    if value is None:
        return None
    return int(value) if float(value).is_integer() else value


def _condition_name(raw: str) -> str | None:
    names = {
        "bleeding": "Bleeding", "burning": "Burning", "confusion": "Confusion",
        "poison": "Poison", "poisoned": "Poison", "torment": "Torment",
        "vulnerability": "Vulnerability", "weakness": "Weakness", "cripple": "Cripple",
        "crippled": "Cripple", "immobilize": "Immobilize", "immobilized": "Immobilize",
        "blind": "Blind", "blinded": "Blind", "chill": "Chill", "chilled": "Chill",
        "fear": "Fear", "slow": "Slow", "daze": "Daze", "stun": "Stun",
    }
    return names.get(raw.strip().lower())


def _parse_skill_facts(infobox_params: dict[str, str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    source = "\n".join([infobox_params.get("facts", ""), infobox_params.get("missing facts", "")])
    damage_facts: list[dict[str, Any]] = []
    conditions: list[dict[str, Any]] = []
    for block in _balanced_templates(source):
        name, params, positional = _parse_template(block)
        if name.lower().replace("_", " ") != "skill fact":
            continue
        fact = positional[0].strip().lower() if positional else str(params.get("type", "")).strip().lower()
        coefficient = _num(params.get("coefficient"))
        strikes = _num(params.get("strikes") or params.get("hits"))
        number = _num(params.get("number") or (positional[1] if len(positional) > 1 else None))
        if fact in {"damage", "strike damage", "power damage"} or coefficient is not None:
            damage_facts.append({
                "coefficient": coefficient,
                "strikes": _integerish(strikes) if strikes is not None else None,
                "number": number,
                "text": _strip_markup(params.get("text", fact.title())),
            })
        condition = _condition_name(fact)
        if condition:
            duration = _num(params.get("duration") or (positional[1] if len(positional) > 1 else None)) or 0.0
            stacks = _num(params.get("stacks") or params.get("apply count") or params.get("count")) or 1.0
            conditions.append({
                "condition": condition,
                "stacks": int(stacks) if float(stacks).is_integer() else stacks,
                "duration": float(duration),
            })
    return damage_facts, conditions


def _best_total_coefficient(damage_facts: list[dict[str, Any]]) -> tuple[float | None, int | None, str | None]:
    valid = [f for f in damage_facts if f.get("coefficient") is not None]
    if not valid:
        return None, None, None
    total = 0.0
    total_hits = 0
    display: list[str] = []
    for fact in valid:
        coeff = float(fact["coefficient"])
        strikes = int(fact.get("strikes") or 1)
        # Wiki convention commonly stores total coefficient even with strikes. Do not multiply automatically.
        total += coeff
        total_hits += strikes
        display.append(f"{coeff:g}" + (f" ({strikes} hits)" if strikes > 1 else ""))
    return total, total_hits or None, " + ".join(display)


def _classification_from_infobox(params: dict[str, str], fallback: dict[str, Any], page_title: str = "") -> dict[str, str]:
    slot_raw = _strip_markup(params.get("slot", "" )).lower()
    weapon = "None"
    for key in ("twohand", "mainhand", "offhand", "bundle", "mechanic weapon"):
        if params.get(key):
            weapon = _strip_markup(params[key]).title()
            break
    if weapon == "None":
        weapon = str(fallback.get("weapon_type") or "None")
    weapon_slot = _integerish(_num(params.get("weapon slot")))
    api_slot = str(fallback.get("slot") or "Unknown")
    slot = f"Weapon_{weapon_slot}" if weapon_slot else api_slot
    category = str(fallback.get("type") or "Other")
    type_raw = _strip_markup(params.get("type", "")).lower()
    parent_raw = _strip_markup(params.get("parent skill", "")).lower()
    if slot_raw == "transform" or type_raw == "shroud" or "shadow shroud" in parent_raw:
        category = "Shroud"
        weapon = "Shadow Shroud"
        slot = f"Shroud_{weapon_slot}" if weapon_slot else "Shroud"
    elif slot_raw in {"weapon", "stealth attack"} or weapon_slot:
        category = "Stealth Attack" if "stealth" in slot_raw or "stealth" in type_raw else "Weapon"
    elif slot_raw in {"healing", "heal"}: category = "Heal"
    elif slot_raw == "utility": category = "Utility"
    elif slot_raw == "elite": category = "Elite"
    elif slot_raw in {"mechanic", "profession"}: category = "Profession"
    elif "downed" in slot_raw: category = "Downed"
    specialization = (_strip_markup(params.get("specialization", "")) or "Core").title()
    chain_role = "—"
    activation_type = _strip_markup(params.get("activation type", "")).lower()
    if activation_type == "chain": chain_role = "Chain"
    return {
        "profession": "Thief",
        "specialization": specialization,
        "category": category,
        "weapon": weapon,
        "environment": "Aquatic" if weapon in {"Harpoon", "Speargun", "Trident"} or "underwater" in page_title.lower() else "Land",
        "slot": slot,
        "chain_role": chain_role,
    }


def _event_tags(classification: dict[str, str], initiative: float | None, hits: int | None, conditions: list[dict[str, Any]], params: dict[str, str]) -> list[str]:
    tags = ["skill_cast"]
    if hits and hits > 0: tags += ["skill_hit", "critical_hit"]
    if initiative and initiative > 0: tags.append("initiative_spent")
    if conditions: tags.append("condition_applied")
    if classification["category"] == "Stealth Attack": tags.append("stealth_attack")
    text = " ".join([params.get("description", ""), params.get("type", ""), params.get("movement type", "")]).lower()
    if "shadowstep" in text: tags.append("shadowstep")
    if "evade" in text: tags.append("evade")
    if "steal" in text: tags.append("steal_used")
    if "mark" in text: tags.append("mark_applied")
    return list(dict.fromkeys(tags))


def _page_id_map() -> dict[str, dict[str, Any]]:
    """Map game skill IDs to exact GW2 Wiki pages via Semantic MediaWiki."""
    result: dict[str, dict[str, Any]] = {}
    offset = 0
    while True:
        # Do not restrict by skill supertype here. Weapon, stealth, profession,
        # utility and elite skills use different supertypes on the wiki. The
        # profession property plus exact game ID is the reliable key.
        ask = (
            "[[Is for profession::Thief]]"
            "|?Has game id=ID|?Is for specialization=Specialization"
            f"|limit=500|offset={offset}"
        )
        payload = _request_json({"action": "ask", "query": ask, "format": "json"})
        rows = ((payload.get("query") or {}).get("results") or {})
        for title, row in rows.items():
            printouts = row.get("printouts") or {}
            ids = printouts.get("ID") or printouts.get("Has game id") or []
            for raw_id in ids:
                if isinstance(raw_id, dict): raw_id = raw_id.get("value") or raw_id.get("fulltext")
                try: sid = str(int(float(raw_id)))
                except (TypeError, ValueError): continue
                result[sid] = {"title": title, "fullurl": row.get("fullurl", "")}
        if len(rows) < 500:
            break
        offset += 500
    return result


def _fetch_wikitext(titles: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch page source and retain aliases for requested, normalized and redirected titles."""
    result: dict[str, dict[str, Any]] = {}
    for batch in _chunks(titles, 40):
        payload = _request_json({
            "action": "query", "prop": "revisions|info", "rvprop": "ids|timestamp|content",
            "rvslots": "main", "inprop": "url", "redirects": 1, "titles": "|".join(batch), "format": "json", "formatversion": 2,
        })
        query = payload.get("query") or {}
        aliases: dict[str, str] = {}
        for row in query.get("normalized") or []:
            aliases[str(row.get("from") or "")] = str(row.get("to") or "")
        for row in query.get("redirects") or []:
            aliases[str(row.get("from") or "")] = str(row.get("to") or "")

        canonical: dict[str, dict[str, Any]] = {}
        for page in query.get("pages") or []:
            title = str(page.get("title") or "")
            revs = page.get("revisions") or []
            rev = revs[0] if revs else {}
            slots = rev.get("slots") or {}
            text = ((slots.get("main") or {}).get("content")) or rev.get("content") or ""
            record = {
                "text": text,
                "revid": rev.get("revid"),
                "timestamp": rev.get("timestamp"),
                "fullurl": page.get("fullurl", ""),
                "title": title,
                "missing": bool(page.get("missing")),
            }
            canonical[title] = record
            result[title] = record

        # Resolve alias chains so callers can look up the exact title they asked for.
        for requested in batch:
            current = requested
            seen: set[str] = set()
            while current in aliases and current not in seen:
                seen.add(current)
                current = aliases[current]
            if current in canonical:
                result[requested] = canonical[current]
    return result


def _candidate_titles(skill: dict[str, Any]) -> list[str]:
    """Generate conservative title variants used by the GW2 Wiki."""
    name = str(skill.get("name") or "").strip()
    if not name:
        return []
    weapon = str(skill.get("weapon_type") or "").strip()
    slot = str(skill.get("slot") or "").strip()
    variants = [
        name,
        f"{name} (skill)",
        f"{name} (thief skill)",
        f"{name} (Thief skill)",
    ]
    if weapon and weapon not in {"None", "Unknown"}:
        variants += [f"{name} ({weapon})", f"{name} ({weapon} skill)"]
    if slot.startswith("Profession_"):
        variants += [f"{name} (profession skill)"]
    # Preserve order while removing duplicates.
    return list(dict.fromkeys(variants))


def _page_matches_skill(page: dict[str, Any] | None, skill_id: str) -> bool:
    if not page or page.get("missing"):
        return False
    params, _ = _find_infobox(str(page.get("text") or ""))
    if not params:
        return False
    wiki_id = _num(params.get("id"))
    if wiki_id is None:
        return False
    return str(int(wiki_id)) == str(int(float(skill_id)))


def _search_page_by_id(skill: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Resolve difficult aliases by searching likely titles and requiring an exact game-ID match."""
    sid = str(skill.get("id") or "")
    name = str(skill.get("name") or "").strip()
    if not sid or not name:
        return None
    try:
        payload = _request_json({
            "action": "query", "list": "search",
            "srsearch": f'intitle:"{name}"', "srnamespace": 0, "srlimit": 12,
            "format": "json", "formatversion": 2,
        })
    except Exception:
        return None
    titles = [str(row.get("title") or "") for row in ((payload.get("query") or {}).get("search") or [])]
    titles = [t for t in titles if t]
    if not titles:
        return None
    pages = _fetch_wikitext(titles)
    for title in titles:
        page = pages.get(title)
        if _page_matches_skill(page, sid):
            return title, page
    return None


def _find_infobox(text: str) -> tuple[dict[str, str], str | None]:
    # Capture outer top-level templates, then accept skill infobox variants.
    for block in _balanced_templates(text):
        name, params, _ = _parse_template(block)
        normalized = name.lower().replace("_", " ").strip()
        if normalized in {"skill infobox", "user skill infobox"}:
            return params, normalized
    return {}, None


def build_wiki_override(skill: dict[str, Any], page: dict[str, Any], page_title: str) -> dict[str, Any]:
    params, template_name = _find_infobox(str(page.get("text") or ""))
    if not params:
        return {
            "data_status": "Needs review",
            "wiki_url": page.get("fullurl") or f"https://wiki.guildwars2.com/wiki/{urllib.parse.quote(page_title.replace(' ', '_'))}",
            "review_flags": ["Could not parse a Skill infobox from the current wiki page"],
            "wiki_revision": page.get("revid"),
        }
    damage_facts, conditions = _parse_skill_facts(params)
    coefficient, hits, display = _best_total_coefficient(damage_facts)
    activation = _num(params.get("activation"))
    initiative = _num(params.get("initiative"))
    recharge = _num(params.get("recharge"))
    classification = _classification_from_infobox(params, skill, page_title)
    result: dict[str, Any] = {
        "classification": classification,
        "wiki_url": page.get("fullurl") or f"https://wiki.guildwars2.com/wiki/{urllib.parse.quote(page_title.replace(' ', '_'))}",
        "wiki_page": page_title,
        "wiki_revision": page.get("revid"),
        "verified_mode": "PvE",
        "verified_on": datetime.now(timezone.utc).date().isoformat(),
        "wiki_synced": True,
        "source_fields": {
            "classification": "GW2 Wiki Skill infobox",
            "cast_time": "GW2 Wiki Skill infobox",
            "initiative_cost": "GW2 Wiki Skill infobox",
            "recharge": "GW2 Wiki Skill infobox",
            "power_coefficient": "GW2 Wiki skill facts",
            "hits": "GW2 Wiki skill facts",
            "conditions": "GW2 Wiki skill facts",
        },
    }
    if activation is not None: result["cast_time"] = activation
    if initiative is not None: result["initiative_cost"] = _integerish(initiative)
    if recharge is not None: result["recharge_override"] = recharge
    if coefficient is not None:
        result["power_coefficient"] = coefficient
        result["coefficient_display"] = display or f"{coefficient:g}"
    if hits is not None: result["hits"] = hits
    if conditions: result["conditions"] = conditions
    result["event_tags"] = _event_tags(classification, initiative, hits, conditions, params)
    flags: list[str] = []
    wiki_id = _num(params.get("id"))
    api_id = _num(skill.get("id"))
    if wiki_id is not None and api_id is not None and int(wiki_id) != int(api_id):
        flags.append(f"Wiki page game ID {int(wiki_id)} does not match API skill ID {int(api_id)}; likely a same-name variant")
    if classification["category"] in {"Weapon", "Stealth Attack"} and coefficient is None and (hits or 0) > 0:
        flags.append("No PvE power coefficient found in structured wiki skill facts")
    if classification["category"] in {"Weapon", "Stealth Attack"} and activation is None:
        flags.append("No activation time stored on the wiki infobox")
    if template_name != "skill infobox":
        flags.append(f"Parsed legacy template: {template_name}")
    result["review_flags"] = flags
    result["data_status"] = "Wiki verified" if not flags else "Partial"
    result["notes"] = "Automatically synchronized from structured GW2 Wiki infobox and skill-fact parameters. Manual overrides take precedence."
    return result


def sync_all_thief_wiki_data(skills: list[dict[str, Any]], override_path: Path, *, preserve_manual: bool = True) -> dict[str, int]:
    id_map = _page_id_map()
    skill_by_id = {str(s.get("id")): s for s in skills if s.get("id") is not None}
    relevant = {sid: row for sid, row in id_map.items() if sid in skill_by_id}

    # First pass: exact SMW game-ID mapping plus conservative title variants.
    title_candidates: dict[str, list[str]] = {}
    for sid, skill in skill_by_id.items():
        candidates: list[str] = []
        if sid in relevant:
            candidates.append(str(relevant[sid]["title"]))
        candidates.extend(_candidate_titles(skill))
        title_candidates[sid] = list(dict.fromkeys(t for t in candidates if t))

    all_titles = sorted({title for rows in title_candidates.values() for title in rows})
    pages = _fetch_wikitext(all_titles)

    try:
        existing = json.loads(override_path.read_text(encoding="utf-8")) if override_path.exists() else {}
    except (OSError, json.JSONDecodeError):
        existing = {}
    if not isinstance(existing, dict):
        existing = {}

    counts = {
        "mapped": 0, "wiki_verified": 0, "partial": 0, "review": 0,
        "missing_page": 0, "resolved_by_search": 0, "id_mismatch": 0,
    }

    for sid, skill in skill_by_id.items():
        chosen_title: str | None = None
        chosen_page: dict[str, Any] | None = None
        for title in title_candidates.get(sid, []):
            page = pages.get(title)
            if _page_matches_skill(page, sid):
                chosen_title, chosen_page = title, page
                break

        # Last resort: MediaWiki full-text title search, still requiring exact infobox ID.
        if chosen_page is None:
            found = _search_page_by_id(skill)
            if found:
                chosen_title, chosen_page = found
                counts["resolved_by_search"] += 1

        if chosen_page is None or chosen_title is None:
            counts["missing_page"] += 1
            continue

        counts["mapped"] += 1
        generated = build_wiki_override(skill, chosen_page, str(chosen_page.get("title") or chosen_title))
        old = existing.get(sid, {}) if isinstance(existing.get(sid), dict) else {}
        # Existing hand-reviewed fields win; generated metadata fills the rest.
        if preserve_manual and old:
            generated.update(old)
            generated.setdefault("wiki_synced", True)
        existing[sid] = generated
        status = str(generated.get("data_status"))
        if status == "Wiki verified": counts["wiki_verified"] += 1
        elif status == "Partial": counts["partial"] += 1
        else: counts["review"] += 1

    override_path.parent.mkdir(parents=True, exist_ok=True)
    override_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    return counts

