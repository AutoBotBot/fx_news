"""
End-of-day capture orchestrator — runs at 12:01 PM UK time on weekdays.

Fetches 5-minute GBP/USD block data for the three intraday time blocks
and appends them to today's Notion page.

Test locally: FORCE_RUN=1 uv run python -m src.end_of_day
Note: Open Block and Session Block will return None before the session ends.
"""

import asyncio
import logging
import os
import sys
from datetime import datetime

import pytz
from dotenv import load_dotenv

from src import block_data, notion_log, price_data
from src.research_dataset import sync_labels_from_notion, upsert_session_row
from src.research_features import build_session_features
from src.run_health import record_run_health
from src.telegram_send import escape_markdown_v2, send_message

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

LONDON = pytz.timezone("Europe/London")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _send(text: str, parse_mode: str = "MarkdownV2") -> bool:
    return asyncio.run(send_message(text, parse_mode=parse_mode))


def _alert(stage: str, error: str) -> None:
    msg = f"⚠️ End-of-day capture failed at {stage}: {error}"
    logger.error(msg)
    _send(msg, parse_mode=None)


def _block_line(label: str, block: dict) -> str:
    """One-line summary for a single block."""
    if block.get("high") is None:
        return f"{label} ({block['time_start']}–{block['time_end']}): no data"
    return (
        f"{label} ({block['time_start']}–{block['time_end']}): "
        f"H {block['high']:.5f}  L {block['low']:.5f}  {block['range_pips']:.1f} pips"
    )


def _build_telegram_message(blocks: dict, notion_url: str | None, today_uk: datetime) -> str:
    """Compose a short MarkdownV2 Telegram confirmation message."""
    def e(s) -> str:
        return escape_markdown_v2(str(s))

    date_str = today_uk.strftime("%-d %b")

    asian = blocks["asian_block"]
    opn = blocks["open_block"]
    sess = blocks["session_block"]

    def fmt(label: str, block: dict) -> str:
        if block.get("high") is None:
            return f"{e(label)}: no data"
        h = f"{block['high']:.5f}"
        lo = f"{block['low']:.5f}"
        rng = f"{block['range_pips']:.1f}"
        return f"{e(label)}: H {e(h)}  L {e(lo)}  {e(rng)} pips"

    lines = [
        f"📊 *Block Data Captured — {e(date_str)}*",
        "",
        fmt("Asian  00:00–07:00", asian),
        fmt("Open   08:00–08:30", opn),
        fmt("Session 08:30–12:00", sess),
    ]

    if notion_url:
        lines.append("")
        lines.append(f"📔 [Today's log]({notion_url})")

    return "\n".join(lines)


def _infer_volatility_actual(session_range_pips: float | None, avg_daily_range_pips: float | None) -> str | None:
    if session_range_pips is None or avg_daily_range_pips is None or avg_daily_range_pips <= 0:
        return None
    baseline = avg_daily_range_pips / 4
    if baseline <= 0:
        return None
    ratio = session_range_pips / baseline
    if ratio >= 1.4:
        return "Expansion"
    if ratio <= 0.7:
        return "Contraction"
    return "Normal"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    load_dotenv()

    # --- Time gate ---
    now_uk = datetime.now(LONDON)
    force = os.environ.get("FORCE_RUN")

    if now_uk.weekday() >= 5:
        logger.info("Skipping — weekend (%s)", now_uk.strftime("%A"))
        sys.exit(0)

    if not force:
        hour, minute = now_uk.hour, now_uk.minute
        in_window = (hour == 11 and minute >= 55) or (hour == 12 and minute <= 15)
        if not in_window:
            logger.info(
                "Outside window (UK time %02d:%02d) — skipping. Set FORCE_RUN=1 to bypass.",
                hour, minute,
            )
            sys.exit(0)

    logger.info("Starting end-of-day capture — %s UK", now_uk.strftime("%Y-%m-%d %H:%M"))
    health = {
        "run_type": "end_of_day",
        "telegram_sent": 0,
        "notion_written": 0,
        "research_exported": 0,
    }

    # --- Fetch block data ---
    blocks: dict = {}
    volatility_actual = None
    try:
        blocks = block_data.get_daily_blocks()
        market_context = price_data.get_market_context()
        volatility_actual = _infer_volatility_actual(
            blocks["session_block"].get("range_pips"),
            market_context.get("range_20day_avg_pips"),
        )
        logger.info(
            "Blocks fetched — Asian: %s pips, Open: %s pips, Session: %s pips",
            blocks["asian_block"].get("range_pips"),
            blocks["open_block"].get("range_pips"),
            blocks["session_block"].get("range_pips"),
        )
    except Exception as e:
        _alert("block_data", str(e))
        sys.exit(1)

    # --- Notion writes ---
    page_id = None
    notion_url = None
    try:
        page_id = notion_log.get_or_create_today_page()
        notion_log.populate_block_data(
            page_id=page_id,
            asian_block=blocks["asian_block"],
            open_block=blocks["open_block"],
            session_block=blocks["session_block"],
            volatility_actual=volatility_actual,
        )
        notion_url = notion_log.get_page_url(page_id)
        health["notion_written"] = 1
        health["notion_url"] = notion_url
        logger.info("Block data written to Notion: %s", notion_url)
    except Exception as e:
        logger.error("Notion write failed: %s", e)
        # Build a plain-text fallback with values so data isn't lost
        fallback = (
            f"⚠️ End-of-day Notion write failed: {e}\n\n"
            f"Block data:\n"
            f"{_block_line('Asian', blocks['asian_block'])}\n"
            f"{_block_line('Open', blocks['open_block'])}\n"
            f"{_block_line('Session', blocks['session_block'])}"
        )
        _send(fallback, parse_mode=None)
        sys.exit(1)

    try:
        research_row = build_session_features(now_uk)
        upsert_session_row(research_row)
        sync_labels_from_notion(days_back=7)
        health["research_exported"] = 1
        logger.info("Session research row exported")
    except Exception as e:
        logger.error("Research export failed: %s", e)
        _alert("research_export", str(e))

    # --- Telegram confirmation ---
    tg_msg = _build_telegram_message(blocks, notion_url, now_uk)
    ok = _send(tg_msg)
    if ok:
        health["telegram_sent"] = 1
        logger.info("Telegram confirmation sent")
    else:
        logger.error("Telegram send failed — block data is in Notion: %s", notion_url)

    record_run_health(health)
    logger.info("End-of-day capture complete")


if __name__ == "__main__":
    main()
