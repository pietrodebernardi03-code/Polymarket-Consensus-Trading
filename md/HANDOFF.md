# Project Handoff — Polymarket Smart-Money Consensus

**Purpose of this file:** everything a fresh assistant needs to continue the project without the
prior chat history. Read this first, then the files it references.

**Author / context:** Peter, MSc Finance, Nova School of Business and Economics (Lisbon). This is a
personal quantitative-research project intended to end in a **publishable LaTeX paper**.

---

## 1. The question
Do the most profitable Polymarket traders carry information a follower can copy for profit? We test
copying **consensus** among vetted traders — and, crucially, copying their **exits** as well as
their entries.

## 2. What we found (the arc)
1. **Static consensus** (who currently holds what) is too *late* — price already reflects it.
2. **Fresh-entry consensus** (≥2 sharps buying the same side in a short window) is too *rare* —
   elite traders are diversified specialists, they barely overlap live.
3. **Backtests, entry-only, out-of-sample** (point-in-time roster, realistic prices): **edge ≈ 0**.
   Copying *visible entries and holding to resolution* does not beat the market. Consensus didn't
   help; survivorship + look-ahead had inflated the naive in-sample numbers.
4. **Adding exits changed the answer.** Mirroring entries **and** exits (each position's realised
   `realizedPnl/totalBought`) is **positive**: frictionless ceiling ≈ +11% (≥1 backer) to +21%
   (≥3), positive medians, ~68–79% profitable, and consensus *helps*.
5. **Latency stress-test** (notebook 10, ~86% coverage, haircut sweep): median return stays
   **positive out to a 12% round-trip haircut** (≥1: ~+0.11→+0.17; ≥2: ~+0.22→+0.32; % profitable
   57–74%). Robust to being a step behind.
6. **Overfitting suite (notebook 11), all favourable:**
   - Permutation test, consensus effect: observed gap **+0.122**, **p = 0.0005**.
   - Random-roster test (skill filter vs random leaderboard wallets): qualified median **+0.063**
     vs random **+0.023**, **p = 0.020**.
   - **PBO = 0.000** across the qualification-gate grid (López de Prado CSCV).

**Headline:** in-sample and robustness evidence support a *copy-with-exits, consensus-weighted*
edge. The one bias no historical test removes — **survivorship** of the candidate pool (today's
leaderboard) — is being resolved by a **forward paper-trade**, now running.

## 3. The frozen strategy (see PRE_REGISTRATION.md, v1.1)
- **Roster:** leaderboard ALL+MONTH, top 150 each; qualify point-in-time if ≥30 resolved trades and
  ≥55% trailing win-rate; re-ranked monthly.
- **Entry:** ≥2 qualified sharps co-hold the same outcome; current price ≤ their median entry +0.06;
  price in [0.10, 0.90]; ≥48h to resolution; the sharps agree on ONE side (no dissent).
- **Exit:** when qualified holders drop below 2 (they left) OR the market resolves. (Copying exits
  is the piece that carried the edge.)
- **Sizing (ledger only):** flat 1u AND ¼-Kelly (5% cap, €5,000 nominal).
- **Success (pre-committed):** on ≥30 *resolved* paper trades (resolving ≥48h after entry),
  **median per-trade return > 0 AND hit-rate > average entry price paid.**

## 4. Forward paper-trade status
- Engine: `paper_trader.py`, running daily via macOS launchd (9am). Read-only, no real money.
- Started 2026-07-05 with ~29–34 open positions (mostly long-horizon: crypto year-end, 2026/2028
  elections, World Cup winner, macro). Slow by design — many resolve in months.
- Progress check: `grep -c "resolved_" paper_ledger.csv`. Verdict prints automatically at ≥30
  valid resolved trades. Sub-48h resolutions are auto-excluded at scoring.

## 5. File inventory
- `pmc.py` — shared API client + all config/thresholds (edit endpoints/params here only).
- `01_fetch` … `04_fresh_entries` — data layer + live signal engines.
- `05_backtest` (in-sample), `06_walkforward`, `07_freshentry_walkforward` — entry-only backtests
  (showed ~0 out-of-sample edge).
- `08_mirror_ceiling` — exits-included ceiling (positive).
- `09_lagged_mirror`, `10_mirror_haircut` — realistic lagged mirror; **10 is the trustworthy one**
  (full coverage + haircut sweep).
- `11_overfitting_tests` — permutation, random-roster, PBO.
- `PRE_REGISTRATION.md` — frozen rules + success criterion (v1.1).
- `paper_trader.py`, `RUNBOOK.md`, `run.command`, `com.peter.polymarket-paper.plist` — the forward
  engine and its automation.
- `paper_ledger.csv` — the growing forward record (the out-of-sample dataset).
- The `.pdf` files are executed notebook runs (the actual result tables/figures).

## 6. The next deliverable (what to build next)
When enough trades have resolved (even 10–15 for an interim draft; 30+ for the final), write a
**LaTeX research paper**. Suggested structure:
1. Abstract · 2. Introduction & hypothesis · 3. Related work / market-efficiency framing ·
4. Data & methodology (Polymarket API; point-in-time design; survivorship & look-ahead controls) ·
5. In-sample results (mirror, haircut sweep — `booktabs` tables + edge-vs-backers and calibration
   figures) · 6. Robustness / overfitting (permutation, random-roster, PBO) · 7. Forward
   out-of-sample results (the paper_ledger) · 8. Discussion · 9. Limitations (survivorship,
   researcher DoF, capacity) · 10. Conclusion.
Deliver `paper.tex` + `references.bib`; compile to PDF. Ask Peter for the author line / affiliation
framing (standalone working paper vs Master's submission) before finalising tone.

## 7. Honest caveats to preserve in the paper
- Candidate-pool **survivorship** remains (no historical leaderboard available); forward test
  reframes it into the deployment-realistic question but doesn't fully remove it.
- The skill-filter increment is **modest** (+0.04 over a +0.023 random-leaderboard baseline) — a
  large part of raw return is leaderboard membership.
- PBO=0 covers the **gate grid**, not the whole strategy-family search; forward data closes that.
- No real capital; Polymarket eligibility under its terms and local law is a separate prerequisite.
