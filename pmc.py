"""
pmc.py — Polymarket Consensus: shared client + config.

Read-only data layer for the smart-money consensus engine described in the
Strategy Blueprint. NO trade execution lives here by design (see Blueprint §11).

All endpoints are public (no auth needed for reads). If an endpoint path or
parameter name has changed on Polymarket's side, adjust it in ONE place here.

Tested against the documented Data API / Gamma API surfaces (June 2026).
Because Polymarket occasionally renames endpoints, run the smoke test in
01_fetch.ipynb first and fix any base URL / path here if a call 404s.
"""

from __future__ import annotations
import time, json, os, math
from dataclasses import dataclass, field, asdict
from pathlib import Path
import requests

# --------------------------------------------------------------------------
# CONFIG — every tunable threshold from the Blueprint lives here.
# Change numbers here, never in the notebooks.
# --------------------------------------------------------------------------

@dataclass
class Config:
    # --- hosts -------------------------------------------------------------
    DATA_API: str = "https://data-api.polymarket.com"
    GAMMA_API: str = "https://gamma-api.polymarket.com"
    CLOB_API: str = "https://clob.polymarket.com"
    # Official 2026 leaderboard endpoint (the old lb-api host is dead).
    LEADERBOARD_URL: str = "https://data-api.polymarket.com/v1/leaderboard"
    LEADERBOARD_CATEGORY: str = "OVERALL"   # OVERALL|POLITICS|SPORTS|CRYPTO|...

    # --- universe (Blueprint §2) ------------------------------------------
    # Windows must be one of: DAY, WEEK, MONTH, ALL  (union of proven + active)
    LEADERBOARD_WINDOWS: tuple = ("ALL", "MONTH")
    LEADERBOARD_TOP_N: int = 150                    # candidates per window (paginated, 50/page)

    # --- skill gate (Blueprint §3) ----------------------------------------
    MIN_RESOLVED_TRADES: int = 75
    MIN_LIFETIME_PNL: float = 20_000.0
    MIN_WIN_RATE: float = 0.55
    MIN_ROI: float = 0.04            # +4% on volume
    ACTIVE_WITHIN_DAYS: int = 30
    MAX_SINGLE_TRADE_PROFIT_SHARE: float = 0.40   # consistency check
    MARKET_MAKER_POSITION_COUNT: int = 400        # exclude above this (heuristic)
    TARGET_ROSTER_SIZE: int = 60

    # --- consensus (Blueprint §4) -----------------------------------------
    CONVICTION_CAP: float = 0.20          # cap position/portfolio weight
    INDEPENDENCE_FLOOR: float = 0.30      # min weight for clustered wallets
    MIN_INDEPENDENT_BACKERS: int = 3      # 4+ independent sharps on one market is rare; start at 3
    MAX_DISSENTERS: int = 1               # < 2 on opposite side
    CONSENSUS_SCORE_CUTOFF: float = 0.12  # starting point; calibrate via backtest
    # positions in markets this close to 0/1 are effectively resolved → ignore
    RESOLVED_PRICE_BAND: float = 0.03     # drop curPrice <= band or >= 1-band

    # --- price guard (Blueprint §5) ---------------------------------------
    SLIPPAGE_TOLERANCE: float = 0.06
    PRICE_CEILING: float = 0.90
    PRICE_FLOOR: float = 0.10

    # --- market filters (Blueprint §4) ------------------------------------
    MIN_MARKET_LIQUIDITY: float = 5_000.0   # USDC depth proxy
    MIN_HOURS_TO_RESOLUTION: int = 48

    # --- walk-forward backtest (notebook 06) ------------------------------
    WF_CANDIDATES: int = 150              # candidate pool from current leaderboard
    WF_LOOKBACK_MONTHS: int = 12          # how far back the walk-forward runs
    WF_REBALANCE_MONTHS: int = 3          # re-rank the roster every N months
    WF_MIN_TRAILING_TRADES: int = 30      # min resolved bets BEFORE T to be eligible
    WF_MIN_TRAILING_WINRATE: float = 0.55 # trailing win-rate gate at each rebalance
    WF_ROSTER_SIZE: int = 50              # PIT roster size each rebalance
    WF_USE_PRICE_HISTORY: bool = True     # True = realistic price at T; False = sharps' entry (faster)
    PRICE_HISTORY_TTL_S: int = 60 * 60 * 24 * 30  # historical prices are immutable → cache 30d

    # --- lagged mirror backtest (notebook 09) -----------------------------
    COPY_LAG_HOURS: int = 6               # how long after a sharp's action we manage to copy it
    MIRROR_SAMPLE: int = 600             # positions to sample for the (heavy) lagged sim

    # --- fresh-entry detection (the flow engine, notebook 04) -------------
    # The edge is in copying sharps WHEN they enter, before the price moves.
    ENTRY_LOOKBACK_HOURS: int = 72        # only consider entries opened this recently
    MIN_FRESH_BACKERS: int = 2            # distinct sharps entering same side in the window
    FRESH_SCORE_CUTOFF: float = 0.80      # sum of backer skill scores (≈ 2 mid-skill sharps)
    MIN_TRADE_USDC: float = 500.0         # ignore dust trades below this notional

    # --- sizing (Blueprint §8, "Balanced") --------------------------------
    BANKROLL: float = 5_000.0          # EDIT to your real bankroll
    KELLY_FRACTION: float = 0.25       # quarter-Kelly
    BASE_SIZE_PCT: float = 0.02
    MAX_SIZE_PCT_PER_MARKET: float = 0.05
    MAX_TOTAL_DEPLOYED_PCT: float = 0.60
    MAX_PER_CATEGORY_PCT: float = 0.25

    # --- infra ------------------------------------------------------------
    REQUEST_DELAY_S: float = 1.0       # be polite, ~1 req/sec
    MAX_RETRIES: int = 3
    CACHE_DIR: str = ".pmc_cache"
    CACHE_TTL_S: int = 60 * 60         # 1h for open positions

CFG = Config()

# --------------------------------------------------------------------------
# HTTP layer — caching + retries (Blueprint §2 "be polite")
# --------------------------------------------------------------------------

_session = requests.Session()
_session.headers.update({"User-Agent": "pmc-consensus/0.1 (research)"})

def _cache_path(key: str) -> Path:
    d = Path(CFG.CACHE_DIR); d.mkdir(exist_ok=True)
    safe = "".join(c if c.isalnum() else "_" for c in key)[:180]
    return d / f"{safe}.json"

def _get(url: str, params: dict | None = None, cache_ttl: int | None = None):
    """GET with retry + optional on-disk caching. Returns parsed JSON or None."""
    key = url + "?" + "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
    cp = _cache_path(key)
    if cache_ttl and cp.exists() and (time.time() - cp.stat().st_mtime) < cache_ttl:
        try:
            return json.loads(cp.read_text())
        except Exception:
            pass
    last = None
    for attempt in range(CFG.MAX_RETRIES):
        try:
            r = _session.get(url, params=params, timeout=30)
            if r.status_code == 429:           # rate limited
                time.sleep(2 * (attempt + 1)); continue
            r.raise_for_status()
            data = r.json()
            if cache_ttl:
                cp.write_text(json.dumps(data))
            time.sleep(CFG.REQUEST_DELAY_S)
            return data
        except Exception as e:                 # noqa
            last = e
            time.sleep(1.5 * (attempt + 1))
    print(f"[warn] GET failed after retries: {url} params={params} err={last}")
    return None

# --------------------------------------------------------------------------
# DATA API wrappers
# --------------------------------------------------------------------------

_LB_WINDOWS = {"DAY", "WEEK", "MONTH", "ALL"}

def get_leaderboard(window: str = "ALL", limit: int = 100) -> list[dict]:
    """
    Candidate wallets ranked by PnL via the official /v1/leaderboard endpoint.
    Returns list of dicts {wallet, user, pnl, vol}.

    The API caps `limit` at 50 per call, so we paginate with `offset` until we
    have `limit` rows. Params: category, timePeriod, orderBy=PNL (all uppercase).
    """
    win = window.upper()
    if win not in _LB_WINDOWS:
        win = "ALL"
    out, offset, PAGE = [], 0, 50
    while len(out) < limit:
        page = _get(CFG.LEADERBOARD_URL, {
            "category": CFG.LEADERBOARD_CATEGORY,
            "timePeriod": win,
            "orderBy": "PNL",
            "limit": min(PAGE, limit - len(out)),
            "offset": offset,
        }, cache_ttl=CFG.CACHE_TTL_S)
        rows = page if isinstance(page, list) else (page or {}).get("data", [])
        if not rows:
            break
        for x in rows:
            w = (x.get("proxyWallet") or x.get("wallet") or x.get("address") or "").lower()
            if w:
                out.append({
                    "wallet": w,
                    "user": x.get("userName") or x.get("name") or "",
                    "pnl": float(x.get("pnl") or 0),
                    "vol": float(x.get("vol") or 0),
                })
        offset += PAGE
        if len(rows) < PAGE:   # last page
            break
    return out

def get_open_positions(wallet: str, limit: int = 500) -> list[dict]:
    """Current open positions for a wallet (Blueprint §2)."""
    data = _get(f"{CFG.DATA_API}/positions",
                {"user": wallet, "limit": limit, "sizeThreshold": 1},
                cache_ttl=CFG.CACHE_TTL_S)
    return data if isinstance(data, list) else (data or {}).get("data", []) or []

def get_closed_positions(wallet: str, max_positions: int = 300) -> list[dict]:
    """
    Resolved positions for a wallet → used to score skill ourselves (§3).
    Endpoint: /closed-positions. The API caps `limit` at 50, so we paginate
    with `offset` until we run out or hit max_positions.

    IMPORTANT: we sort by TIMESTAMP (most recent first), NOT by realized PnL.
    Sorting by PnL would only ever return a wallet's winners for heavy traders
    (>max_positions resolved trades), inflating win-rate/ROI to ~100%. A recent
    chronological sample is an unbiased estimate of current skill.
    Fields: realizedPnl, totalBought, avgPrice, curPrice, timestamp, outcome, title.
    """
    out, offset, PAGE = [], 0, 50
    while len(out) < max_positions:
        page = _get(f"{CFG.DATA_API}/closed-positions", {
            "user": wallet, "limit": PAGE, "offset": offset,
            "sortBy": "TIMESTAMP", "sortDirection": "DESC",
        }, cache_ttl=CFG.CACHE_TTL_S)
        rows = page if isinstance(page, list) else (page or {}).get("data", [])
        if not rows:
            break
        out.extend(rows)
        offset += PAGE
        if len(rows) < PAGE:
            break
    return out

def get_recent_buys(wallet: str, since_ts: int, max_rows: int = 1500) -> list[dict]:
    """
    Recent BUY trades for a wallet via /activity (type=TRADE, side=BUY), newest
    first, back to `since_ts` (unix seconds). This is the flow signal: it tells
    us WHEN a sharp opened/added a position, with the price they paid.
    Fields per row: timestamp, conditionId, asset, outcome, outcomeIndex,
    price, size, usdcSize, side, title, slug.
    """
    out, offset, PAGE = [], 0, 500
    while len(out) < max_rows:
        page = _get(f"{CFG.DATA_API}/activity", {
            "user": wallet, "type": "TRADE", "side": "BUY",
            "start": since_ts, "sortBy": "TIMESTAMP", "sortDirection": "DESC",
            "limit": PAGE, "offset": offset,
        }, cache_ttl=CFG.CACHE_TTL_S)
        rows = page if isinstance(page, list) else (page or {}).get("data", [])
        if not rows:
            break
        # keep only rows in-window (defensive; the API should already filter by start)
        rows = [r for r in rows if float(r.get("timestamp") or 0) >= since_ts]
        out.extend(rows)
        if len(rows) < PAGE:
            break
        offset += PAGE
    return out

def get_user_trades(wallet: str, start_ts: int = 0, max_rows: int = 3000,
                    markets: list[str] | None = None) -> list[dict]:
    """
    A wallet's TRADE activity (both BUY and SELL) via /activity.
    Fields per row: side, timestamp, conditionId, asset, outcome, price, size, usdcSize.

    If `markets` (a list of conditionIds) is given, results are filtered to just those
    markets — this is the reliable way to get the exact trades for a specific position,
    with ~100% coverage and no pagination-ceiling issues. Without it, we page newest-first
    (so recent positions are covered before the offset ceiling truncates old history).
    """
    base = {"user": wallet, "type": "TRADE", "start": start_ts,
            "sortBy": "TIMESTAMP", "sortDirection": "DESC"}
    if markets:
        base["market"] = ",".join(markets)
    out, offset, PAGE = [], 0, 500
    while len(out) < max_rows:
        page = _get(f"{CFG.DATA_API}/activity", {**base, "limit": PAGE, "offset": offset},
                    cache_ttl=CFG.CACHE_TTL_S)
        rows = page if isinstance(page, list) else (page or {}).get("data", [])
        if not rows:
            break
        out.extend(rows)
        if len(rows) < PAGE or offset >= 3000:   # offset ceiling on /activity
            break
        offset += PAGE
    return out

def get_market(condition_id: str) -> dict | None:
    """Market metadata via Gamma (liquidity, end date, category)."""
    data = _get(f"{CFG.GAMMA_API}/markets", {"condition_ids": condition_id})
    rows = data if isinstance(data, list) else (data or {}).get("data", [])
    return rows[0] if rows else None

def get_price_history(asset_id: str, start_ts: int | None = None,
                      end_ts: int | None = None, fidelity: int = 60) -> list[dict]:
    """
    Historical price series for an outcome TOKEN (asset id, not conditionId).
    Endpoint: CLOB /prices-history → {"history": [{"t": unix, "p": price}, ...]}.
    `fidelity` is the bucket size in minutes (60 = hourly). Cached 30 days
    (historical prices never change).
    """
    params = {"market": asset_id, "fidelity": fidelity}
    if start_ts is not None:
        params["startTs"] = int(start_ts)
    if end_ts is not None:
        params["endTs"] = int(end_ts)
    data = _get(f"{CFG.CLOB_API}/prices-history", params, cache_ttl=CFG.PRICE_HISTORY_TTL_S)
    if not data:
        return []
    return data.get("history", []) if isinstance(data, dict) else (data or [])

def price_at(asset_id: str, ts: int, window_days: int = 14) -> float | None:
    """
    The token's price as of unix time `ts` — the realistic price you'd have paid
    entering then. Returns the most recent print at or before `ts`; if none in
    the window, the nearest available print. None if no data.
    """
    hist = get_price_history(asset_id, ts - window_days * 86400, ts + 86400, fidelity=60)
    if not hist:
        return None
    before = [h for h in hist if float(h.get("t", 0)) <= ts]
    if before:
        return float(max(before, key=lambda h: h["t"])["p"])
    nearest = min(hist, key=lambda h: abs(float(h.get("t", 0)) - ts))
    return float(nearest.get("p")) if nearest.get("p") is not None else None

def get_top_holders(condition_id: str) -> list[dict]:
    """Backup universe source: top holders of a given market (always public)."""
    data = _get(f"{CFG.DATA_API}/holders", {"market": condition_id})
    return data if isinstance(data, list) else (data or {}).get("data", [])

# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def portfolio_value(positions: list[dict]) -> float:
    """Sum currentValue across a wallet's open positions (for conviction)."""
    tot = 0.0
    for p in positions:
        tot += float(p.get("currentValue") or p.get("current_value") or 0)
    return tot

def kelly_fraction(p: float, c: float) -> float:
    """f* = (p - c) / (1 - c), clamped to [0, 1]. Blueprint §8."""
    if c >= 1 or c <= 0:
        return 0.0
    f = (p - c) / (1 - c)
    return max(0.0, min(1.0, f))

def position_size_eur(p_est: float, price: float, score: float, cutoff: float,
                      cfg: Config = CFG) -> float:
    """Balanced sizing: min(¼-Kelly, hard cap), scaled by consensus strength."""
    kelly = kelly_fraction(p_est, price) * cfg.KELLY_FRACTION
    scaled_base = cfg.BASE_SIZE_PCT * min(2.0, max(1.0, score / cutoff))
    frac = min(kelly if kelly > 0 else scaled_base, cfg.MAX_SIZE_PCT_PER_MARKET)
    return round(frac * cfg.BANKROLL, 2)

if __name__ == "__main__":
    print("pmc config loaded. Bankroll:", CFG.BANKROLL, "Kelly fraction:", CFG.KELLY_FRACTION)
