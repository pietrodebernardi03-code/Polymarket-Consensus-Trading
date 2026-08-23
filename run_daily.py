#!/usr/bin/env python3
"""
run_daily.py — daily driver for the paper-trade experiment.

Point cron at THIS file instead of paper_trader.py. It:
  1. runs the frozen engine exactly as before (paper_trader.run_once), then
  2. self-audits the ledger with check_stuck and logs any orphaned positions.

It changes NOTHING about the strategy or the engine — it just adds the safety net
so a repeat of the "stuck OPEN" bug (or a fresh API outage) is flagged automatically
in stuck_alerts.log instead of going unnoticed until the next manual check.

Cron line (replaces the old paper_trader.py line):
  0 9 * * * cd "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Extra Projects/Polymarket Consesus Trading" && /usr/bin/python3 run_daily.py >> paper_trader.log 2>&1
"""
from __future__ import annotations
import csv, datetime as dt
from pathlib import Path

import paper_trader
import check_stuck

HERE      = Path(__file__).resolve().parent
LEDGER_F  = HERE / "paper_ledger.csv"
ALERT_LOG = HERE / "stuck_alerts.log"


def main():
    paper_trader.run_once()                       # frozen engine, unchanged

    rows  = list(csv.DictReader(open(LEDGER_F, newline="")))
    today = dt.datetime.now(dt.timezone.utc).date()
    stuck = check_stuck.find_stuck(rows, today)
    ts    = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    if stuck:
        with open(ALERT_LOG, "a") as f:
            f.write(f"[{ts}] {len(stuck)} stuck position(s) flagged:\n")
            for s in stuck:
                f.write(f"    last_update={s['last_update']} stale={s['stale_days']}d "
                        f"{s['outcome']} :: {s['title']}\n")
        print(f"[check_stuck] WARNING: {len(stuck)} stuck position(s) — logged to {ALERT_LOG.name}. "
              f"Review and run: python3 resolve_stuck.py")
    else:
        print("[check_stuck] clean — every open position is being refreshed.")


if __name__ == "__main__":
    main()
