"""Synthetic Polymarket simulator.

Generates a fictional population of wallets (every market, team and person
is made up) and serves it through a fake HTTP transport that mimics the real
Data/Gamma API response shapes and pagination caps. Used by ``pmscout demo``
and the test-suite so the whole pipeline can run without network access.
Nothing produced here describes real Polymarket activity.
"""

from __future__ import annotations

import json
import math
import random
import urllib.parse
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

DAY = 86400

_FIRST = ["Mara", "Tomas", "Ines", "Darius", "Leona", "Viktor", "Priya", "Osric", "Talia", "Ezra"]
_LAST = ["Ellison", "Reyes", "Okafor", "Lindqvist", "Marchetti", "Vance-Hollow", "Adeyemi", "Kerrigan"]
_REGION = ["Northland", "Port Avalon", "East Meridian", "Calder Valley", "New Brixton", "Sunmoor"]
_TEAMS = ["Harbor City Comets", "Ridgeview Ravens", "Iron Bay Pilots", "Summit Falcons", "Delta Mariners",
          "Granite Owls", "Lakeshore Lynx", "Copper Hill Miners", "Westgate Wolves", "Bayside Herons"]
_ETEAMS = ["Nova Esports", "Team Halcyon", "Crimson Byte", "Polar Five", "Vortex GG", "Lumen Squad"]
_CITIES = ["Avalon City", "Port Kestrel", "Meridian", "Sunmoor", "Calder"]
_FILMS = ["The Glass Orchard", "Low Tide Hymn", "Paper Comets", "A Quiet Engine", "Saltwater Kings"]
_COMPANIES = ["Lumora Labs", "Quillon AI", "Tessellate", "Northwind Robotics"]

ARCHETYPES = {
    # name: (positions in 130d, usd size range, entry price range, edge, sell prob, category bias)
    "grinder":  (140, (400, 6000), (0.86, 0.985), 0.035, 0.05, None),
    "longshot": (120, (40, 900), (0.03, 0.20), 0.03, 0.15, None),
    "swing":    (160, (150, 3000), (0.25, 0.75), 0.04, 0.85, None),
    "whale":    (22, (6000, 60000), (0.35, 0.90), 0.06, 0.25, None),
    "special":  (110, (200, 4000), (0.25, 0.80), 0.06, 0.25, "Sports"),
    "general":  (100, (100, 2500), (0.20, 0.85), 0.03, 0.30, None),
    "loser":    (90, (100, 3000), (0.20, 0.85), -0.06, 0.30, None),
    "onehit":   (30, (100, 800), (0.10, 0.60), -0.02, 0.20, None),
    "quiet":    (60, (500, 5000), (0.30, 0.80), 0.04, 0.25, None),
}

POPULATION = [  # (archetype, count)
    ("grinder", 8), ("longshot", 6), ("swing", 8), ("whale", 5), ("special", 8),
    ("general", 14), ("loser", 8), ("onehit", 3), ("quiet", 4), ("mm", 2), ("twin", 2),
]

CATS = ["Politics", "Sports", "Crypto", "Economics", "Weather", "Esports", "Culture", "Mentions", "Tech"]
CAT_WEIGHTS = [0.24, 0.30, 0.16, 0.08, 0.05, 0.05, 0.05, 0.04, 0.03]


def _hex(rng: random.Random, n: int) -> str:
    return "".join(rng.choice("0123456789abcdef") for _ in range(n))


def _fmt_date(ts: int) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return f"{dt:%b} {dt.day}"


class Market:
    __slots__ = ("c", "assets", "title", "slug", "eventSlug", "category", "end", "winner",
                 "p_now", "smart_side", "outcomes")

    def __init__(self, rng: random.Random, i: int, category: str, end: int, now: int):
        self.c = "0x" + _hex(rng, 64)
        self.assets = [str(rng.randrange(10 ** 75, 10 ** 76)) for _ in range(2)]
        self.category = category
        self.end = end
        self.winner = rng.randrange(2)
        self.smart_side = rng.randrange(2)
        self.p_now = rng.uniform(0.12, 0.88)
        self.outcomes = ["Yes", "No"]
        self.title, base = self._title(rng, category, end)
        self.eventSlug = base
        self.slug = f"{base}-{i}"

    def _title(self, rng: random.Random, cat: str, end: int) -> Tuple[str, str]:
        d = _fmt_date(end)
        if cat == "Politics":
            t = rng.choice([f"Will {rng.choice(_FIRST)} {rng.choice(_LAST)} win the {rng.choice(_REGION)} governor race?",
                            f"Will {rng.choice(_REGION)} hold a snap election by {d}?",
                            f"{rng.choice(_REGION)} parliament passes the budget bill by {d}?"])
        elif cat == "Sports":
            a, b = rng.sample(_TEAMS, 2)
            t = f"{a} vs. {b} ({d})"
            self.outcomes = [a, b]
        elif cat == "Crypto":
            t = rng.choice([f"Bitcoin above ${rng.randrange(90, 160)}k on {d}?",
                            f"Ethereum Up or Down - {d}", f"Solana above ${rng.randrange(120, 320)} on {d}?"])
            if "Up or Down" in t:
                self.outcomes = ["Up", "Down"]
        elif cat == "Economics":
            t = rng.choice([f"Fed rate cut at the {d} meeting?", f"US CPI above {rng.choice([2.6, 2.8, 3.0])}% in {d} report?"])
        elif cat == "Weather":
            t = f"Highest temperature in {rng.choice(_CITIES)} on {d}?"
        elif cat == "Esports":
            a, b = rng.sample(_ETEAMS, 2)
            t = f"{a} vs {b} - LCK esports ({d})"
            self.outcomes = [a, b]
        elif cat == "Culture":
            t = f"Will '{rng.choice(_FILMS)}' win Best Picture at the oscars?"
        elif cat == "Mentions":
            t = f"Will {rng.choice(_FIRST)} {rng.choice(_LAST)} say 'tariff' during the press conference on {d}?"
        else:
            t = f"Will {rng.choice(_COMPANIES)} release a new AI model by {d}?"
        slug = "".join(ch if ch.isalnum() else "-" for ch in t.lower()).strip("-")
        while "--" in slug:
            slug = slug.replace("--", "-")
        return t, slug[:60].strip("-")

    def meta(self, oi: int) -> dict:
        return {"conditionId": self.c, "title": self.title, "slug": self.slug, "eventSlug": self.eventSlug,
                "icon": "", "outcome": self.outcomes[oi], "outcomeIndex": oi,
                "oppositeOutcome": self.outcomes[1 - oi], "oppositeAsset": self.assets[1 - oi],
                "endDate": datetime.fromtimestamp(self.end, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


class World:
    def __init__(self, seed: int = 7, now: Optional[int] = None, scale: float = 1.0):
        self.rng = random.Random(seed)
        self.now = int(now if now is not None else datetime.now(timezone.utc).timestamp())
        self.markets: List[Market] = []
        for i in range(420):
            cat = self.rng.choices(CATS, CAT_WEIGHTS)[0]
            end = self.now + int(self.rng.uniform(-130, 60) * DAY)
            self.markets.append(Market(self.rng, i, cat, end, self.now))
        self.by_cat: Dict[str, List[Market]] = defaultdict(list)
        for m in self.markets:
            self.by_cat[m.category].append(m)
        self.activity: Dict[str, List[dict]] = defaultdict(list)
        self.closed: Dict[str, List[dict]] = defaultdict(list)
        self.positions: Dict[str, List[dict]] = defaultdict(list)
        self.profiles: Dict[str, dict] = {}
        n = 0
        for arch, count in POPULATION:
            for k in range(max(1, int(round(count * scale)))):
                n += 1
                w = "0x" + _hex(self.rng, 40)
                self.profiles[w] = {"userName": f"demo_{arch}_{k + 1:02d}", "arch": arch,
                                    "xUsername": "", "verifiedBadge": False, "profileImage": ""}
                if arch == "mm":
                    self._gen_mm(w)
                elif arch == "twin":
                    continue  # generated in pairs below
                else:
                    self._gen_directional(w, arch)
        twins = [w for w, p in self.profiles.items() if p["arch"] == "twin"]
        if len(twins) >= 2:
            self._gen_directional(twins[0], "general", record_into=twins[1])

    # ------------------------------------------------------------------ #
    def _row_base(self, w: str, m: Market, oi: int) -> dict:
        r = m.meta(oi)
        r.update(proxyWallet=w, asset=m.assets[oi], name=self.profiles[w]["userName"],
                 pseudonym=self.profiles[w]["userName"], bio="", profileImage="", profileImageOptimized="")
        return r

    def _trade(self, w: str, m: Market, oi: int, t: int, side: str, price: float, usd: float) -> dict:
        price = round(min(0.999, max(0.001, price)), 3)
        size = round(usd / price, 2)
        r = self._row_base(w, m, oi)
        r.update(timestamp=t, type="TRADE", side=side, price=price, size=size, usdcSize=round(size * price, 4),
                 transactionHash="0x" + _hex(self.rng, 64))
        self.activity[w].append(r)
        return r

    def _redeem(self, w: str, m: Market, oi: int, t: int, usdc: float, size: float) -> None:
        r = self._row_base(w, m, oi)
        r.update(timestamp=t, type="REDEEM", side="", price=0, size=round(size, 2), usdcSize=round(usdc, 4),
                 transactionHash="0x" + _hex(self.rng, 64), asset="", outcomeIndex=999)
        self.activity[w].append(r)

    def _pick_market(self, bias: Optional[str], late: bool) -> Market:
        if bias and self.rng.random() < 0.8:
            pool = self.by_cat[bias]
        else:
            pool = self.markets
        return self.rng.choice(pool)

    def _gen_directional(self, w: str, arch: str, record_into: Optional[str] = None) -> None:
        rng = self.rng
        n, (lo_usd, hi_usd), (lo_p, hi_p), edge, sell_prob, bias = ARCHETYPES[arch]
        edge += rng.uniform(-0.015, 0.015)
        horizon = 130 * DAY
        for k in range(n):
            m = self._pick_market(bias, arch == "grinder")
            open_start = max(m.end - 30 * DAY, self.now - horizon)
            open_end = min(m.end, self.now) - 1800
            if open_end <= open_start:
                continue
            if arch == "quiet":
                open_end = min(open_end, self.now - 40 * DAY)
                if open_end <= open_start:
                    continue
            if arch == "grinder":
                t_e = int(max(open_start, open_end - rng.uniform(1, 48) * 3600))
            else:
                t_e = int(rng.uniform(open_start, open_end))
            usd = math.exp(rng.uniform(math.log(lo_usd), math.log(hi_usd)))
            if arch == "onehit" and k == 0:
                usd, q_range = 9000.0, (0.06, 0.09)
            else:
                q_range = (lo_p, hi_p)
            q = rng.uniform(*q_range)
            resolved = m.end <= self.now
            if resolved:
                p_win = min(0.995, max(0.01, q + edge))
                if arch == "onehit" and k == 0:
                    p_win = 1.0
                oi = m.winner if rng.random() < p_win else 1 - m.winner
                won = oi == m.winner
            else:
                skilled = edge > 0.02
                oi = m.smart_side if rng.random() < (0.8 if skilled else 0.45) else 1 - m.smart_side
                q = None
                won = False
            targets = [w] + ([record_into] if record_into else [])
            for j, ww in enumerate(targets):
                delay = 0 if j == 0 else rng.randrange(20, 95)
                self._position(ww, m, oi, t_e + delay, usd * (1 if j == 0 else rng.uniform(0.3, 0.6)),
                               q, resolved, won, sell_prob, edge, arch)

    def _position(self, w: str, m: Market, oi: int, t_e: int, usd: float, q: Optional[float], resolved: bool,
                  won: bool, sell_prob: float, edge: float, arch: str) -> None:
        rng = self.rng
        cur_now = m.p_now if oi == 0 else 1 - m.p_now
        if q is None:  # open market: entry relative to today's price
            drift = rng.gauss(edge * 1.2, 0.05)
            q = min(0.97, max(0.03, cur_now - drift))
        fills = rng.randint(1, 3)
        tokens = cost = 0.0
        for f in range(fills):
            fp = min(0.995, max(0.005, q + rng.uniform(-0.01, 0.01)))
            r = self._trade(w, m, oi, t_e + f * rng.randrange(5, 600), "BUY", fp, usd / fills)
            tokens += r["size"]
            cost += r["usdcSize"]
        avg = cost / tokens
        last_buy = t_e + fills * 600
        base = self._row_base(w, m, oi)
        if resolved:
            if rng.random() < sell_prob and m.end - last_buy > 3600:
                t_s = int(rng.uniform(last_buy + 600, min(m.end, last_buy + (rng.uniform(2, 60) * 3600))))
                move = rng.uniform(0.05, 0.6) * ((1 - avg) if won else -avg)
                sp = min(0.995, max(0.005, avg + move))
                r = self._trade(w, m, oi, t_s, "SELL", sp, tokens * sp)
                pnl = r["usdcSize"] - cost
                self.closed[w].append(dict(base, avgPrice=round(avg, 4), totalBought=round(tokens, 2),
                                           realizedPnl=round(pnl, 4), curPrice=1 if won else 0, timestamp=t_s))
            elif won:
                t_r = m.end + rng.randrange(600, 2 * DAY)
                if t_r > self.now:
                    self.positions[w].append(self._pos_row(base, tokens, avg, 1.0, True))
                    return
                self._redeem(w, m, oi, t_r, tokens, tokens)
                self.closed[w].append(dict(base, avgPrice=round(avg, 4), totalBought=round(tokens, 2),
                                           realizedPnl=round(tokens - cost, 4), curPrice=1, timestamp=t_r))
            else:
                if rng.random() < 0.3 and m.end + DAY < self.now:
                    t_r = m.end + rng.randrange(600, DAY)
                    self._redeem(w, m, oi, t_r, 0.0, tokens)
                    self.closed[w].append(dict(base, avgPrice=round(avg, 4), totalBought=round(tokens, 2),
                                               realizedPnl=round(-cost, 4), curPrice=0, timestamp=t_r))
                else:
                    self.positions[w].append(self._pos_row(base, tokens, avg, 0.0, True))
        else:
            if arch == "swing" and rng.random() < 0.6:  # trims open positions too
                t_s = min(self.now - 60, last_buy + int(rng.uniform(1, 30) * 3600))
                part = rng.uniform(0.5, 0.9)
                self._trade(w, m, oi, t_s, "SELL", cur_now, tokens * part * cur_now)
                tokens *= 1 - part
                if tokens < 1:
                    return
            self.positions[w].append(self._pos_row(base, tokens, avg, round(cur_now, 3), False))

    @staticmethod
    def _pos_row(base: dict, tokens: float, avg: float, cur: float, redeemable: bool) -> dict:
        iv, cv = tokens * avg, tokens * cur
        return dict(base, size=round(tokens, 2), avgPrice=round(avg, 4), initialValue=round(iv, 4),
                    currentValue=round(cv, 4), cashPnl=round(cv - iv, 4),
                    percentPnl=round((cv - iv) / iv * 100, 2) if iv else 0, totalBought=round(tokens, 2),
                    realizedPnl=0, percentRealizedPnl=0, curPrice=cur, redeemable=redeemable,
                    mergeable=False, negativeRisk=False)

    def _gen_mm(self, w: str) -> None:
        """Market maker: thousands of small two-sided fills; crosses the activity offset cap."""
        rng = self.rng
        live = [m for m in self.markets if m.category in ("Sports", "Crypto", "Politics")]
        books = rng.sample(live, 40)
        for m in books:
            t0 = max(self.now - 100 * DAY, m.end - 25 * DAY)
            t1 = min(self.now, m.end) - 600
            if t1 <= t0:
                continue
            for oi in (0, 1):
                tokens_b = cost_b = proceeds = 0.0
                for _ in range(rng.randint(70, 110)):
                    t = int(rng.uniform(t0, t1))
                    mid = rng.uniform(0.3, 0.7) if oi == 0 else rng.uniform(0.3, 0.7)
                    usd = rng.uniform(15, 220)
                    rb = self._trade(w, m, oi, t, "BUY", mid - 0.01, usd)
                    rs = self._trade(w, m, oi, t + rng.randrange(1, 900), "SELL", mid + 0.01 - rng.uniform(0, 0.012),
                                     rb["size"] * (mid + 0.005))
                    tokens_b += rb["size"]
                    cost_b += rb["usdcSize"]
                    proceeds += rs["usdcSize"]
                base = self._row_base(w, m, oi)
                self.closed[w].append(dict(base, avgPrice=round(cost_b / tokens_b, 4), totalBought=round(tokens_b, 2),
                                           realizedPnl=round(proceeds - cost_b, 4), curPrice=0.5,
                                           timestamp=int(t1)))

    # ------------------------------------------------------------------ #
    # Leaderboards
    # ------------------------------------------------------------------ #
    def _period_stats(self, w: str, since: int, category: Optional[str] = None) -> Tuple[float, float]:
        pnl = sum(c["realizedPnl"] for c in self.closed[w] if c["timestamp"] >= since
                  and (category is None or self._cat_of(c["conditionId"]) == category))
        pnl += sum(p["cashPnl"] for p in self.positions[w]
                   if (category is None or self._cat_of(p["conditionId"]) == category))
        vol = sum(a["usdcSize"] for a in self.activity[w] if a["type"] == "TRADE" and a["timestamp"] >= since
                  and (category is None or self._cat_of(a["conditionId"]) == category))
        return pnl, vol

    def _cat_of(self, c: str) -> str:
        if not hasattr(self, "_cat_index"):
            self._cat_index = {m.c: m.category for m in self.markets}
        return self._cat_index.get(c, "Other")

    def leaderboard(self, period: str, order_by: str, category: str) -> List[dict]:
        since = {"DAY": self.now - DAY, "WEEK": self.now - 7 * DAY, "MONTH": self.now - 30 * DAY,
                 "ALL": 0}[period]
        cat = None if category == "OVERALL" else category.title()
        rows = []
        for w, prof in self.profiles.items():
            pnl, vol = self._period_stats(w, since, cat)
            if vol <= 0 and pnl == 0:
                continue
            rows.append({"proxyWallet": w, "userName": prof["userName"], "vol": round(vol, 2),
                         "pnl": round(pnl, 2), "profileImage": "", "xUsername": "", "verifiedBadge": False})
        rows.sort(key=lambda r: -(r["pnl"] if order_by == "PNL" else r["vol"]))
        for i, r in enumerate(rows, 1):
            r["rank"] = str(i)
        return rows


class FakeTransport:
    """Serves a :class:`World` with the real endpoints' parameters and caps."""

    def __init__(self, world: World, fail_first: int = 0):
        self.world = world
        self.calls: List[str] = []
        self.fail_first = fail_first

    def __call__(self, url: str, timeout: float):
        self.calls.append(url)
        if self.fail_first > 0:
            self.fail_first -= 1
            return 429, {"Retry-After": "0"}, b'{"error":"rate limited"}'
        u = urllib.parse.urlparse(url)
        q = {k: v[-1] for k, v in urllib.parse.parse_qs(u.query).items()}
        path = u.path
        try:
            if u.netloc.startswith("gamma"):
                return self._ok(self._gamma(path, urllib.parse.parse_qs(u.query)))
            if path == "/v1/leaderboard":
                limit, offset = int(q.get("limit", 25)), int(q.get("offset", 0))
                if limit > 50 or offset > 1000:
                    return self._bad("limit/offset out of range")
                rows = self.world.leaderboard(q.get("timePeriod", "DAY"), q.get("orderBy", "PNL"),
                                              q.get("category", "OVERALL"))
                return self._ok(rows[offset:offset + limit])
            if path == "/activity":
                return self._activity(q)
            if path == "/closed-positions":
                return self._closed(q)
            if path == "/positions":
                return self._positions(q)
        except ValueError as e:
            return self._bad(str(e))
        return 404, {}, b'{"error":"not found"}'

    @staticmethod
    def _ok(obj) -> tuple:
        return 200, {"Content-Type": "application/json"}, json.dumps(obj).encode()

    @staticmethod
    def _bad(msg: str) -> tuple:
        return 400, {}, json.dumps({"error": msg}).encode()

    def _activity(self, q: dict) -> tuple:
        limit, offset = int(q.get("limit", 100)), int(q.get("offset", 0))
        if limit > 500 or offset > 5000:
            return self._bad("max historical activity offset exceeded")
        start, end = int(q.get("start", 0)), int(q.get("end", 1 << 62))
        rows = [r for r in self.world.activity.get(q["user"].lower(), []) if start <= r["timestamp"] <= end]
        rows.sort(key=lambda r: -r["timestamp"])
        return self._ok(rows[offset:offset + limit])

    def _closed(self, q: dict) -> tuple:
        limit, offset = int(q.get("limit", 10)), int(q.get("offset", 0))
        if limit > 50 or offset > 100000:
            return self._bad("limit/offset out of range")
        rows = list(self.world.closed.get(q["user"].lower(), []))
        if q.get("sortBy") == "TIMESTAMP":
            rows.sort(key=lambda r: r["timestamp"], reverse=q.get("sortDirection", "DESC") == "DESC")
        else:
            rows.sort(key=lambda r: -r["realizedPnl"])
        return self._ok(rows[offset:offset + limit])

    def _positions(self, q: dict) -> tuple:
        limit, offset = int(q.get("limit", 100)), int(q.get("offset", 0))
        if limit > 500 or offset > 10000:
            return self._bad("limit/offset out of range")
        thr = float(q.get("sizeThreshold", 1))
        rows = [r for r in self.world.positions.get(q["user"].lower(), []) if r["size"] >= thr]
        rows.sort(key=lambda r: -r["currentValue"])
        return self._ok(rows[offset:offset + limit])

    def _gamma(self, path: str, qs: dict) -> list:
        if path != "/events":
            return []
        out = []
        for slug in qs.get("slug", []):
            m = next((m for m in self.world.markets if m.eventSlug == slug), None)
            if m:
                out.append({"slug": slug, "tags": [{"label": m.category}]})
        return out
