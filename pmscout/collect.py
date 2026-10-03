"""Build the top-wallet universe and download each wallet's 90-day history.

Raw data is written as one gzip JSON file per wallet under ``<out>/raw/wallets``.
Those files double as a resumable cache: a re-run skips wallets whose file is
fresh and already covers the requested window.
"""

from __future__ import annotations

import gzip
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .api import ApiError, Client

LEADERBOARD_PAGE = 50
LEADERBOARD_MAX_OFFSET = 1000
ACTIVITY_PAGE = 500
ACTIVITY_MAX_OFFSET = 4500  # documented cap is 5000; stay one page under it
CLOSED_PAGE = 50
CLOSED_MAX_OFFSET = 100_000
POSITIONS_PAGE = 500
POSITIONS_MAX_OFFSET = 10_000

OVERALL_PERIODS = ("WEEK", "MONTH", "ALL")
ORDERS = ("PNL", "VOL")
CATEGORIES = (
    "POLITICS", "SPORTS", "ESPORTS", "CRYPTO", "CULTURE", "MENTIONS",
    "WEATHER", "ECONOMICS", "TECH", "FINANCE",
)

REWARD_TYPES = {"REWARD", "MAKER_REBATE", "TAKER_REBATE", "REFERRAL_REWARD", "YIELD"}

Log = Callable[[str], None]


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def fnum(x: Any, default: float = 0.0) -> float:
    try:
        if x is None or x == "":
            return default
        v = float(x)
        return v if v == v else default  # NaN guard
    except (TypeError, ValueError):
        return default


def inum(x: Any, default: int = 0) -> int:
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# Leaderboard universe
# --------------------------------------------------------------------------- #

def fetch_leaderboard(client: Client, period: str, order_by: str, category: str = "OVERALL",
                      depth: int = 100) -> List[dict]:
    rows: List[dict] = []
    offset = 0
    while offset < depth and offset <= LEADERBOARD_MAX_OFFSET:
        limit = min(LEADERBOARD_PAGE, depth - offset)
        page = client.data("/v1/leaderboard", category=category, timePeriod=period,
                           orderBy=order_by, limit=limit, offset=offset)
        if not isinstance(page, list) or not page:
            break
        rows.extend(page)
        if len(page) < limit:
            break
        offset += len(page)
    return rows[:depth]


def build_universe(client: Client, depth: int = 100, category_depth: int = 50,
                   extra_wallets: Iterable[str] = (), log: Log = _stderr) -> Dict[str, dict]:
    boards: List[Tuple[str, str, str, int]] = [
        ("OVERALL", p, o, depth) for p in OVERALL_PERIODS for o in ORDERS
    ]
    if category_depth > 0:
        boards += [(c, "MONTH", "PNL", category_depth) for c in CATEGORIES]

    universe: Dict[str, dict] = {}
    for category, period, order_by, d in boards:
        key = f"{category}:{period}:{order_by}"
        try:
            rows = fetch_leaderboard(client, period, order_by, category, d)
        except ApiError as e:
            log(f"  leaderboard {key} failed: {e}")
            continue
        log(f"  leaderboard {key}: {len(rows)} wallets")
        for i, r in enumerate(rows):
            w = str(r.get("proxyWallet") or "").lower()
            if not w.startswith("0x"):
                continue
            u = universe.setdefault(w, {"wallet": w, "boards": {}})
            for src, dst in (("userName", "name"), ("xUsername", "x"), ("profileImage", "image")):
                if r.get(src) and not u.get(dst):
                    u[dst] = r[src]
            if r.get("verifiedBadge"):
                u["verified"] = True
            u["boards"][key] = {
                "rank": inum(r.get("rank"), i + 1),
                "pnl": fnum(r.get("pnl")),
                "vol": fnum(r.get("vol")),
                "depth": d,
            }
    for w in extra_wallets:
        w = w.lower()
        universe.setdefault(w, {"wallet": w, "boards": {}})["manual"] = True
    return universe


def priority(entry: dict) -> float:
    """Lower is better. Used to choose which candidates get deep analysis."""
    if entry.get("manual"):
        return -1.0
    best = float("inf")
    for key, b in entry.get("boards", {}).items():
        category, _period, order_by = key.split(":")
        weight = 1.0 if order_by == "PNL" else 1.6
        if category != "OVERALL":
            weight *= 1.25
        best = min(best, weight * b["rank"] / max(b.get("depth") or 1, 1))
    return best


def select_candidates(universe: Dict[str, dict], max_wallets: int) -> List[dict]:
    ranked = sorted(universe.values(), key=lambda e: (priority(e), e["wallet"]))
    return ranked if max_wallets <= 0 else ranked[:max_wallets]


# --------------------------------------------------------------------------- #
# Per-wallet history
# --------------------------------------------------------------------------- #

def _activity_key(r: dict) -> tuple:
    return (r.get("transactionHash"), r.get("type"), r.get("side"), r.get("asset"),
            r.get("conditionId"), str(r.get("size")), str(r.get("price")),
            str(r.get("usdcSize")), inum(r.get("timestamp")))


def fetch_activity(client: Client, wallet: str, start: int, end: int,
                   max_rows: int = 15_000) -> Tuple[List[dict], bool]:
    """All on-chain activity in [start, end], newest first.

    Offset pagination is capped server-side, so once a segment reaches the cap
    we move ``end`` back to the oldest timestamp seen and restart at offset 0.
    Rows sharing that boundary timestamp are re-served by the next segment and
    are skipped with a multiset of their keys.
    """
    rows: List[dict] = []
    seg_end = end
    boundary_seen: Counter = Counter()
    while True:
        offset = 0
        seg_rows: List[dict] = []
        hit_cap = False
        while True:
            try:
                page = client.data("/activity", user=wallet, limit=ACTIVITY_PAGE, offset=offset,
                                   start=start, end=seg_end, sortBy="TIMESTAMP",
                                   sortDirection="DESC")
            except ApiError as e:
                if e.status in (400, 422) and offset > 0:
                    hit_cap = True
                    break
                raise
            if not isinstance(page, list) or not page:
                break
            seg_rows.extend(page)
            if len(page) < ACTIVITY_PAGE:
                break
            offset += len(page)
            if offset > ACTIVITY_MAX_OFFSET:
                hit_cap = True
                break
        fresh = []
        for r in seg_rows:
            k = _activity_key(r)
            if boundary_seen[k] > 0:
                boundary_seen[k] -= 1
                continue
            fresh.append(r)
        rows.extend(fresh)
        if len(rows) >= max_rows:
            return rows[:max_rows], True
        if not hit_cap or not seg_rows:
            return rows, False
        oldest = min(inum(r.get("timestamp")) for r in seg_rows)
        if oldest <= start:
            return rows, False
        if oldest >= seg_end:
            # An entire capped segment shares one timestamp; step past it.
            seg_end = oldest - 1
            boundary_seen = Counter()
            continue
        seg_end = oldest
        boundary_seen = Counter(_activity_key(r) for r in seg_rows if inum(r.get("timestamp")) == oldest)


def _is_desc(ts: List[int]) -> bool:
    return all(a >= b for a, b in zip(ts, ts[1:]))


def fetch_closed_positions(client: Client, wallet: str, start: int,
                           max_rows: int = 6_000) -> Tuple[List[dict], bool]:
    """Closed positions whose close timestamp is >= start."""
    params: Dict[str, Any] = {"sortBy": "TIMESTAMP", "sortDirection": "DESC"}
    rows: List[dict] = []
    offset = 0
    sorted_ok = True
    while offset <= CLOSED_MAX_OFFSET:
        try:
            page = client.data("/closed-positions", user=wallet, limit=CLOSED_PAGE, offset=offset, **params)
        except ApiError as e:
            if e.status in (400, 422) and offset == 0 and params:
                params, sorted_ok = {}, False  # server rejected the sort; scan everything
                continue
            if e.status in (400, 422) and offset > 0:
                return rows, True
            raise
        if not isinstance(page, list) or not page:
            return rows, False
        ts = [inum(r.get("timestamp")) for r in page]
        if sorted_ok and not _is_desc(ts):
            sorted_ok = False
        rows.extend(r for r, t in zip(page, ts) if t >= start)
        if len(rows) >= max_rows:
            return rows[:max_rows], True
        if sorted_ok and ts[-1] < start:
            return rows, False
        if len(page) < CLOSED_PAGE:
            return rows, False
        offset += len(page)
    return rows, True


def fetch_positions(client: Client, wallet: str, size_threshold: float = 1.0,
                    max_rows: int = 5_000) -> Tuple[List[dict], bool]:
    rows: List[dict] = []
    offset = 0
    while offset <= POSITIONS_MAX_OFFSET:
        page = client.data("/positions", user=wallet, limit=POSITIONS_PAGE, offset=offset,
                           sizeThreshold=size_threshold, sortBy="CURRENT", sortDirection="DESC")
        if not isinstance(page, list) or not page:
            return rows, False
        rows.extend(page)
        if len(rows) >= max_rows:
            return rows[:max_rows], True
        if len(page) < POSITIONS_PAGE:
            return rows, False
        offset += len(page)
    return rows, True


# --------------------------------------------------------------------------- #
# Slimming: keep only what the analysis needs; market metadata is shared.
# --------------------------------------------------------------------------- #

def _note_market(markets: Dict[str, dict], r: dict) -> str:
    c = str(r.get("conditionId") or "")
    if not c:
        return c
    m = markets.setdefault(c, {"title": "", "slug": "", "eventSlug": "", "outcomes": {}})
    for k in ("title", "slug", "eventSlug", "endDate"):
        if r.get(k) and not m.get(k):
            m[k] = r[k]
    oi = r.get("outcomeIndex")
    if r.get("outcome") and oi is not None and inum(oi, 999) != 999:
        m["outcomes"].setdefault(str(inum(oi)), r["outcome"])
    if r.get("oppositeOutcome") and oi is not None and inum(oi, 999) in (0, 1):
        m["outcomes"].setdefault(str(1 - inum(oi)), r["oppositeOutcome"])
    return c


def slim_activity(r: dict, markets: Dict[str, dict]) -> dict:
    c = _note_market(markets, r)
    size, price = fnum(r.get("size")), fnum(r.get("price"))
    usdc = fnum(r.get("usdcSize"), -1.0)
    if usdc < 0:
        usdc = size * price
    return {"t": inum(r.get("timestamp")), "ty": str(r.get("type") or "TRADE").upper(),
            "sd": str(r.get("side") or "").upper(), "p": price, "sz": size, "u": usdc,
            "c": c, "a": str(r.get("asset") or ""), "oi": inum(r.get("outcomeIndex"), 999)}


def slim_closed(r: dict, markets: Dict[str, dict]) -> dict:
    c = _note_market(markets, r)
    return {"a": str(r.get("asset") or ""), "c": c, "oi": inum(r.get("outcomeIndex"), 999),
            "avg": fnum(r.get("avgPrice")), "tb": fnum(r.get("totalBought")),
            "pnl": fnum(r.get("realizedPnl")), "cur": fnum(r.get("curPrice")),
            "t": inum(r.get("timestamp")), "end": r.get("endDate") or ""}


def slim_position(r: dict, markets: Dict[str, dict]) -> dict:
    c = _note_market(markets, r)
    return {"a": str(r.get("asset") or ""), "c": c, "oi": inum(r.get("outcomeIndex"), 999),
            "sz": fnum(r.get("size")), "avg": fnum(r.get("avgPrice")), "cur": fnum(r.get("curPrice")),
            "iv": fnum(r.get("initialValue")), "cv": fnum(r.get("currentValue")),
            "cpnl": fnum(r.get("cashPnl")), "rpnl": fnum(r.get("realizedPnl")),
            "tb": fnum(r.get("totalBought")), "red": bool(r.get("redeemable")),
            "end": r.get("endDate") or "", "neg": bool(r.get("negativeRisk"))}


def fetch_wallet(client: Client, wallet: str, start: int, end: int, cfg: dict) -> dict:
    t0 = time.time()
    acts, act_trunc = fetch_activity(client, wallet, start, end, cfg.get("max_activity", 15_000))
    closed, closed_trunc = fetch_closed_positions(client, wallet, start, cfg.get("max_closed", 6_000))
    pos, pos_trunc = fetch_positions(client, wallet, cfg.get("size_threshold", 1.0),
                                     cfg.get("max_positions", 5_000))
    markets: Dict[str, dict] = {}
    profile: Dict[str, str] = {}
    for r in acts[:50]:
        for k in ("name", "pseudonym"):
            if r.get(k) and not profile.get(k):
                profile[k] = r[k]
    return {
        "wallet": wallet,
        "fetched_at": int(time.time()),
        "window_start": start,
        "window_end": end,
        "profile": profile,
        "activity": [slim_activity(r, markets) for r in acts],
        "closed": [slim_closed(r, markets) for r in closed],
        "positions": [slim_position(r, markets) for r in pos],
        "markets": markets,
        "truncated": {"activity": act_trunc, "closed": closed_trunc, "positions": pos_trunc},
        "seconds": round(time.time() - t0, 2),
    }


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def write_json(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    opener = gzip.open if path.endswith(".gz") else open
    with opener(tmp, "wt", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"))
    os.replace(tmp, path)


def read_json(path: str) -> Any:
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def wallet_path(out_dir: str, wallet: str) -> str:
    return os.path.join(out_dir, "raw", "wallets", f"{wallet}.json.gz")


def _reusable(path: str, start: int, max_age_s: float, now: float) -> bool:
    if not os.path.exists(path):
        return False
    try:
        rec = read_json(path)
    except (OSError, ValueError):
        return False
    return (rec.get("window_start", 1 << 62) <= start
            and now - rec.get("fetched_at", 0) <= max_age_s
            and not rec.get("error"))


def collect(client: Client, out_dir: str, *, days: int = 90, depth: int = 100,
            category_depth: int = 50, max_wallets: int = 500, extra_wallets: Iterable[str] = (),
            workers: int = 6, max_age_hours: float = 12.0, refresh: bool = False,
            now: Optional[float] = None, wallet_cfg: Optional[dict] = None,
            log: Log = _stderr) -> dict:
    now = float(now if now is not None else time.time())
    end = int(now)
    start = end - days * 86400
    cfg = wallet_cfg or {}

    log(f"Building universe from leaderboards (depth {depth}, category depth {category_depth})...")
    universe = build_universe(client, depth, category_depth, extra_wallets, log)
    candidates = select_candidates(universe, max_wallets)
    log(f"{len(universe)} unique wallets on leaderboards; analysing {len(candidates)}.")

    meta = {
        "generated_at": end, "window_start": start, "window_end": end, "days": days,
        "depth": depth, "category_depth": category_depth, "universe_size": len(universe),
        "candidates": len(candidates),
    }
    write_json(os.path.join(out_dir, "raw", "universe.json"),
               {"meta": meta, "universe": universe, "candidates": [c["wallet"] for c in candidates]})

    todo = []
    for c in candidates:
        p = wallet_path(out_dir, c["wallet"])
        if refresh or not _reusable(p, start, max_age_hours * 3600, now):
            todo.append(c["wallet"])
    log(f"{len(candidates) - len(todo)} wallets cached, {len(todo)} to fetch.")

    done = 0
    failures = 0

    def work(w: str) -> Tuple[str, Optional[dict], Optional[str]]:
        try:
            return w, fetch_wallet(client, w, start, end, cfg), None
        except Exception as e:  # keep going; record the failure
            return w, None, f"{type(e).__name__}: {e}"

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(work, w) for w in todo]
        for fut in as_completed(futures):
            w, rec, err = fut.result()
            done += 1
            if err:
                failures += 1
                write_json(wallet_path(out_dir, w), {"wallet": w, "error": err, "fetched_at": int(now),
                                                     "window_start": start, "window_end": end})
                log(f"  [{done}/{len(todo)}] {w} FAILED: {err}")
                continue
            write_json(wallet_path(out_dir, w), rec)
            log(f"  [{done}/{len(todo)}] {w} activity={len(rec['activity'])} closed={len(rec['closed'])} "
                f"positions={len(rec['positions'])} ({rec['seconds']}s)")

    meta["failures"] = failures
    meta["requests"] = client.requests
    write_json(os.path.join(out_dir, "raw", "universe.json"),
               {"meta": meta, "universe": universe, "candidates": [c["wallet"] for c in candidates]})
    log(f"Collection finished: {client.requests} API requests, {failures} failures.")
    return meta
