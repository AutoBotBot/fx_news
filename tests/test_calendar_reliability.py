import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from src import calendar_fetch


class CalendarReliabilityTests(unittest.TestCase):
    def test_parse_xml_time_assumes_utc_schedule(self):
        parsed = calendar_fetch._parse_xml_time("04-14-2026", "12:30pm")
        self.assertEqual(parsed, datetime(2026, 4, 14, 12, 30, tzinfo=timezone.utc))

    @patch("src.calendar_fetch._fetch_rss_events", return_value=[])
    @patch("src.calendar_fetch._fetch_xml_events")
    def test_get_upcoming_events_uses_xml_fallback(self, mock_xml, _mock_rss):
        mock_xml.return_value = [
            {
                "time_uk": "13:30",
                "time_utc": datetime(2026, 4, 14, 12, 30, tzinfo=timezone.utc),
                "country": "US",
                "event": "CPI y/y",
                "importance": "high",
                "forecast": "3.1%",
                "previous": "3.0%",
                "source": "forex_factory_xml",
            }
        ]
        events = calendar_fetch.get_upcoming_events(hours_ahead=6)
        self.assertEqual(len(events), 1)
        self.assertEqual(calendar_fetch.get_last_source(), "forex_factory_xml")


if __name__ == "__main__":
    unittest.main()
