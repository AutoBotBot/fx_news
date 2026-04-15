import logging
from datetime import timedelta

import yfinance as yf

logger = logging.getLogger(__name__)

TICKERS = {
    "dxy": ("DX-Y.NYB", "DXY (US Dollar Index)"),
    "gold": ("GC=F", "Gold"),
    "es": ("ES=F", "ES (S&P 500 futures)"),
}


def _direction(change_pct: float | None) -> str:
    if change_pct is None:
        return "Unknown"
    if change_pct >= 0.5:
        return "Strong Up"
    if change_pct >= 0.15:
        return "Up"
    if change_pct > -0.15:
        return "Flat"
    if change_pct > -0.5:
        return "Down"
    return "Strong Down"


def _fetch_24h(ticker_symbol: str) -> tuple[float | None, float | None]:
    """
    Return (current_price, price_24h_ago) for the given ticker.
    Uses hourly data for the last 48 hours.
    Returns (None, None) on any failure.
    """
    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period="2d", interval="1h")
        if df.empty or len(df) < 2:
            logger.warning("Insufficient data for %s", ticker_symbol)
            return None, None

        current = float(df["Close"].iloc[-1])
        last_time = df.index[-1]
        target_time = last_time - timedelta(hours=24)
        diffs = abs(df.index - target_time)
        closest_idx = diffs.argmin()
        price_24h_ago = float(df["Close"].iloc[closest_idx])
        return current, price_24h_ago

    except Exception as e:
        logger.error("Failed to fetch data for %s: %s", ticker_symbol, e)
        return None, None


def _fmt(label: str, data: dict, decimals: int = 2) -> str:
    if data["current"] is None:
        return f"{label}: data unavailable"
    sign = "+" if (data["change_pct_24h"] or 0) >= 0 else ""
    chg = f"{sign}{data['change_pct_24h']:.3f}%" if data["change_pct_24h"] is not None else "n/a"
    return f"{label}: {data['direction']} ({chg})"


def get_correlations() -> dict:
    """
    Fetch DXY, gold, and ES futures context.
    Returns a dict with direction labels, % changes, and correlations_text.
    Any individual ticker failure is logged but does not crash the function.
    """
    results = {}

    for key, (symbol, display_name) in TICKERS.items():
        current, price_24h = _fetch_24h(symbol)
        if current is not None and price_24h is not None and price_24h != 0:
            change_pct = round((current - price_24h) / price_24h * 100, 3)
        else:
            change_pct = None
        results[key] = {
            "symbol": symbol,
            "display_name": display_name,
            "current": current,
            "change_pct_24h": change_pct,
            "direction": _direction(change_pct),
        }

    dxy = results["dxy"]
    gold = results["gold"]
    es = results["es"]

    es_dir = es["direction"]
    gold_dir = gold["direction"]

    if es_dir == "Unknown" or gold_dir == "Unknown":
        risk_tone = "Unknown"
    elif es_dir in ("Up", "Strong Up") and gold_dir in ("Down", "Strong Down", "Flat"):
        risk_tone = "Risk On"
    elif es_dir in ("Down", "Strong Down") and gold_dir in ("Up", "Strong Up"):
        risk_tone = "Risk Off"
    else:
        risk_tone = "Mixed"

    risk_desc = {
        "Risk On": "equity futures are firmer and gold is softer, which often points to steadier risk appetite",
        "Risk Off": "equity futures are weaker and gold is firmer, which often points to a more defensive mood",
        "Mixed": "the broader market signals are not aligned in one clear direction",
        "Unknown": "there is not enough data to judge the broader market mood cleanly",
    }.get(risk_tone, "")

    correlations_text = "\n".join(
        [
            _fmt(dxy["display_name"], dxy),
            _fmt(gold["display_name"], gold),
            _fmt(es["display_name"], es),
            f"Risk tone: {risk_tone}" + (f" — {risk_desc}" if risk_desc else ""),
        ]
    )

    return {
        "dxy_current": dxy["current"],
        "dxy_change_pct_24h": dxy["change_pct_24h"],
        "dxy_direction": dxy["direction"],
        "dxy_display_name": dxy["display_name"],
        "gold_current": gold["current"],
        "gold_change_pct_24h": gold["change_pct_24h"],
        "gold_direction": gold["direction"],
        "gold_display_name": gold["display_name"],
        "es_current": es["current"],
        "es_change_pct_24h": es["change_pct_24h"],
        "es_direction": es["direction"],
        "es_display_name": es["display_name"],
        "risk_tone": risk_tone,
        "correlations_text": correlations_text,
    }


if __name__ == "__main__":
    import pprint

    logging.basicConfig(level=logging.INFO)
    result = get_correlations()
    print("\n--- Correlations ---")
    pprint.pprint(result)
    print("\n--- Correlations Text ---")
    print(result["correlations_text"])
