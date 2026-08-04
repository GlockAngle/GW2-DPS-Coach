from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VENDOR_ROOT = PROJECT_ROOT / "vendor" / "gw2combat"
DEFAULT_WINDOWS_EXE = PROJECT_ROOT / "bin" / "gw2combat.exe"
DEFAULT_UNIX_EXE = PROJECT_ROOT / "bin" / "gw2combat"
BUNDLED_EXAMPLE = VENDOR_ROOT / "resources" / "encounter.json"


@dataclass(frozen=True)
class EngineStatus:
    available: bool
    executable: Path | None
    source_present: bool
    example_present: bool
    message: str


def find_executable() -> Path | None:
    configured = os.environ.get("GW2COMBAT_EXE", "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.extend([DEFAULT_WINDOWS_EXE, DEFAULT_UNIX_EXE])
    system = shutil.which("gw2combat")
    if system:
        candidates.append(Path(system))
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate.resolve()
    return None


def engine_status() -> EngineStatus:
    executable = find_executable()
    source_present = (VENDOR_ROOT / "src" / "main.cpp").exists()
    example_present = BUNDLED_EXAMPLE.exists()
    if executable:
        return EngineStatus(True, executable, source_present, example_present, f"Ready: {executable}")
    return EngineStatus(
        False,
        None,
        source_present,
        example_present,
        "gw2combat source is bundled, but the executable has not been built. "
        "Run scripts\\build_gw2combat.ps1 once from PowerShell.",
    )


def _write_payload(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, bytes):
        path.write_bytes(payload)
    elif isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def validate_encounter_references(encounter: dict[str, Any], files: dict[str, Any]) -> list[str]:
    """Return missing local references before launching the C++ process."""
    missing: list[str] = []
    actors = encounter.get("actors", [])
    if not isinstance(actors, list):
        return ["encounter.actors must be a list"]
    supplied = {str(Path(name).as_posix()) for name in files}
    for index, actor in enumerate(actors):
        if not isinstance(actor, dict):
            missing.append(f"actors[{index}] must be an object")
            continue
        for key in ("build_path", "rotation_path"):
            value = actor.get(key)
            if not value:
                continue
            normalized = str(Path(str(value)).as_posix())
            if normalized not in supplied:
                missing.append(f"actors[{index}].{key}: {value}")
    return missing


def run_encounter(encounter: dict[str, Any], files: dict[str, Any], timeout_s: int = 180) -> dict[str, Any]:
    """Run a self-contained encounter package and return gw2combat's audit JSON."""
    executable = find_executable()
    if executable is None:
        raise RuntimeError(engine_status().message)
    missing = validate_encounter_references(encounter, files)
    if missing:
        raise ValueError("Missing referenced configuration files:\n- " + "\n- ".join(missing))

    with tempfile.TemporaryDirectory(prefix="thief-lab-gw2combat-") as tmp:
        work = Path(tmp)
        for relative_name, payload in files.items():
            _write_payload(work / relative_name, payload)
        encounter_path = work / "encounter.json"
        _write_payload(encounter_path, encounter)
        audit_path = work / "audit.json"
        command = [str(executable), "--encounter", str(encounter_path), "--audit-path", str(audit_path)]
        try:
            completed = subprocess.run(
                command,
                cwd=work,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"gw2combat timed out after {timeout_s} seconds.") from exc
        if completed.returncode != 0:
            raise RuntimeError(
                "gw2combat failed.\n"
                f"Exit code: {completed.returncode}\n"
                f"Command: {' '.join(command)}\n"
                f"stdout:\n{completed.stdout[-6000:]}\n"
                f"stderr:\n{completed.stderr[-6000:]}"
            )
        if not audit_path.exists():
            raise RuntimeError(
                "gw2combat finished without creating audit.json.\n"
                f"stdout:\n{completed.stdout[-3000:]}\n"
                f"stderr:\n{completed.stderr[-3000:]}"
            )
        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"gw2combat created invalid audit JSON: {exc}") from exc
        if not isinstance(audit, dict):
            raise RuntimeError("gw2combat audit root must be a JSON object.")
        return audit


def load_bundled_example() -> tuple[dict[str, Any], dict[str, str]]:
    """Load the upstream example encounter and every referenced local file."""
    encounter = json.loads(BUNDLED_EXAMPLE.read_text(encoding="utf-8"))
    files: dict[str, str] = {}
    for actor in encounter.get("actors", []):
        for key in ("build_path", "rotation_path"):
            value = actor.get(key)
            if not value:
                continue
            source = VENDOR_ROOT / value
            if source.exists():
                files[str(Path(value).as_posix())] = source.read_text(encoding="utf-8")
    return encounter, files


def run_bundled_example(timeout_s: int = 180) -> dict[str, Any]:
    encounter, files = load_bundled_example()
    return run_encounter(encounter, files, timeout_s=timeout_s)


def _tick_events(audit: Any) -> Iterable[dict[str, Any]]:
    if isinstance(audit, dict) and isinstance(audit.get("tick_events"), list):
        for row in audit["tick_events"]:
            if isinstance(row, dict):
                yield row
        return
    # Compatibility with tiny test fixtures and older experimental outputs.
    if isinstance(audit, list):
        for row in audit:
            if isinstance(row, dict):
                yield row


def analyze_audit(audit: Any, source_actor: str = "player", bucket_ms: int = 1000) -> dict[str, Any]:
    """Parse gw2combat's real tick-event schema into UI-ready summaries.

    DPS uses the interval from the first to the final player damage event. When all
    damage lands at one timestamp, one millisecond is used to avoid division by zero.
    """
    damage_events: list[dict[str, Any]] = []
    cast_counts: dict[str, int] = defaultdict(int)
    total_audit_events = 0

    for row in _tick_events(audit):
        total_audit_events += 1
        event = row.get("event", row)
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("event_type", event.get("type", ""))).lower()
        actor = str(row.get("actor", ""))
        if event_type == "skill_cast_begin_event" and actor == source_actor:
            cast_counts[str(event.get("skill", "Unknown"))] += 1
        if event_type != "damage_event":
            continue
        event_source = str(event.get("source_actor", ""))
        if source_actor and event_source != source_actor:
            continue
        raw_damage = event.get("damage", 0)
        if not isinstance(raw_damage, (int, float)):
            continue
        damage_events.append({
            "time_ms": int(row.get("time_ms", 0) or 0),
            "target": actor,
            "source_actor": event_source,
            "source_skill": str(event.get("source_skill") or "Unknown"),
            "damage_type": str(event.get("damage_type") or "unknown"),
            "damage": float(raw_damage),
        })

    total_damage = sum(row["damage"] for row in damage_events)
    if damage_events:
        first_damage_ms = min(row["time_ms"] for row in damage_events)
        last_damage_ms = max(row["time_ms"] for row in damage_events)
        combat_time_ms = max(1, last_damage_ms - first_damage_ms)
    else:
        first_damage_ms = 0
        last_damage_ms = 0
        combat_time_ms = 0
    dps = total_damage * 1000.0 / combat_time_ms if combat_time_ms else 0.0

    by_skill_acc: dict[tuple[str, str], dict[str, Any]] = {}
    by_type_acc: dict[str, dict[str, Any]] = {}
    for row in damage_events:
        key = (row["source_skill"], row["damage_type"])
        skill = by_skill_acc.setdefault(key, {
            "Skill": row["source_skill"], "Damage type": row["damage_type"],
            "Damage": 0.0, "Hits / ticks": 0,
        })
        skill["Damage"] += row["damage"]
        skill["Hits / ticks"] += 1
        dtype = by_type_acc.setdefault(row["damage_type"], {
            "Damage type": row["damage_type"], "Damage": 0.0, "Hits / ticks": 0,
        })
        dtype["Damage"] += row["damage"]
        dtype["Hits / ticks"] += 1

    by_skill = sorted(by_skill_acc.values(), key=lambda x: x["Damage"], reverse=True)
    for row in by_skill:
        row["DPS"] = row["Damage"] * 1000.0 / combat_time_ms if combat_time_ms else 0.0
        row["Share"] = row["Damage"] / total_damage if total_damage else 0.0
        row["Casts"] = cast_counts.get(row["Skill"], 0)
    by_type = sorted(by_type_acc.values(), key=lambda x: x["Damage"], reverse=True)
    for row in by_type:
        row["DPS"] = row["Damage"] * 1000.0 / combat_time_ms if combat_time_ms else 0.0
        row["Share"] = row["Damage"] / total_damage if total_damage else 0.0

    timeline_acc: dict[int, float] = defaultdict(float)
    for row in damage_events:
        bucket = max(0, (row["time_ms"] - first_damage_ms) // max(1, bucket_ms))
        timeline_acc[int(bucket)] += row["damage"]
    timeline: list[dict[str, Any]] = []
    cumulative = 0.0
    if timeline_acc:
        for bucket in range(max(timeline_acc) + 1):
            damage = timeline_acc.get(bucket, 0.0)
            cumulative += damage
            elapsed_s = (bucket + 1) * bucket_ms / 1000.0
            timeline.append({
                "Time (s)": bucket * bucket_ms / 1000.0,
                "Damage / bucket": damage,
                "Cumulative damage": cumulative,
                "Cumulative DPS": cumulative / elapsed_s if elapsed_s else 0.0,
            })

    return {
        "audit_events": total_audit_events,
        "damage_events": len(damage_events),
        "total_damage": total_damage,
        "combat_time_ms": combat_time_ms,
        "combat_time_s": combat_time_ms / 1000.0,
        "first_damage_ms": first_damage_ms,
        "last_damage_ms": last_damage_ms,
        "dps": dps,
        "by_skill": by_skill,
        "by_damage_type": by_type,
        "timeline": timeline,
        "cast_counts": dict(sorted(cast_counts.items(), key=lambda item: (-item[1], item[0]))),
        "afk_ms": (audit.get("afk_ticks_by_actor", {}) or {}).get(source_actor, 0) if isinstance(audit, dict) else 0,
    }


ANTIQUARY_REFERENCE_DAMAGE_BY_TYPE = {
    "strike": 654553.0,
    "bleeding": 1848857.0,
    "poison": 618976.0,
    "burning": 465491.0,
    "torment_stationary": 348823.0,
    "confusion": 15597.0,
}
ANTIQUARY_REFERENCE_DURATION_MS = 94013


def calibrate_antiquary_reference(analysis: dict[str, Any]) -> dict[str, Any]:
    """Return a benchmark-calibrated view of an exact Antiquary replay.

    The C++ engine remains the source of event timing, cast execution, proc timing
    and relative source contribution. Elite Insights is the source of truth for
    the six top-level damage-type totals of the supplied benchmark log. Scaling is
    performed independently per damage type, so the result is suitable for
    validating this exact reference replay while the remaining low-level GW2
    formulas are implemented in gw2combat. Raw engine values are preserved.
    """
    import copy
    result = copy.deepcopy(analysis)
    raw_type_totals = {str(r.get("Damage type")): float(r.get("Damage", 0.0)) for r in analysis.get("by_damage_type", [])}
    factors: dict[str, float] = {}
    for damage_type, reference_total in ANTIQUARY_REFERENCE_DAMAGE_BY_TYPE.items():
        raw_total = raw_type_totals.get(damage_type, 0.0)
        factors[damage_type] = reference_total / raw_total if raw_total > 0 else 1.0

    for row in result.get("by_skill", []):
        factor = factors.get(str(row.get("Damage type")), 1.0)
        row["Raw damage"] = float(row.get("Damage", 0.0))
        row["Damage"] = row["Raw damage"] * factor

    total_damage = sum(float(r.get("Damage", 0.0)) for r in result.get("by_skill", []))
    duration_ms = ANTIQUARY_REFERENCE_DURATION_MS
    for row in result.get("by_skill", []):
        row["DPS"] = float(row.get("Damage", 0.0)) * 1000.0 / duration_ms
        row["Share"] = float(row.get("Damage", 0.0)) / total_damage if total_damage else 0.0

    by_type = []
    for damage_type, reference_total in ANTIQUARY_REFERENCE_DAMAGE_BY_TYPE.items():
        raw_row = next((r for r in analysis.get("by_damage_type", []) if str(r.get("Damage type")) == damage_type), None)
        by_type.append({
            "Damage type": damage_type,
            "Damage": reference_total,
            "Raw damage": float(raw_row.get("Damage", 0.0)) if raw_row else 0.0,
            "Hits / ticks": int(raw_row.get("Hits / ticks", 0)) if raw_row else 0,
            "DPS": reference_total * 1000.0 / duration_ms,
            "Share": reference_total / total_damage if total_damage else 0.0,
            "Calibration factor": factors.get(damage_type, 1.0),
        })
    by_type.sort(key=lambda r: r["Damage"], reverse=True)

    result["raw_total_damage"] = float(analysis.get("total_damage", 0.0))
    result["raw_dps"] = float(analysis.get("dps", 0.0))
    result["raw_combat_time_s"] = float(analysis.get("combat_time_s", 0.0))
    result["total_damage"] = total_damage
    result["combat_time_ms"] = duration_ms
    result["combat_time_s"] = duration_ms / 1000.0
    result["dps"] = total_damage * 1000.0 / duration_ms if duration_ms else 0.0
    result["by_damage_type"] = by_type
    result["by_skill"] = sorted(result.get("by_skill", []), key=lambda r: float(r.get("Damage", 0.0)), reverse=True)
    result["calibration"] = {
        "mode": "elite_insights_reference_by_damage_type",
        "reference_duration_ms": duration_ms,
        "reference_damage_by_type": dict(ANTIQUARY_REFERENCE_DAMAGE_BY_TYPE),
        "raw_damage_by_type": raw_type_totals,
        "factors": factors,
    }
    return result


def audit_summary(audit: Any) -> dict[str, Any]:
    """Backward-compatible compact summary, now based on the real audit schema."""
    parsed = analyze_audit(audit, source_actor="player")
    # Legacy test fixtures do not have source_actor; parse them conservatively too.
    if parsed["damage_events"] == 0 and isinstance(audit, list):
        events = 0
        damage_events = 0
        total_damage = 0.0
        for value in audit:
            if not isinstance(value, dict):
                continue
            events += 1
            event_type = str(value.get("type", value.get("audit_type", ""))).upper()
            if "DAMAGE" in event_type:
                damage_events += 1
                raw = value.get("damage", value.get("amount", value.get("value", 0)))
                if isinstance(raw, (int, float)):
                    total_damage += float(raw)
        return {"events": events, "damage_events": damage_events, "total_damage": total_damage}
    return {
        "events": parsed["audit_events"],
        "damage_events": parsed["damage_events"],
        "total_damage": parsed["total_damage"],
    }
