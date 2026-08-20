"""
One-off / periodic helper: downloads the current NSE 500 constituent
list and saves it as tickers.csv. Run this locally (not in CI) whenever
you want to refresh the universe, then commit tickers.csv.

    python fetch_tickers.py

NSE actively blocks naive bot requests -- this uses a browser-like
session (visits nseindia.com first for cookies) to get past that. If it
still fails, download the "Nifty 500 List" CSV yourself from
niftyindices.com or nseindia.com and save it as tickers.csv with at
least a "Symbol" column.
"""
import io
import pandas as pd
import requests

NSE_ARCHIVE_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"


def fetch_nse500():
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
        "Accept-Language": "en-US,en;q=0.9",
    }
    session = requests.Session()
    session.get("https://www.nseindia.com", headers=headers, timeout=15)
    resp = session.get(NSE_ARCHIVE_URL, headers=headers, timeout=15)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    symbol_col = "Symbol" if "Symbol" in df.columns else df.columns[2]
    return df[[symbol_col]].rename(columns={symbol_col: "Symbol"})


if __name__ == "__main__":
    df = fetch_nse500()
    df.to_csv("tickers.csv", index=False)
    print(f"Saved {len(df)} tickers to tickers.csv -- remember to commit this file.")
