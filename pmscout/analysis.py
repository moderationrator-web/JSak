"""Turn raw per-wallet files into ``analysis.json``: per-wallet metrics plus
cross-wallet views (smart-money consensus, contested markets, market heat,
possibly-linked wallets, category leaders)."""

from __future__ import annotations

import bisect
import os
import statistics
import sys
from collections import Counter, defaultdict
from itertools import combinations
from typing import Any, Callable, Dict, List, Optional

from .api import Client
from .categorize import CATEGORIES, Categorizer, fetch_event_tags
from .collect import read_json, wallet_path, write_json
from .metrics import STYLE_BLURBS, STYLES, analyze_wallet

Log = Callable[[str], None]


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _label(s: dict) -> str:
    return s.get("name") or (s["wallet"][:6] + "…" + s["wallet"][-4:])


# --------------------------------------------------------------------------- #
# Cross-wallet views
# --------------------------------------------------------------------------- #

def consensus(results: List[dict], min_value: float = 100.0, min_wallets: int = 2,
              limit: int = 100) -> Dict[str, List[dict]]:
    """Open positions shared by several top wallets (market makers excluded)."""
    groups: Dict[tuple, dict] = {}
    by_market: Dict[str, Dict[int, dict]] = defaultdict(dict)
    for r in results:
        s = r["summary"]
        if s["style"] == "Market Maker":
            continue
        for p in r["internal"]["open_all"]:
            value = p["value"] or 0.0
            if value < min_value or not (0.02 <= (p["cur"] or 0) <= 0.98):
                continue
            key = (p["c"], p["oi"])
            g = groups.get(key)
            if g is None:
                g = groups[key] = {"c": p["c"], "oi": p["oi"], "title": p["title"], "outcome": p["outcome"],
                                   "slug": p["slug"], "eventSlug": p["eventSlug"], "category": p["category"],
                                   "end": p["end"], "cur": p["cur"], "holders": [], "_cost": 0.0, "_size": 0.0}
                by_market[p["c"]][p["oi"]] = g
            g["holders"].append({"wallet": s["wallet"], "name": _label(s), "value": p["value"],
                                 "avg": p["avg"], "upnl": p["upnl"], "rank": s.get("rank"),
                                 "pnl_90d": s["pnl_90d"], "consistency": s["consistency"],
                                 "in_window": p["in_window"]})
            g["_cost"] += (p["size"] or 0) * (p["avg"] or 0)
            g["_size"] += p["size"] or 0
    rows = []
    for g in groups.values():
        g["n_wallets"] = len(g["holders"])
        g["value"] = round(sum(h["value"] for h in g["holders"]), 2)
        g["avg_entry"] = round(g["_cost"] / g["_size"], 4) if g["_size"] else None
        g["edge"] = round(g["cur"] - g["avg_entry"], 4) if g["avg_entry"] is not None else None
        g["conviction"] = round(sum(h["value"] * (h["consistency"] or 0) / 100 for h in g["holders"]), 2)
        others = [o for oi, o in by_market[g["c"]].items() if oi != g["oi"]]
        g["against_n"] = sum(len(o["holders"]) for o in others)
        g["against_value"] = round(sum(h["value"] for o in others for h in o["holders"]), 2)
        g["holders"].sort(key=lambda h: -h["value"])
        rows.append(g)

    agreed = [g for g in rows if g["n_wallets"] >= min_wallets]
    agreed.sort(key=lambda g: (-g["n_wallets"], -g["conviction"], -g["value"]))

    contested = []
    for c, sides in by_market.items():
        if len(sides) < 2:
            continue
        ranked = sorted(sides.values(), key=lambda g: -g["value"])
        a, b = ranked[0], ranked[1]
        total = a["value"] + b["value"]
        if total <= 0 or b["value"] / total < 0.2:
            continue
        contested.append({"c": c, "title": a["title"], "slug": a["slug"], "eventSlug": a["eventSlug"],
                          "category": a["category"], "end": a["end"], "total": round(total, 2),
                          "sides": [{"outcome": g["outcome"], "cur": g["cur"], "n_wallets": g["n_wallets"],
                                     "value": g["value"], "avg_entry": g["avg_entry"],
                                     "holders": g["holders"][:6]} for g in (a, b)]})
    contested.sort(key=lambda x: -x["total"])
    for g in rows:  # trim only after every cross-group aggregate is computed
        g.pop("_cost"), g.pop("_size")
        g["holders"] = g["holders"][:12]
    return {"agreed": agreed[:limit], "contested": contested[:40]}


def market_heat(results: List[dict], market_meta: Dict[str, dict], limit: int = 50) -> List[dict]:
    agg: Dict[str, dict] = {}
    for r in results:
        for c, (b, s) in r["internal"]["trade_vol_by_market"].items():
            if not c:
                continue
            a = agg.setdefault(c, {"c": c, "n_wallets": 0, "buy": 0.0, "sell": 0.0})
            a["n_wallets"] += 1
            a["buy"] += b
            a["sell"] += s
    rows = sorted(agg.values(), key=lambda a: (-a["n_wallets"], -(a["buy"] + a["sell"])))[:limit]
    for a in rows:
        m = market_meta.get(a["c"], {})
        a.update(title=m.get("title") or a["c"][:12], slug=m.get("slug", ""), eventSlug=m.get("eventSlug", ""),
                 category=m.get("category", "Other"), buy=round(a["buy"], 2), sell=round(a["sell"], 2),
                 net=round(a["buy"] - a["sell"], 2))
    return rows


def linked_wallets(results: List[dict], min_markets: int = 15, popular_cap: int = 80,
                   min_shared: int = 10, min_jaccard: float = 0.3, window_s: int = 120,
                   limit: int = 30) -> List[dict]:
    """Pairs of wallets that trade unusually similar market sets, with how often
    they bought the same token within ``window_s`` seconds of each other."""
    sets = {r["summary"]["wallet"]: set(r["internal"]["markets_traded"]) for r in results}
    holders: Dict[str, List[str]] = defaultdict(list)
    for w, ms in sets.items():
        for c in ms:
            holders[c].append(w)
    popular = {c for c, ws in holders.items() if len(ws) > popular_cap}
    eff = {w: ms - popular for w, ms in sets.items()}
    eff = {w: ms for w, ms in eff.items() if len(ms) >= min_markets}
    shared: Counter = Counter()
    for c, ws in holders.items():
        if c in popular:
            continue
        ws = sorted(w for w in ws if w in eff)
        for a, b in combinations(ws, 2):
            shared[(a, b)] += 1
    by_wallet = {r["summary"]["wallet"]: r for r in results}
    pairs = []
    for (a, b), n in shared.items():
        if n < min_shared:
            continue
        j = n / (len(eff[a]) + len(eff[b]) - n)
        if j < min_jaccard:
            continue
        pairs.append((j, n, a, b))
    pairs.sort(reverse=True)
    out = []
    for j, n, a, b in pairs[:limit]:
        sa, sb = by_wallet[a]["summary"], by_wallet[b]["summary"]
        out.append({"a": a, "b": b, "a_name": _label(sa), "b_name": _label(sb),
                    "a_style": sa["style"], "b_style": sb["style"],
                    "a_pnl": sa["pnl_90d"], "b_pnl": sb["pnl_90d"], "shared": n, "jaccard": round(j, 3),
                    "co_entries": _co_entries(by_wallet[a]["internal"]["buys"],
                                              by_wallet[b]["internal"]["buys"], window_s)})
    return out


def _co_entries(buys_a: List[tuple], buys_b: List[tuple], window_s: int) -> int:
    times_b: Dict[str, List[int]] = defaultdict(list)
    for t, asset, _c, _u in buys_b:
        times_b[asset].append(t)
    for v in times_b.values():
        v.sort()
    n = 0
    for t, asset, _c, _u in buys_a:
        ts = times_b.get(asset)
        if not ts:
            continue
        i = bisect.bisect_left(ts, t - window_s)
        if i < len(ts) and ts[i] <= t + window_s:
            n += 1
    return n


def category_views(results: List[dict]) -> Dict[str, Any]:
    leaders: Dict[str, List[dict]] = {}
    totals: Dict[str, dict] = {c: {"category": c, "pnl": 0.0, "gain": 0.0, "loss": 0.0, "buy": 0.0, "wallets": 0}
                               for c in CATEGORIES}
    per_cat: Dict[str, List[tuple]] = defaultdict(list)
    for r in results:
        s = r["summary"]
        for c, v in r["internal"]["cat_pnl_raw"].items():
            t = totals.setdefault(c, {"category": c, "pnl": 0.0, "gain": 0.0, "loss": 0.0, "buy": 0.0, "wallets": 0})
            t["pnl"] += v
            t["gain" if v > 0 else "loss"] += v
            per_cat[c].append((v, s))
        for c, v in r["detail"]["cat_buy"].items():
            t = totals.setdefault(c, {"category": c, "pnl": 0.0, "gain": 0.0, "loss": 0.0, "buy": 0.0, "wallets": 0})
            t["buy"] += v or 0
            t["wallets"] += 1
    for c, rows in per_cat.items():
        rows.sort(key=lambda x: -x[0])
        leaders[c] = [{"wallet": s["wallet"], "name": _label(s), "pnl": round(v, 2), "style": s["style"],
                       "rank": s.get("rank")} for v, s in rows[:6] if v > 0]
    tot = [dict(t, pnl=round(t["pnl"], 2), gain=round(t["gain"], 2), loss=round(t["loss"], 2),
                buy=round(t["buy"], 2)) for t in totals.values() if t["buy"] or t["pnl"]]
    tot.sort(key=lambda t: -t["pnl"])
    return {"leaders": leaders, "totals": tot}


def summarize(wallets: List[dict], meta: dict) -> dict:
    pnl = [w["pnl_90d"] or 0 for w in wallets]
    wr = [w["win_rate"] for w in wallets if w["win_rate"] is not None and w["n_resolved"] >= 10]
    styles = Counter(w["style"] for w in wallets)
    return {
        "n_wallets": len(wallets),
        "n_profitable": sum(1 for x in pnl if x > 0),
        "total_pnl": round(sum(pnl), 2),
        "median_pnl": round(statistics.median(pnl), 2) if pnl else 0,
        "top10_pnl": round(sum(sorted(pnl, reverse=True)[:10]), 2),
        "total_volume": round(sum(w["volume"] or 0 for w in wallets), 2),
        "median_win_rate": round(statistics.median(wr), 4) if wr else None,
        "styles": {s: styles.get(s, 0) for s in STYLES if styles.get(s)},
        "truncated": sum(1 for w in wallets if w["truncated"]),
        "failures": meta.get("failures", 0),
        "universe_size": meta.get("universe_size"),
    }


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def run_analysis(out_dir: str, enrich_client: Optional[Client] = None, enrich_top: int = 400,
                 synthetic: bool = False, log: Log = _stderr) -> dict:
    uni = read_json(os.path.join(out_dir, "raw", "universe.json"))
    meta, universe, candidates = uni["meta"], uni["universe"], uni["candidates"]
    start, end = meta["window_start"], meta["window_end"]

    tags_path = os.path.join(out_dir, "raw", "gamma_tags.json")
    event_tags: Dict[str, List[str]] = read_json(tags_path) if os.path.exists(tags_path) else {}
    if enrich_client is not None:
        vol: Counter = Counter()
        for w in candidates:
            p = wallet_path(out_dir, w)
            if not os.path.exists(p):
                continue
            rec = read_json(p)
            if rec.get("error"):
                continue
            mk = rec.get("markets") or {}
            for a in rec.get("activity") or []:
                ev = (mk.get(a["c"]) or {}).get("eventSlug")
                if ev and a["ty"] == "TRADE":
                    vol[ev] += a["u"]
        top = [ev for ev, _ in vol.most_common(enrich_top) if ev not in event_tags]
        log(f"Fetching Gamma tags for {len(top)} events...")
        event_tags = fetch_event_tags(enrich_client, top, event_tags, log)
        write_json(tags_path, event_tags)

    categorize = Categorizer(event_tags)
    results: List[dict] = []
    market_meta: Dict[str, dict] = {}
    failed: List[str] = []
    for i, w in enumerate(candidates, 1):
        p = wallet_path(out_dir, w)
        if not os.path.exists(p):
            failed.append(w)
            continue
        rec = read_json(p)
        if rec.get("error"):
            failed.append(w)
            continue
        for c, m in (rec.get("markets") or {}).items():
            if c not in market_meta:
                market_meta[c] = {"title": m.get("title", ""), "slug": m.get("slug", ""),
                                  "eventSlug": m.get("eventSlug", ""), "category": categorize(m)}
        r = analyze_wallet(rec, start, end, categorize, universe.get(w))
        r["internal"]["buys"] = r["internal"]["buys"][-5000:]
        results.append(r)
        if i % 50 == 0:
            log(f"  analysed {i}/{len(candidates)}")

    results.sort(key=lambda r: -(r["summary"]["pnl_90d"] or 0))
    for i, r in enumerate(results, 1):
        r["summary"]["rank"] = i
    meta = dict(meta, failures=len(failed), synthetic=bool(synthetic or meta.get("synthetic")),
                tags_enriched=bool(event_tags))

    wallets = [r["summary"] for r in results]
    cons = consensus(results)
    analysis = {
        "meta": meta,
        "summary": summarize(wallets, meta),
        "styles": STYLE_BLURBS,
        "wallets": wallets,
        "details": {r["summary"]["wallet"]: r["detail"] for r in results},
        "consensus": cons["agreed"],
        "contested": cons["contested"],
        "heat": market_heat(results, market_meta),
        "linked": linked_wallets(results),
        "categories": category_views(results),
    }
    write_json(os.path.join(out_dir, "analysis.json"), analysis)
    log(f"Analysed {len(results)} wallets ({len(failed)} missing/failed).")
    return analysis
