# Economic calendar for the morning brief.
# Fetches UK and US high/medium-importance events from the Forex Factory RSS feed.
# No API key required. Returns an empty list on any failure — the brief must
# still work without calendar data.

import logging
from datetime import datetime, timedelta, timezone

import feedparser
import pytz

logger = logging.getLogger(__name__)

LONDON = pytz.timezone("Europe/London")
FF_RSS_URL = "https://rss.forexfactory.com"

_COUNTRY_MAP = {"GBP": "UK", "USD": "US"}
_IMPORTANCE_MAP = {"High": "high", "Medium": "medium"}


def _parse_ff_entry(entry: dict) -> dict | None:
    """
    Parse a single Forex Factory RSS entry.
    Returns a dict or None if the entry should be skipped.
    """
    title = entry.get("title", "")
    # FF titles are formatted: "Currency Event Name"
    # e.g. "GBP CPI y/y" or "USD Non-Farm Payrolls"
    parts = title.split(" ", 1)
    if len(parts) < 2:
        return None

    currency, event_name = parts[0].strip(), parts[1].strip()
    country = _COUNTRY_MAP.get(currency)
    if country is None:
        return None

    # Impact is stored in the ff_impact tag
    importance_raw = entry.get("ff_impact", "")
    importance = _IMPORTANCE_MAP.get(importance_raw)
    if importance is None:
        return None

    # Parse published time (RFC 2822 / struct_time from feedparser)
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
    }


def get_upcoming_events(hours_ahead: int = 6) -> list[dict]:
    """
    Fetch UK and US medium/high-importance economic events from Forex Factory RSS.

    Returns a list of event dicts sorted by time_utc, filtered to the next
    `hours_ahead` hours. Returns an empty list if the feed is unavailable.
    """
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
        parsed = _parse_ff_entry(entry)
        if parsed is None:
            continue
        # Only include events within the look-ahead window
        if parsed["time_utc"] < now_utc or parsed["time_utc"] > window_end:
            continue
        events.append(parsed)

    events.sort(key=lambda e: e["time_utc"])
    logger.info("Fetched %d upcoming events (next %dh)", len(events), hours_ahead)
    return events


if __name__ == "__main__":
    import pprint
    logging.basicConfig(level=logging.INFO)
    events = get_upcoming_events(hours_ahead=8)
    print(f"\n--- Upcoming Events (next 8 hours) — {len(events)} found ---")
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
