import logging
from datetime import datetime, timedelta

import pandas as pd
import pytz
import yfinance as yf

from src import price_data

logger = logging.getLogger(__name__)

LONDON = pytz.timezone("Europe/London")
PIPS = 10_000


def _week_of_month(dt: datetime) -> int:
    return ((dt.day - 1) // 7) + 1


def _session_bounds(today_uk: datetime.date) -> tuple[datetime, datetime]:
    start = LONDON.localize(datetime(today_uk.year, today_uk.month, today_uk.day, 8, 0))
    end = LONDON.localize(datetime(today_uk.year, today_uk.month, today_uk.day, 12, 0))
    return start, end


def _intraday_history(ticker_symbol: str, hours_back: int = 36, interval: str = "5m") -> pd.DataFrame:
    now_utc = datetime.now(pytz.utc)
    start_utc = now_utc - timedelta(hours=hours_back)
    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(start=start_utc, interval=interval)
    except Exception as e:
        logger.warning("Failed to fetch intraday history for %s: %s", ticker_symbol, e)
        return pd.DataFrame()

    if df.empty:
        return df

    if df.index.tzinfo is None:
        df.index = df.index.tz_localize("UTC")
    return df.tz_convert(LONDON)


def _session_event_metrics(calendar: list[dict], session_start: datetime, session_end: datetime) -> dict:
    in_window = []
    for event in calendar:
        time_utc = event.get("time_utc")
        if not isinstance(time_utc, datetime):
            continue
        time_uk = time_utc.astimezone(LONDON)
        if session_start <= time_uk <= session_end:
            in_window.append({**event, "time_uk_dt": time_uk})

    in_window.sort(key=lambda item: item["time_uk_dt"])
    high_events = [ev for ev in in_window if ev.get("importance") == "high"]

    next_any = in_window[0]["time_uk_dt"] if in_window else None
    next_high = high_events[0]["time_uk_dt"] if high_events else None

    def _minutes_from_open(target: datetime | None) -> int | None:
        if target is None:
            return None
        return int((target - session_start).total_seconds() / 60)

    return {
        "high_event_count_0800_1200": len(high_events),
        "medium_event_count_0800_1200": sum(1 for ev in in_window if ev.get("importance") == "medium"),
        "minutes_from_0800_to_next_high_event": _minutes_from_open(next_high),
        "minutes_from_0800_to_next_any_event": _minutes_from_open(next_any),
        "high_impact_first_hour_flag": int(
            any(0 <= int((ev["time_uk_dt"] - session_start).total_seconds() / 60) <= 60 for ev in high_events)
        ),
    }


def build_morning_features(
    today_uk: datetime,
    market: dict,
    corr: dict,
    parsed_brief: dict,
    calendar: list[dict],
    catalysts: list[dict],
) -> dict:
    session_start, session_end = _session_bounds(today_uk.date())
    event_metrics = _session_event_metrics(calendar, session_start, session_end)

    row = {
        "session_date": today_uk.strftime("%Y-%m-%d"),
        "day_of_week": today_uk.strftime("%A"),
        "week_of_month": _week_of_month(today_uk),
        "volatility_expectation": parsed_brief.get("volatility_expectation"),
        "liquidity_context": parsed_brief.get("liquidity_context"),
        "asian_high": market.get("asian_high"),
        "asian_low": market.get("asian_low"),
        "asian_range_pips": market.get("asian_range_pips"),
        "asian_range_vs_20d_ratio": market.get("overnight_vs_avg_ratio"),
        "dxy_change_24h_pct": corr.get("dxy_change_pct_24h"),
        "gold_change_24h_pct": corr.get("gold_change_pct_24h"),
        "es_change_24h_pct": corr.get("es_change_pct_24h"),
        "calendar_available": int(bool(calendar)),
        "dxy_available": int(corr.get("dxy_change_pct_24h") is not None),
        "eurusd_available": "",
        **event_metrics,
    }

    severity_counts = {"High": 0, "Medium": 0, "Low": 0}
    for catalyst in catalysts[:3]:
        severity_counts[catalyst["severity"]] += 1

    row.update(
        {
            "top_catalyst_1_label": catalysts[0]["label"] if len(catalysts) > 0 else "",
            "top_catalyst_1_title": catalysts[0]["title"] if len(catalysts) > 0 else "",
            "top_catalyst_2_label": catalysts[1]["label"] if len(catalysts) > 1 else "",
            "top_catalyst_2_title": catalysts[1]["title"] if len(catalysts) > 1 else "",
            "top_catalyst_3_label": catalysts[2]["label"] if len(catalysts) > 2 else "",
            "top_catalyst_3_title": catalysts[2]["title"] if len(catalysts) > 2 else "",
            "high_severity_catalyst_count": severity_counts["High"],
            "medium_severity_catalyst_count": severity_counts["Medium"],
            "low_severity_catalyst_count": severity_counts["Low"],
        }
    )

    return row


def _nearest_level(open_price: float, levels: dict) -> tuple[str | None, float | None]:
    candidates = {
        "asian_high": levels.get("asian_high"),
        "asian_low": levels.get("asian_low"),
        "yesterday_high": levels.get("yesterday_session_high"),
        "yesterday_low": levels.get("yesterday_session_low"),
        "this_week_high": levels.get("this_week_high"),
        "this_week_low": levels.get("this_week_low"),
        "last_week_high": levels.get("last_week_high"),
        "last_week_low": levels.get("last_week_low"),
    }
    best_name = None
    best_distance = None
    for name, value in candidates.items():
        if value is None:
            continue
        distance = round((open_price - value) * PIPS, 1)
        if best_distance is None or abs(distance) < abs(best_distance):
            best_name = name
            best_distance = distance
    return best_name, best_distance


def _count_preopen_same_direction(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    preopen = df.between_time("06:00", "07:55")
    if preopen.empty:
        return 0

    fifteen = (
        preopen[["Open", "High", "Low", "Close"]]
        .resample("15min", label="left", closed="left")
        .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"})
        .dropna()
    )
    if fifteen.empty:
        return 0

    directions = []
    for _, row in fifteen.iterrows():
        if row["Close"] > row["Open"]:
            directions.append(1)
        elif row["Close"] < row["Open"]:
            directions.append(-1)
        else:
            directions.append(0)

    count = 0
    last = None
    for direction in reversed(directions):
        if direction == 0:
            break
        if last is None:
            last = direction
            count = 1
            continue
        if direction == last:
            count += 1
        else:
            break
    return count


def _compute_first_break_features(
    session_df: pd.DataFrame,
    asian_high: float,
    asian_low: float,
    session_start: datetime,
) -> dict:
    empty = {
        "first_break_side": "",
        "first_break_minute": "",
        "first_reentry_minute": "",
        "fakeout_flag": "",
        "fakeout_duration_min": "",
        "fakeout_penetration_pips": "",
        "first_break_15m_follow_through_pips": "",
        "first_break_30m_follow_through_pips": "",
    }
    if session_df.empty:
        return empty

    break_time = None
    break_side = ""
    for timestamp, row in session_df.iterrows():
        broke_up = row["High"] > asian_high
        broke_down = row["Low"] < asian_low
        if not (broke_up or broke_down):
            continue
        break_time = timestamp
        if broke_up and broke_down:
            break_side = "both"
        elif broke_up:
            break_side = "up"
        else:
            break_side = "down"
        break

    if break_time is None:
        return empty

    result = {
        "first_break_side": break_side,
        "first_break_minute": int((break_time - session_start).total_seconds() / 60),
        "first_reentry_minute": "",
        "fakeout_flag": 0 if break_side != "both" else "",
        "fakeout_duration_min": "",
        "fakeout_penetration_pips": "",
        "first_break_15m_follow_through_pips": "",
        "first_break_30m_follow_through_pips": "",
    }

    if break_side == "up":
        ref = asian_high
        penetration = lambda frame: round((frame["High"].max() - ref) * PIPS, 1)
        follow = lambda frame: round((frame["High"].max() - ref) * PIPS, 1)
        reentered = lambda row: asian_low <= row["Close"] <= asian_high
    elif break_side == "down":
        ref = asian_low
        penetration = lambda frame: round((ref - frame["Low"].min()) * PIPS, 1)
        follow = lambda frame: round((ref - frame["Low"].min()) * PIPS, 1)
        reentered = lambda row: asian_low <= row["Close"] <= asian_high
    else:
        return result

    post_break = session_df[session_df.index >= break_time]
    win_15 = post_break[post_break.index < break_time + timedelta(minutes=15)]
    win_30 = post_break[post_break.index < break_time + timedelta(minutes=30)]
    if not win_15.empty:
        result["first_break_15m_follow_through_pips"] = follow(win_15)
    if not win_30.empty:
        result["first_break_30m_follow_through_pips"] = follow(win_30)

    reentry_time = None
    for timestamp, row in post_break.iloc[1:].iterrows():
        if reentered(row):
            reentry_time = timestamp
            break

    if reentry_time is not None:
        result["first_reentry_minute"] = int((reentry_time - session_start).total_seconds() / 60)
        result["fakeout_flag"] = 1
        result["fakeout_duration_min"] = int((reentry_time - break_time).total_seconds() / 60)
        result["fakeout_penetration_pips"] = penetration(post_break[post_break.index <= reentry_time])

    return result


def build_session_features(today_uk: datetime) -> dict:
    """
    Compute London-session feature columns from 5-minute price action.
    """
    row = {"session_date": today_uk.strftime("%Y-%m-%d")}
    gu = _intraday_history("GBPUSD=X", hours_back=40, interval="5m")
    if gu.empty:
        logger.warning("No GBP/USD intraday data available for session features")
        return row

    session_start, session_end = _session_bounds(today_uk.date())
    day_df = gu[gu.index.date == today_uk.date()]
    if day_df.empty:
        return row

    asian_df = day_df.between_time("00:00", "06:55")
    session_df = day_df[(day_df.index >= session_start) & (day_df.index < session_end)]
    if asian_df.empty or session_df.empty:
        return row

    asian_high = float(asian_df["High"].max())
    asian_low = float(asian_df["Low"].min())
    open_bar = session_df.iloc[0]
    open_0800 = round(float(open_bar["Open"]), 5)
    session_high = float(session_df["High"].max())
    session_low = float(session_df["Low"].min())
    session_close = float(session_df["Close"].iloc[-1])

    market_levels = price_data.get_market_context()
    nearest_level_type, nearest_level_distance = _nearest_level(open_0800, market_levels)

    row.update(
        {
            "open_0800": open_0800,
            "open_distance_asian_high_pips": round((open_0800 - asian_high) * PIPS, 1),
            "open_distance_asian_low_pips": round((open_0800 - asian_low) * PIPS, 1),
            "open_distance_yday_high_pips": (
                round((open_0800 - market_levels["yesterday_session_high"]) * PIPS, 1)
                if market_levels.get("yesterday_session_high") is not None
                else ""
            ),
            "open_distance_yday_low_pips": (
                round((open_0800 - market_levels["yesterday_session_low"]) * PIPS, 1)
                if market_levels.get("yesterday_session_low") is not None
                else ""
            ),
            "nearest_level_type": nearest_level_type or "",
            "nearest_level_distance_pips": nearest_level_distance if nearest_level_distance is not None else "",
            "session_true_range_pips": round((session_high - session_low) * PIPS, 1),
            "max_extension_above_asian_high_pips": round((session_high - asian_high) * PIPS, 1),
            "max_extension_below_asian_low_pips": round((asian_low - session_low) * PIPS, 1),
            "net_move_0800_1200_pips": round((session_close - open_0800) * PIPS, 1),
            "preopen_same_direction_15m_count": _count_preopen_same_direction(day_df),
            "eurusd_available": 0,
        }
    )

    row.update(_compute_first_break_features(session_df, asian_high, asian_low, session_start))

    dxy = _intraday_history("DX-Y.NYB", hours_back=12, interval="5m")
    if not dxy.empty:
        dxy_day = dxy[dxy.index.date == today_uk.date()].between_time("06:00", "08:00")
        if len(dxy_day) >= 2:
            start = float(dxy_day["Close"].iloc[0])
            end = float(dxy_day["Close"].iloc[-1])
            row["dxy_change_0600_0800_pct"] = round((end - start) / start * 100, 3)

    eurusd = _intraday_history("EURUSD=X", hours_back=12, interval="5m")
    if not eurusd.empty:
        eu_day = eurusd[eurusd.index.date == today_uk.date()].between_time("06:00", "08:00")
        if len(eu_day) >= 2:
            start = float(eu_day["Close"].iloc[0])
            end = float(eu_day["Close"].iloc[-1])
            row["eurusd_change_0600_0800_pct"] = round((end - start) / start * 100, 3)
            row["eurusd_available"] = 1

    return row
