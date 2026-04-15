import csv
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytz

from src import notion_log
from src.research_features import build_morning_features

logger = logging.getLogger(__name__)

LONDON = pytz.timezone("Europe/London")
DEFAULT_DATASET_PATH = "data/cable_session_features.csv"


def _dataset_path(path: str | None = None) -> Path:
    target = Path(path or os.environ.get("RESEARCH_DATASET_PATH", DEFAULT_DATASET_PATH))
    if not target.is_absolute():
        target = Path.cwd() / target
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _normalize_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=True)
    return value


def upsert_session_row(row: dict, path: str = DEFAULT_DATASET_PATH) -> None:
    """Upsert a single session row into the local CSV dataset."""
    session_date = row.get("session_date")
    if not session_date:
        raise ValueError("session_date is required for dataset upsert")

    target = _dataset_path(path)
    normalized = {key: _normalize_value(value) for key, value in row.items()}

    existing_rows: list[dict] = []
    fieldnames = list(normalized.keys())
    if target.exists():
        with target.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames or [])
            existing_rows = list(reader)

    for key in normalized:
        if key not in fieldnames:
            fieldnames.append(key)

    updated = False
    for existing in existing_rows:
        if existing.get("session_date") != session_date:
            continue
        for key, value in normalized.items():
            if value != "":
                existing[key] = value
            else:
                existing.setdefault(key, "")
        updated = True
        break

    if not updated:
        new_row = {field: "" for field in fieldnames}
        new_row.update(normalized)
        existing_rows.append(new_row)

    for existing in existing_rows:
        for field in fieldnames:
            existing.setdefault(field, "")

    existing_rows.sort(key=lambda item: item.get("session_date", ""))
    with target.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(existing_rows)


def sync_labels_from_notion(days_back: int = 30, path: str = DEFAULT_DATASET_PATH) -> int:
    """Mirror recent manual Notion labels into the local research dataset."""
    rows = notion_log.list_recent_page_summaries(days_back=days_back)
    updated = 0
    for row in rows:
        upsert_session_row(
            {
                "session_date": row["session_date"],
                "trades_taken": row.get("trades_taken"),
                "net_r": row.get("net_r"),
                "net_gbp": row.get("net_gbp"),
                "volatility_actual": row.get("volatility_actual"),
                "brief_useful": row.get("brief_useful"),
                "followed_rules": row.get("followed_rules"),
                "tags": row.get("tags") or [],
            },
            path=path,
        )
        updated += 1
    return updated


def backfill_market_only(days_back: int = 30, path: str = DEFAULT_DATASET_PATH) -> int:
    """
    One-off helper to backfill market-only rows from recent dates.
    Historical event fields are intentionally left blank.
    """
    written = 0
    today = datetime.now(LONDON).date()
    for offset in range(days_back):
        dt = datetime.combine(today - timedelta(days=offset), datetime.min.time())
        dt = LONDON.localize(dt)
        try:
            row = build_morning_features(
                today_uk=dt,
                market={},
                corr={},
                parsed_brief={},
                calendar=[],
                catalysts=[],
            )
        except Exception as e:
            logger.warning("Backfill skipped %s: %s", dt.date(), e)
            continue
        upsert_session_row(row, path=path)
        written += 1
    return written
