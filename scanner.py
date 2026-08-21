"""
Scanner: checks every ticker for FRESH ema_confluence or long_term_200ema
signals and appends them to results.csv as "Pending" rows, tagged with
which strategy fired via the StrategyType column.

Run AFTER market close each trading day (the workflow does this
automatically, or trigger manually with mode=scan).
"""
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

from strategy_core import CONFIG, SIGNAL_CHECKERS, compute_emas, market_session_finalized

RESULTS_PATH = Path("results.csv")
TICKERS_PATH = Path("tickers.csv")

COLUMNS = [
    "SerialNo", "ScanDate", "Ticker", "StrategyType", "Status", "Strategy",
    "EntryDate", "Entry", "StopLoss", "Target",
    "ExitDate", "Exit", "Outcome", "Return", "Return%", "HoldingDays", "Taken",
    "EMA9", "EMA21", "EMA50", "EMA200",
]


STRING_COLS = ["Ticker", "StrategyType", "Status", "Strategy", "Outcome", "Taken"]
NUMERIC_COLS = ["SerialNo", "Entry", "StopLoss", "Target", "Exit", "Return", "Return%",
                "HoldingDays", "EMA9", "EMA21", "EMA50", "EMA200"]
DATE_COLS = ["ScanDate", "EntryDate", "ExitDate"]


def parse_date_column(series: pd.Series) -> pd.Series:
    """See tracker.py's parse_date_column for why dayfirst=True alone is unsafe here."""
    s = series.astype(str).str.strip()
    s = s.replace({"nan": None, "NaT": None, "": None})
    result = pd.to_datetime(s, format="%Y-%m-%d", errors="coerce")
    still_missing = result.isna() & s.notna()
    if still_missing.any():
        result.loc[still_missing] = pd.to_datetime(
            s[still_missing], format="%Y-%m-%d %H:%M:%S", errors="coerce")
    still_missing = result.isna() & s.notna()
    if still_missing.any():
        result.loc[still_missing] = pd.to_datetime(
            s[still_missing], format="%d/%m/%Y", errors="coerce")
    return result


def coerce_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """See tracker.py's coerce_dtypes for why this is necessary."""
    for col in STRING_COLS:
        if col in df.columns:
            df[col] = df[col].astype(object)
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in DATE_COLS:
        if col in df.columns:
            df[col] = parse_date_column(df[col])
    return df


def load_results():
    if RESULTS_PATH.exists():
        df = pd.read_csv(RESULTS_PATH)
        df = coerce_dtypes(df)
        return df
    return pd.DataFrame(columns=COLUMNS)


def load_tickers():
    df = pd.read_csv(TICKERS_PATH)
    col = "Symbol" if "Symbol" in df.columns else df.columns[0]
    syms = df[col].astype(str).str.strip().tolist()
    return [s if s.endswith(".NS") else s + ".NS" for s in syms if s]


def already_flagged_recently(results, ticker, strategy_type, today, dedup_days):
    """
    True if we should SKIP this ticker for this specific strategy --
    scoped to (Ticker, StrategyType) since a stock can independently
    have an open ema_confluence position AND separately trigger a fresh
    long_term_200ema signal; they're tracked as separate books.
    """
    if results.empty:
        return False
    sub = results[(results["Ticker"] == ticker) & (results["StrategyType"] == strategy_type)]
    if sub.empty:
        return False
    if (sub["Taken"] == "No").any():
        return True
    entered = sub.dropna(subset=["EntryDate"])
    if entered.empty:
        return False
    recent = entered[(today - entered["EntryDate"]).dt.days <= dedup_days]
    return not recent.empty


def main():
    if not market_session_finalized():
        print("Refusing to scan: today's NSE session isn't finalized yet "
              "(before 3:35pm IST on a weekday). Run this again after market close.")
        return

    results = load_results()
    tickers = load_tickers()
    today = pd.Timestamp(datetime.now().date())

    print(f"Scanning {len(tickers)} tickers for ema_confluence and long_term_200ema signals...")
    new_rows = []
    serial_start = (
        int(results["SerialNo"].max()) + 1
        if not results.empty and results["SerialNo"].notna().any() else 1
    )

    for i, ticker in enumerate(tickers):
        try:
            df = yf.download(ticker, period="3y", auto_adjust=True, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.dropna()
            if df.empty:
                continue
            df = compute_emas(df)

            for strat_name, checker in SIGNAL_CHECKERS.items():
                cfg = CONFIG[strat_name]
                if already_flagged_recently(results, ticker, strat_name, today, cfg["dedup_days"]):
                    continue
                signal = checker(df, cfg)
                if signal is None:
                    continue

                new_rows.append({
                    "SerialNo": serial_start + len(new_rows),
                    "ScanDate": today,
                    "Ticker": ticker,
                    "StrategyType": strat_name,
                    "Status": "Pending",
                    "Strategy": signal["note"],
                    "EntryDate": pd.NaT, "Entry": None,
                    "StopLoss": signal["stop"], "Target": signal["target"],
                    "ExitDate": pd.NaT, "Exit": None, "Outcome": None,
                    "Return": None, "Return%": None, "HoldingDays": None,
                    "Taken": "No",
                    "EMA9": signal["ema9"], "EMA21": signal["ema21"],
                    "EMA50": signal["ema50"], "EMA200": signal["ema200"],
                })
                print(f"  [{i+1}/{len(tickers)}] {ticker}: NEW {strat_name} CANDIDATE")
        except Exception as e:
            print(f"  [{i+1}/{len(tickers)}] {ticker}: error - {e}")
            continue

    if new_rows:
        results = pd.concat([results, pd.DataFrame(new_rows)], ignore_index=True)
        results.to_csv(RESULTS_PATH, index=False)
        print(f"\nAdded {len(new_rows)} new candidates. Saved to {RESULTS_PATH}")
    else:
        print("\nNo new candidates found today.")
        if not RESULTS_PATH.exists():
            results.to_csv(RESULTS_PATH, index=False)


if __name__ == "__main__":
    main()
