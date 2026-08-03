from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
        return EngineStatus(
            True,
            executable,
            source_present,
            example_present,
            f"Ready: {executable}",
        )
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
            if not value or (key == "rotation_path" and value == ""):
                continue
            normalized = str(Path(str(value)).as_posix())
            if normalized not in supplied:
                missing.append(f"actors[{index}].{key}: {value}")
    return missing


def run_encounter(encounter: dict[str, Any], files: dict[str, Any], timeout_s: int = 120) -> dict[str, Any]:
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
        completed = subprocess.run(
            [str(executable), "--encounter", str(encounter_path), "--audit-path", str(audit_path)],
            cwd=work,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "gw2combat failed.\n"
                f"Exit code: {completed.returncode}\n"
                f"stdout:\n{completed.stdout[-4000:]}\n"
                f"stderr:\n{completed.stderr[-4000:]}"
            )
        if not audit_path.exists():
            raise RuntimeError("gw2combat finished without creating audit.json")
        return json.loads(audit_path.read_text(encoding="utf-8"))


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


def run_bundled_example(timeout_s: int = 120) -> dict[str, Any]:
    encounter, files = load_bundled_example()
    return run_encounter(encounter, files, timeout_s=timeout_s)


def audit_summary(audit: Any) -> dict[str, Any]:
    """Return a conservative summary without assuming one fixed audit schema."""
    summary: dict[str, Any] = {"events": 0, "damage_events": 0, "total_damage": 0.0}

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            summary["events"] += 1
            event_type = str(value.get("type", value.get("audit_type", ""))).upper()
            if "DAMAGE" in event_type:
                summary["damage_events"] += 1
                for key in ("damage", "amount", "value"):
                    raw = value.get(key)
                    if isinstance(raw, (int, float)):
                        summary["total_damage"] += float(raw)
                        break
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(audit)
    return summary
