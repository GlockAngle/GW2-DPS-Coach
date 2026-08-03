from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

APP_DIR_NAME = "ThiefLab"


def user_data_dir() -> Path:
    """Return a persistent per-user folder outside the extracted project.

    Windows: %LOCALAPPDATA%/ThiefLab
    Other platforms: ~/.thief_lab
    """
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        root = Path(local_app_data) / APP_DIR_NAME
    else:
        root = Path.home() / ".thief_lab"
    root.mkdir(parents=True, exist_ok=True)
    return root


def persistent_json_path(filename: str, bundled_path: Path | None = None) -> Path:
    """Return persistent JSON path and migrate an existing bundled file once.

    This keeps saved builds/presets when the user replaces the project folder with
    a new ZIP. The bundled file is only copied when no persistent file exists yet.
    """
    target = user_data_dir() / filename
    if not target.exists():
        if bundled_path and bundled_path.exists():
            try:
                shutil.copy2(bundled_path, target)
            except OSError:
                target.write_text("{}", encoding="utf-8")
        else:
            target.write_text("{}", encoding="utf-8")
    return target


def load_json_dict(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_json_dict(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)
