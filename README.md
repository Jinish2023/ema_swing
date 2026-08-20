# EMA Swing Strategy Scanner + Tracker

Automates two validated EMA strategies -- scans NSE stocks for fresh
signals and tracks open positions to exit, entirely through GitHub
Actions. Every row in the output tells you exactly which strategy
produced it via the **StrategyType** column.

## The two strategies

| StrategyType | Entry trigger | Exit | Character |
|---|---|---|---|
| `ema_confluence` | Fresh 9/21 EMA crossover **AND** full EMA9>EMA21>EMA50 alignment on the same day, price above EMA50 | EMA9 crosses below EMA21 | Swing (avg ~3 weeks hold) |
| `long_term_200ema` | Close crosses above a **rising** 200 EMA | Close falls below EMA200 | Positional (can hold months) |

Both were backtested on the NSE 500 over 15 years with realistic
one-position-per-ticker enforcement and cost-adjustment -- see your
conversation history for the full numbers. Thresholds live in
`strategy_core.py` under `CONFIG` if you want to tune them.

---

## Step-by-step setup

### 1. Create the repo
Create a new (private or public) GitHub repository and push all the
files in this folder to it, preserving the folder structure (the
`.github/workflows/` folder must stay exactly where it is).

### 2. Install dependencies locally (one time, to run `fetch_tickers.py`)
```
pip install -r requirements.txt
```

### 3. Replace the sample ticker list with the full NSE 500
The included `tickers.csv` is just a 20-stock sample so you can test
quickly. Get the real list:
```
python fetch_tickers.py
```
This overwrites `tickers.csv` with the live NSE 500 constituent list.
Commit the updated file. Re-run this every few months since index
constituents change periodically.

### 4. Give the workflow permission to save results
In your repo: **Settings -> Actions -> General -> Workflow permissions**
-> select **"Read and write permissions"** -> Save.
(Without this, the bot can scan/track but can't commit `results.csv`
back to the repo, and your history won't persist between runs.)

### 5. Run it
Go to the **Actions** tab -> **EMA Swing Strategy Bot** -> **Run workflow**
-> choose **scan** or **track** from the dropdown -> **Run workflow**.

- **scan**: checks every ticker in `tickers.csv` for a signal that
  fired on the most recent trading day, for both strategies
  independently. New candidates are appended to `results.csv` with
  `Status = Pending`, `Taken = No`, tagged with `StrategyType`.
- **track**: fills any Pending candidate at the next available day's
  open price (flips it to `Status = Open`), then checks every Open
  position against its own strategy's exit rule (stop-loss, the
  EMA-based exit, or a time-based cap), closing it out if triggered.

### 6. Let it run automatically
It's already scheduled for weekdays: scan ~3:35pm IST, track ~3:50pm
IST. No further action needed -- just check `results.csv` periodically.
Edit the cron lines in `.github/workflows/ema_swing_bot.yml` if you
want different timing (cron times are in UTC; IST = UTC+5:30).

**Safety guard**: both scripts refuse to run before ~3:35pm IST on a
weekday (see `market_session_finalized()` in `strategy_core.py`).
Running mid-session would read a partial, incomplete daily bar --
today's Close/EMA values aren't reliable until the market shuts, and a
false signal from partial data would otherwise lock in via the dedup
rule until resolved. If you trigger the workflow manually before that
time, it'll just print a message and exit cleanly.

---

## Reading results.csv

| Column | Meaning |
|---|---|
| SerialNo | Sequential ID |
| ScanDate | Date the signal was first flagged |
| Ticker | NSE symbol (.NS suffix) |
| **StrategyType** | `ema_confluence` or `long_term_200ema` -- which strategy triggered this row |
| Status | Pending / Open / Closed |
| Strategy | Plain-English justification (EMA values, crossover/alignment date) |
| EntryDate / Entry | Filled at next-day open once taken |
| StopLoss | Entry-based % stop (6% for confluence, 15% for long-term) |
| Target | Always blank -- both strategies use a dynamic EMA-based exit, not a fixed target |
| ExitDate / Exit / Outcome | Stop / EMA_Cross_Exit / Close_Below_EMA / TimeExit, once closed |
| Return / Return% | Absolute and % P&L once closed |
| HoldingDays | Trading days held, filled once closed |
| Taken | No while still Pending, Yes once entered |
| EMA9 / EMA21 / EMA50 / EMA200 | Reference EMA values at signal time, for transparency |

Since both strategies write to the same file, you can filter/pivot by
`StrategyType` in Excel or Sheets to track them separately, or just
scan the column at a glance to see which book a given trade belongs to.

## Honest limitations
- Dedup (`already_flagged_recently` in `scanner.py`) is scoped per
  `(Ticker, StrategyType)` pair -- a stock can independently have an
  open `ema_confluence` position and also trigger a fresh
  `long_term_200ema` signal on the same day. They're tracked as
  separate books; decide for yourself whether you'd actually take both
  in real capital or pick one.
- No position sizing or portfolio-level capital limits -- this is a
  signal generator + tracker, not a portfolio simulator. Reuse
  `portfolio_simulator.py` from earlier in your project if you want to
  reason about realistic capital allocation across concurrent signals.
- `long_term_200ema` is explicitly positional (hold periods can run
  months). Don't blend its signals into your day-to-day swing-trading
  decisions -- track it as a separate mental bucket, per the earlier
  discussion.
- Data quality depends entirely on Yahoo Finance / yfinance uptime.
- NSE's ticker-list endpoint can change or block requests without
  warning -- if `fetch_tickers.py` breaks, get the CSV manually from
  niftyindices.com.
