"""
resolve_stuck.py — one-off back-fill for positions the engine left stuck OPEN.

CONTEXT
-------
paper_trader.py resolves a position only if it catches Gamma returning the market
as closed (or price pinned to 0/1) on the exact day it polls. During the mid-July
API gaps, several markets resolved while Gamma wasn't returning them, so the exit
loop's cur_price stayed None and the rows froze OPEN forever (see check_stuck.py).

This script closes those orphaned rows using the SAME resolution semantics as the
frozen engine, so the scored sample stays rule-faithful. It is deliberately a
SEPARATE tool: paper_trader.py is frozen per PRE_REGISTRATION.md and is NOT edited.

SAFETY MODEL (this is the whole point)
--------------------------------------
  * Read-only by default. It prints what it WOULD do; it writes nothing unless
    you pass --apply.
  * It only ever acts on data the API CONFIRMS. If Gamma returns nothing for a
    market (outage, delisting, UMA not finalised), the row is LEFT OPEN and
    reported as UNVERIFIED — a blackout can never cause a wrong close.
  * It only touches rows flagged by check_stuck.find_stuck AND still OPEN.
    It is idempotent: re-running after --apply is a no-op on already-closed rows.
  * Before writing it backs up the ledger to paper_ledger.bak.<timestamp>.csv and
    appends every action to resolve_stuck_audit.csv (the pre-registration trail).

RESOLUTION SEMANTICS (identical to paper_trader.run_once exit loop)
------------------------------------------------------------------
  resolved = market.closed  OR  final_price within RESOLVED_BAND of 0/1
  win      = final_price >= 0.5   ->  exit_price 1.0, exit_type resolved_win
  loss     = otherwise            ->  exit_price 0.0, exit_type resolved_loss
  ret      = (exit_price - entry_price) / entry_price
date_closed is set to the market's resolution/end date when the API provides it
(more accurate for the >=48h scoring filter than "today"); else today.

USAGE
-----
    python3 resolve_stuck.py            # dry-run: show proposed closes
    python3 resolve_stuck.py --apply    # back up, write ledger, append audit log
"""
from __future__ import annotations
import argparse, csv, datetime as dt, json, shutil, sys
from pathlib import Path

import pmc
import paper_trader as pt          # reuse frozen constants + market_state, don't edit it
from check_stuck import find_stuck

HERE      = Path(__file__).resolve().parent
LEDGER_F  = HERE / "paper_ledger.csv"
AUDIT_F   = HERE / "resolve_stuck_audit.csv"
RESOLVED_BAND = pt.RESOLVED_BAND   # 0.02, straight from the frozen engine

AUDIT_COLS = ["run_ts", "conditionId", "outcome", "title", "entry_price",
              "final_price", "exit_type", "ret", "date_closed", "source"]


def _today() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


def _fetch_market(cid: str) -> dict | None:
    """Robust Gamma lookup. The default /markets query filters OUT closed markets,
    which is exactly why the engine and the first resolver draft saw nothing for
    resolved conditionIds. We try closed=true FIRST (recovers resolved markets),
    then the plain query (recovers still-open ones like NC Dinos)."""
    g = pmc.CFG.GAMMA_API
    for params in ({"condition_ids": cid, "closed": "true"},
                   {"condition_ids": cid},
                   {"condition_ids": cid, "active": "false"}):
        d = pmc._get(f"{g}/markets", params)
        rows = d if isinstance(d, list) else (d or {}).get("data", [])
        if rows:
            return rows[0]
    return None


def _state_from_row(m: dict) -> dict:
    """Build the same {closed, prices} shape paper_trader.market_state produces."""
    try:
        outs = json.loads(m.get("outcomes") or "[]")
        prs  = [float(x) for x in json.loads(m.get("outcomePrices") or "[]")]
        prices = dict(zip(outs, prs))
    except Exception:
        prices = {}
    return {"closed": bool(m.get("closed")), "prices": prices}


def _market_end_date(m: dict) -> str | None:
    """Best-effort actual resolution date from Gamma metadata (endDate)."""
    for k in ("endDate", "end_date", "endDateIso", "closedTime"):
        v = m.get(k) if isinstance(m, dict) else None
        if v:
            try:
                return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")).strftime("%Y-%m-%d")
            except Exception:
                pass
    return None


def decide(row: dict, state: dict | None, market_meta: dict | None, today: str) -> dict:
    """Pure decision: given a ledger row and the API's market_state/meta, return
    an action dict. No I/O here so it is unit-testable.

    action = {"kind": "close"|"unverified"|"still_open", ...}
    """
    outcome = row.get("outcome")
    entry   = float(row["entry_price"])
    if not state:
        return {"kind": "unverified", "reason": "API returned no market data"}

    price = state["prices"].get(outcome)
    resolved = bool(state.get("closed"))
    pinned   = price is not None and (price >= 1 - RESOLVED_BAND or price <= RESOLVED_BAND)

    if not (resolved or pinned):
        # API says the market is genuinely still live (e.g. not yet UMA-finalised)
        return {"kind": "still_open", "reason": "market not closed and price not pinned",
                "price": price}

    win   = price is not None and price >= 0.5
    exitp = 1.0 if win else 0.0
    ret   = round((exitp - entry) / entry, 4)
    date_closed = (_market_end_date(market_meta) if market_meta else None) or today
    return {"kind": "close", "final_price": price, "exit_price": exitp,
            "exit_type": "resolved_win" if win else "resolved_loss",
            "ret": ret, "date_closed": date_closed}


def _append_audit(entries: list[dict]):
    new = not AUDIT_F.exists()
    with open(AUDIT_F, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=AUDIT_COLS)
        if new:
            w.writeheader()
        for e in entries:
            w.writerow({c: e.get(c, "") for c in AUDIT_COLS})


def main() -> int:
    ap = argparse.ArgumentParser(description="Back-fill resolutions for stuck OPEN positions.")
    ap.add_argument("--ledger", default=str(LEDGER_F))
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    ap.add_argument("--stale-days", type=int, default=2)
    ap.add_argument("--event-days", type=int, default=3)
    args = ap.parse_args()

    path  = Path(args.ledger)
    rows  = list(csv.DictReader(open(path, newline="")))
    today = dt.datetime.now(dt.timezone.utc).date()
    today_s = today.isoformat()

    candidates = find_stuck(rows, today, args.stale_days, args.event_days)
    cand_ids = {(c["conditionId"], c["outcome"]) for c in candidates}
    print(f"=== resolve_stuck {today_s} ({'APPLY' if args.apply else 'DRY-RUN'}) ===")
    print(f"stuck candidates from check_stuck: {len(candidates)}\n")

    closes, unverified, still_open, audit = [], [], [], []
    row_by_key = {(r["conditionId"], r["outcome"]): r for r in rows}

    for cid, outcome in sorted(cand_ids):
        row = row_by_key[(cid, outcome)]
        if (row.get("status") or "").upper() != "OPEN":
            continue                                   # idempotent guard
        meta  = _fetch_market(cid)                     # closed=true first, then plain
        state = _state_from_row(meta) if meta else None
        action = decide(row, state, meta, today_s)
        title = (row.get("title") or "")[:48]

        if action["kind"] == "close":
            closes.append((row, action))
            print(f"  CLOSE   {outcome[:20]:<20} entry {row['entry_price']:<7} "
                  f"-> {action['exit_type']:<13} ret {action['ret']:+.4f}  {title}")
            audit.append({"run_ts": dt.datetime.now(dt.timezone.utc).isoformat(),
                          "conditionId": cid, "outcome": outcome, "title": row.get("title"),
                          "entry_price": row["entry_price"], "final_price": action.get("final_price"),
                          "exit_type": action["exit_type"], "ret": action["ret"],
                          "date_closed": action["date_closed"], "source": "gamma_market_state"})
        elif action["kind"] == "unverified":
            unverified.append(row)
            print(f"  SKIP    {outcome[:20]:<20} UNVERIFIED ({action['reason']}) — left OPEN  {title}")
        else:
            still_open.append(row)
            print(f"  KEEP    {outcome[:20]:<20} API says still live — left OPEN  {title}")

    print(f"\nsummary: {len(closes)} to close, {len(still_open)} still live per API, "
          f"{len(unverified)} unverified (API silent).")

    if not args.apply:
        print("\nDRY-RUN — nothing written. Re-run with --apply to commit.")
        return 0
    if not closes:
        print("\nNothing to write.")
        return 0

    # backup, then apply
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"paper_ledger.bak.{stamp}.csv")
    shutil.copy2(path, backup)
    for row, action in closes:
        row.update(status="CLOSED", date_closed=action["date_closed"],
                   exit_price=action["exit_price"], exit_type=action["exit_type"],
                   ret=action["ret"], mark_price=action.get("final_price", row.get("mark_price")),
                   last_update=today_s)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=pt.LEDGER_COLS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in pt.LEDGER_COLS})
    _append_audit(audit)
    print(f"\nAPPLIED: closed {len(closes)} rows. Backup -> {backup.name}. "
          f"Audit -> {AUDIT_F.name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
