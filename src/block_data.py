# Block data for end-of-day capture.
# Fetches 5-minute GBPUSD data and computes high/low/range for three
# time blocks in UK local time:
#   Asian Block  : 00:00–07:00
#   Open Block   : 08:00–08:30
#   Session Block: 08:30–12:00

import logging
from datetime import datetime, timedelta

import pytz
import yfinance as yf

logger = logging.getLogger(__name__)

LONDON = pytz.timezone("Europe/London")
TICKER = "GBPUSD=X"
PIPS = 10_000  # 1 pip = 0.0001 for GBPUSD

_BLOCKS = [
    ("asian_block",   "00:00", "07:00",  0,  0,  7,  0),
    ("open_block",    "08:00", "08:30",  8,  0,  8, 30),
    ("session_block", "08:30", "12:00",  8, 30, 12,  0),
]


def _empty_block(time_start: str, time_end: str) -> dict:
    return {
        "high": None,
        "low": None,
        "range_pips": None,
        "time_start": time_start,
        "time_end": time_end,
    }


def get_daily_blocks() -> dict:
    """
    Fetch 5-minute GBPUSD data and compute high/low/range for each of the
    three intraday time blocks for today in Europe/London time.

    Returns a dict with keys: asian_block, open_block, session_block.
    Each value is a dict with: high, low, range_pips, time_start, time_end.
    If a block has no data, its high/low/range_pips are None.
    If yfinance fails entirely, all blocks contain None values.
    """
    result = {
        key: _empty_block(ts, te)
        for key, ts, te, *_ in _BLOCKS
    }

    now_utc = datetime.now(pytz.utc)
    now_uk = now_utc.astimezone(LONDON)
    today_uk = now_uk.date()

    try:
        ticker = yf.Ticker(TICKER)
        df = ticker.history(period="1d", interval="5m")

        # yfinance sometimes returns less than a full day with period="1d";
        # fall back to an explicit start time covering the last 18 hours.
        if df.empty:
            start_utc = now_utc - timedelta(hours=18)
            df = ticker.history(start=start_utc, interval="5m")

        if df.empty:
            logger.warning("yfinance returned no 5-minute data for %s", TICKER)
            return result

        # Localise index to London time
        if df.index.tzinfo is None:
            df.index = df.index.tz_localize("UTC")
        df.index = df.index.tz_convert(LONDON)

        # Filter to today's UK date only
        df = df[df.index.date == today_uk]

        if df.empty:
            logger.warning("No 5-minute data for today (%s) after timezone filter", today_uk)
            return result

    except Exception as e:
        logger.error("Failed to fetch 5-minute price data: %s", e)
        return result

    for key, time_start, time_end, sh, sm, eh, em in _BLOCKS:
        block_start = LONDON.localize(
            datetime(today_uk.year, today_uk.month, today_uk.day, sh, sm)
        )
        block_end = LONDON.localize(
            datetime(today_uk.year, today_uk.month, today_uk.day, eh, em)
        )
        block_df = df[(df.index >= block_start) & (df.index < block_end)]

        if block_df.empty:
            logger.warning(
                "No data for %s (%s–%s) — market may be closed or block not yet complete",
                key, time_start, time_end,
            )
            continue

        high = round(float(block_df["High"].max()), 5)
        low = round(float(block_df["Low"].min()), 5)
        range_pips = round((high - low) * PIPS, 1)

        result[key] = {
            "high": high,
            "low": low,
            "range_pips": range_pips,
            "time_start": time_start,
            "time_end": time_end,
        }

    return result


if __name__ == "__main__":
    import pprint
    logging.basicConfig(level=logging.INFO)
    blocks = get_daily_blocks()
    print("\n--- Daily Block Data ---")
    pprint.pprint(blocks)
    for key, data in blocks.items():
        if data["high"] is not None:
            print(
                f"\n{key}: {data['time_start']}–{data['time_end']}  "
                f"H={data['high']:.5f}  L={data['low']:.5f}  "
                f"Range={data['range_pips']} pips"
            )
        else:
            print(f"\n{key}: {data['time_start']}–{data['time_end']}  No data")
