import json
from pathlib import Path
from typing import Any


def read_json_file(path: Path, default: Any):
    if not path.exists() or path.stat().st_size == 0:
        return default
    try:
        with path.open('r', encoding='utf-8') as file:
            return json.load(file)
    except Exception:
        return default


def write_json_file(path: Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
