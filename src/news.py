# News headlines, catalyst ranking, and Claude brief generation.
# The live brief stays strategy-agnostic: we rank the drivers
# deterministically, then ask Claude Sonnet to summarise those ranked
# catalysts in plain English without inventing new priorities.

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anthropic
import feedparser
import pytz
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

LONDON = pytz.timezone("Europe/London")
PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "session_context.md"

FEEDS = [
    ("Reuters Business", "https://feeds.reuters.com/reuters/businessNews"),
    ("FT Markets", "https://www.ft.com/markets?format=rss"),
    ("BBC Business", "http://feeds.bbci.co.uk/news/business/rss.xml"),
    ("ForexLive", "https://www.forexlive.com/feed/news"),
    ("Investing.com Forex", "https://www.investing.com/rss/news_1.rss"),
]

_GBP_TERMS = {
    "uk", "britain", "british", "sterling", "pound", "boe", "bank of england",
    "gilts", "ftse", "london", "ons",
}
_USD_TERMS = {
    "us", "u.s.", "america", "american", "dollar", "fed", "fomc",
    "treasury", "powell", "washington",
}
_MACRO_TERMS = {
    "cpi", "ppi", "inflation", "payroll", "jobs", "employment", "unemployment",
    "gdp", "retail sales", "pmi", "services", "manufacturing", "wages",
    "rates", "rate decision", "minutes", "speech", "consumer confidence",
}
_RISK_OFF_TERMS = {
    "war", "missile", "attack", "tariff", "sanction", "hormuz", "geopolitical",
    "risk-off", "oil spike", "shipping", "conflict",
}
_RISK_ON_TERMS = {
    "ceasefire", "deal", "talks", "risk-on", "stimulus", "support package",
    "truce",
}
_HAWKISH_TERMS = {
    "hotter", "higher than expected", "above expected", "re-accelerat",
    "sticky", "hawkish", "stronger", "surges", "rises more than expected",
}
_DOVISH_TERMS = {
    "cooler", "lower than expected", "below expected", "softer",
    "dovish", "weaker", "misses estimates", "slows more than expected",
}
_REVERSE_SURPRISE_TERMS = {"unemployment", "jobless claims"}
_EXPLAINER_LIBRARY = {
    "GBP/USD": (
        "GBP/USD: this is the Pound Sterling versus the US Dollar. If it rises, the Pound is gaining against the Dollar. "
        "If it falls, the Dollar is gaining against the Pound."
    ),
    "Asian range": (
        "Asian range: the highest and lowest GBP/USD prices set during the quieter overnight Asian session. "
        "London traders often watch whether price respects or breaks that overnight box."
    ),
    "pips": (
        "Pips: the standard small unit used to measure foreign exchange movement. In GBP/USD, 1 pip is 0.0001."
    ),
    "Volatility": (
        "Volatility: how much price is moving. Higher volatility usually means bigger price swings and faster reactions."
    ),
    "Liquidity": (
        "Liquidity: how easily price can trade without jumping around. Heavier liquidity usually means smoother movement, while thin liquidity can mean sharper spikes."
    ),
    "DXY": (
        "DXY (US Dollar Index): a basket that measures broad US Dollar strength. If DXY is rising, GBP/USD often finds it harder to move higher because the Dollar is strong more generally."
    ),
    "Gold": (
        "Gold: traders often watch gold as part of the broader risk and inflation picture. It can help show whether markets are moving toward safety or away from it."
    ),
    "ES": (
        "ES (S&P 500 futures): this tracks expected direction in major US stock index futures. It helps show whether markets look more confident or more defensive before cash markets open."
    ),
    "CPI": (
        "CPI (Consumer Price Index): a key inflation report. Inflation data matters because it can change expectations for interest rates, which often moves currencies."
    ),
    "PPI": (
        "PPI (Producer Price Index): an inflation report focused on prices received by producers. Traders watch it because it can hint at future inflation pressure."
    ),
    "GDP": (
        "GDP (Gross Domestic Product): a broad measure of economic growth. Stronger or weaker growth can shift expectations for a country's currency."
    ),
    "PMI": (
        "PMI (Purchasing Managers' Index): a survey-based growth indicator for businesses. It matters because it gives an early read on economic momentum."
    ),
    "BoE": (
        "BoE (Bank of England): the United Kingdom's central bank. Its rate decisions and speeches can move Pound Sterling sharply."
    ),
    "Fed": (
        "Fed (Federal Reserve): the United States central bank. Its rate decisions and comments often move the US Dollar across the board."
    ),
    "Risk-on": (
        "Risk-on: a market mood where traders are more willing to buy growth or risk assets. That can reduce safe-haven demand for the US Dollar."
    ),
    "Risk-off": (
        "Risk-off: a defensive market mood where traders move toward safety. That can increase demand for the US Dollar."
    ),
    "Forecast": (
        "Forecast: the market's consensus expectation before a data release. Price often reacts to whether the actual result beats or misses this number."
    ),
    "Previous": (
        "Previous: the last reported reading for that data series. It gives context for whether the new number shows improvement, weakness, or no real change."
    ),
    "GBP+": (
        "GBP+: a label meaning the news or event is supportive for Pound Sterling."
    ),
    "GBP-": (
        "GBP-: a label meaning the news or event is negative for Pound Sterling."
    ),
    "USD+": (
        "USD+: a label meaning the news or event is supportive for the US Dollar."
    ),
    "USD-": (
        "USD-: a label meaning the news or event is negative for the US Dollar."
    ),
    "Confidence": (
        "Confidence: how clear the likely market implication looks. High confidence means the read is relatively straightforward; low confidence means the link is weaker or more mixed."
    ),
    "Severity": (
        "Severity: how important the driver looks for the session. Higher severity means the item is more likely to matter for price action."
    ),
}


def get_configured_model() -> str:
    """Return the configured Claude model alias or snapshot."""
    return os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")


def fetch_headlines(hours_back: int = 12) -> list[dict]:
    """
    Fetch recent headlines from multiple RSS feeds.

    Returns a list of dicts with: title, summary, source, published (UTC
    datetime), link. Filtered to the last `hours_back` hours. Individual
    feed failures are logged and skipped. Results are de-duplicated by
    normalised title.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    seen_titles: set[str] = set()
    headlines: list[dict] = []

    for source, url in FEEDS:
        try:
            feed = feedparser.parse(url)
            count = 0
            for entry in feed.entries:
                title = entry.get("title", "").strip()
                if not title:
                    continue

                norm = re.sub(r"\s+", " ", title.lower().strip())
                if norm in seen_titles:
                    continue

                published_parsed = entry.get("published_parsed")
                if published_parsed is None:
                    continue

                published = datetime(*published_parsed[:6], tzinfo=timezone.utc)
                if published < cutoff:
                    continue

                seen_titles.add(norm)
                headlines.append(
                    {
                        "title": title,
                        "summary": entry.get("summary", ""),
                        "source": source,
                        "published": published,
                        "link": entry.get("link", ""),
                    }
                )
                count += 1

            logger.info("Feed '%s': %d headlines in window", source, count)

        except Exception as e:
            logger.warning("Feed '%s' failed: %s", source, e)

    headlines.sort(key=lambda h: h["published"], reverse=True)
    logger.info("Total headlines fetched: %d", len(headlines))
    return headlines


def _contains_any(text: str, needles: set[str]) -> bool:
    lower = text.lower()
    return any(term in lower for term in needles)


def _surprise_direction(text: str) -> int | None:
    """
    Return +1 when the first numeric surprise reads "above expected",
    -1 when it reads "below expected", else None.
    """
    lower = text.lower()
    if any(term in lower for term in _HAWKISH_TERMS):
        return 1
    if any(term in lower for term in _DOVISH_TERMS):
        return -1

    match = re.search(
        r"([+-]?\d+(?:\.\d+)?)\s*%?(?:\s*[a-z/]+)?\s+vs\.?\s+([+-]?\d+(?:\.\d+)?)",
        lower,
    )
    if not match:
        return None

    actual = float(match.group(1))
    expected = float(match.group(2))
    if actual > expected:
        return 1
    if actual < expected:
        return -1
    return 0


def _surprise_to_label(text: str, base_currency: str) -> str:
    surprise = _surprise_direction(text)
    if surprise is None or surprise == 0:
        return "Mixed"

    if _contains_any(text, _REVERSE_SURPRISE_TERMS):
        surprise *= -1

    if base_currency == "GBP":
        return "GBP+" if surprise > 0 else "GBP-"
    if base_currency == "USD":
        return "USD+" if surprise > 0 else "USD-"
    return "Mixed"


def _label_meaning(label: str) -> str:
    return {
        "GBP+": "supports Pound Sterling",
        "GBP-": "pressures Pound Sterling",
        "USD+": "supports the US Dollar",
        "USD-": "pressures the US Dollar",
        "Risk-on": "supports risk appetite",
        "Risk-off": "signals defensive risk appetite",
        "Mixed": "has no clear one-way bias",
    }.get(label, "has mixed market implications")


def _severity_from_score(score: float) -> str:
    if score >= 9:
        return "High"
    if score >= 5:
        return "Medium"
    return "Low"


def _confidence_from_score(score: float) -> str:
    if score >= 8:
        return "High"
    if score >= 4:
        return "Medium"
    return "Low"


def _headline_reason(title: str, label: str) -> str:
    if _contains_any(title, _RISK_OFF_TERMS):
        return "This is a broad risk sentiment headline that can pull the US Dollar stronger when markets turn defensive."
    if _contains_any(title, _RISK_ON_TERMS):
        return "This is a broader market mood headline that can soften demand for the US Dollar if risk appetite improves."
    if _contains_any(title, _GBP_TERMS):
        return f"This directly relates to the United Kingdom or the Bank of England and { _label_meaning(label) }."
    if _contains_any(title, _USD_TERMS):
        return f"This directly relates to the United States or the Federal Reserve and { _label_meaning(label) }."
    return "This can move GBP/USD, but the effect is less direct than a United Kingdom or United States macro release."


def _event_reason(event: dict) -> str:
    country_name = "United Kingdom" if event["country"] == "UK" else "United States"
    return (
        f"This scheduled {country_name} event lands during or near the London session and can move GBP/USD "
        "depending on the result versus expectations."
    )


def _calendar_score(event: dict, session_start: datetime) -> float:
    score = 4.0
    if event.get("importance") == "high":
        score += 5.0
    elif event.get("importance") == "medium":
        score += 2.5

    time_utc = event.get("time_utc")
    if isinstance(time_utc, datetime):
        time_uk = time_utc.astimezone(LONDON)
        minutes_from_open = int((time_uk - session_start).total_seconds() / 60)
        if 0 <= minutes_from_open <= 240:
            score += 4.0
            if minutes_from_open <= 60:
                score += 1.0
        elif -60 <= minutes_from_open < 0:
            score += 2.0

    event_name = event.get("event", "")
    if _contains_any(event_name, _MACRO_TERMS):
        score += 2.0
    return score


def _headline_score(headline: dict, now_utc: datetime) -> float:
    title = headline["title"]
    lower = title.lower()
    score = 0.0

    if _contains_any(lower, _MACRO_TERMS):
        score += 4.0
    if _contains_any(lower, _GBP_TERMS):
        score += 3.0
    if _contains_any(lower, _USD_TERMS):
        score += 3.0
    if _contains_any(lower, _RISK_OFF_TERMS | _RISK_ON_TERMS):
        score += 2.5

    source = headline.get("source", "")
    if source in {"Reuters Business", "FT Markets", "ForexLive"}:
        score += 1.0

    published = headline["published"]
    age_hours = max((now_utc - published).total_seconds() / 3600, 0.0)
    score += max(0.0, 4.0 - min(age_hours, 4.0))

    title_words = set(re.findall(r"[a-zA-Z]+", lower))
    if len(title_words & {"fed", "boe", "cpi", "ppi", "payroll", "inflation", "gdp", "rates"}) >= 2:
        score += 1.5

    return score


def _headline_label(title: str) -> str:
    lower = title.lower()
    if _contains_any(lower, _RISK_OFF_TERMS):
        return "Risk-off"
    if _contains_any(lower, _RISK_ON_TERMS):
        return "Risk-on"
    if _contains_any(lower, _GBP_TERMS):
        return _surprise_to_label(lower, "GBP")
    if _contains_any(lower, _USD_TERMS):
        return _surprise_to_label(lower, "USD")
    return "Mixed"


def _calendar_label(event: dict) -> str:
    event_name = event.get("event", "").lower()
    if _contains_any(event_name, _RISK_OFF_TERMS):
        return "Risk-off"
    if _contains_any(event_name, _RISK_ON_TERMS):
        return "Risk-on"
    return "Mixed"


def _catalyst_display_text(catalyst: dict) -> str:
    return (
        f"{catalyst['time_uk']} UK — {catalyst['label']} ({catalyst['severity']} severity, "
        f"{catalyst['confidence']} confidence): {catalyst['title']} — {catalyst['reason']}"
    )


def build_ranked_catalysts(
    headlines: list[dict],
    calendar: list[dict],
    limit: int = 8,
    now_utc: datetime | None = None,
) -> list[dict]:
    """
    Combine headlines and calendar events into one deterministic ranked list.

    Each catalyst has:
      kind, time_uk, title, source, label, severity, confidence, reason, rank_score
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    now_uk = now_utc.astimezone(LONDON)
    session_start = LONDON.localize(
        datetime(now_uk.year, now_uk.month, now_uk.day, 8, 0)
    )

    catalysts: list[dict] = []

    for event in calendar:
        score = _calendar_score(event, session_start)
        catalyst = {
            "kind": "calendar",
            "time_uk": event["time_uk"],
            "title": event["event"],
            "source": f"{event['country']} calendar",
            "label": _calendar_label(event),
            "severity": "High" if event.get("importance") == "high" else "Medium",
            "confidence": "High" if event.get("importance") == "high" else "Medium",
            "reason": _event_reason(event),
            "rank_score": round(score, 2),
        }
        catalyst["display_text"] = _catalyst_display_text(catalyst)
        catalysts.append(catalyst)

    for headline in headlines:
        score = _headline_score(headline, now_utc)
        label = _headline_label(headline["title"])
        catalyst = {
            "kind": "headline",
            "time_uk": headline["published"].astimezone(LONDON).strftime("%H:%M"),
            "title": headline["title"],
            "source": headline["source"],
            "label": label,
            "severity": _severity_from_score(score),
            "confidence": _confidence_from_score(score),
            "reason": _headline_reason(headline["title"], label),
            "rank_score": round(score, 2),
        }
        catalyst["display_text"] = _catalyst_display_text(catalyst)
        catalysts.append(catalyst)

    catalysts.sort(
        key=lambda item: (
            item["rank_score"],
            item["severity"] == "High",
            item["confidence"] == "High",
        ),
        reverse=True,
    )
    return catalysts[:limit]


def _format_headlines(headlines: list[dict]) -> str:
    if headlines:
        return "\n".join(
            f"- [{h['source']}] {h['title']} ({h['published'].strftime('%H:%M')} UTC)"
            for h in headlines
        )
    return "No headlines retrieved."


def _format_calendar(calendar: list[dict]) -> str:
    if not calendar:
        return "No medium/high-importance UK or US events scheduled."

    lines = []
    for ev in calendar:
        parts = [f"{ev['time_uk']} UK", ev["country"], ev["event"]]
        extras = []
        if ev.get("forecast"):
            extras.append(f"forecast: {ev['forecast']}")
        if ev.get("previous"):
            extras.append(f"previous: {ev['previous']}")
        line = " – ".join(parts)
        if extras:
            line += f" ({', '.join(extras)})"
        lines.append(f"- {line}")
    return "\n".join(lines)


def _format_catalysts(catalysts: list[dict]) -> str:
    if not catalysts:
        return "No ranked catalysts. Quiet overnight; use the raw inputs as supporting context only."

    return "\n".join(
        f"- {item['time_uk']} UK | {item['label']} | {item['severity']} severity | "
        f"{item['confidence']} confidence | {item['title']} | Why it matters: {item['reason']}"
        for item in catalysts[:5]
    )


def build_daily_explainer(
    catalysts: list[dict],
    calendar: list[dict],
    corr: dict,
) -> list[str]:
    """
    Build a small day-specific glossary in plain English.
    """
    text_parts = [
        " ".join(c.get("title", "") for c in catalysts[:5]),
        " ".join(c.get("reason", "") for c in catalysts[:5]),
        " ".join(ev.get("event", "") for ev in calendar[:6]),
        corr.get("correlations_text", ""),
        " ".join(c.get("label", "") for c in catalysts[:5]),
        " ".join(c.get("severity", "") for c in catalysts[:5]),
        " ".join(c.get("confidence", "") for c in catalysts[:5]),
    ]
    all_text = " ".join(text_parts)

    explainer_keys = ["GBP/USD", "Asian range", "pips", "Volatility", "Liquidity"]
    if corr.get("dxy_change_pct_24h") is not None:
        explainer_keys.append("DXY")
    if corr.get("gold_change_pct_24h") is not None:
        explainer_keys.append("Gold")
    if corr.get("es_change_pct_24h") is not None:
        explainer_keys.append("ES")

    conditional_terms = [
        "GBP+", "GBP-", "USD+", "USD-", "Risk-on", "Risk-off",
        "CPI", "PPI", "GDP", "PMI", "BoE", "Fed",
        "Forecast", "Previous", "Confidence", "Severity",
    ]
    for term in conditional_terms:
        if term.lower() in all_text.lower():
            explainer_keys.append(term)

    unique_keys = []
    for key in explainer_keys:
        if key not in unique_keys:
            unique_keys.append(key)

    return [_EXPLAINER_LIBRARY[key] for key in unique_keys[:12]]


def estimate_news_impact(catalysts: list[dict], calendar: list[dict]) -> str:
    """
    Estimate the day-level news impact for Notion.
    """
    if any(ev.get("importance") == "high" for ev in calendar):
        return "High"
    if any(item.get("severity") == "High" for item in catalysts[:3]):
        return "High"
    if any(ev.get("importance") == "medium" for ev in calendar):
        return "Medium"
    if any(item.get("severity") == "Medium" for item in catalysts[:5]):
        return "Medium"
    if catalysts:
        return "Low"
    return "None"


def _select_summary_headlines(headlines: list[dict], limit: int = 10) -> list[dict]:
    """Reduce prompt noise by only passing the most relevant raw headlines."""
    if not headlines:
        return []

    now_utc = datetime.now(timezone.utc)
    ranked = sorted(
        headlines,
        key=lambda item: (_headline_score(item, now_utc), item["published"]),
        reverse=True,
    )
    return ranked[:limit]


def generate_session_context(
    catalysts: list[dict],
    headlines: list[dict],
    calendar: list[dict],
    price_summary: str,
    yesterday_recap: str,
    levels_text: str,
    correlations_text: str,
) -> str:
    """
    Load the prompt template, format inputs, call Claude, return brief text.
    Returns an error string if the API call fails.
    """
    try:
        template = PROMPT_PATH.read_text(encoding="utf-8")
    except Exception as e:
        logger.error("Failed to load prompt template: %s", e)
        return f"Brief generation failed: could not load prompt template ({e}). Check logs."

    prompt = template.format(
        ranked_catalysts=_format_catalysts(catalysts),
        headlines=_format_headlines(_select_summary_headlines(headlines)),
        calendar=_format_calendar(calendar[:6]),
        price_summary=price_summary,
        yesterday_recap=yesterday_recap,
        levels_text=levels_text,
        correlations_text=correlations_text,
    )

    model = get_configured_model()
    try:
        client = anthropic.Anthropic()
        message = client.messages.create(
            model=model,
            max_tokens=1500,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
        )
        logger.info("Claude brief generated with model %s", model)
        return message.content[0].text
    except Exception as e:
        logger.error("Claude API call failed with model %s: %s", model, e)
        return f"Brief generation failed: {e}. Check logs."


def build_fallback_brief(
    catalysts: list[dict],
    market: dict,
    calendar: list[dict],
    corr: dict,
    now_uk: datetime | None = None,
) -> str:
    """Deterministic brief used when Claude is unavailable or malformed."""
    overnight = market.get("summary_text") or "Overnight summary unavailable."
    yesterday = market.get("yesterday_recap_text") or "Yesterday's session recap unavailable."
    top_lines = [f"- {item['display_text']}" for item in catalysts[:3]]
    if not top_lines:
        top_lines = ["- No strong overnight driver stood out. Treat the session as cleaner but quieter context."]

    cal_lines = []
    for ev in calendar[:3]:
        forecast = ev.get("forecast") or "n/a"
        previous = ev.get("previous") or "n/a"
        cal_lines.append(
            f"- {ev['time_uk']} UK — {ev['country']} — {ev['event']} (forecast: {forecast}, previous: {previous})"
        )
    if not cal_lines:
        cal_lines = ["- No medium or high importance United Kingdom or United States event is scheduled in the look-ahead window."]

    asian_ratio = market.get("overnight_vs_avg_ratio")
    high_events = sum(1 for ev in calendar if ev.get("importance") == "high")
    if asian_ratio is None:
        vol = "Unclear"
        vol_reason = "The overnight range versus its recent average is unavailable, so the session cannot be judged cleanly."
    elif asian_ratio >= 1.4 or high_events >= 2:
        vol = "Expansion"
        vol_reason = "The overnight range or event calendar suggests a more active London session than usual."
    elif asian_ratio <= 0.7 and high_events == 0:
        vol = "Contraction"
        vol_reason = "The overnight range was small versus normal and the event calendar is light."
    else:
        vol = "Normal"
        vol_reason = "The overnight range and event schedule look close to a normal London session."

    now_uk = now_uk or datetime.now(LONDON)
    weekday = now_uk.weekday()
    if high_events >= 2:
        liq = "Heavy"
        liq_reason = "Multiple meaningful events are scheduled, so participation and reactions could be stronger than usual."
    elif weekday in (0, 4) and high_events == 0:
        liq = "Thin"
        liq_reason = "Monday or Friday sessions with light data often trade with less clean follow-through."
    else:
        liq = "Normal"
        liq_reason = "Nothing obvious suggests unusually thin or unusually heavy participation."

    corr_line = corr.get("correlations_text") or "Correlation context unavailable."

    return "\n".join(
        [
            "## Overnight summary",
            overnight,
            "",
            "## Top drivers today",
            *top_lines,
            "",
            "## Today's calendar",
            *cal_lines,
            "",
            "## Yesterday's recap",
            yesterday,
            "",
            "## Correlation context",
            corr_line,
            "",
            f"Volatility expectation: {vol}. Reasoning: {vol_reason}",
            f"Liquidity: {liq}. Reasoning: {liq_reason}",
        ]
    )


def brief_needs_fallback(brief_text: str) -> bool:
    return evaluate_brief_quality(brief_text)["needs_fallback"]


def evaluate_brief_quality(brief_text: str) -> dict:
    """Return quality details for the generated brief."""
    reasons = []
    parsed = parse_brief(brief_text)
    lower = (brief_text or "").lower()

    if not brief_text:
        reasons.append("empty_response")
    elif brief_text.startswith("Brief generation failed:"):
        reasons.append("api_failure_message")
    if len((brief_text or "").strip()) < 120:
        reasons.append("too_short")
    if parsed["volatility_expectation"] is None:
        reasons.append("missing_volatility_line")
    if parsed["liquidity_context"] is None:
        reasons.append("missing_liquidity_line")
    if "overnight" not in lower:
        reasons.append("missing_overnight_section")
    if "top drivers" not in lower and "material catalysts" not in lower:
        reasons.append("missing_driver_section")
    if "today's calendar" not in lower and "calendar" not in lower:
        reasons.append("missing_calendar_section")

    return {
        "needs_fallback": bool(reasons),
        "reasons": reasons,
        "parsed": parsed,
    }


def parse_brief(brief_text: str) -> dict:
    """
    Parse volatility_expectation and liquidity_context from the brief text.
    Returns None for any field that fails to parse.
    """
    volatility_expectation = None
    liquidity_context = None

    vol_match = re.search(
        r"Volatility expectation:\s*\**\s*(Expansion|Contraction|Normal|Unclear)\s*\**",
        brief_text,
        re.IGNORECASE,
    )
    if vol_match:
        raw = vol_match.group(1).strip().lower()
        mapping = {
            "expansion": "Expansion",
            "contraction": "Contraction",
            "normal": "Normal",
            "unclear": "Unclear",
        }
        volatility_expectation = mapping.get(raw)

    liq_match = re.search(
        r"Liquidity:\s*\**\s*(Thin|Normal|Heavy)\s*\**",
        brief_text,
        re.IGNORECASE,
    )
    if liq_match:
        raw = liq_match.group(1).strip().lower()
        mapping = {"thin": "Thin", "normal": "Normal", "heavy": "Heavy"}
        liquidity_context = mapping.get(raw)

    return {
        "volatility_expectation": volatility_expectation,
        "liquidity_context": liquidity_context,
    }


if __name__ == "__main__":
    import pprint

    logging.basicConfig(level=logging.INFO)

    from src.calendar_fetch import get_upcoming_events
    from src.correlations import get_correlations
    from src.price_data import get_market_context

    print("Fetching headlines...")
    headlines = fetch_headlines(hours_back=12)
    print(f"  {len(headlines)} headlines retrieved")

    print("Fetching price data...")
    market = get_market_context()

    print("Fetching correlations...")
    corr = get_correlations()

    print("Fetching calendar...")
    calendar = get_upcoming_events(hours_ahead=6)

    print("Ranking catalysts...")
    catalysts = build_ranked_catalysts(headlines=headlines, calendar=calendar)
    pprint.pprint(catalysts[:5])

    print("\nGenerating session context brief via Claude...\n")
    brief = generate_session_context(
        catalysts=catalysts,
        headlines=headlines,
        calendar=calendar,
        price_summary=market.get("summary_text", "No price data."),
        yesterday_recap=market.get("yesterday_recap_text", "No recap data."),
        levels_text=market.get("levels_text", "No levels data."),
        correlations_text=corr.get("correlations_text", "No correlations data."),
    )

    if brief_needs_fallback(brief):
        print("Claude output was weak or missing required fields. Using deterministic fallback.\n")
        brief = build_fallback_brief(catalysts, market, calendar, corr)

    print("=" * 60)
    print(brief)
    print("=" * 60)

    parsed = parse_brief(brief)
    print("\n--- Parsed fields ---")
    pprint.pprint(parsed)
