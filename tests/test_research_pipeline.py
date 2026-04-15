import csv
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytz

from src.research_dataset import upsert_session_row
from src.research_features import _compute_first_break_features, _count_preopen_same_direction

LONDON = pytz.timezone("Europe/London")


class ResearchPipelineTests(unittest.TestCase):
    def test_upsert_session_row_merges_existing_date(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "dataset.csv"
            upsert_session_row(
                {"session_date": "2026-04-14", "volatility_expectation": "Normal"},
                path=str(path),
            )
            upsert_session_row(
                {"session_date": "2026-04-14", "liquidity_context": "Heavy"},
                path=str(path),
            )

            with path.open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["volatility_expectation"], "Normal")
            self.assertEqual(rows[0]["liquidity_context"], "Heavy")

    def test_compute_first_break_features_detects_fakeout(self):
        idx = pd.DatetimeIndex(
            [
                LONDON.localize(datetime(2026, 4, 14, 8, 0)),
                LONDON.localize(datetime(2026, 4, 14, 8, 5)),
                LONDON.localize(datetime(2026, 4, 14, 8, 10)),
                LONDON.localize(datetime(2026, 4, 14, 8, 15)),
            ]
        )
        session_df = pd.DataFrame(
            [
                {"Open": 1.1000, "High": 1.1005, "Low": 1.0995, "Close": 1.1001},
                {"Open": 1.1001, "High": 1.1008, "Low": 1.0998, "Close": 1.1006},
                {"Open": 1.1006, "High": 1.1013, "Low": 1.1004, "Close": 1.1011},
                {"Open": 1.1011, "High": 1.1012, "Low": 1.0999, "Close": 1.1002},
            ],
            index=idx,
        )

        result = _compute_first_break_features(
            session_df=session_df,
            asian_high=1.1010,
            asian_low=1.0990,
            session_start=LONDON.localize(datetime(2026, 4, 14, 8, 0)),
        )

        self.assertEqual(result["first_break_side"], "up")
        self.assertEqual(result["first_break_minute"], 10)
        self.assertEqual(result["first_reentry_minute"], 15)
        self.assertEqual(result["fakeout_flag"], 1)
        self.assertEqual(result["fakeout_duration_min"], 5)
        self.assertGreater(result["fakeout_penetration_pips"], 0)

    def test_count_preopen_same_direction(self):
        idx = pd.DatetimeIndex(
            [
                LONDON.localize(datetime(2026, 4, 14, 6, 0)),
                LONDON.localize(datetime(2026, 4, 14, 6, 5)),
                LONDON.localize(datetime(2026, 4, 14, 6, 10)),
                LONDON.localize(datetime(2026, 4, 14, 6, 15)),
                LONDON.localize(datetime(2026, 4, 14, 6, 20)),
                LONDON.localize(datetime(2026, 4, 14, 6, 25)),
                LONDON.localize(datetime(2026, 4, 14, 6, 30)),
                LONDON.localize(datetime(2026, 4, 14, 6, 35)),
                LONDON.localize(datetime(2026, 4, 14, 6, 40)),
            ]
        )
        df = pd.DataFrame(
            [
                {"Open": 1.1000, "High": 1.1004, "Low": 1.0998, "Close": 1.1003},
                {"Open": 1.1003, "High": 1.1006, "Low": 1.1002, "Close": 1.1005},
                {"Open": 1.1005, "High": 1.1007, "Low": 1.1003, "Close": 1.1006},
                {"Open": 1.1006, "High": 1.1009, "Low": 1.1004, "Close": 1.1008},
                {"Open": 1.1008, "High": 1.1011, "Low": 1.1007, "Close": 1.1010},
                {"Open": 1.1010, "High": 1.1012, "Low": 1.1009, "Close": 1.1011},
                {"Open": 1.1011, "High": 1.1014, "Low": 1.1010, "Close": 1.1013},
                {"Open": 1.1013, "High": 1.1016, "Low": 1.1012, "Close": 1.1015},
                {"Open": 1.1015, "High": 1.1018, "Low": 1.1014, "Close": 1.1017},
            ],
            index=idx,
        )

        self.assertGreaterEqual(_count_preopen_same_direction(df), 3)


if __name__ == "__main__":
    unittest.main()
