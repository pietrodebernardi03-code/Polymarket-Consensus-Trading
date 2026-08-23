"""
check_stuck.py — read-only integrity monitor for paper_ledger.csv.

WHY THIS EXISTS
---------------
paper_trader.py can silently leave a trade OPEN forever. Its exit loop only
resolves a position if Gamma (/markets?condition_ids=) returns the market with
closed=true or a price pinned to 0/1 AT THE MOMENT IT POLLS. When a market
resolves, the roster wallets stop holding it, so it also drops out of `holds`;
if Gamma doesn't return it that day (API outage, delisting, UMA lag), cur_price
stays None, mark_price/last_update freeze, and NO exit branch fires. The row is
stuck. This happened to ~30 positions (all concluded sports + finished World Cup
markets) during the mid-July API gaps.

This script does NOT touch the engine and does NOT hit the network. It reads the
ledger only, so it is safe to run any time — including while the API is down —
and it exploits the one reliable fingerprint of a stuck row: its last_update
stops advancing while live positions keep getting refreshed every daily run.

TWO DETECTORS
-------------
  A. STALE_FEED  — OPEN and last_update older than --stale-days (default 2).
                   A live market is re-marked every run, so a frozen last_update
                   means the engine lost the market → almost certainly already
                   resolved but never recorded. Catches the World Cup / tennis /
                   MLB freezes.
  B. EVENT_PASSED — OPEN, title looks like a single dated event (a "X vs Y"
                    match, or a title carrying an explicit date), and it was
                    opened more than --event-days ago (default 3). Catches the
                    NC Dinos case, where Gamma still returns a mid price so
                    last_update keeps advancing but the game is long over.

Long-dated markets (Bitcoin "by Dec 31", "before 2027", 2026 elections, etc.)
are correctly NOT flagged: they are refreshed daily, so last_update is current
and they carry no near-term single-event signature.

USAGE
-----
    python3 check_stuck.py                 # audit the default ledger
    python3 check_stuck.py --stale-days 3  # looser staleness threshold
    python3 check_stuck.py --json          # machine-readable output

Exit code is 0 if the book is clean, 1 if any position looks stuck — so you can
wire it into the daily run (e.g. `python3 check_stuck.py || notify ...`).
"""
from __future__ import annotations
import argparse, csv, json, re, sys
import datetime as dt
from pathlib import Path

LEDGER_F = Path(__file__).resolve().parent / "paper_ledger.csv"

# A title is a "single dated event" if it pits two named sides against each
# other (" vs " / " vs. ") or embeds an explicit YYYY-MM-DD date.
_VS_RE   = re.compile(r"\bvs\.?\b", re.IGNORECASE)
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _parse_date(s: str) -> dt.date | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return dt.date.fromisoformat(s[:10])
    except ValueError:
        return None


def _is_single_event(title: str) -> bool:
    return bool(_VS_RE.search(title or "") or _DATE_RE.search(title or ""))


def find_stuck(rows: list[dict], today: dt.date,
               stale_days: int = 2, event_days: int = 3) -> list[dict]:
    """Return OPEN rows that look resolved-but-unrecorded, each annotated with
    the reason(s) it was flagged and how stale it is."""
    flagged = []
    for r in rows:
        if (r.get("status") or "").upper() != "OPEN":
            continue
        opened   = _parse_date(r.get("date_opened", ""))
        updated  = _parse_date(r.get("last_update", ""))
        title    = r.get("title", "") or ""
        reasons  = []

        stale_by = (today - updated).days if updated else None
        if stale_by is not None and stale_by >= stale_days:
            reasons.append(f"STALE_FEED (last_update {stale_by}d old)")

        if opened and _is_single_event(title) and (today - opened).days >= event_days:
            # only useful when it wasn't already caught as stale, but we still
            # record it so single-event freezes with a live feed surface too
            reasons.append(f"EVENT_PASSED (opened {(today - opened).days}d ago, single-event title)")

        if reasons:
            flagged.append({
                "date_opened": r.get("date_opened", ""),
                "last_update": r.get("last_update", ""),
                "stale_days":  stale_by,
                "outcome":     r.get("outcome", ""),
                "entry_price": r.get("entry_price", ""),
                "mark_price":  r.get("mark_price", ""),
                "title":       title,
                "conditionId": r.get("conditionId", ""),
                "reasons":     reasons,
            })
    # worst offenders (most stale) first; None-stale rows sort last
    flagged.sort(key=lambda x: (x["stale_days"] is None, -(x["stale_days"] or 0)))
    return flagged


def _load(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit paper_ledger.csv for stuck positions.")
    ap.add_argument("--ledger", default=str(LEDGER_F))
    ap.add_argument("--stale-days", type=int, default=2)
    ap.add_argument("--event-days", type=int, default=3)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows  = _load(Path(args.ledger))
    today = dt.datetime.now(dt.timezone.utc).date()
    stuck = find_stuck(rows, today, args.stale_days, args.event_days)

    n_open = sum(1 for r in rows if (r.get("status") or "").upper() == "OPEN")

    if args.json:
        print(json.dumps({"today": today.isoformat(), "open": n_open,
                          "stuck": len(stuck), "positions": stuck}, indent=2))
        return 1 if stuck else 0

    print(f"=== check_stuck {today} ===")
    print(f"open positions: {n_open}   flagged as stuck: {len(stuck)}\n")
    if not stuck:
        print("Clean — every open position is being refreshed. Nothing to resolve by hand.")
        return 0

    for s in stuck:
        stale = f"{s['stale_days']}d" if s["stale_days"] is not None else "n/a"
        print(f"  [{s['last_update']} | stale {stale:>4}] {s['outcome'][:22]:<22} "
              f"entry {s['entry_price']:<7} mark {s['mark_price']:<7} {s['title'][:52]}")
        print(f"      -> {'; '.join(s['reasons'])}")
    print(f"\n{len(stuck)} position(s) almost certainly resolved but still OPEN. "
          f"Verify on Polymarket and close them by hand (or run the resolver).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
