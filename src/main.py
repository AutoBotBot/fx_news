"""
Morning brief orchestrator — runs at 07:30 UK time on weekdays.

Fetches price data, correlations, calendar, and headlines; ranks the
morning catalysts; asks Claude Sonnet to summarise that ranked context;
writes to Notion; exports a research row; and sends a short Telegram
snapshot.

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
from src.research_dataset import upsert_session_row
from src.research_features import build_morning_features
from src.run_health import record_run_health
from src.telegram_send import escape_markdown_v2, send_message

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

LONDON = pytz.timezone("Europe/London")


def _send(text: str, parse_mode: str = "MarkdownV2") -> bool:
    return asyncio.run(send_message(text, parse_mode=parse_mode))


def _alert(stage: str, error: str) -> None:
    msg = f"⚠️ Morning brief failed at {stage}: {error}"
    logger.error(msg)
    _send(msg, parse_mode=None)


def _extract_overnight_summary(brief_text: str) -> str:
    for line in brief_text.split("\n"):
        stripped = line.strip().lstrip("-").strip()
        if stripped and not stripped.startswith("#") and len(stripped) > 30:
            return stripped
    return "Brief generated — see Notion for details."


def _fmt_asset_line(display_name: str, direction: str | None, change_pct: float | None) -> str:
    if change_pct is None:
        return f"{display_name}: data unavailable"
    sign = "+" if change_pct >= 0 else ""
    return f"{display_name}: {direction or 'Unknown'} ({sign}{change_pct:.3f}%)"


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _fmt_catalyst_line(catalyst: dict) -> str:
    label_note = {
        "GBP+": "supports Pound Sterling",
        "GBP-": "pressures Pound Sterling",
        "USD+": "supports the US Dollar",
        "USD-": "pressures the US Dollar",
        "Risk-on": "supports risk appetite",
        "Risk-off": "signals a defensive market mood",
        "Mixed": "has no clear one-way bias",
    }.get(catalyst["label"], "has mixed implications")
    return _truncate(
        (
        f"{catalyst['time_uk']} UK • {catalyst['label']} • "
        f"{catalyst['severity']} severity • {catalyst['confidence']} confidence • "
        f"{catalyst['title']} ({label_note})"
        ),
        180,
    )


def _build_telegram_message(
    brief_text: str,
    market: dict,
    corr: dict,
    parsed: dict,
    catalysts: list[dict],
    notion_url: str | None,
    today_uk: datetime,
) -> str:
    def e(s) -> str:
        return escape_markdown_v2(str(s))

    date_str = today_uk.strftime("%-d %b")
    asian_high = market.get("asian_high")
    asian_low = market.get("asian_low")
    asian_range = market.get("asian_range_pips")
    overnight = _truncate(_extract_overnight_summary(brief_text), 260)

    if asian_high is not None and asian_low is not None and asian_range is not None:
        asian_line = f"Asian range: H {e(f'{asian_high:.5f}')}  L {e(f'{asian_low:.5f}')}  {e(f'({asian_range} pips)')}"
    else:
        asian_line = "Asian range: data unavailable"

    lines = [
        f"🌅 *GBP/USD Brief — {e(date_str)}*",
        "",
        asian_line,
        f"Volatility: {e(parsed.get('volatility_expectation') or 'Unknown')}",
        f"Liquidity: {e(parsed.get('liquidity_context') or 'Unknown')}",
        e(_fmt_asset_line(
            corr.get("dxy_display_name") or "DXY",
            corr.get("dxy_direction"),
            corr.get("dxy_change_pct_24h"),
        )),
        e(_fmt_asset_line(
            corr.get("gold_display_name") or "Gold",
            corr.get("gold_direction"),
            corr.get("gold_change_pct_24h"),
        )),
        e(_fmt_asset_line(
            corr.get("es_display_name") or "ES",
            corr.get("es_direction"),
            corr.get("es_change_pct_24h"),
        )),
        "",
        f"*Top drivers*",
    ]

    top_catalysts = catalysts[:3]
    if top_catalysts:
        for catalyst in top_catalysts:
            lines.append(e(_fmt_catalyst_line(catalyst)))
    else:
        lines.append(e("No strong overnight driver stood out. This looks more like a cleaner, quieter morning."))

    lines.extend(["", e(overnight)])

    if notion_url:
        lines.extend(["", f"📔 [Open today's log]({notion_url})"])

    return "\n".join(lines)


def _format_headlines_for_notion(raw_headlines: list[dict]) -> list[dict]:
    result = []
    for h in raw_headlines:
        pub = h.get("published")
        pub_str = pub.strftime("%H:%M") + " UTC" if hasattr(pub, "strftime") else str(pub)
        result.append({**h, "published": pub_str})
    return result


def main() -> None:
    load_dotenv()

    now_uk = datetime.now(LONDON)
    force = os.environ.get("FORCE_RUN")

    if now_uk.weekday() >= 5:
        logger.info("Skipping — weekend (%s)", now_uk.strftime("%A"))
        sys.exit(0)

    if not force:
        hour, minute = now_uk.hour, now_uk.minute
        target_window = hour == 7 and 25 <= minute <= 35
        delayed_delivery_window = 7 <= hour < 11
        if not delayed_delivery_window:
            logger.info(
                "Outside delivery window (UK time %02d:%02d) — skipping. Set FORCE_RUN=1 to bypass.",
                hour,
                minute,
            )
            sys.exit(0)
        if not target_window:
            logger.warning(
                "Outside target 07:25–07:35 UK window (current %02d:%02d) — continuing because a delayed scheduler run is better than no brief.",
                hour,
                minute,
            )

    logger.info("Starting morning brief — %s UK", now_uk.strftime("%Y-%m-%d %H:%M"))
    logger.info("Configured Claude model: %s", news.get_configured_model())
    health = {
        "run_type": "morning",
        "model": news.get_configured_model(),
        "calendar_source": "unavailable",
        "calendar_count": 0,
        "headline_count": 0,
        "catalyst_count": 0,
        "used_fallback_brief": 0,
        "telegram_sent": 0,
        "notion_written": 0,
        "research_exported": 0,
    }

    page_id = None
    notion_url = None
    try:
        page_id = notion_log.get_or_create_today_page()
        notion_url = notion_log.get_page_url(page_id)
        if notion_log.section_has_content(page_id, "🌅 Morning Brief"):
            logger.info("Morning brief already exists for today — skipping duplicate send/write")
            health["notion_written"] = 1
            health["notion_url"] = notion_url
            health["skipped_duplicate"] = 1
            record_run_health(health)
            sys.exit(0)
    except Exception as e:
        logger.error("Initial Notion page check failed: %s — continuing without dedupe guard", e)

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
            "overnight_vs_avg_ratio",
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
        corr = {
            "dxy_direction": None,
            "dxy_change_pct_24h": None,
            "gold_direction": None,
            "gold_change_pct_24h": None,
            "es_direction": None,
            "es_change_pct_24h": None,
            "correlations_text": "Correlations unavailable.",
        }

    cal: list = []
    try:
        cal = calendar_fetch.get_upcoming_events(hours_ahead=6)
        health["calendar_source"] = calendar_fetch.get_last_source()
        health["calendar_count"] = len(cal)
        logger.info("Calendar fetched: %d events", len(cal))
    except Exception as e:
        logger.warning("Calendar fetch failed: %s — continuing without it", e)

    raw_headlines: list = []
    try:
        raw_headlines = news.fetch_headlines(hours_back=12)
        health["headline_count"] = len(raw_headlines)
        logger.info("Headlines fetched: %d", len(raw_headlines))
    except Exception as e:
        logger.warning("Headlines fetch failed: %s — continuing without them", e)

    catalysts = news.build_ranked_catalysts(headlines=raw_headlines, calendar=cal)
    health["catalyst_count"] = len(catalysts)
    logger.info("Ranked catalysts built: %d", len(catalysts))
    explainer_lines = news.build_daily_explainer(catalysts=catalysts, calendar=cal, corr=corr)

    brief_text = news.generate_session_context(
        catalysts=catalysts,
        headlines=raw_headlines,
        calendar=cal,
        price_summary=market.get("summary_text") or "No price data.",
        yesterday_recap=market.get("yesterday_recap_text") or "No recap data.",
        levels_text=market.get("levels_text") or "No levels data.",
        correlations_text=corr.get("correlations_text") or "No correlations data.",
    )

    quality = news.evaluate_brief_quality(brief_text)
    if quality["needs_fallback"]:
        logger.warning(
            "Claude output was weak or malformed — using deterministic fallback brief (%s)",
            ", ".join(quality["reasons"]) or "no reason captured",
        )
        health["used_fallback_brief"] = 1
        health["brief_quality_reasons"] = quality["reasons"]
        brief_text = news.build_fallback_brief(catalysts, market, cal, corr)
        parsed = news.parse_brief(brief_text)
    else:
        parsed = quality["parsed"]
    logger.info("Parsed brief fields: %s", parsed)

    try:
        if page_id is None:
            page_id = notion_log.get_or_create_today_page()
        notion_log.populate_morning_brief(
            page_id=page_id,
            brief_text=brief_text,
            headlines=[
                *[{**item, "display_text": item["display_text"]} for item in catalysts[:3]],
                *_format_headlines_for_notion(raw_headlines[:5]),
            ],
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
                "news_impact": news.estimate_news_impact(catalysts, cal),
            },
            explainer_lines=explainer_lines,
        )
        notion_url = notion_log.get_page_url(page_id)
        health["notion_written"] = 1
        health["notion_url"] = notion_url
        logger.info("Notion page populated: %s", notion_url)
    except Exception as e:
        logger.error("Notion write failed: %s — will continue without a page link", e)
        _alert("notion_write", str(e))

    try:
        research_row = build_morning_features(
            today_uk=now_uk,
            market=market,
            corr=corr,
            parsed_brief=parsed,
            calendar=cal,
            catalysts=catalysts,
        )
        upsert_session_row(research_row)
        health["research_exported"] = 1
        logger.info("Morning research row exported")
    except Exception as e:
        logger.error("Research export failed: %s", e)
        _alert("research_export", str(e))

    tg_msg = _build_telegram_message(
        brief_text=brief_text,
        market=market,
        corr=corr,
        parsed=parsed,
        catalysts=catalysts,
        notion_url=notion_url,
        today_uk=now_uk,
    )
    ok = _send(tg_msg)
    if ok:
        health["telegram_sent"] = 1
        logger.info("Telegram message sent")
    else:
        logger.error("Telegram send failed — brief is in Notion: %s", notion_url or "n/a")

    record_run_health(health)
    logger.info("Morning brief complete")


if __name__ == "__main__":
    main()
