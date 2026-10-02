"""Per-wallet 90-day metrics, trading-style classification and scores.

PnL attribution (all figures in USDC):

* realized_90d   - realized PnL of positions *closed* inside the window
                   (``/closed-positions`` with timestamp in window) plus resolved
                   but unredeemed positions from ``/positions`` whose market end
                   date falls inside the window.
* upnl_window    - unrealized PnL of still-open positions the wallet bought into
                   during the window (positions untouched since before the window
                   are excluded because their PnL accrued outside it).
* pnl_90d        - realized_90d + upnl_window (the headline ranking number).
* net_cash_90d   - pure cash-flow lens from the activity ledger: sells + redeems +
                   merges + rewards - buys - splits. Ignores holdings, so it is a
                   cross-check rather than a PnL.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

DAY = 86400
REWARD_TYPES = {"REWARD", "MAKER_REBATE", "TAKER_REBATE", "REFERRAL_REWARD", "YIELD"}
SCRATCH_USD = 0.5  # |pnl| below this counts as neither win nor loss
PRICE_BINS = 10

STYLES = ["Market Maker", "Whale", "Favorite Grinder", "Longshot Hunter", "Swing Trader",
          "Specialist", "Generalist", "Inactive"]

STYLE_BLURBS = {
    "Market Maker": "Very high trade frequency and/or quoting both sides of the same markets.",
    "Whale": "Few, very large positions (median trade >= $5k).",
    "Favorite Grinder": "Most buy volume at >= 85c - collects small edges on near-certain outcomes.",
    "Longshot Hunter": "Large share of buy volume at <= 20c - asymmetric bets on underdogs.",
    "Swing Trader": "Sells most of what it buys before resolution; trades price moves, not outcomes.",
    "Specialist": ">= 70% of buy volume in a single category.",
    "Generalist": "No dominant pattern - diversified across prices and categories.",
    "Inactive": "No trades inside the window.",
}


def parse_end_date(s: Any) -> Optional[int]:
    if not s:
        return None
    s = str(s).strip()
    try:
        if len(s) == 10:
            dt = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except ValueError:
        return None


def clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _pct(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = clip(q, 0, 1) * (len(s) - 1)
    lo, hi = int(math.floor(idx)), int(math.ceil(idx))
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


def _r(x: Optional[float], nd: int = 2) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, float) and (math.isinf(x) or math.isnan(x)):
        return None
    return round(x, nd)


def max_drawdown(curve: List[float]) -> tuple:
    """(absolute drawdown, drawdown relative to the running peak) for a cumulative curve from 0."""
    peak = 0.0
    mdd = 0.0
    rel = 0.0
    for v in curve:
        peak = max(peak, v)
        dd = peak - v
        if dd > mdd:
            mdd = dd
            rel = dd / peak if peak > 0 else 1.0
    return mdd, clip(rel)


def analyze_wallet(rec: dict, window_start: int, window_end: int,
                   categorize: Callable[[dict], str], universe_entry: Optional[dict] = None) -> Dict[str, Any]:
    markets: Dict[str, dict] = rec.get("markets") or {}
    entry = universe_entry or {}

    def mk(c: str) -> dict:
        return markets.get(c) or {"title": c[:10], "slug": "", "eventSlug": "", "outcomes": {}}

    def outcome_name(c: str, oi: int) -> str:
        return (mk(c).get("outcomes") or {}).get(str(oi), "") or ("Yes" if oi == 0 else "No" if oi == 1 else "")

    cat_of: Dict[str, str] = {}

    def cat(c: str) -> str:
        if c not in cat_of:
            cat_of[c] = categorize(mk(c))
        return cat_of[c]

    in_win = lambda t: window_start <= t <= window_end  # noqa: E731
    acts = [a for a in rec.get("activity") or [] if in_win(a["t"])]
    trades = [a for a in acts if a["ty"] == "TRADE"]
    buys = [a for a in trades if a["sd"] == "BUY"]
    sells = [a for a in trades if a["sd"] == "SELL"]

    # ---------------- cash-flow lens ----------------
    sums = defaultdict(float)
    for a in acts:
        if a["ty"] == "TRADE":
            sums["buy" if a["sd"] == "BUY" else "sell"] += a["u"]
        elif a["ty"] in REWARD_TYPES:
            sums["reward"] += a["u"]
        else:
            sums[a["ty"].lower()] += a["u"]
    buy_vol, sell_vol = sums["buy"], sums["sell"]
    net_cash = sell_vol + sums["redeem"] + sums["merge"] + sums["reward"] - buy_vol - sums["split"]

    first_buy: Dict[str, int] = {}
    bought_assets = set()
    for a in buys:
        bought_assets.add(a["a"])
        if a["a"] not in first_buy or a["t"] < first_buy[a["a"]]:
            first_buy[a["a"]] = a["t"]

    # ---------------- realized PnL in window ----------------
    realized: List[dict] = []
    seen = set()
    for c in rec.get("closed") or []:
        if not in_win(c["t"]):
            continue
        key = c["a"] or (c["c"], c["oi"])
        if key in seen:
            continue
        seen.add(key)
        realized.append({"a": c["a"], "c": c["c"], "oi": c["oi"], "pnl": c["pnl"],
                         "cost": c["tb"] * c["avg"], "t": c["t"], "avg": c["avg"], "src": "closed"})
    open_pos: List[dict] = []
    for p in rec.get("positions") or []:
        key = p["a"] or (p["c"], p["oi"])
        if p["red"]:
            end_t = parse_end_date(p["end"])
            if key in seen or end_t is None or not in_win(end_t):
                continue
            seen.add(key)
            cost = p["tb"] * p["avg"] if p["tb"] > 0 else p["iv"]
            realized.append({"a": p["a"], "c": p["c"], "oi": p["oi"], "pnl": p["cpnl"] + p["rpnl"],
                             "cost": cost, "t": end_t, "avg": p["avg"], "src": "resolved"})
        else:
            open_pos.append(p)

    pnls = [r["pnl"] for r in realized]
    wins = [x for x in pnls if x > SCRATCH_USD]
    losses = [x for x in pnls if x < -SCRATCH_USD]
    realized_pnl = sum(pnls)
    realized_cost = sum(r["cost"] for r in realized)
    gross_win, gross_loss = sum(wins), -sum(losses)
    n_decided = len(wins) + len(losses)
    win_rate = len(wins) / n_decided if n_decided else None
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (math.inf if gross_win > 0 else None)
    max_win = max(wins) if wins else 0.0
    concentration = max_win / gross_win if gross_win > 0 else None

    # ---------------- open positions ----------------
    window_open = [p for p in open_pos if p["a"] in bought_assets]
    upnl_window = sum(p["cpnl"] for p in window_open)
    upnl_all = sum(p["cpnl"] for p in open_pos)
    open_value = sum(p["cv"] for p in open_pos)
    pnl_90d = realized_pnl + upnl_window

    # Dependence on a single bet: what is left of pnl_90d without the best one?
    contributions = pnls + [p["cpnl"] for p in window_open]
    best_bet = max(contributions) if contributions else 0.0
    pnl_ex_best = pnl_90d - max(best_bet, 0.0)
    top_win_share = best_bet / pnl_90d if pnl_90d > 0 and best_bet > 0 else None

    # ---------------- time series ----------------
    n_days = max(1, int(math.ceil((window_end - window_start) / DAY)))
    daily = [0.0] * n_days
    for r in realized:
        daily[min(n_days - 1, max(0, (r["t"] - window_start) // DAY))] += r["pnl"]
    curve, acc = [], 0.0
    for d in daily:
        acc += d
        curve.append(acc)
    n_weeks = max(1, int(math.ceil(n_days / 7)))
    weekly = [sum(daily[i * 7:(i + 1) * 7]) for i in range(n_weeks)]
    active_weeks = [w for w in weekly if abs(w) > SCRATCH_USD]
    pct_up_weeks = (sum(1 for w in active_weeks if w > 0) / len(active_weeks)) if active_weeks else None
    sharpe = None
    if len(active_weeks) >= 4:
        sd = statistics.pstdev(weekly)
        if sd > 0:
            sharpe = statistics.mean(weekly) / sd * math.sqrt(52)
    mdd, rel_dd = max_drawdown(curve)

    # ---------------- behaviour ----------------
    sizes = [a["u"] for a in trades]
    trade_days = {a["t"] // DAY for a in trades}
    active_days = len(trade_days)
    markets_traded = {a["c"] for a in trades if a["c"]}
    events_traded = {mk(c).get("eventSlug") or c for c in markets_traded}

    price_hist = [0.0] * PRICE_BINS
    fav_vol = long_vol = wprice = 0.0
    for a in buys:
        price_hist[min(PRICE_BINS - 1, int(a["p"] * PRICE_BINS))] += a["u"]
        wprice += a["p"] * a["u"]
        if a["p"] >= 0.85:
            fav_vol += a["u"]
        if a["p"] <= 0.20:
            long_vol += a["u"]
    fav_share = fav_vol / buy_vol if buy_vol > 0 else 0.0
    long_share = long_vol / buy_vol if buy_vol > 0 else 0.0
    avg_buy_price = wprice / buy_vol if buy_vol > 0 else None

    sides_by_market: Dict[str, set] = defaultdict(set)
    for a in buys:
        if a["c"] and a["oi"] != 999:
            sides_by_market[a["c"]].add(a["oi"])
    two_sided = (sum(1 for s in sides_by_market.values() if len(s) > 1) / len(sides_by_market)
                 if sides_by_market else 0.0)
    sell_ratio = sell_vol / buy_vol if buy_vol > 0 else 0.0

    hours = [0] * 24
    weekdays = [0] * 7
    for a in trades:
        dt = datetime.fromtimestamp(a["t"], tz=timezone.utc)
        hours[dt.hour] += 1
        weekdays[dt.weekday()] += 1

    holds = [(r["t"] - first_buy[r["a"]]) / 3600 for r in realized
             if r["a"] in first_buy and r["t"] >= first_buy[r["a"]]]
    median_hold_h = statistics.median(holds) if holds else None

    cat_buy: Dict[str, float] = defaultdict(float)
    for a in buys:
        cat_buy[cat(a["c"])] += a["u"]
    cat_pnl: Dict[str, float] = defaultdict(float)
    cat_n: Counter = Counter()
    for r in realized:
        cat_pnl[cat(r["c"])] += r["pnl"]
        cat_n[cat(r["c"])] += 1
    top_cat, top_cat_share = None, 0.0
    if buy_vol > 0:
        top_cat, v = max(cat_buy.items(), key=lambda kv: kv[1])
        top_cat_share = v / buy_vol
    elif cat_n:
        top_cat = cat_n.most_common(1)[0][0]

    last_trade = max((a["t"] for a in trades), default=None)
    first_trade = min((a["t"] for a in trades), default=None)
    trades_per_day = len(trades) / active_days if active_days else 0.0

    m = {
        "n_trades": len(trades), "n_buys": len(buys), "n_sells": len(sells),
        "trades_per_day": trades_per_day, "active_days": active_days,
        "median_trade": statistics.median(sizes) if sizes else 0.0,
        "n_markets": len(markets_traded), "two_sided": two_sided, "sell_ratio": sell_ratio,
        "fav_share": fav_share, "long_share": long_share, "avg_buy_price": avg_buy_price,
        "median_hold_h": median_hold_h, "top_cat": top_cat, "top_cat_share": top_cat_share,
        "realized_pnl": realized_pnl, "pnl_90d": pnl_90d, "n_resolved": len(realized),
        "win_rate": win_rate, "profit_factor": profit_factor, "concentration": concentration,
        "top_win_share": top_win_share, "pnl_ex_best": pnl_ex_best, "n_contrib": len(contributions),
        "pct_up_weeks": pct_up_weeks, "rel_dd": rel_dd,
        "last_trade": last_trade, "window_end": window_end,
    }
    style, tags = classify_style(m)
    consistency = consistency_score(m)
    copy = copyability_score(m, style, consistency)

    def market_info(c: str, oi: int) -> dict:
        info = mk(c)
        return {"title": info.get("title") or c[:12], "outcome": outcome_name(c, oi),
                "eventSlug": info.get("eventSlug", ""), "category": cat(c)}

    top_realized = sorted(realized, key=lambda r: r["pnl"], reverse=True)
    best = [dict(market_info(r["c"], r["oi"]), pnl=_r(r["pnl"]), cost=_r(r["cost"]), avg=_r(r["avg"], 3),
                 t=r["t"]) for r in top_realized[:8] if r["pnl"] > 0]
    worst = [dict(market_info(r["c"], r["oi"]), pnl=_r(r["pnl"]), cost=_r(r["cost"]), avg=_r(r["avg"], 3),
                  t=r["t"]) for r in reversed(top_realized[-8:]) if r["pnl"] < 0]
    opens = sorted(open_pos, key=lambda p: p["cv"], reverse=True)
    open_rows = [dict(market_info(p["c"], p["oi"]), size=_r(p["sz"]), avg=_r(p["avg"], 3), cur=_r(p["cur"], 3),
                      value=_r(p["cv"]), upnl=_r(p["cpnl"]), end=p["end"][:10], in_window=p["a"] in bought_assets)
                 for p in opens]

    recent_cut = window_end - 3 * DAY
    recent = sorted((a for a in trades if a["t"] >= recent_cut), key=lambda a: a["u"], reverse=True)[:12]
    recent_rows = [dict(market_info(a["c"], a["oi"]), t=a["t"], side=a["sd"], price=_r(a["p"], 3),
                        usdc=_r(a["u"])) for a in sorted(recent, key=lambda a: a["t"], reverse=True)]

    boards = entry.get("boards") or {}
    profile = rec.get("profile") or {}
    name = entry.get("name") or profile.get("name") or profile.get("pseudonym") or ""
    summary = {
        "wallet": rec["wallet"],
        "name": name if name and name.lower() != rec["wallet"] else "",
        "x": entry.get("x") or "",
        "verified": bool(entry.get("verified")),
        "style": style, "tags": tags,
        "pnl_90d": _r(pnl_90d), "realized_90d": _r(realized_pnl), "upnl_window": _r(upnl_window),
        "upnl_all": _r(upnl_all), "open_value": _r(open_value), "n_open": len(open_pos),
        "net_cash_90d": _r(net_cash),
        "volume": _r(buy_vol + sell_vol), "buy_vol": _r(buy_vol), "sell_vol": _r(sell_vol),
        "redeemed": _r(sums["redeem"]), "rewards": _r(sums["reward"]),
        "roi": _r(realized_pnl / realized_cost, 4) if realized_cost > 0 else None,
        "n_resolved": len(realized), "wins": len(wins), "losses": len(losses),
        "win_rate": _r(win_rate, 4), "profit_factor": _r(min(profit_factor, 99.0), 2) if profit_factor else None,
        "avg_win": _r(gross_win / len(wins)) if wins else None,
        "avg_loss": _r(-gross_loss / len(losses)) if losses else None,
        "max_win": _r(max_win), "max_loss": _r(min(losses)) if losses else None,
        "concentration": _r(concentration, 4), "top_win_share": _r(top_win_share, 4),
        "pnl_ex_best": _r(pnl_ex_best),
        "pct_up_weeks": _r(pct_up_weeks, 4), "sharpe": _r(sharpe), "max_dd": _r(mdd), "rel_dd": _r(rel_dd, 4),
        "n_trades": len(trades), "active_days": active_days, "trades_per_day": _r(trades_per_day),
        "avg_trade": _r(statistics.mean(sizes)) if sizes else 0.0, "median_trade": _r(m["median_trade"]),
        "p90_trade": _r(_pct(sizes, 0.9)), "max_trade": _r(max(sizes)) if sizes else 0.0,
        "n_markets": len(markets_traded), "n_events": len(events_traded),
        "avg_buy_price": _r(avg_buy_price, 4), "fav_share": _r(fav_share, 4), "long_share": _r(long_share, 4),
        "two_sided": _r(two_sided, 4), "sell_ratio": _r(sell_ratio, 4),
        "median_hold_h": _r(median_hold_h, 1),
        "top_cat": top_cat, "top_cat_share": _r(top_cat_share, 4),
        "first_trade": first_trade, "last_trade": last_trade,
        "consistency": _r(consistency, 1), "copy_score": _r(copy, 1),
        "lb_month_pnl": _r(boards.get("OVERALL:MONTH:PNL", {}).get("pnl")),
        "lb_month_rank": boards.get("OVERALL:MONTH:PNL", {}).get("rank"),
        "lb_all_pnl": _r(boards.get("OVERALL:ALL:PNL", {}).get("pnl")),
        "lb_all_rank": boards.get("OVERALL:ALL:PNL", {}).get("rank"),
        "lb_boards": sorted(boards.keys()),
        "truncated": any((rec.get("truncated") or {}).values()),
    }
    detail = {
        "curve": [_r(x, 0) for x in curve],
        "weekly": [_r(x, 0) for x in weekly],
        "price_hist": [_r(x, 0) for x in price_hist],
        "hours": hours, "weekdays": weekdays,
        "cat_buy": {k: _r(v) for k, v in sorted(cat_buy.items(), key=lambda kv: -kv[1])},
        "cat_pnl": {k: _r(v) for k, v in sorted(cat_pnl.items(), key=lambda kv: -kv[1])},
        "best": best, "worst": worst, "open": open_rows[:12], "recent": recent_rows,
        "cash": {k: _r(v) for k, v in sums.items()},
        "boards": boards,
    }
    # Internal fields consumed by cross-wallet analysis, stripped before the report.
    internal = {"open_all": [dict(r, c=p["c"], oi=p["oi"], slug=mk(p["c"]).get("slug", ""))
                             for r, p in zip(open_rows, opens)],
                "markets_traded": sorted(markets_traded),
                "buys": [(a["t"], a["a"], a["c"], a["u"]) for a in buys],
                "trade_vol_by_market": _vol_by_market(trades), "cat_pnl_raw": dict(cat_pnl)}
    return {"summary": summary, "detail": detail, "internal": internal}


def _vol_by_market(trades: List[dict]) -> Dict[str, List[float]]:
    out: Dict[str, List[float]] = {}
    for a in trades:
        v = out.setdefault(a["c"], [0.0, 0.0])
        v[0 if a["sd"] == "BUY" else 1] += a["u"]
    return out


def classify_style(m: Dict[str, Any]) -> tuple:
    tags: List[str] = []
    if m["n_trades"] == 0:
        style = "Inactive"
    elif m["trades_per_day"] >= 80 or (m["two_sided"] >= 0.35 and m["n_trades"] >= 1500):
        style = "Market Maker"
    elif m["median_trade"] >= 5000 and m["n_markets"] <= 60:
        style = "Whale"
    elif m["fav_share"] >= 0.5:
        style = "Favorite Grinder"
    elif m["long_share"] >= 0.35:
        style = "Longshot Hunter"
    elif m["sell_ratio"] >= 0.5 and (m["median_hold_h"] is None or m["median_hold_h"] <= 72):
        style = "Swing Trader"
    elif m["top_cat_share"] >= 0.7:
        style = "Specialist"
    else:
        style = "Generalist"
    if m["top_cat"] and m["top_cat_share"] >= 0.6:
        tags.append(f"{m['top_cat']} focus")
    if m["pnl_90d"] > 0 and m["pnl_ex_best"] <= 0 and m["n_contrib"] >= 3:
        tags.append("One big hit")
    if m["median_hold_h"] is not None and m["median_hold_h"] < 2:
        tags.append("Scalper")
    if m["last_trade"] is not None and m["window_end"] - m["last_trade"] > 14 * DAY:
        tags.append("Gone quiet")
    if m["win_rate"] is not None and m["win_rate"] >= 0.7 and m["n_resolved"] >= 30:
        tags.append("High hit rate")
    return style, tags


def consistency_score(m: Dict[str, Any]) -> float:
    """0-100: how repeatable the wallet's 90-day result looks, not how big it is."""
    pw = m["pct_up_weeks"] or 0.0
    pf = m["profit_factor"]
    pf_s = 0.0 if not pf else (1.0 if math.isinf(pf) else clip(math.log(pf) / math.log(4)) if pf > 1 else 0.0)
    conc = 1.0 - clip(m["concentration"]) if m["concentration"] is not None else 0.0
    sample = clip(m["n_resolved"] / 60)
    dd = 1.0 - clip(m["rel_dd"])
    score = 100 * (0.30 * pw + 0.25 * pf_s + 0.20 * conc + 0.15 * sample + 0.10 * dd)
    if m["realized_pnl"] <= 0:
        score *= 0.5
    return score


def copyability_score(m: Dict[str, Any], style: str, consistency: float) -> float:
    """0-100: consistency discounted for traits a follower cannot realistically replicate."""
    mult = 1.0
    if style == "Market Maker":
        mult *= 0.25
    if m["median_hold_h"] is not None and m["median_hold_h"] < 2:
        mult *= 0.6
    if m["avg_buy_price"] is not None and m["avg_buy_price"] >= 0.93:
        mult *= 0.7
    if m["n_trades"] < 10:
        mult *= 0.5
    if m["last_trade"] is None or m["window_end"] - m["last_trade"] > 14 * DAY:
        mult *= 0.7
    if m["pnl_90d"] <= 0:
        mult *= 0.5
    return consistency * mult
