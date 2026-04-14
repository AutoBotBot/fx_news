"""
Morning brief orchestrator — runs at 07:30 UK time on weekdays.

Fetches price data, correlations, calendar, and headlines; generates
a Claude session context brief; writes to Notion; sends a Telegram
push notification.

Test locally: FORCE_RUN=1 uv run python -m src.main
"""

import asyncio
import logging
import os
import sys
from datetime import datetime

import pytz
from dotenv import load_dotenv

from src import calendar_fetch, correlations, news, notion_log, price_data
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
    """Send a plain-text failure alert to Telegram."""
    msg = f"⚠️ Morning brief failed at {stage}: {error}"
    logger.error(msg)
    _send(msg, parse_mode=None)


def _extract_overnight_summary(brief_text: str) -> str:
    """Pull the first substantive sentence from the brief for the Telegram push."""
    for line in brief_text.split("\n"):
        stripped = line.strip()
        # Skip markdown headings, bold labels, and very short lines
        if stripped and not stripped.startswith("#") and len(stripped) > 30:
            # Strip leading markdown bold markers if present
            stripped = stripped.lstrip("*").rstrip("*").strip()
            if len(stripped) > 20:
                return stripped
    return "Brief generated — see Notion for details."


def _build_telegram_message(
    brief_text: str,
    market: dict,
    corr: dict,
    parsed: dict,
    notion_url: str | None,
    today_uk: datetime,
) -> str:
    """Compose a short MarkdownV2 Telegram message."""
    def e(s) -> str:
        return escape_markdown_v2(str(s))

    date_str = today_uk.strftime("%-d %b")
    asian_high = market.get("asian_high")
    asian_low = market.get("asian_low")
    asian_range = market.get("asian_range_pips")
    vol = parsed.get("volatility_expectation") or "Unknown"
    liq = parsed.get("liquidity_context") or "Unknown"
    dxy = corr.get("dxy_direction") or "Unknown"
    overnight = _extract_overnight_summary(brief_text)

    if asian_high and asian_low and asian_range is not None:
        asian_line = f"Asian: H {e(f'{asian_high:.5f}')} L {e(f'{asian_low:.5f}')} {e(f'({asian_range} pips)')}"
    else:
        asian_line = "Asian: data unavailable"

    lines = [
        f"🌅 *GBP/USD Brief — {e(date_str)}*",
        "",
        asian_line,
        f"Vol: {e(vol)}",
        f"Liquidity: {e(liq)}",
        f"DXY: {e(dxy)}",
        "",
        e(overnight),
    ]

    if notion_url:
        lines.append("")
        lines.append(f"📔 [Open today's log]({notion_url})")

    return "\n".join(lines)


def _format_headlines_for_notion(raw_headlines: list[dict]) -> list[dict]:
    """Convert datetime published field to HH:MM UTC string for notion_log."""
    result = []
    for h in raw_headlines:
        pub = h.get("published")
        pub_str = pub.strftime("%H:%M") + " UTC" if hasattr(pub, "strftime") else str(pub)
        result.append({**h, "published": pub_str})
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    load_dotenv()

    # --- Time gate ---
    now_uk = datetime.now(LONDON)
    force = os.environ.get("FORCE_RUN")

    if now_uk.weekday() >= 5:  # Saturday=5, Sunday=6
        logger.info("Skipping — weekend (%s)", now_uk.strftime("%A"))
        sys.exit(0)

    if not force:
        hour, minute = now_uk.hour, now_uk.minute
        in_window = (hour == 7 and 25 <= minute <= 35)
        if not in_window:
            logger.info("Outside window (UK time %02d:%02d) — skipping. Set FORCE_RUN=1 to bypass.", hour, minute)
            sys.exit(0)

    logger.info("Starting morning brief — %s UK", now_uk.strftime("%Y-%m-%d %H:%M"))

    # --- Fetch pipeline ---
    market: dict = {}
    try:
        market = price_data.get_market_context()
        logger.info("Price data fetched")
    except Exception as e:
        _alert("price_data", str(e))
        market = {k: None for k in [
            "asian_high", "asian_low", "asian_range_pips", "current_price",
            "yesterday_session_high", "yesterday_session_low",
            "summary_text", "yesterday_recap_text", "levels_text",
        ]}
        market["summary_text"] = "Price data unavailable."
        market["yesterday_recap_text"] = "No recap data."
        market["levels_text"] = "No levels data."

    corr: dict = {}
    try:
        corr = correlations.get_correlations()
        logger.info("Correlations fetched")
    except Exception as e:
        _alert("correlations", str(e))
        corr = {"dxy_direction": None, "correlations_text": "Correlations unavailable."}

    cal: list = []
    try:
        cal = calendar_fetch.get_upcoming_events(hours_ahead=6)
        logger.info("Calendar fetched: %d events", len(cal))
    except Exception as e:
        logger.warning("Calendar fetch failed: %s — continuing without it", e)

    raw_headlines: list = []
    try:
        raw_headlines = news.fetch_headlines(hours_back=12)
        logger.info("Headlines fetched: %d", len(raw_headlines))
    except Exception as e:
        logger.warning("Headlines fetch failed: %s — continuing without them", e)

    # --- Generate brief ---
    brief_text = ""
    try:
        brief_text = news.generate_session_context(
            headlines=raw_headlines,
            calendar=cal,
            price_summary=market.get("summary_text") or "No price data.",
            yesterday_recap=market.get("yesterday_recap_text") or "No recap data.",
            levels_text=market.get("levels_text") or "No levels data.",
            correlations_text=corr.get("correlations_text") or "No correlations data.",
        )
        logger.info("Brief generated (%d chars)", len(brief_text))
    except Exception as e:
        _alert("brief_generation", str(e))
        sys.exit(1)

    parsed = news.parse_brief(brief_text)
    logger.info("Parsed: %s", parsed)

    # --- Notion writes ---
    page_id = None
    notion_url = None
    try:
        page_id = notion_log.get_or_create_today_page()
        notion_log.populate_morning_brief(
            page_id=page_id,
            brief_text=brief_text,
            headlines=_format_headlines_for_notion(raw_headlines),
            calendar=cal,
            levels_text=market.get("levels_text") or "",
            correlations_text=corr.get("correlations_text") or "",
            properties={
                "volatility_expectation": parsed.get("volatility_expectation"),
                "liquidity_context": parsed.get("liquidity_context"),
                "asian_high": market.get("asian_high"),
                "asian_low": market.get("asian_low"),
                "asian_range_pips": market.get("asian_range_pips"),
                "yesterday_high": market.get("yesterday_session_high"),
                "yesterday_low": market.get("yesterday_session_low"),
                "dxy_direction": corr.get("dxy_direction"),
            },
        )
        notion_url = notion_log.get_page_url(page_id)
        logger.info("Notion page populated: %s", notion_url)
    except Exception as e:
        logger.error("Notion write failed: %s — will send brief to Telegram without link", e)
        _alert("notion_write", str(e))

    # --- Telegram ---
    tg_msg = _build_telegram_message(
        brief_text=brief_text,
        market=market,
        corr=corr,
        parsed=parsed,
        notion_url=notion_url,
        today_uk=now_uk,
    )
    ok = _send(tg_msg)
    if ok:
        logger.info("Telegram message sent")
    else:
        logger.error("Telegram send failed — brief is in Notion: %s", notion_url or "n/a")

    logger.info("Morning brief complete")


if __name__ == "__main__":
    main()
