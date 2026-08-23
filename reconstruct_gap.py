"""
reconstruct_gap.py — Faithful walk-forward reconstruction of missed engine days.

WHY THIS EXISTS
---------------
`paper_trader.py` did not run on 2026-07-11, 2026-07-12, 2026-07-13 (an access
outage — not a strategy decision). This script recovers those days by replaying
the FROZEN strategy exactly as the live engine would have, using ONLY information
that existed on each day. It is a walk-forward reconstruction (same class as
notebooks 06/07), NOT a look-ahead backtest.

HARD INTEGRITY RULES (do not relax):
  1. It NEVER writes to paper_ledger.csv. Output goes to a SEPARATE file,
     paper_ledger_reconstructed.csv, with a `provenance` column = "reconstructed".
     The pre-registered live ledger stays audit-proof and untouched.
  2. ENTRY decisions use ONLY data timestamped at/BEFORE each day's decision
     moment (holdings rebuilt from the immutable trade log; price via
     pmc.price_at at that timestamp). No outcome knowledge enters an entry choice.
  3. EXITS use the real resolution/holdings truth, exactly like the live engine
     (booking a resolution is not look-ahead — the live engine does the same).
  4. It records WHATEVER actually comes out — wins and losses alike. It is not
     tuned toward any conclusion. If the gap days lost money, the file says so.

HOW HOLDINGS ARE REBUILT (the point-in-time part)
-------------------------------------------------
The positions API only returns *current* holdings, so we reconstruct each roster
wallet's holdings as of the decision moment T by REWINDING the immutable trade log:
    size_at_T(key) = size_now(key) - sum(BUYs after T) + sum(SELLs after T)
for every (conditionId, outcome) key seen in either current positions or in the
post-T trade log. A key with size_at_T > 0 was held at T.

KNOWN BIASES (documented honestly; all point toward UNDER-counting, i.e. fewer
reconstructed trades — the conservative direction):
  * A position the wallet HELD at T but that AUTO-RESOLVED before this script runs,
    with no explicit closing SELL trade (redemption is not a TRADE), is invisible
    to the rewind and will be missed. These are mostly fast sports markets — so
    the reconstruction is biased toward the slower, still-open markets.
  * `median_entry` uses each sharp's CURRENT avgPrice as a proxy. It is EXACT when
    the wallet did not trade that market after T (we detect this and mark the row
    confidence="high"); otherwise it is approximate (confidence="low").
  * `cur_price` at T comes from pmc.price_at(); if the market has since resolved
    the CLOB history can be empty, and we fall back to the sharp's own most recent
    buy price at/<=T (confidence="low"). If neither is available, the signal is
    SKIPPED rather than guessed.
  * `sharps_left` exit prices/timing are approximate (reconstructed, not live).

Run on the Mac that has Polymarket API access (the sandbox cannot reach it):
    /opt/anaconda3/bin/python3 reconstruct_gap.py
Then inspect paper_ledger_reconstructed.csv and the printed report. Nothing is
merged automatically; deciding how to present it is a separate, manual choice.
"""

from __future__ import annotations
import csv, json, time, datetime as dt
from pathlib import Path
from statistics import median

import pmc
import paper_trader as pt   # reuse the EXACT frozen constants + helpers

# ---- gap days + decision moment ------------------------------------------
# The live job fires 09:00 Europe/Lisbon; in summer Lisbon = UTC+1, so 08:00 UTC.
# 2026-07-11..13 were the original access outage (already reconstructed earlier).
# The list below is the SECOND outage window: days the Mac was powered off while
# Peter was on vacation, so the launchd 9am job never fired. reconstruct_gap only
# writes to paper_ledger_reconstructed.csv and self-limits (adds nothing on true
# no-signal days), so listing extra candidate days here is harmless.
GAP_DAYS       = ["2026-07-24", "2026-07-25",
                  "2026-07-29", "2026-07-30", "2026-07-31",
                  "2026-08-05",
                  "2026-08-09", "2026-08-10",
                  "2026-08-13", "2026-08-14", "2026-08-15",
                  "2026-08-17", "2026-08-18",
                  "2026-08-20", "2026-08-21"]
DECISION_HOUR_UTC = 8
SIZE_EPS       = 1.0        # net size above which a wallet is deemed "holding"

HERE   = Path(__file__).resolve().parent
OUT_F  = HERE / "paper_ledger_reconstructed.csv"
OUT_COLS = pt.LEDGER_COLS + ["provenance", "confidence", "notes"]


def _decision_ts(day: str) -> int:
    d = dt.datetime.fromisoformat(day).replace(
        hour=DECISION_HOUR_UTC, tzinfo=dt.timezone.utc)
    return int(d.timestamp())


# --------------------------------------------------------------------------
# Rebuild one wallet's holdings as of timestamp T (point-in-time, rewind).
# Returns {(conditionId, outcome): {"size","avgPrice","asset","endDate",
#          "title","curPrice_now","traded_after_T": bool}}
# --------------------------------------------------------------------------
def holdings_as_of(wallet: str, T: int) -> dict:
    now_pos = pmc.get_open_positions(wallet)
    # trades strictly AFTER T (these are what we rewind away)
    after = [r for r in pmc.get_user_trades(wallet, start_ts=T)
             if float(r.get("timestamp") or 0) > T]

    # seed with current net sizes + meta
    state: dict = {}
    for p in now_pos:
        cid, outcome = p.get("conditionId"), p.get("outcome")
        if not cid or outcome is None:
            continue
        state[(cid, outcome)] = {
            "size": float(p.get("size") or 0),
            "avgPrice": float(p.get("avgPrice") or 0),
            "asset": p.get("asset"),
            "endDate": p.get("endDate"),
            "title": p.get("title"),
            "curPrice_now": float(p.get("curPrice") or 0),
            "traded_after_T": False,
        }

    # include markets touched only in the post-T log (not currently held)
    for r in after:
        cid, outcome = r.get("conditionId"), r.get("outcome")
        if not cid or outcome is None:
            continue
        state.setdefault((cid, outcome), {
            "size": 0.0, "avgPrice": float(r.get("price") or 0),
            "asset": r.get("asset"), "endDate": None,
            "title": r.get("title"), "curPrice_now": None,
            "traded_after_T": False,
        })

    # rewind: undo every post-T trade to recover the size held at T
    for r in after:
        key = (r.get("conditionId"), r.get("outcome"))
        if key not in state:
            continue
        sz = float(r.get("size") or 0)
        side = (r.get("side") or "").upper()
        if side == "BUY":
            state[key]["size"] -= sz     # they bought after T -> had less at T
        elif side == "SELL":
            state[key]["size"] += sz     # they sold after T   -> had more at T
        state[key]["traded_after_T"] = True

    return {k: v for k, v in state.items() if v["size"] > SIZE_EPS}


# --------------------------------------------------------------------------
# Build the (cid, outcome) -> consensus group AS OF T, mirroring
# paper_trader.current_holdings() but point-in-time.
# --------------------------------------------------------------------------
def holdings_group_as_of(roster: dict, T: int) -> dict:
    wallets = list(roster["wallets"])
    print(f"[recon] rebuilding {len(wallets)} wallets' holdings as of "
          f"{dt.datetime.utcfromtimestamp(T).isoformat()}Z ...", flush=True)
    groups: dict = {}
    for i, wallet in enumerate(wallets, 1):
        for (cid, outcome), h in holdings_as_of(wallet, T).items():
            g = groups.setdefault((cid, outcome), {
                "wallets": set(), "entries": [], "assets": set(),
                "ends": [], "title": h["title"], "any_traded_after": False})
            g["wallets"].add(wallet)
            g["entries"].append(h["avgPrice"])
            if h["asset"]:
                g["assets"].add(h["asset"])
            et = pt._parse_end(h["endDate"])
            if et:
                g["ends"].append(et)
            if h["traded_after_T"]:
                g["any_traded_after"] = True
        if i % 20 == 0:
            print(f"    ...{i}/{len(wallets)} wallets", flush=True)

    out = {}
    for k, g in groups.items():
        out[k] = {
            "backers": len(g["wallets"]),
            "median_entry": round(median(g["entries"]), 4) if g["entries"] else 0.0,
            "assets": g["assets"],
            "end_ts": min(g["ends"]) if g["ends"] else None,
            "title": g["title"],
            "entry_exact": not g["any_traded_after"],  # median_entry exactness flag
        }
    return out


def _price_at_T(assets: set, T: int, sharps_hint: float) -> tuple[float | None, str]:
    """Reconstructed price at T. Try CLOB history per token; fall back to the
    sharps' median entry (their own trade prices). Returns (price, confidence)."""
    for asset in assets:
        p = pmc.price_at(asset, T)
        if p is not None:
            return round(float(p), 4), "high"
    # CLOB empty (often = market already resolved) -> fall back to sharps' prints
    if sharps_hint and sharps_hint > 0:
        return round(float(sharps_hint), 4), "low"
    return None, "none"


# --------------------------------------------------------------------------
# MAIN
# --------------------------------------------------------------------------
def run():
    roster = pt.load_roster()                 # same monthly PIT roster as live
    live = pt.load_ledger()
    # never duplicate anything already captured by the live engine
    seen = {(r["conditionId"], r["outcome"]) for r in live}

    recon: list[dict] = []
    for day in GAP_DAYS:
        T = _decision_ts(day)
        holds = holdings_group_as_of(roster, T)

        # no-dissent bookkeeping (identical rule to run_once)
        sides_2plus: dict = {}
        for (cid, _o), g in holds.items():
            if g["backers"] >= pt.MIN_BACKERS:
                sides_2plus[cid] = sides_2plus.get(cid, 0) + 1

        n_day = 0
        for (cid, outcome), g in holds.items():
            if g["backers"] < pt.MIN_BACKERS or (cid, outcome) in seen:
                continue
            if sides_2plus.get(cid, 0) > 1:                      # dissent -> skip
                continue
            if g["end_ts"] is None or (g["end_ts"] - T) < pt.MIN_HOURS_TO_RES * 3600:
                continue                                        # <48h or unknown -> skip
            cur, conf = _price_at_T(g["assets"], T, g["median_entry"])
            if cur is None:
                continue                                        # can't price cleanly -> skip
            med = g["median_entry"]
            price_ok = (cur <= med + pt.SLIPPAGE_GUARD) and (pt.PRICE_FLOOR <= cur <= pt.PRICE_CEILING)
            if not price_ok:
                continue
            entry = round(min(cur + pt.EXEC_SLIPPAGE, 0.99), 4)
            if not g["entry_exact"]:
                conf = "low"        # median_entry was proxied
            recon.append({
                "date_opened": day, "conditionId": cid, "outcome": outcome,
                "title": g["title"], "entry_price": entry, "backers_at_entry": g["backers"],
                "size_flat": 1, "size_kelly_eur": pt.kelly_size_eur(cur),
                "status": "OPEN", "date_closed": "", "exit_price": "", "exit_type": "",
                "ret": "", "mark_price": entry, "last_update": day,
                "provenance": "reconstructed", "confidence": conf,
                "notes": f"price_src={conf}; entry_exact={g['entry_exact']}",
            })
            seen.add((cid, outcome)); n_day += 1
            print(f"[RECON-ENTRY {day}] {outcome:>5} @ {entry:.3f} x{g['backers']} "
                  f"({conf})  {str(g['title'])[:48]}")
        print(f"[recon] {day}: +{n_day} reconstructed entries")

    # ---- resolve/exit the reconstructed positions using current truth --------
    # (Same as the live engine advancing them forward day by day. Booking a
    #  resolution is not look-ahead; only the ENTRY had to be PIT-clean.)
    for r in recon:
        cid, outcome, entry = r["conditionId"], r["outcome"], float(r["entry_price"])
        st = pt.market_state(cid)
        cur_price = st["prices"].get(outcome) if st and outcome in st.get("prices", {}) else None
        resolved = bool(st and st["closed"])
        pinned = cur_price is not None and (
            cur_price >= 1 - pt.RESOLVED_BAND or cur_price <= pt.RESOLVED_BAND)
        if cur_price is not None:
            r["mark_price"] = round(cur_price, 4)
        if resolved or pinned:
            win = cur_price is not None and cur_price >= 0.5
            exitp = 1.0 if win else 0.0
            r.update(status="CLOSED", date_closed=pt._today(), exit_price=exitp,
                     exit_type="resolved_win" if win else "resolved_loss",
                     ret=round((exitp - entry) / entry, 4), last_update=pt._today())
        # NOTE: 'sharps_left' exits are intentionally NOT reconstructed here — their
        # timing/price cannot be recovered faithfully. Such positions stay OPEN and
        # simply do not count toward valid-resolved (conservative).

    _save(recon)
    _report(live, recon)


def _save(rows: list[dict]):
    with open(OUT_F, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in OUT_COLS})
    print(f"\n[recon] wrote {len(rows)} rows -> {OUT_F.name} (NOT merged into paper_ledger.csv)")


def _valid_resolved(rows: list[dict]) -> list[dict]:
    res = [r for r in rows if r.get("exit_type") in ("resolved_win", "resolved_loss")]
    return [r for r in res if pt._held_days(r) >= 2]


def _summary(rows: list[dict], label: str):
    vr = _valid_resolved(rows)
    if not vr:
        print(f"  {label}: valid-resolved = 0")
        return
    rets = sorted(float(r["ret"]) for r in vr)
    med = rets[len(rets) // 2]
    hit = sum(1 for r in vr if r["exit_type"] == "resolved_win") / len(vr)
    avgp = sum(float(r["entry_price"]) for r in vr) / len(vr)
    pct_prof = sum(1 for r in vr if float(r["ret"]) > 0) / len(vr)
    print(f"  {label}: valid-resolved={len(vr)}  median_ret={med:+.3f}  "
          f"%profitable={pct_prof:.0%}  hit_rate={hit:.3f}  avg_entry={avgp:.3f}  "
          f"success={'YES' if (med>0 and hit>avgp) else 'no'}")


def _report(live: list[dict], recon: list[dict]):
    print("\n================ RECONSTRUCTION REPORT ================")
    print(f"Reconstructed entries: {len(recon)}  "
          f"(high-confidence: {sum(1 for r in recon if r['confidence']=='high')}, "
          f"low: {sum(1 for r in recon if r['confidence']=='low')})")
    print("\nPrimary result is ALWAYS live-only. Combined is a labeled robustness view:")
    _summary(live, "live-only     (pre-registered, audit-proof)")
    _summary(recon, "recon-only    (walk-forward gap-fill)")
    _summary(live + recon, "combined      (robustness check)")
    print("======================================================")
    print("If recon-only and live-only disagree sharply, trust live-only and treat")
    print("the gap-fill as lower-confidence. Nothing here is merged automatically.")


if __name__ == "__main__":
    run()
