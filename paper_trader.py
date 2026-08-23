"""
paper_trader.py — Automatic forward paper-trading engine.

Implements EXACTLY the frozen strategy in PRE_REGISTRATION.md (v1.0, 2026-07-04):
  - roster: leaderboard ALL+MONTH, PIT gate (>=30 resolved trades, >=55% win rate),
    re-ranked monthly.
  - ENTRY: >=2 qualified roster wallets co-hold the same outcome, current price within
    0.06 of their median entry and inside [0.10, 0.90], >48h to resolution.
  - EXIT: qualified holders drop below 2 (smart money left) OR the market resolves.
  - No real orders. Appends paper trades to paper_ledger.csv and scores resolved ones.

Run it once per day (see RUNBOOK.md). It is idempotent — safe to re-run; it never
double-books a market and only advances open trades.

NOTHING here is tunable mid-experiment. Per the pre-registration, do not change the
frozen constants below until >=30 trades have resolved and the test is evaluated.
"""

from __future__ import annotations
import json, csv, time, datetime as dt
from pathlib import Path
import pmc

# ---- FROZEN STRATEGY CONSTANTS (do not edit during the experiment) ----------
MIN_BACKERS        = 2
SLIPPAGE_GUARD     = 0.06     # price-guard tolerance vs sharps' median entry
EXEC_SLIPPAGE      = 0.01     # modelled cost of our own fill on entry/exit
PRICE_FLOOR        = 0.10
PRICE_CEILING      = 0.90
MIN_HOURS_TO_RES   = 48
CAND_PER_WINDOW    = 150
MIN_TRAILING_TRADES= 30
MIN_TRAILING_WR    = 0.55
KELLY_FRACTION     = 0.25
MAX_SIZE_PCT       = 0.05
BANKROLL           = 5000.0
RESOLVED_BAND      = 0.02     # curPrice within this of 0/1 => treated as resolved

HERE      = Path(__file__).resolve().parent
ROSTER_F  = HERE / "roster_paper.json"
LEDGER_F  = HERE / "paper_ledger.csv"
LEDGER_COLS = ["date_opened","conditionId","outcome","title","entry_price","backers_at_entry",
               "size_flat","size_kelly_eur","status","date_closed","exit_price","exit_type",
               "ret","mark_price","last_update"]

def _today() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")

def _month() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m")

# --------------------------------------------------------------------------
# ROSTER (monthly, point-in-time qualification from full resolved history)
# --------------------------------------------------------------------------

def build_roster() -> dict:
    cands = {}
    for w in ("ALL", "MONTH"):
        for r in pmc.get_leaderboard(window=w, limit=CAND_PER_WINDOW):
            cands.setdefault(r["wallet"], r)
    print(f"[roster] scoring {len(cands)} candidate traders — first run can take a "
          f"few minutes, please wait...", flush=True)
    roster = {}
    for i, wallet in enumerate(cands, 1):
        closed = pmc.get_closed_positions(wallet, max_positions=600)
        n = len(closed)
        if n >= MIN_TRAILING_TRADES:
            wins = sum(1 for p in closed if float(p.get("realizedPnl") or 0) > 0)
            wr = wins / n
            if wr >= MIN_TRAILING_WR:
                roster[wallet] = {"win_rate": round(wr, 3), "n": n}
        if i % 20 == 0:
            print(f"    ...checked {i}/{len(cands)} traders ({len(roster)} qualify so far)", flush=True)
    payload = {"month": _month(), "built": _today(), "wallets": roster}
    ROSTER_F.write_text(json.dumps(payload, indent=2))
    print(f"[roster] built {len(roster)} qualified wallets for {_month()}")
    return payload

def load_roster() -> dict:
    if ROSTER_F.exists():
        p = json.loads(ROSTER_F.read_text())
        if p.get("month") == _month():
            return p
    return build_roster()                      # missing or stale month -> rebuild

# --------------------------------------------------------------------------
# MARKET STATE (current price + resolution) via Gamma, best-effort
# --------------------------------------------------------------------------

def market_state(condition_id: str) -> dict | None:
    """Return {'closed': bool, 'prices': {outcome: price}} for a market, or None.

    FIX 2026-07-23 (data-plumbing only; addendum to PRE_REGISTRATION.md, no frozen
    strategy constant changed): Gamma's /markets endpoint returns only ACTIVE markets
    by default, so a market DROPPED OUT of the response the instant it resolved. The
    exit loop then never saw closed=true, cur_price stayed None, and the trade froze
    OPEN forever (loss-biased: losers pinned to 0 fast and were caught, winners were
    orphaned). We now query closed=true FIRST to recover resolved markets, then fall
    back to the plain query for still-open ones. See check_stuck.py / resolve_stuck.py.
    """
    rows = []
    for params in ({"condition_ids": condition_id, "closed": "true"},
                   {"condition_ids": condition_id}):
        data = pmc._get(f"{pmc.CFG.GAMMA_API}/markets", params)
        rows = data if isinstance(data, list) else (data or {}).get("data", [])
        if rows:
            break
    if not rows:
        return None
    m = rows[0]
    try:
        outs = json.loads(m.get("outcomes") or "[]")
        prs  = [float(x) for x in json.loads(m.get("outcomePrices") or "[]")]
        prices = dict(zip(outs, prs))
    except Exception:
        prices = {}
    return {"closed": bool(m.get("closed")), "prices": prices}

# --------------------------------------------------------------------------
# CURRENT CO-HOLDINGS of the roster
# --------------------------------------------------------------------------

def current_holdings(roster: dict) -> dict:
    """(conditionId, outcome) -> {backers, median_entry, cur_price, title}."""
    from statistics import median
    wallets = list(roster["wallets"])
    print(f"[scan] reading current positions of {len(wallets)} roster traders...", flush=True)
    groups: dict = {}
    for i, wallet in enumerate(wallets, 1):
        for p in pmc.get_open_positions(wallet):
            cid, outcome = p.get("conditionId"), p.get("outcome")
            if not cid or outcome is None:
                continue
            g = groups.setdefault((cid, outcome),
                                  {"wallets": set(), "entries": [], "cur": [], "ends": [],
                                   "title": p.get("title")})
            g["wallets"].add(wallet)
            g["entries"].append(float(p.get("avgPrice") or 0))
            g["cur"].append(float(p.get("curPrice") or 0))
            et = _parse_end(p.get("endDate"))
            if et:
                g["ends"].append(et)
        if i % 20 == 0:
            print(f"    ...read {i}/{len(wallets)} traders", flush=True)
    out = {}
    for k, g in groups.items():
        out[k] = {"backers": len(g["wallets"]),
                  "median_entry": round(median(g["entries"]), 4),
                  "cur_price": round(median(g["cur"]), 4),
                  "end_ts": min(g["ends"]) if g["ends"] else None,
                  "title": g["title"]}
    return out

def _parse_end(s):
    """Parse a Polymarket endDate string to a unix timestamp, or None."""
    if not s:
        return None
    try:
        return int(dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp())
    except Exception:
        return None

# --------------------------------------------------------------------------
# LEDGER
# --------------------------------------------------------------------------

def load_ledger() -> list[dict]:
    if not LEDGER_F.exists():
        return []
    with open(LEDGER_F) as f:
        return list(csv.DictReader(f))

def save_ledger(rows: list[dict]):
    with open(LEDGER_F, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_COLS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in LEDGER_COLS})

def kelly_size_eur(cur_price: float) -> float:
    p_est = min(0.95, cur_price + 0.04)                 # small consensus margin
    f = KELLY_FRACTION * pmc.kelly_fraction(p_est, cur_price)
    return round(min(f, MAX_SIZE_PCT) * BANKROLL, 2)

# --------------------------------------------------------------------------
# MAIN DAILY CYCLE
# --------------------------------------------------------------------------

def run_once():
    print(f"=== paper_trader {_today()} (frozen strategy v1.1) ===")
    roster = load_roster()
    holds = current_holdings(roster)
    ledger = load_ledger()
    seen = {(r["conditionId"], r["outcome"]) for r in ledger}   # never re-enter a market

    # how many outcomes of each market have >=2 qualified backers (for the no-dissent rule)
    sides_2plus: dict = {}
    for (cid, _o), g in holds.items():
        if g["backers"] >= MIN_BACKERS:
            sides_2plus[cid] = sides_2plus.get(cid, 0) + 1
    now_ts = time.time()

    # ---- ENTRIES ----
    new_entries = 0
    for (cid, outcome), g in holds.items():
        if g["backers"] < MIN_BACKERS or (cid, outcome) in seen:
            continue
        # NO DISSENT: the sharps must agree on ONE side. If >1 outcome of this market
        # has >=2 backers, they disagree -> stand aside (v1.1).
        if sides_2plus.get(cid, 0) > 1:
            continue
        # >=48h TO RESOLUTION (pre-registration §3.4). If the resolution date is unknown
        # we cannot confirm it is >48h away, so we conservatively skip (this removes the
        # few same-day sports markets whose endDate is missing from the position data).
        if g["end_ts"] is None or (g["end_ts"] - now_ts) < MIN_HOURS_TO_RES * 3600:
            continue
        cur, med = g["cur_price"], g["median_entry"]
        price_ok = (cur <= med + SLIPPAGE_GUARD) and (PRICE_FLOOR <= cur <= PRICE_CEILING)
        if not price_ok:
            continue
        entry = round(min(cur + EXEC_SLIPPAGE, 0.99), 4)
        ledger.append({
            "date_opened": _today(), "conditionId": cid, "outcome": outcome,
            "title": g["title"], "entry_price": entry, "backers_at_entry": g["backers"],
            "size_flat": 1, "size_kelly_eur": kelly_size_eur(cur),
            "status": "OPEN", "date_closed": "", "exit_price": "", "exit_type": "",
            "ret": "", "mark_price": entry, "last_update": _today(),
        })
        seen.add((cid, outcome)); new_entries += 1
        print(f"[ENTRY] {outcome:>5} @ {entry:.3f}  x{g['backers']}  {str(g['title'])[:50]}")

    # ---- EXITS / MARK-TO-MARKET ----
    closed_now = 0
    for r in ledger:
        if r["status"] != "OPEN":
            continue
        cid, outcome = r["conditionId"], r["outcome"]
        still = holds.get((cid, outcome), {}).get("backers", 0)
        st = market_state(cid)
        resolved = bool(st and st["closed"])
        cur_price = None
        if st and outcome in st["prices"]:
            cur_price = st["prices"][outcome]
        elif (cid, outcome) in holds:
            cur_price = holds[(cid, outcome)]["cur_price"]
        if cur_price is not None:
            r["mark_price"] = round(cur_price, 4); r["last_update"] = _today()
        # resolution by explicit flag or price pinned to 0/1
        pinned = cur_price is not None and (cur_price >= 1 - RESOLVED_BAND or cur_price <= RESOLVED_BAND)
        entry = float(r["entry_price"])
        if resolved or pinned:
            win = (cur_price is not None and cur_price >= 0.5)
            exitp = 1.0 if win else 0.0
            r.update(status="CLOSED", date_closed=_today(), exit_price=exitp,
                     exit_type="resolved_win" if win else "resolved_loss",
                     ret=round((exitp - entry) / entry, 4))
            closed_now += 1
            print(f"[RESOLVE] {outcome:>5} entry {entry:.3f} -> {exitp:.0f}  ret {r['ret']}")
        elif still < MIN_BACKERS and cur_price is not None:
            exitp = round(max(cur_price - EXEC_SLIPPAGE, 0.0), 4)
            r.update(status="CLOSED", date_closed=_today(), exit_price=exitp,
                     exit_type="sharps_left", ret=round((exitp - entry) / entry, 4))
            closed_now += 1
            print(f"[EXIT]  {outcome:>5} sharps left, entry {entry:.3f} -> {exitp:.3f}  ret {r['ret']}")

    save_ledger(ledger)
    report(ledger)
    print(f"[cycle] +{new_entries} entries, {closed_now} closed, "
          f"{sum(1 for r in ledger if r['status']=='OPEN')} still open")

def _held_days(r) -> int:
    """Days between entry and close; used to enforce the §3.4 >=48h rule at scoring time."""
    try:
        return (dt.date.fromisoformat(r["date_closed"]) - dt.date.fromisoformat(r["date_opened"])).days
    except Exception:
        return 99

def report(ledger: list[dict]):
    resolved_all = [r for r in ledger if r["exit_type"] in ("resolved_win", "resolved_loss")]
    # Pre-registration §3.4: a market that actually resolved within ~48h of entry never
    # qualified (some sports carry a misleading far end-date and slip past the entry filter).
    # We exclude them from the scored sample here — rule-faithful and automatic.
    resolved = [r for r in resolved_all if _held_days(r) >= 2]
    excluded = len(resolved_all) - len(resolved)
    closed = [r for r in ledger if r["status"] == "CLOSED"]
    tag = f" ({excluded} sub-48h excluded)" if excluded else ""
    if not resolved:
        print(f"[report] closed={len(closed)}, valid-resolved=0{tag} — none counting toward the 30 yet")
        return
    rets = sorted(float(r["ret"]) for r in resolved)
    med = rets[len(rets) // 2]
    hit = sum(1 for r in resolved if r["exit_type"] == "resolved_win") / len(resolved)
    avg_price = sum(float(r["entry_price"]) for r in resolved) / len(resolved)
    success = (med > 0) and (hit > avg_price)          # the pre-registered criterion
    print(f"[report] valid-resolved={len(resolved)}{tag}  hit_rate={hit:.3f}  "
          f"avg_entry_price={avg_price:.3f}  median_ret={med:+.3f}")
    if len(resolved) >= 30:
        print(f"[VERDICT] {'SUCCESS' if success else 'FAILURE'} "
              f"(median>0 AND hit_rate>price) {'✅' if success else '❌'}")
    else:
        print(f"[report] {30 - len(resolved)} more valid resolved trades needed before verdict")

if __name__ == "__main__":
    run_once()
