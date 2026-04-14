# yfinance FX data is delayed and approximate.
# For v1 this is acceptable because we're providing context, not making
# trade decisions.

import logging
from datetime import datetime, timedelta

import pandas as pd
import pytz
import yfinance as yf

logger = logging.getLogger(__name__)

LONDON = pytz.timezone("Europe/London")
TICKER = "GBPUSD=X"
PIPS = 10_000  # 1 pip = 0.0001 for GBPUSD


def _to_london(dt_utc: pd.Timestamp) -> datetime:
    """Convert a UTC pandas Timestamp to a London-timezone datetime."""
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.tz_localize("UTC")
    return dt_utc.tz_convert(LONDON)


def _fetch_hourly(days: int = 30) -> pd.DataFrame:
    """Fetch hourly GBPUSD data for the last N days, index in UTC."""
    ticker = yf.Ticker(TICKER)
    df = ticker.history(period=f"{days}d", interval="1h")
    if df.empty:
        logger.warning("yfinance returned empty dataframe for %s", TICKER)
    return df


def _week_bounds_london(ref: datetime) -> tuple[datetime, datetime]:
    """Return Monday 00:00 and Sunday 23:59:59 UK for the week containing ref."""
    monday = ref - timedelta(days=ref.weekday())
    monday_start = LONDON.localize(
        datetime(monday.year, monday.month, monday.day, 0, 0, 0)
    )
    sunday_end = monday_start + timedelta(days=7) - timedelta(seconds=1)
    return monday_start, sunday_end


def get_market_context() -> dict:
    """
    Fetch overnight GBP/USD price action, Asian range, yesterday's session
    recap, and key nearby levels.

    All time windows are in Europe/London local time.
    Returns a dict with None values and a descriptive summary_text on error.
    """
    now_utc = datetime.now(pytz.utc)
    now_uk = now_utc.astimezone(LONDON)
    today_uk = now_uk.date()

    error_result = {
        k: None for k in [
            "asian_high", "asian_low", "asian_range_pips", "current_price",
            "distance_from_asian_high_pips", "distance_from_asian_low_pips",
            "yesterday_close", "overnight_change_pips",
            "yesterday_session_high", "yesterday_session_low",
            "yesterday_session_close",
            "this_week_high", "this_week_low",
            "last_week_high", "last_week_low",
            "range_20day_avg_pips", "overnight_vs_avg_ratio",
            "summary_text", "levels_text", "yesterday_recap_text",
        ]
    }

    try:
        df = _fetch_hourly(days=30)
        if df.empty:
            error_result["summary_text"] = "No price data available from yfinance."
            error_result["levels_text"] = "No data."
            error_result["yesterday_recap_text"] = "No data."
            return error_result

        # Convert index to London time for filtering
        df.index = df.index.tz_convert(LONDON)

    except Exception as e:
        logger.error("Failed to fetch price data: %s", e)
        error_result["summary_text"] = f"Price data fetch failed: {e}"
        error_result["levels_text"] = "Data unavailable."
        error_result["yesterday_recap_text"] = "Data unavailable."
        return error_result

    # --- Current price ---
    current_price = float(df["Close"].iloc[-1])

    # --- Asian session today: 00:00–07:00 UK ---
    asian_start = LONDON.localize(datetime(today_uk.year, today_uk.month, today_uk.day, 0, 0))
    asian_end = LONDON.localize(datetime(today_uk.year, today_uk.month, today_uk.day, 7, 0))
    asian_df = df[(df.index >= asian_start) & (df.index < asian_end)]

    if asian_df.empty:
        logger.warning("No Asian session data for today — market may be closed or data gap")
        asian_high = current_price
        asian_low = current_price
    else:
        asian_high = float(asian_df["High"].max())
        asian_low = float(asian_df["Low"].min())

    asian_range_pips = round((asian_high - asian_low) * PIPS, 1)
    distance_from_asian_high_pips = round((current_price - asian_high) * PIPS, 1)
    distance_from_asian_low_pips = round((current_price - asian_low) * PIPS, 1)

    # --- Yesterday's close (~22:00 UK) ---
    # "Yesterday" = previous calendar day in UK time
    yesterday_uk = today_uk - timedelta(days=1)
    # Handle Monday: yesterday is Friday
    if yesterday_uk.weekday() == 6:  # Sunday
        yesterday_uk = yesterday_uk - timedelta(days=2)

    yesterday_close_window_start = LONDON.localize(
        datetime(yesterday_uk.year, yesterday_uk.month, yesterday_uk.day, 21, 0)
    )
    yesterday_close_window_end = LONDON.localize(
        datetime(yesterday_uk.year, yesterday_uk.month, yesterday_uk.day, 23, 59)
    )
    yesterday_close_df = df[
        (df.index >= yesterday_close_window_start) &
        (df.index <= yesterday_close_window_end)
    ]
    yesterday_close = float(yesterday_close_df["Close"].iloc[-1]) if not yesterday_close_df.empty else None
    overnight_change_pips = (
        round((current_price - yesterday_close) * PIPS, 1) if yesterday_close else None
    )

    # --- Yesterday's London session: 08:00–17:00 UK ---
    session_start = LONDON.localize(
        datetime(yesterday_uk.year, yesterday_uk.month, yesterday_uk.day, 8, 0)
    )
    session_end = LONDON.localize(
        datetime(yesterday_uk.year, yesterday_uk.month, yesterday_uk.day, 17, 0)
    )
    session_df = df[(df.index >= session_start) & (df.index < session_end)]

    if session_df.empty:
        logger.warning("No session data for yesterday (%s)", yesterday_uk)
        yesterday_session_high = None
        yesterday_session_low = None
        yesterday_session_close = None
    else:
        yesterday_session_high = float(session_df["High"].max())
        yesterday_session_low = float(session_df["Low"].min())
        yesterday_session_close = float(session_df["Close"].iloc[-1])

    # --- This week: Monday 00:00 UK to now ---
    this_monday = today_uk - timedelta(days=today_uk.weekday())
    this_week_start = LONDON.localize(
        datetime(this_monday.year, this_monday.month, this_monday.day, 0, 0)
    )
    this_week_df = df[df.index >= this_week_start]
    this_week_high = float(this_week_df["High"].max()) if not this_week_df.empty else None
    this_week_low = float(this_week_df["Low"].min()) if not this_week_df.empty else None

    # --- Last week: previous Monday 00:00 to Sunday 23:59 UK ---
    last_monday = this_monday - timedelta(days=7)
    last_week_start = LONDON.localize(
        datetime(last_monday.year, last_monday.month, last_monday.day, 0, 0)
    )
    last_week_end = last_week_start + timedelta(days=7) - timedelta(seconds=1)
    last_week_df = df[(df.index >= last_week_start) & (df.index <= last_week_end)]
    last_week_high = float(last_week_df["High"].max()) if not last_week_df.empty else None
    last_week_low = float(last_week_df["Low"].min()) if not last_week_df.empty else None

    # --- 20-day average daily range ---
    # Use daily high-low range from the last 20 trading days
    daily_groups = df.groupby(df.index.date)
    daily_ranges = []
    for date, group in daily_groups:
        rng = float(group["High"].max() - group["Low"].min()) * PIPS
        daily_ranges.append(rng)

    # Keep last 20 trading days (excluding today which is incomplete)
    if len(daily_ranges) > 1:
        recent_ranges = daily_ranges[-21:-1]  # exclude today
        range_20day_avg_pips = round(sum(recent_ranges) / len(recent_ranges), 1)
    else:
        range_20day_avg_pips = None

    overnight_vs_avg_ratio = (
        round(asian_range_pips / (range_20day_avg_pips / 4), 2)
        if range_20day_avg_pips and range_20day_avg_pips > 0
        else None
    )

    # --- Human-readable summaries ---
    direction = "up" if overnight_change_pips and overnight_change_pips > 0 else "down"
    change_str = f"{abs(overnight_change_pips):.1f} pips {direction}" if overnight_change_pips else "change unknown"

    summary_text = (
        f"GBP/USD overnight: {change_str} from yesterday's close "
        f"({yesterday_close:.5f} → {current_price:.5f}). "
        f"Asian range: {asian_range_pips} pips "
        f"({asian_low:.5f}–{asian_high:.5f})."
    ) if yesterday_close else (
        f"GBP/USD current: {current_price:.5f}. "
        f"Asian range: {asian_range_pips} pips ({asian_low:.5f}–{asian_high:.5f})."
    )

    if yesterday_session_high and yesterday_session_low:
        session_range = round((yesterday_session_high - yesterday_session_low) * PIPS, 1)
        yesterday_recap_text = (
            f"Yesterday's London session: High {yesterday_session_high:.5f}, "
            f"Low {yesterday_session_low:.5f}, "
            f"Range {session_range} pips, "
            f"Close {yesterday_session_close:.5f}."
        )
    else:
        yesterday_recap_text = "Yesterday's session data unavailable."

    def _level_line(label: str, price: float | None) -> str:
        if price is None:
            return f"{label}: n/a"
        dist = round((current_price - price) * PIPS, 1)
        nearby = " ← NEARBY" if abs(dist) <= 50 else ""
        sign = "+" if dist >= 0 else ""
        return f"{label}: {price:.5f}  ({sign}{dist} pips from current){nearby}"

    levels_lines = [
        f"Current price: {current_price:.5f}",
        "",
        _level_line("Asian High (today)", asian_high),
        _level_line("Asian Low (today)", asian_low),
        _level_line("Yesterday Session High", yesterday_session_high),
        _level_line("Yesterday Session Low", yesterday_session_low),
        _level_line("Yesterday Close", yesterday_close),
        _level_line("This Week High", this_week_high),
        _level_line("This Week Low", this_week_low),
        _level_line("Last Week High", last_week_high),
        _level_line("Last Week Low", last_week_low),
    ]
    levels_text = "\n".join(levels_lines)

    return {
        "asian_high": asian_high,
        "asian_low": asian_low,
        "asian_range_pips": asian_range_pips,
        "current_price": current_price,
        "distance_from_asian_high_pips": distance_from_asian_high_pips,
        "distance_from_asian_low_pips": distance_from_asian_low_pips,
        "yesterday_close": yesterday_close,
        "overnight_change_pips": overnight_change_pips,
        "yesterday_session_high": yesterday_session_high,
        "yesterday_session_low": yesterday_session_low,
        "yesterday_session_close": yesterday_session_close,
        "this_week_high": this_week_high,
        "this_week_low": this_week_low,
        "last_week_high": last_week_high,
        "last_week_low": last_week_low,
        "range_20day_avg_pips": range_20day_avg_pips,
        "overnight_vs_avg_ratio": overnight_vs_avg_ratio,
        "summary_text": summary_text,
        "levels_text": levels_text,
        "yesterday_recap_text": yesterday_recap_text,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import pprint
    result = get_market_context()
    print("\n--- Market Context ---")
    pprint.pprint(result)
    print("\n--- Summary ---")
    print(result["summary_text"])
    print("\n--- Yesterday Recap ---")
    print(result["yesterday_recap_text"])
    print("\n--- Levels ---")
    print(result["levels_text"])
