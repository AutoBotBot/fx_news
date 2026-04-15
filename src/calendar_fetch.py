# Economic calendar for the morning brief.
# Fetches UK and US high/medium-importance events from Forex Factory.
# Falls back from the old RSS hostname to the weekly XML feed when needed.

import logging
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import feedparser
import pytz
import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

LONDON = pytz.timezone("Europe/London")
FF_RSS_URL = os.environ.get("FOREX_FACTORY_RSS", "https://rss.forexfactory.com")
FF_XML_URL = os.environ.get(
    "FOREX_FACTORY_XML",
    "https://nfs.faireconomy.media/ff_calendar_thisweek.xml",
)

_COUNTRY_MAP = {"GBP": "UK", "USD": "US"}
_IMPORTANCE_MAP = {"High": "high", "Medium": "medium"}
_LAST_SOURCE = "unavailable"


def get_last_source() -> str:
    return _LAST_SOURCE


def _parse_ff_rss_entry(entry: dict) -> dict | None:
    title = entry.get("title", "")
    parts = title.split(" ", 1)
    if len(parts) < 2:
        return None

    currency, event_name = parts[0].strip(), parts[1].strip()
    country = _COUNTRY_MAP.get(currency)
    if country is None:
        return None

    importance_raw = entry.get("ff_impact", "")
    importance = _IMPORTANCE_MAP.get(importance_raw)
    if importance is None:
        return None

    published_parsed = entry.get("published_parsed")
    if published_parsed is None:
        return None

    time_utc = datetime(*published_parsed[:6], tzinfo=timezone.utc)
    time_uk = time_utc.astimezone(LONDON)

    forecast = entry.get("ff_forecast") or None
    previous = entry.get("ff_previous") or None

    return {
        "time_uk": time_uk.strftime("%H:%M"),
        "time_utc": time_utc,
        "country": country,
        "event": event_name,
        "importance": importance,
        "forecast": forecast,
        "previous": previous,
        "source": "forex_factory_rss",
    }


def _fetch_rss_events(hours_ahead: int) -> list[dict]:
    try:
        feed = feedparser.parse(FF_RSS_URL)
        if feed.bozo and not feed.entries:
            logger.warning("Forex Factory RSS feed parse error: %s", feed.bozo_exception)
            return []
    except Exception as e:
        logger.warning("Failed to fetch Forex Factory RSS: %s", e)
        return []

    now_utc = datetime.now(timezone.utc)
    window_end = now_utc + timedelta(hours=hours_ahead)
    events = []
    for entry in feed.entries:
        parsed = _parse_ff_rss_entry(entry)
        if parsed is None:
            continue
        if parsed["time_utc"] < now_utc or parsed["time_utc"] > window_end:
            continue
        events.append(parsed)

    events.sort(key=lambda e: e["time_utc"])
    return events


def _parse_xml_time(date_text: str, time_text: str) -> datetime | None:
    date_text = (date_text or "").strip()
    time_text = (time_text or "").strip()
    if not date_text or not time_text:
        return None

    cleaned = time_text.lower().replace(" ", "")
    if cleaned == "all day":
        cleaned = "12:00am"
    if cleaned == "tentative":
        return None

    try:
        naive = datetime.strptime(f"{date_text} {cleaned}", "%m-%d-%Y %I:%M%p")
    except ValueError:
        return None

    # The XML feed times line up with UTC for standard macro releases.
    return naive.replace(tzinfo=timezone.utc)


def _text(node: ET.Element | None, tag: str) -> str:
    if node is None:
        return ""
    child = node.find(tag)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def _fetch_xml_events(hours_ahead: int) -> list[dict]:
    try:
        response = requests.get(
            FF_XML_URL,
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
    except Exception as e:
        logger.warning("Failed to fetch Forex Factory XML calendar: %s", e)
        return []

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as e:
        logger.warning("Failed to parse Forex Factory XML calendar: %s", e)
        return []

    now_utc = datetime.now(timezone.utc)
    window_end = now_utc + timedelta(hours=hours_ahead)
    events = []
    for event in root.findall(".//event"):
        currency = _text(event, "country")
        country = _COUNTRY_MAP.get(currency)
        if country is None:
            continue

        importance = _IMPORTANCE_MAP.get(_text(event, "impact"))
        if importance is None:
            continue

        time_utc = _parse_xml_time(_text(event, "date"), _text(event, "time"))
        if time_utc is None or time_utc < now_utc or time_utc > window_end:
            continue

        time_uk = time_utc.astimezone(LONDON)
        events.append(
            {
                "time_uk": time_uk.strftime("%H:%M"),
                "time_utc": time_utc,
                "country": country,
                "event": _text(event, "title"),
                "importance": importance,
                "forecast": _text(event, "forecast") or None,
                "previous": _text(event, "previous") or None,
                "source": "forex_factory_xml",
            }
        )

    events.sort(key=lambda e: e["time_utc"])
    return events


def get_upcoming_events(hours_ahead: int = 6) -> list[dict]:
    """
    Fetch UK and US medium/high-importance economic events.

    First tries the legacy RSS feed, then falls back to the weekly XML
    feed. Returns an empty list only if both sources fail or there are
    genuinely no events in the window.
    """
    global _LAST_SOURCE

    events = _fetch_rss_events(hours_ahead=hours_ahead)
    if events:
        _LAST_SOURCE = "forex_factory_rss"
        logger.info("Fetched %d upcoming events from RSS (next %dh)", len(events), hours_ahead)
        return events

    xml_events = _fetch_xml_events(hours_ahead=hours_ahead)
    if xml_events:
        _LAST_SOURCE = "forex_factory_xml"
        logger.info("Fetched %d upcoming events from XML fallback (next %dh)", len(xml_events), hours_ahead)
        return xml_events

    _LAST_SOURCE = "unavailable"
    logger.warning("No calendar events available from RSS or XML fallback")
    return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    events = get_upcoming_events(hours_ahead=8)
    print(f"\n--- Upcoming Events (next 8 hours) — {len(events)} found from {get_last_source()} ---")
    if events:
        for ev in events:
            forecast_str = f"  Forecast: {ev['forecast']}" if ev['forecast'] else ""
            previous_str = f"  Previous: {ev['previous']}" if ev['previous'] else ""
            print(
                f"[{ev['time_uk']} UK] [{ev['country']}] [{ev['importance'].upper()}] "
                f"{ev['event']}{forecast_str}{previous_str}"
            )
    else:
        print("No medium/high importance UK or US events in the next 8 hours.")
