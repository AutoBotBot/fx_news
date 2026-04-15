import json
import os
from datetime import datetime
from pathlib import Path

import pytz

LONDON = pytz.timezone("Europe/London")
DEFAULT_HEALTH_PATH = "data/run_health.jsonl"


def _target_path(path: str | None = None) -> Path:
    target = Path(path or os.environ.get("RUN_HEALTH_PATH", DEFAULT_HEALTH_PATH))
    if not target.is_absolute():
        target = Path.cwd() / target
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def record_run_health(payload: dict, path: str | None = None) -> None:
    target = _target_path(path)
    row = {
        "timestamp_uk": datetime.now(LONDON).isoformat(),
        **payload,
    }
    with target.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=True) + "\n")
