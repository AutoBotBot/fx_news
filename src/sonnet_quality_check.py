"""
Manual Claude Sonnet quality checks for the morning brief prompt.

Run:
  uv run python -m src.sonnet_quality_check

This exercises the prompt and summarisation path against a few fixed
sample cases without touching Telegram or Notion.
"""

import logging

from src import news

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


SAMPLE_CASES = [
    {
        "name": "major-event day",
        "headlines": [
            {
                "title": "US March CPI 3.4% y/y vs 3.1% expected",
                "summary": "",
                "source": "ForexLive",
                "published": news.datetime(2026, 4, 14, 6, 20, tzinfo=news.timezone.utc),
                "link": "",
            }
        ],
        "calendar": [
            {
                "time_uk": "08:30",
                "time_utc": news.datetime(2026, 4, 14, 7, 30, tzinfo=news.timezone.utc),
                "country": "US",
                "event": "CPI y/y",
                "importance": "high",
                "forecast": "3.1%",
                "previous": "3.0%",
            }
        ],
    },
    {
        "name": "quiet day",
        "headlines": [],
        "calendar": [],
    },
    {
        "name": "headline-heavy low relevance day",
        "headlines": [
            {
                "title": "Global retailers prepare for summer holiday demand",
                "summary": "",
                "source": "BBC Business",
                "published": news.datetime(2026, 4, 14, 5, 45, tzinfo=news.timezone.utc),
                "link": "",
            },
            {
                "title": "Energy firms discuss long-term investment plans",
                "summary": "",
                "source": "Reuters Business",
                "published": news.datetime(2026, 4, 14, 4, 45, tzinfo=news.timezone.utc),
                "link": "",
            },
        ],
        "calendar": [],
    },
    {
        "name": "conflicting macro day",
        "headlines": [
            {
                "title": "US retail sales slow more than expected in March",
                "summary": "",
                "source": "Reuters Business",
                "published": news.datetime(2026, 4, 14, 5, 50, tzinfo=news.timezone.utc),
                "link": "",
            },
            {
                "title": "Oil jumps as shipping risks return to focus",
                "summary": "",
                "source": "FT Markets",
                "published": news.datetime(2026, 4, 14, 5, 15, tzinfo=news.timezone.utc),
                "link": "",
            },
        ],
        "calendar": [
            {
                "time_uk": "09:00",
                "time_utc": news.datetime(2026, 4, 14, 8, 0, tzinfo=news.timezone.utc),
                "country": "UK",
                "event": "CPI y/y",
                "importance": "high",
                "forecast": "2.8%",
                "previous": "2.7%",
            }
        ],
    },
]


def main() -> None:
    for case in SAMPLE_CASES:
        print(f"\n=== {case['name']} ===")
        catalysts = news.build_ranked_catalysts(case["headlines"], case["calendar"])
        brief = news.generate_session_context(
            catalysts=catalysts,
            headlines=case["headlines"],
            calendar=case["calendar"],
            price_summary="GBP/USD traded quietly overnight. Asian range: 24 pips (1.2500–1.2524). Current price is near the top of the range.",
            yesterday_recap="Yesterday's London session was broadly range-bound with a mild late recovery.",
            levels_text="Asian High: 1.25240\nAsian Low: 1.25000\nYesterday High: 1.25310\nYesterday Low: 1.24880",
            correlations_text="DXY (US Dollar Index): Up (+0.220%)\nGold: Down (-0.140%)\nES (S&P 500 futures): Flat (+0.030%)",
        )

        if news.brief_needs_fallback(brief):
            print("Claude output was weak or malformed. Deterministic fallback would be used.\n")
            brief = news.build_fallback_brief(
                catalysts=catalysts,
                market={
                    "summary_text": "GBP/USD traded quietly overnight. Asian range: 24 pips (1.2500–1.2524).",
                    "yesterday_recap_text": "Yesterday's London session was broadly range-bound.",
                    "overnight_vs_avg_ratio": 0.9,
                },
                calendar=case["calendar"],
                corr={"correlations_text": "DXY (US Dollar Index): Up (+0.220%)"},
            )

        print(brief)


if __name__ == "__main__":
    main()
