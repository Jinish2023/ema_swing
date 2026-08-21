"""
Tracker: does two jobs each time it runs --

1. For "Pending" candidates (from a prior scan), fills the entry at the
   NEXT available trading day's OPEN price and flips them to "Open".
2. For "Open" positions, checks the latest bar against the exit rule
   that matches ITS OWN StrategyType:
     - ema_confluence:   stop hit, OR EMA9 crosses below EMA21
     - long_term_200ema: stop hit, OR close falls below EMA200
   plus a time-based exit after each strategy's own max_hold_days.

Run AFTER market close each trading day (the workflow does this
automatically, or trigger manually with mode=track).
"""
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

from strategy_core import CONFIG, compute_emas, market_session_finalized

RESULTS_PATH = Path("results.csv")


def fetch_latest_with_emas(ticker):
    """
    Downloads enough history to compute a meaningful EMA200 (long_term_200ema
    needs real warmup, not just a handful of bars) and returns the frame
    with EMA columns attached, or None if unavailable.
    """
    df = yf.download(ticker, period="3y", auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna()
    if df.empty:
        return None
    return compute_emas(df)


STRING_COLS = ["Ticker", "StrategyType", "Status", "Strategy", "Outcome", "Taken"]
NUMERIC_COLS = ["SerialNo", "Entry", "StopLoss", "Target", "Exit", "Return", "Return%",
                "HoldingDays", "EMA9", "EMA21", "EMA50", "EMA200"]
DATE_COLS = ["ScanDate", "EntryDate", "ExitDate"]


def coerce_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """
    Force every column to its intended dtype right after loading from CSV.
    Necessary because an entirely-empty column (e.g. Outcome before any
    trade has closed, or HoldingDays before any position is open) gets its
    dtype GUESSED by pandas -- and that guess differs across pandas
    versions (float64 in some, StringDtype in others with the newer
    string-inference default). Either guess breaks the moment we try to
    write the "wrong" kind of value into it later. Explicit coercion here
    makes this version-independent.
    """
    for col in STRING_COLS:
        if col in df.columns:
            df[col] = df[col].astype(object)
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in DATE_COLS:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def main():
    if not market_session_finalized():
        print("Refusing to track: today's NSE session isn't finalized yet "
              "(before 3:35pm IST on a weekday). Entry-fills are already "
              "date-guarded and won't fire early, but run this after market "
              "close anyway so exit checks use the full day's range.")
        return

    if not RESULTS_PATH.exists():
        print("No results.csv found -- run the scanner first.")
        return

    results = pd.read_csv(RESULTS_PATH)
    results = coerce_dtypes(results)

    changed = False

    # 1. Fill pending candidates at the next available day's open
    for idx in results.index[results["Taken"] == "No"]:
        ticker = results.at[idx, "Ticker"]
        strat = results.at[idx, "StrategyType"]
        df = fetch_latest_with_emas(ticker)
        if df is None:
            continue
        bar_date = df.index[-1]
        if bar_date <= results.at[idx, "ScanDate"]:
            continue  # no new trading day available yet, try again next run
        row = df.iloc[-1]
        results.at[idx, "EntryDate"] = bar_date
        results.at[idx, "Entry"] = round(float(row["Open"]), 2)
        results.at[idx, "Status"] = "Open"
        results.at[idx, "Taken"] = "Yes"
        changed = True
        print(f"Filled entry: {ticker} ({strat}) @ {row['Open']:.2f} on {bar_date.date()}")

    # 2. Check open positions against each strategy's own exit rule
    for idx in results.index[results["Status"] == "Open"]:
        ticker = results.at[idx, "Ticker"]
        strat = results.at[idx, "StrategyType"]
        cfg = CONFIG[strat]
        df = fetch_latest_with_emas(ticker)
        if df is None:
            continue
        bar_date = df.index[-1]
        entry_date = results.at[idx, "EntryDate"]
        if pd.isna(entry_date) or bar_date < entry_date:
            continue

        row = df.iloc[-1]
        stop = results.at[idx, "StopLoss"]
        entry_price = results.at[idx, "Entry"]
        days_held = (bar_date - entry_date).days

        outcome, exit_price = None, None
        if row["Low"] <= stop:
            outcome, exit_price = "Stop", stop
        elif cfg["exit_mode"] == "ema_cross_down" and row["EMA9"] < row["EMA21"]:
            outcome, exit_price = "EMA_Cross_Exit", round(float(row["Close"]), 2)
        elif cfg["exit_mode"] == "close_below_ema" and row["Close"] < row[f"EMA{cfg['exit_ema']}"]:
            outcome, exit_price = "Close_Below_EMA", round(float(row["Close"]), 2)
        elif days_held >= cfg["max_hold_days"]:
            outcome, exit_price = "TimeExit", round(float(row["Close"]), 2)

        if outcome:
            results.at[idx, "ExitDate"] = bar_date
            results.at[idx, "Exit"] = exit_price
            results.at[idx, "Outcome"] = outcome
            results.at[idx, "Status"] = "Closed"
            results.at[idx, "Return"] = round(exit_price - entry_price, 2)
            results.at[idx, "Return%"] = round((exit_price - entry_price) / entry_price * 100, 2)
            results.at[idx, "HoldingDays"] = days_held
            changed = True
            print(f"Closed: {ticker} ({strat}) -> {outcome} @ {exit_price:.2f}")

    if changed:
        results.to_csv(RESULTS_PATH, index=False)
        print(f"\nSaved updates to {RESULTS_PATH}")
    else:
        print("\nNo updates today.")


if __name__ == "__main__":
    main()
