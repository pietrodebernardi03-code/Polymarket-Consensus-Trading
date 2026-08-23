"""
segment_stats.py — read-only stratified performance report on paper_ledger.csv.

WHY
---
As of the v1.3 amendment the scored sample is ~90% sports concentrated in one ~two-week
window (Wimbledon + the FIFA World Cup). A single-number verdict can therefore be driven
by one regime. This script re-computes the pre-registered success criterion WITHIN strata
— by market category and by resolution month — so we can see whether the edge survives
outside the World Cup / tennis fortnight. It changes NOTHING; it only reads and summarises.

SCORED SAMPLE (matches paper_trader.report and PRE_REGISTRATION §6)
------------------------------------------------------------------
  exit_type in {resolved_win, resolved_loss} AND held >= 48h (date_closed - date_opened >= 2 days).
A broader lens including sharps_left exits is also printed for context.

CATEGORY CLASSIFIER
-------------------
Keyword-based and deliberately transparent: every trade is printed with the label it was
given (use --list) so the buckets can be audited and corrected by eye. Non-sports buckets
are matched first (so a football "X vs Y" title is not swallowed by a generic "vs" rule).

USAGE
-----
    python3 segment_stats.py            # stratified tables
    python3 segment_stats.py --list     # also dump every trade's assigned category
"""
from __future__ import annotations
import argparse, csv, datetime as dt, statistics as st
from pathlib import Path

LEDGER_F = Path(__file__).resolve().parent / "paper_ledger.csv"

# --- category keywords, checked in this order (first hit wins) ----------------
_RULES = [
    ("crypto",      ("bitcoin", "ethereum", " btc", " eth", "$")),
    ("macro",       ("fed ", "rate cut", "rate hike", " ipo", "interest rate")),
    ("politics",    ("senate", "house", "midterm", "primary", "president", "election",
                     "balance of power", "patel", "alito", "retirement", "nominee",
                     "newsom", "bolsonaro", "el-sayed", "governor", "parliamentary",
                     "seats", "democratic party", "republican party")),
    ("geopolitics", ("iran", "venezuela", "ukraine", "russia", "cuba", "hormuz",
                     "nuclear", "ceasefire", "blockade", "invade", "mou", "enrichment",
                     "trade deal", "delcy", "netanyahu", "uranium")),
    ("mma",         ("ufc", "middleweight")),
    ("football",    ("fifa", "world cup", "goalscorer", "mbappe", "win on 2026-",
                     "reach the", "semifinal", "end in a draw", "santos", "morocco",
                     "to advance", "draw?")),
    ("tennis",      ("wimbledon", " atp", " wta", " open:", "open ", "bastad", "trieste",
                     "braunschweig", "newport", "contrexeville", "cordenons", "iasi",
                     "granby", "winnipeg", "prague", "hamburg", "set handicap", "sinner",
                     "croatia", "swiss", "swedish")),
    ("baseball",    ("white sox", "guardians", "braves", "pirates", "nationals", "twins",
                     "red sox", "orioles", "kbo", "dinos", "tigers", "lions")),
]


def classify(title: str) -> str:
    t = (title or "").lower()
    for label, kws in _RULES:
        if any(k in t for k in kws):
            return label
    if " vs " in t or " vs. " in t or "win on" in t:
        return "sports-other"
    return "other"


def held(r) -> int:
    try:
        return (dt.date.fromisoformat(r["date_closed"]) - dt.date.fromisoformat(r["date_opened"])).days
    except Exception:
        return 99


def _month(r) -> str:
    return (r.get("date_closed") or "")[:7] or "—"


def stats(sample) -> dict | None:
    if not sample:
        return None
    rets = [float(r["ret"]) for r in sample]
    n = len(rets)
    med = st.median(rets)
    hit = sum(1 for x in rets if x > 0) / n
    avgp = sum(float(r["entry_price"]) for r in sample) / n
    return {"n": n, "median": med, "mean": sum(rets) / n, "hit": hit, "avg_entry": avgp,
            "success": (med > 0 and hit > avgp)}


def _row(label, s) -> str:
    if s is None:
        return f"  {label:<16} n=0"
    if s["n"] < 5:
        verdict = "small sample"
    else:
        verdict = "PASS ✅" if s["success"] else "FAIL ❌"
    return (f"  {label:<16} n={s['n']:<3} median={s['median']:+.3f}  hit={s['hit']:.2f}  "
            f"avg_entry={s['avg_entry']:.2f}  -> {verdict}")


def report(rows, show_list=False):
    scored = [r for r in rows if r["exit_type"] in ("resolved_win", "resolved_loss") and held(r) >= 2]
    broad  = [r for r in rows if r.get("ret") not in ("", None) and held(r) >= 2]

    for r in scored:
        r["_cat"] = classify(r["title"])

    print("=== SCORED sample (resolved_win/loss, held >=48h) — PRE_REGISTRATION §6 ===")
    print(_row("OVERALL", stats(scored)))

    print("\n-- by category --")
    cats = sorted({r["_cat"] for r in scored})
    for c in cats:
        print(_row(c, stats([r for r in scored if r["_cat"] == c])))

    # sports vs non-sports (the v1.3 pre-committed split)
    sports_set = {"tennis", "football", "baseball", "mma", "sports-other"}
    print("\n-- sports vs non-sports (v1.3 pre-committed split) --")
    print(_row("sports", stats([r for r in scored if r["_cat"] in sports_set])))
    print(_row("non-sports", stats([r for r in scored if r["_cat"] not in sports_set])))

    print("\n-- by resolution month --")
    for m in sorted({_month(r) for r in scored}):
        print(_row(m, stats([r for r in scored if _month(r) == m])))

    print("\n=== BROADER lens (incl. sharps_left exits, held >=48h) ===")
    print(_row("OVERALL", stats(broad)))

    if show_list:
        print("\n=== per-trade category assignment (audit) ===")
        for r in sorted(scored, key=lambda x: x["_cat"]):
            print(f"  {r['_cat']:<14} {float(r['ret']):+.3f}  {r['title'][:60]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", default=str(LEDGER_F))
    ap.add_argument("--list", action="store_true", help="dump each trade's assigned category")
    a = ap.parse_args()
    rows = list(csv.DictReader(open(a.ledger, newline="")))
    report(rows, a.list)


if __name__ == "__main__":
    main()
