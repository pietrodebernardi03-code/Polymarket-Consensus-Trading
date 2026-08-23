# Continuation Prompt — Polymarket Smart-Money Consensus (read fully before acting)

You are continuing a quantitative-finance research project with **Peter** (MSc Finance, Nova School
of Business and Economics, Lisbon). This message is the complete history of the project so you
understand every decision and, critically, **do not re-introduce problems we already solved**. Read
all of it before doing anything. The project files live in the connected folder (`pmc.py`, notebooks
`01`–`11`, `paper_trader.py`, `PRE_REGISTRATION.md`, `paper_ledger.csv`, etc.); `HANDOFF.md`
summarises them.

## 0. How to work on this project
- **Be rigorous and brutally honest about statistical bias.** Peter explicitly values intellectual
  honesty over optimism. Every time a result looked good, our job was to try to break it. Keep doing
  that. Flag survivorship, look-ahead, multiple-comparisons, and small-sample issues proactively.
- **Report medians and % profitable, never just the mean.** Prediction-market returns are
  longshot-skewed; a positive mean can hide a −100% median.
- **The strategy is FROZEN** (see `PRE_REGISTRATION.md`, v1.1). Do not tune it. Genuinely new ideas
  become *new pre-registered forward tracks*, never in-sample optimisation of the frozen one.
- **Where the code runs:** everything live runs on Peter's Mac (Polymarket API + local files). Your
  sandbox generally **cannot reach Polymarket's API** and cannot reliably mount his iCloud folder.
  So: deliver code for him to run; use Read/Write/Edit/Grep on the host path for his folder; verify
  on-disk state by grepping the actual file (iCloud sync can lag).

## 1. The research question
Do the most profitable Polymarket traders carry information a follower can copy for profit? Original
idea (Peter's): scan the top traders, act only where several of them **agree** (consensus), to avoid
copying any single trader's mistakes.

## 2. The full journey (what we tried, learned, and why we pivoted)
1. **Blueprint + data layer.** Confirmed Polymarket exposes public, no-auth data (leaderboard,
   positions, closed positions, activity, prices, markets). Built `pmc.py` (shared client + all
   thresholds) and notebooks 01–04.
2. **Static consensus (nb03):** group roster traders' current holdings; enter where ≥N co-hold a
   side. Problem discovered: by the time consensus is *visible*, the price has already moved — you're
   late (market efficiency / latency).
3. **Fresh-entry engine (nb04):** only act when ≥2 sharps *just bought* the same side. Live result:
   **zero** overlap — across 27 vetted sharps over 72h, never did two land on the same side. Elite
   traders are diversified specialists; live consensus is structurally *rare*, not just hard to tune.
4. **In-sample backtest (nb05):** copying looked spectacular (+34% to +134% per bet, rising with
   backers). **Not trustworthy** — survivorship + look-ahead (we selected all-time winners then
   "discovered" they won).
5. **Walk-forward, point-in-time (nb06, nb07):** rank the roster using only bets resolved *before*
   each decision date; buy at the realistic price then. **Edge collapsed to ≈ 0** (even slightly
   negative), and consensus stopped helping. Copying *visible entries and holding to resolution* does
   not beat the market. The spectacular in-sample numbers were bias.
6. **Peter's key insight — copy the exits too.** We were only copying entries. Sharps make much of
   their money by *timing exits* (selling before resolution). 
   - **nb08 (mirror ceiling):** each position's actual `realizedPnl/totalBought` (entries AND exits
     included), point-in-time qualified. **Positive:** ~+11% (≥1 backer) to +21% (≥3), positive
     medians, 68–79% profitable, and **consensus helps**. This is the frictionless ceiling.
   - **nb09/nb10 (realistic lagged mirror):** model being a step behind as a **haircut** on both
     legs and sweep it. nb10 (the trustworthy version, ~86% coverage) shows median return **stays
     positive out to a 12% round-trip haircut** (≥2 backers ≈ +0.22→+0.32; 57–74% profitable).
7. **Overfitting suite (nb11), all favourable:**
   - Permutation test (consensus effect): observed gap **+0.122**, **p = 0.0005**.
   - Random-roster test (does the skill filter beat random leaderboard wallets?): qualified median
     **+0.063** vs random **+0.023**, **p = 0.020** (note: modest increment; a lot of raw return is
     just leaderboard membership = survivorship).
   - **PBO = 0.000** (López de Prado CSCV) across the qualification-gate grid.
8. **Forward paper-trade (current phase).** The one bias no historical test removes is
   candidate-pool **survivorship** (Polymarket has no historical leaderboard). So we pre-registered
   the frozen strategy and built `paper_trader.py` to trade it forward on paper, out-of-sample.

## 3. The frozen strategy (PRE_REGISTRATION.md v1.1)
- **Roster:** leaderboard ALL+MONTH, top 150 each; qualify point-in-time if ≥30 resolved trades and
  ≥55% trailing win-rate; **re-ranked monthly**.
- **Entry:** ≥2 qualified sharps co-hold the same outcome; current price ≤ their median entry +0.06;
  price in [0.10, 0.90]; ≥48h to resolution; sharps agree on ONE side (**no dissent**).
- **Exit:** when qualified holders drop below 2 (they left) OR the market resolves. Copying exits is
  the piece that carried the edge.
- **Sizing (ledger only):** flat 1u AND ¼-Kelly (5% cap, €5,000 nominal).
- **Success (pre-committed):** on ≥30 *valid* resolved trades (resolving ≥48h after entry),
  **median per-trade return > 0 AND hit-rate > average entry price paid.**

## 4. GOTCHAS ALREADY SOLVED — do not repeat these
**API specifics (all public, no auth; base fixes already in `pmc.py`):**
- Leaderboard: `GET https://data-api.polymarket.com/v1/leaderboard?category=OVERALL&timePeriod=ALL|MONTH&orderBy=PNL&limit(≤50)&offset`. The old `lb-api.polymarket.com` host is **dead**; `limit` max is **50**, so paginate.
- Open positions: `GET .../positions?user=&limit(≤500)&sizeThreshold`. Has `endDate`, `curPrice`, `avgPrice`, `realizedPnl`, `asset`, `conditionId`, `outcome`.
- Closed positions: `GET .../closed-positions?user=&limit(≤50)&offset&sortBy=TIMESTAMP`. **Sort by TIMESTAMP, not REALIZEDPNL** (see win-rate bug).
- Activity: `GET .../activity?user=&type=TRADE&side=&start=&sortBy=TIMESTAMP&limit(≤500)&market=<csv conditionIds>`. Offset ceiling ~3000 (400 above). **Filter by `market` for coverage.**
- Price history: `GET https://clob.polymarket.com/prices-history?market=<assetId>&fidelity=`. **Returns nothing for already-resolved/delisted markets** — don't rely on it for historical resolved-market prices.
- Gamma: `GET https://gamma-api.polymarket.com/markets?condition_ids=`. `outcomes`/`outcomePrices` are JSON strings; `closed` flag; sports sub-markets may carry a **far tournament endDate**.

**Bugs we already fixed (do not reintroduce):**
1. **Win-rate inflation** — sorting closed positions by `REALIZEDPNL` returned only winners for heavy
   traders → fake ~100% win rates. Fixed by sorting by `TIMESTAMP` (unbiased recent sample).
2. **Survivorship + look-ahead** — fixed with point-in-time roster ranking; residual pool
   survivorship remains and is what the forward test addresses.
3. **Longshot-mean mirage** — always report median and % profitable.
4. **Lagged-backtest coverage 83% missing** — CLOB price-history is empty for resolved markets;
   fixed by reconstructing entry/exit prices from the sharps' **own activity trade prices** (100%
   coverage) and modelling latency as a haircut.
5. **Activity coverage 12%** — pulling oldest-first hit the offset ceiling and missed recent
   positions; fixed with **market-filtered** activity pulls, **small chunks** (long multi-market URLs
   cause `408` timeouts — use ~1–3 conditionIds per request).
6. **Both-sides entries** — engine booked Yes AND No of one market (guaranteed loss); fixed with the
   **no-dissent** rule (skip a market if >1 outcome has ≥2 backers).
7. **Same-day sports flood** — missing/misleading `endDate` let sub-48h markets in; fixed by
   requiring ≥48h at entry AND, because some sports carry a far tournament `endDate`, **also excluding
   at scoring** any trade that in fact resolved <48h after entry (`_held_days >= 2`).

**Ops gotchas:**
- The `paper_ledger.csv` is **append-only with a `seen` guard** — re-running without deleting it
  keeps old rows. To reset, delete the file then re-run.
- iCloud can lag; if a change "didn't take", grep the on-disk file to confirm, and have Peter
  delete+rerun. The engine is scheduled via macOS **launchd** (daily 9am) using
  `/opt/anaconda3/bin/python3`.
- Your sandbox cannot reach Polymarket or reliably mount the folder — deliver code, don't try to run
  the live pipeline yourself.

## 5. Current status & the next deliverable
- Forward paper-trade is **live and automated**; `paper_ledger.csv` is accumulating (started
  2026-07-05; ~29–34 initial long-horizon positions; most resolve in weeks–months). Progress:
  `grep -c "resolved_" paper_ledger.csv`. The engine prints `[VERDICT]` at ≥30 valid resolved trades.
- **Next task:** when enough trades have resolved (≥15 for an interim draft, 30+ for final), write a
  **LaTeX research paper**: abstract; intro & hypothesis; related work / market efficiency; data &
  methodology (API, point-in-time design, bias controls); in-sample results (mirror + haircut sweep,
  `booktabs` tables + edge-vs-backers and calibration figures); robustness/overfitting (permutation,
  random-roster, PBO); forward out-of-sample results (the ledger); discussion; limitations
  (survivorship, researcher DoF, capacity); conclusion. Deliver `paper.tex` + `references.bib` and
  compile to PDF. Ask Peter for the author-line / affiliation framing (standalone working paper vs
  Master's submission) before finalising tone.

## 6. Caveats to preserve honestly in any write-up
Candidate-pool survivorship remains; the skill-filter increment is modest (+0.04 over a +0.023
random-leaderboard baseline); PBO=0 covers only the gate grid, not the whole strategy-family search;
no real capital and Polymarket eligibility under its terms/local law is a separate prerequisite.

---
*End of continuation prompt. Read the referenced files for detail; do not re-run solved analyses or
re-introduce fixed bugs.*
