# Pre-Registration — Polymarket Smart-Money Consensus, Forward Paper-Trade

**Author:** Peter (MSc Finance, Nova SBE) · **Frozen on:** 4 July 2026 · **Version:** 1.1 (locked 5 July 2026)

> This document freezes the strategy and the success criterion **before** any forward data is
> observed. Its purpose is to eliminate hindsight: no rule, threshold, or goalpost below may be
> changed once forward tracking begins. Any change voids the experiment and starts a new one.

---

## 1. Hypothesis

Copying point-in-time-qualified ("skilled") Polymarket traders — entering markets where **at
least two** of them independently hold the **same** outcome while the price is still near their
entry, and **exiting when they exit** — produces a positive, calibration-beating return on
markets that have **not yet resolved** as of the freeze date.

The in-sample backtest supports this (median realized ROI ≈ +6–22%, robust to a 12% latency
haircut; consensus effect permutation p = 0.0005; skill-filter random-roster p = 0.020; PBO =
0.00 across gate settings). The **one** risk no historical test can remove is survivorship of the
candidate pool. This forward test is designed to remove it.

## 2. Frozen universe & roster rule

- **Candidate pool:** Polymarket leaderboard, windows `ALL` and `MONTH`, ordered by PnL, top 150
  each (union).
- **Qualification gate (point-in-time):** a wallet qualifies if, using only its trades resolved
  **before** the evaluation date, it has **≥ 30 resolved trades** and a **trailing win-rate ≥ 0.55**.
- **Roster refresh:** re-ranked on the **1st of each month**, re-applying the gate. Mechanical, no
  human selection. (Continuous updating is intended; the *procedure* is frozen, not the list.)

## 3. Frozen signal — ENTRY

A `(market, outcome)` becomes an open paper position when **all** hold at detection time:

1. **≥ 2** qualified roster wallets currently hold that exact outcome (co-holding consensus).
2. `current_price ≤ median(their entry prices) + 0.06` (price guard — we can still get in near them).
3. `0.10 ≤ current_price ≤ 0.90` (avoid near-resolved and lottery longshots).
4. Market does not resolve within 48 hours.
5. **No dissent (added v1.1):** no *other* outcome of the same market has ≥ 2 qualified
   holders. The sharps must agree on **one** side; if they are split across sides, stand aside.
6. The market-outcome is not already open, or previously closed, in the ledger (no re-entry).

Entry is booked at the **current market price** at detection (plus modelled slippage), not the
sharps' original entry.

## 4. Frozen signal — EXIT

An open paper position is closed on the **first** of:

1. **Smart money leaves:** the number of qualified roster wallets still holding that outcome drops
   **below 2**. Exit at current price. (This is the copy-the-exit rule — the piece that carried the
   backtest edge.)
2. **Resolution:** the market resolves. Settle at 1 (if the outcome won) or 0 (if it lost).

No discretionary exits. No mid-trade re-sizing.

## 5. Frozen sizing (for the P&L ledger only)

Every trade is logged under **two** sizing conventions, so the result does not depend on one choice:
- **Flat:** 1 unit per trade (equal weight).
- **Quarter-Kelly:** `f = 0.25 × (p − c)/(1 − c)`, capped at 5% of a nominal €5,000 paper bankroll,
  where `c` = entry price and `p` = entry price + a small consensus-scaled margin.

Sizing affects the P&L view but **not** the primary success metric (which is per-trade, size-agnostic).

## 6. Frozen success criterion (pre-committed)

After **≥ 30 resolved** paper trades (evaluated no earlier than 4 weeks from the freeze date), the
strategy is declared:

- **SUCCESS** if, on the resolved paper trades: **median per-trade return > 0** **AND**
  **hit-rate > average entry price paid** (i.e. the trades won more often than the price implied).
- **FAILURE** otherwise.

If fewer than 30 trades have resolved at the 4-week mark, tracking continues unchanged until 30 are
reached; the criterion is not relaxed.

## 7. What will NOT be done (anti-overfitting commitments)

- No changing any threshold, window, or rule above once tracking starts.
- No adding, dropping, or swapping strategy tracks mid-experiment.
- No re-optimising on the forward data. Forward data is used **only** to evaluate the frozen rule.
- No moving the success bar, and no post-hoc "it would have worked if…" adjustments.

## 8. Acknowledged residual limitations

- **Survivorship (partial):** the candidate pool is *today's* leaderboard. Forward testing reframes
  this into the deployment-realistic question — "starting from today's best traders, does copying
  them from here on pay?" — but does not fully remove pool survivorship.
- **Skill-filter increment is modest:** random leaderboard wallets already showed positive median
  ROI (+0.023); the filter adds ~+0.04. A meaningful part of the raw edge is leaderboard membership.
- **PBO scope:** the 0.00 PBO covers the qualification-gate grid, not the entire strategy-family
  search across the project. Only forward data neutralises that fully.
- **Not investment advice; no real capital.** This is a research experiment. Trading eligibility
  under Polymarket's terms and local law is a separate prerequisite before any real deployment.

---

## 9. Amendment log

- **v1.1 (5 July 2026), before any valid forward data.** The first engine run (5 July) exposed two
  defects: (a) the code did not implement the §3.4 "≥48h to resolution" rule that v1.0 already
  specified, so it flooded with same-day sports micro-markets; (b) with no dissent rule it opened
  **both sides** of the same market (guaranteed loss). Both are corrected: §3.4 is now enforced in
  code, and the no-dissent rule §3.5 is added. Because these were fixed **before** any resolved
  trade could count, the v1.0 ledger is discarded and the forward experiment begins from the v1.1
  engine. No result has been observed; no goalpost has moved.

- **v1.2 (23 July 2026) — data-plumbing fix; NO frozen rule, threshold, window, or success bar
  changed (§§2–7 untouched).** A measurement defect was discovered in the market-state lookup, not
  in the strategy.

  *Defect.* Gamma's `/markets` endpoint returns only **active** markets by default, so a market
  **dropped out of the query the instant it resolved**. `market_state()` then returned `None`, the
  exit loop never observed `closed=true`, `cur_price` stayed `None`, and the trade **froze OPEN
  forever**. Critically the failure was **asymmetric and loss-biased**: a losing outcome pins to ~0
  quickly and was usually caught before it dropped out (recorded as `resolved_loss`), whereas a
  winning outcome was orphaned. The mid-July Polymarket API outages (see `DATA_OUTAGE.md`) widened
  the window in which resolutions were missed. Net effect: ~30 resolved trades — skewed toward
  winners — were silently never scored.

  *Impact on the interim read.* The 22 July interim figures (median ≈ −4%, hit-rate ≈ 46% on n≈26)
  were **biased downward** by this artifact, not by the strategy.

  *Fix (retrieval only).* `market_state()` now queries `closed=true` first (recovers resolved
  markets), then falls back to the plain query (still-open markets). No §2–§7 rule is altered. The
  daily engine self-heals going forward. Two read-only tools were added: `check_stuck.py` (flags
  orphaned rows) and `resolve_stuck.py` (retroactively closes them).

  *Back-fill & audit.* The 30 orphaned trades were closed using the **identical** resolution
  semantics as the frozen engine (settle 1/0; ≥48h scoring filter), applied to **all** of them —
  including the 11 losses — not selectively. Mapping was verified against raw Gamma `outcomePrices`
  on a spot sample. Every action is logged in `resolve_stuck_audit.csv`; the pre-fix ledger is
  preserved as `paper_ledger.bak.20260722-234529.csv`. Both pre- and post-fix ledgers are retained
  for independent re-derivation.

  *Post-fix state.* Scored sample n = 42 (`resolved_win/loss`, held ≥48h): median per-trade return
  ≈ +44%, hit-rate ≈ 74% (31/42), average entry price ≈ 0.54 → the §6 criterion (median > 0 **and**
  hit-rate > avg entry) is **met**, and n now exceeds the 30-trade threshold. This is disclosed as a
  correction required to measure the frozen rule **correctly**, not to improve its apparent
  performance; the verdict should be treated as **provisional** pending independent re-derivation
  from the audit trail.

- **v1.3 (23 July 2026) — pre-committed extension of the observation window; NO strategy rule or
  success bar changed.** The 30-resolved-trade threshold (§6) is already met, but the accrued sample
  is narrow: ~90% of scored trades are **sports** (chiefly tennis and the FIFA World Cup) resolving
  inside a single ~two-week window (5–25 July). The World Cup in particular is a plausible **outlier
  regime**, and the diversifying markets (politics, macro, crypto, geopolitics) are still open and
  resolve on far-later horizons. To test the frozen rule across **multiple regimes** rather than one
  tournament fortnight — and to avoid the mirror risk of *optional stopping* (choosing to continue
  because a passing result was seen) — the following extension is fixed **now, before any further
  data is evaluated**:

  1. **Single pre-committed evaluation point:** the **first engine run on or after 30 September
     2026**. No verdict is declared, and no stop/continue decision is taken, before that date,
     regardless of what interim numbers show.
  2. **Minimum sample:** ≥ **80** valid scored trades (`resolved_win/loss`, held ≥48h) by that date.
     If fewer than 80 have accrued, tracking continues unchanged until 80 are reached; the bar is not
     relaxed.
  3. **Pre-committed reporting:** the §6 criterion is reported (a) overall, (b) split **sports vs
     non-sports**, and (c) split **pre- vs post-v1.2-fix**, so a pass cannot rest on the single
     World Cup window alone. All three are reported whatever they show.
  4. Nothing else changes: §§2–7 remain frozen; the engine continues on the v1.1 strategy with the
     v1.2 measurement fix only.

  *Peter to confirm or adjust the 30 September date and the 80-trade minimum in point 1–2 now,
  while it is still ahead of the data; once later data is observed these values are locked.*

---

*Signed (frozen): v1.0 on 4 July 2026, v1.1 on 5 July 2026. The forward test runs on v1.1, with the
v1.2 data-plumbing correction (23 July 2026) affecting measurement only. Changes after this date are
recorded as new, dated versions and do not count toward the pre-registered test.*
