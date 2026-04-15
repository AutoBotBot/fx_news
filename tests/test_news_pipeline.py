import unittest
from datetime import datetime, timezone

import pytz

from src import news

LONDON = pytz.timezone("Europe/London")


class NewsPipelineTests(unittest.TestCase):
    def test_calendar_event_can_outrank_generic_headline(self):
        now_utc = datetime(2026, 4, 14, 6, 30, tzinfo=timezone.utc)
        headlines = [
            {
                "title": "Oil traders watch shipping disruption headlines",
                "summary": "",
                "source": "Reuters Business",
                "published": datetime(2026, 4, 14, 5, 50, tzinfo=timezone.utc),
                "link": "",
            }
        ]
        calendar = [
            {
                "time_uk": "08:30",
                "time_utc": datetime(2026, 4, 14, 7, 30, tzinfo=timezone.utc),
                "country": "US",
                "event": "CPI y/y",
                "importance": "high",
                "forecast": "2.9%",
                "previous": "3.1%",
            }
        ]

        catalysts = news.build_ranked_catalysts(headlines, calendar, now_utc=now_utc)
        self.assertEqual(catalysts[0]["kind"], "calendar")
        self.assertEqual(catalysts[0]["severity"], "High")
        self.assertIn("scheduled", catalysts[0]["reason"].lower())

    def test_macro_surprise_headline_gets_directional_label(self):
        headlines = [
            {
                "title": "US March PPI final demand 4.0% y/y vs +4.7% expected",
                "summary": "",
                "source": "ForexLive",
                "published": datetime(2026, 4, 14, 12, 30, tzinfo=timezone.utc),
                "link": "",
            }
        ]

        catalysts = news.build_ranked_catalysts(headlines, [], now_utc=datetime(2026, 4, 14, 12, 40, tzinfo=timezone.utc))
        self.assertEqual(catalysts[0]["label"], "USD-")
        self.assertIn("United States", catalysts[0]["reason"])

    def test_fallback_brief_stays_parseable(self):
        brief = news.build_fallback_brief(
            catalysts=[
                {
                    "time_uk": "08:30",
                    "label": "USD-",
                    "severity": "High",
                    "confidence": "High",
                    "title": "US CPI due",
                    "display_text": "08:30 UK — USD- (High severity, High confidence): US CPI due — This can move GBP/USD.",
                }
            ],
            market={
                "summary_text": "GBP/USD traded quietly overnight. Asian range: 24 pips (1.2500–1.2524).",
                "yesterday_recap_text": "Yesterday was broadly range-bound.",
                "overnight_vs_avg_ratio": 0.8,
            },
            calendar=[],
            corr={"correlations_text": "DXY (US Dollar Index): Up (+0.120%)"},
            now_uk=LONDON.localize(datetime(2026, 4, 13, 7, 30)),
        )

        parsed = news.parse_brief(brief)
        self.assertFalse(news.brief_needs_fallback(brief))
        self.assertEqual(parsed["volatility_expectation"], "Normal")
        self.assertEqual(parsed["liquidity_context"], "Thin")

    def test_daily_explainer_includes_relevant_terms(self):
        lines = news.build_daily_explainer(
            catalysts=[
                {
                    "title": "US CPI due",
                    "reason": "This directly relates to the United States or the Federal Reserve.",
                    "label": "USD-",
                    "severity": "High",
                    "confidence": "High",
                }
            ],
            calendar=[
                {
                    "event": "CPI y/y",
                    "importance": "high",
                }
            ],
            corr={
                "dxy_change_pct_24h": 0.2,
                "gold_change_pct_24h": -0.1,
                "es_change_pct_24h": 0.05,
                "correlations_text": "DXY (US Dollar Index): Up (+0.200%)",
            },
        )
        joined = " ".join(lines)
        self.assertIn("DXY", joined)
        self.assertIn("CPI", joined)
        self.assertIn("USD-", joined)


if __name__ == "__main__":
    unittest.main()
