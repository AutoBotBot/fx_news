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

from src import block_data, notion_log
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

    # --- Fetch block data ---
    blocks: dict = {}
    try:
        blocks = block_data.get_daily_blocks()
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
        )
        notion_url = notion_log.get_page_url(page_id)
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

    # --- Telegram confirmation ---
    tg_msg = _build_telegram_message(blocks, notion_url, now_uk)
    ok = _send(tg_msg)
    if ok:
        logger.info("Telegram confirmation sent")
    else:
        logger.error("Telegram send failed — block data is in Notion: %s", notion_url)

    logger.info("End-of-day capture complete")


if __name__ == "__main__":
    main()
