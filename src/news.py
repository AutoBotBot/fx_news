# News headlines and Claude session context brief generation.
# Fetches RSS headlines, formats inputs, calls Claude API to produce
# the structured morning brief, and parses key fields from the output.

import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anthropic
import feedparser
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"
PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "session_context.md"

FEEDS = [
    ("Reuters Business", "https://feeds.reuters.com/reuters/businessNews"),
    ("FT Markets", "https://www.ft.com/markets?format=rss"),
    ("BBC Business", "http://feeds.bbci.co.uk/news/business/rss.xml"),
    ("ForexLive", "https://www.forexlive.com/feed/news"),
    ("Investing.com Forex", "https://www.investing.com/rss/news_1.rss"),
]


# ---------------------------------------------------------------------------
# 1. fetch_headlines
# ---------------------------------------------------------------------------

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

                # De-duplicate by normalised title
                norm = re.sub(r"\s+", " ", title.lower().strip())
                if norm in seen_titles:
                    continue

                # Parse published time
                published_parsed = entry.get("published_parsed")
                if published_parsed is None:
                    continue
                published = datetime(*published_parsed[:6], tzinfo=timezone.utc)

                if published < cutoff:
                    continue

                seen_titles.add(norm)
                headlines.append({
                    "title": title,
                    "summary": entry.get("summary", ""),
                    "source": source,
                    "published": published,
                    "link": entry.get("link", ""),
                })
                count += 1

            logger.info("Feed '%s': %d headlines in window", source, count)

        except Exception as e:
            logger.warning("Feed '%s' failed: %s", source, e)

    headlines.sort(key=lambda h: h["published"], reverse=True)
    logger.info("Total headlines fetched: %d", len(headlines))
    return headlines


# ---------------------------------------------------------------------------
# 2. generate_session_context
# ---------------------------------------------------------------------------

def generate_session_context(
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
    # Format headlines
    if headlines:
        headlines_str = "\n".join(
            f"- [{h['source']}] {h['title']} ({h['published'].strftime('%H:%M')} UTC)"
            for h in headlines
        )
    else:
        headlines_str = "No headlines retrieved."

    # Format calendar
    if calendar:
        cal_lines = []
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
            cal_lines.append(f"- {line}")
        calendar_str = "\n".join(cal_lines)
    else:
        calendar_str = "No medium/high-importance UK or US events scheduled."

    # Load and fill prompt template
    try:
        template = PROMPT_PATH.read_text(encoding="utf-8")
    except Exception as e:
        logger.error("Failed to load prompt template: %s", e)
        return f"Brief generation failed: could not load prompt template ({e}). Check logs."

    prompt = template.format(
        headlines=headlines_str,
        calendar=calendar_str,
        price_summary=price_summary,
        yesterday_recap=yesterday_recap,
        levels_text=levels_text,
        correlations_text=correlations_text,
    )

    # Call Claude API
    try:
        client = anthropic.Anthropic()
        message = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            temperature=0.3,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
    except Exception as e:
        logger.error("Claude API call failed: %s", e)
        return f"Brief generation failed: {e}. Check logs."


# ---------------------------------------------------------------------------
# 3. parse_brief
# ---------------------------------------------------------------------------

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
        # Normalise to exact Notion select capitalisation
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


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import pprint
    logging.basicConfig(level=logging.INFO)

    from src.price_data import get_market_context
    from src.correlations import get_correlations
    from src.calendar_fetch import get_upcoming_events

    print("Fetching headlines...")
    headlines = fetch_headlines(hours_back=12)
    print(f"  {len(headlines)} headlines retrieved")

    print("Fetching price data...")
    market = get_market_context()

    print("Fetching correlations...")
    corr = get_correlations()

    print("Fetching calendar...")
    calendar = get_upcoming_events(hours_ahead=6)

    print("\nGenerating session context brief via Claude...\n")
    brief = generate_session_context(
        headlines=headlines,
        calendar=calendar,
        price_summary=market.get("summary_text", "No price data."),
        yesterday_recap=market.get("yesterday_recap_text", "No recap data."),
        levels_text=market.get("levels_text", "No levels data."),
        correlations_text=corr.get("correlations_text", "No correlations data."),
    )

    print("=" * 60)
    print(brief)
    print("=" * 60)

    parsed = parse_brief(brief)
    print("\n--- Parsed fields ---")
    pprint.pprint(parsed)
