"""
Shared logic for the EMA scanner + tracker.

Two strategies, validated via backtest on NSE 500 (15 years, cost-adjusted):
  - ema_confluence:   fresh 9/21 EMA crossover THAT ALSO has full
                       EMA9>EMA21>EMA50 alignment on the same day, price
                       above EMA50. Exit: EMA9 crosses below EMA21.
  - long_term_200ema: close crosses above a RISING 200 EMA. Exit: close
                       falls below EMA200. POSITIONAL, not swing -- long
                       hold periods expected by design.

Both checkers only fire on the very last bar of the dataframe passed in,
so the scanner only ever flags FRESH, actionable signals.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

IST = ZoneInfo("Asia/Kolkata")
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MINUTE = 35  # 5 min buffer after NSE's actual 15:30 close


def market_session_finalized() -> bool:
    """
    True only once today's NSE session data should be finalized. Guards
    the scanner/tracker from acting on partial intraday bars -- see the
    README for why this matters (a false mid-day signal would otherwise
    lock in via the dedup rule).
    """
    now_ist = datetime.now(IST)
    if now_ist.weekday() >= 5:  # Saturday/Sunday
        return True
    close_time = now_ist.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MINUTE,
                                  second=0, microsecond=0)
    return now_ist >= close_time


CONFIG = {
    "ema_confluence": dict(
        fast=9, mid=21, slow=50, trend_filter_ema=50,
        stop_pct=0.06,
        exit_mode="ema_cross_down",
        max_hold_days=180,
        dedup_days=5,
    ),
    "long_term_200ema": dict(
        trend_ema=200,
        slope_lookback=20,
        stop_pct=0.15,
        exit_mode="close_below_ema",
        exit_ema=200,
        max_hold_days=750,
        dedup_days=15,   # signals are naturally rarer and held far longer
    ),
}


def compute_emas(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for span in (9, 21, 50, 200):
        df[f"EMA{span}"] = df["Close"].ewm(span=span, adjust=False).mean()
    return df


def check_ema_confluence(df: pd.DataFrame, cfg: dict):
    """Returns a signal dict if TODAY (last bar) is a fresh confluence day, else None."""
    if len(df) < 60:
        return None
    i = len(df) - 1
    f, m, s = df["EMA9"], df["EMA21"], df["EMA50"]
    t = df[f"EMA{cfg['trend_filter_ema']}"]

    crossed_up = f.iloc[i - 1] <= m.iloc[i - 1] and f.iloc[i] > m.iloc[i]
    full_alignment = f.iloc[i] > m.iloc[i] > s.iloc[i]
    above_trend = df["Close"].iloc[i] > t.iloc[i]

    if crossed_up and full_alignment and above_trend:
        close_now = df["Close"].iloc[i]
        stop = close_now * (1 - cfg["stop_pct"])
        note = (f"Confluence: fresh 9/21 EMA crossover + EMA9>EMA21>EMA50 alignment on "
                f"{df.index[i].date()}, above EMA{cfg['trend_filter_ema']} trend filter. "
                f"EMA9={f.iloc[i]:.2f} EMA21={m.iloc[i]:.2f} EMA50={s.iloc[i]:.2f}")
        return dict(
            stop=round(stop, 2), target=None, note=note,
            ema9=round(f.iloc[i], 2), ema21=round(m.iloc[i], 2),
            ema50=round(s.iloc[i], 2), ema200=round(df["EMA200"].iloc[i], 2),
        )
    return None


def check_long_term_200ema(df: pd.DataFrame, cfg: dict):
    """Returns a signal dict if TODAY is a fresh rising-200EMA cross day, else None."""
    if len(df) < cfg["slope_lookback"] + 210:
        return None
    i = len(df) - 1
    ema200 = df["EMA200"]

    crossed_up = df["Close"].iloc[i - 1] <= ema200.iloc[i - 1] and df["Close"].iloc[i] > ema200.iloc[i]
    ema_rising = ema200.iloc[i] > ema200.iloc[i - cfg["slope_lookback"]]

    if crossed_up and ema_rising:
        close_now = df["Close"].iloc[i]
        stop = close_now * (1 - cfg["stop_pct"])
        note = (f"Close crossed above rising EMA200 on {df.index[i].date()}. "
                f"EMA200={ema200.iloc[i]:.2f} (vs {cfg['slope_lookback']}d ago: "
                f"{ema200.iloc[i - cfg['slope_lookback']]:.2f})")
        return dict(
            stop=round(stop, 2), target=None, note=note,
            ema9=round(df["EMA9"].iloc[i], 2), ema21=round(df["EMA21"].iloc[i], 2),
            ema50=round(df["EMA50"].iloc[i], 2), ema200=round(ema200.iloc[i], 2),
        )
    return None


SIGNAL_CHECKERS = {
    "ema_confluence": check_ema_confluence,
    "long_term_200ema": check_long_term_200ema,
}
