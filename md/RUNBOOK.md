# Runbook — Automatic Paper-Trading Engine

`paper_trader.py` runs the **frozen** strategy from `PRE_REGISTRATION.md` once per day, with no
real money. It maintains two files in this folder:

- `roster_paper.json` — the qualified roster (rebuilt automatically on the 1st of each month).
- `paper_ledger.csv` — every paper trade: entry, backers, sizing, exit, and return.

## 1. One-time setup
```bash
pip install requests pandas
```

## 2. Run it manually (do this once first)
```bash
cd "~/Library/Mobile Documents/com~apple~CloudDocs/Extra Projects/Polymarket Consesus Trading"
python3 paper_trader.py
```
The **first** run builds the roster (a few minutes; cached afterward), then scans for signals.
Most days it will open **0 trades** — that is expected and correct. The strategy is selective;
genuine ≥2-sharp consensus at an un-run price is rare, which is the whole point.

## 3. Make it automatic (daily, macOS)
Open your crontab:
```bash
crontab -e
```
Add one line (runs every day at 09:00; adjust the python path if needed — check with `which python3`):
```
0 9 * * * cd "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Extra Projects/Polymarket Consesus Trading" && /usr/bin/python3 run_daily.py >> paper_trader.log 2>&1
```
`run_daily.py` runs the frozen engine and then self-audits the ledger with `check_stuck.py`,
appending any orphaned ("stuck OPEN") positions to `stuck_alerts.log`. (Running `paper_trader.py`
directly still works and is identical minus the safety check.)

**Safety / integrity tools (added 23 July 2026, read-only unless noted):**
- `check_stuck.py` — flags OPEN positions whose feed froze (almost certainly resolved but unrecorded).
- `resolve_stuck.py` — back-fills those resolutions (dry-run by default; `--apply` backs up + logs to `resolve_stuck_audit.csv`).
- `segment_stats.py` — stratified performance (by category / month / sports-vs-non-sports) per PRE_REGISTRATION §6.
Every run appends to `paper_trader.log` and updates `paper_ledger.csv`. It is idempotent — running
twice in a day does no harm and never double-books a market.

*(If you prefer, `launchd` works too; cron is simplest for a personal Mac.)*

## 4. Reading the output
Each run prints:
- `[ENTRY]` — a new paper position opened (market, price, number of backing sharps).
- `[EXIT]` / `[RESOLVE]` — a position closed because the sharps left, or the market resolved.
- `[report]` — running `hit_rate`, `avg_entry_price`, and `median_ret`.
- `[VERDICT]` — appears once **≥ 30 trades have resolved**: SUCCESS if `median_ret > 0` **and**
  `hit_rate > avg_entry_price` (the pre-registered criterion), else FAILURE.

`paper_ledger.csv` is the full record — open it in Excel any time.

## 5. Rules of the experiment (from the pre-registration)
- **Do not edit the FROZEN constants** at the top of `paper_trader.py` until the verdict is in.
- Let it run ~4–6 weeks (or until ≥30 resolved trades). Prediction markets resolve on varied
  horizons, so be patient — a thin week is normal.
- When the verdict prints, that is the out-of-sample result for the paper. Send me
  `paper_ledger.csv` and I'll do the write-up and the figures.

## 6. If something looks off on the first run
- If it opens *no* trades ever and `[report]` says "no closed trades," that's usually just the
  strategy being selective — give it a week.
- If you see repeated warnings about the Gamma `/markets` call (current price / resolution), the
  price endpoint may need the same kind of small tweak we did for others — send me the warning and
  I'll patch `market_state()` in `paper_trader.py`.
