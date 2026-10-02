import json
import os
import urllib.parse
from collections import Counter

import pytest

from pmscout.api import ApiError, Client
from pmscout.collect import (build_universe, collect, fetch_activity, fetch_closed_positions,
                             fetch_leaderboard, select_candidates)


class Router:
    """Minimal fake transport: route(path, params) -> (status, obj)."""

    def __init__(self, route):
        self.route = route
        self.calls = []

    def __call__(self, url, timeout):
        u = urllib.parse.urlparse(url)
        q = {k: v[-1] for k, v in urllib.parse.parse_qs(u.query).items()}
        self.calls.append((u.path, q))
        status, obj = self.route(u.path, q)
        return status, {}, json.dumps(obj).encode()


def client(route):
    r = Router(route)
    return Client(transport=r, rate=1e6, sleep=lambda s: None), r


def activity_server(rows, cap=5000):
    def route(path, q):
        limit, offset = int(q["limit"]), int(q["offset"])
        if limit > 500 or offset > cap:
            return 400, {"error": "offset cap"}
        sel = [r for r in rows if int(q["start"]) <= r["timestamp"] <= int(q["end"])]
        sel.sort(key=lambda r: -r["timestamp"])
        return 200, sel[offset:offset + limit]
    return route


def make_rows(n, per_ts=7, t0=2_000_000):
    rows = []
    for i in range(n):
        rows.append({"timestamp": t0 - i // per_ts, "type": "TRADE", "side": "BUY", "asset": f"a{i % 3}",
                     "conditionId": "c", "size": 10 + i, "price": 0.5, "usdcSize": 5 + i / 2,
                     "transactionHash": f"0x{i // 2:x}"})  # hashes shared by pairs of fills
    return rows


def key(r):
    return (r["transactionHash"], r["size"], r["timestamp"])


def test_activity_crosses_offset_cap_without_gaps_or_duplicates():
    rows = make_rows(12_345)
    c, router = client(activity_server(rows))
    got, truncated = fetch_activity(c, "0xw", 0, 10**10, max_rows=100_000)
    assert not truncated
    assert len(got) == len(rows)
    assert Counter(map(key, got)) == Counter(map(key, rows))
    assert all(int(q["offset"]) <= 5000 for _, q in router.calls)


def test_activity_respects_max_rows():
    c, _ = client(activity_server(make_rows(3000)))
    got, truncated = fetch_activity(c, "0xw", 0, 10**10, max_rows=1200)
    assert truncated and len(got) == 1200


def test_activity_single_timestamp_flood_terminates():
    rows = make_rows(6000, per_ts=10_000)  # every row has the same timestamp
    rows += [dict(r, timestamp=r["timestamp"] - 50, size=-r["size"]) for r in make_rows(10)]
    c, _ = client(activity_server(rows))
    got, _ = fetch_activity(c, "0xw", 0, 10**10, max_rows=100_000)
    assert 5000 <= len(got) <= len(rows)
    assert any(r["size"] < 0 for r in got)  # reached the older rows after the flood


def closed_server(rows, sortable=True):
    def route(path, q):
        if q.get("sortBy") == "TIMESTAMP" and not sortable:
            return 400, {"error": "bad sortBy"}
        sel = sorted(rows, key=lambda r: -r["timestamp"]) if q.get("sortBy") == "TIMESTAMP" else list(rows)
        o, l = int(q["offset"]), int(q["limit"])
        return 200, sel[o:o + l]
    return route


def test_closed_positions_stop_early_when_sorted():
    rows = [{"timestamp": 1000 - i, "realizedPnl": i} for i in range(1000)]
    c, router = client(closed_server(rows))
    got, truncated = fetch_closed_positions(c, "0xw", start=1000 - 120)
    assert not truncated and len(got) == 121
    assert len(router.calls) == 3  # 150 rows scanned, not 1000


def test_closed_positions_fall_back_when_sort_rejected():
    rows = [{"timestamp": t, "realizedPnl": 1} for t in (5, 900, 950, 10, 999)]
    c, router = client(closed_server(rows, sortable=False))
    got, _ = fetch_closed_positions(c, "0xw", start=900)
    assert sorted(r["timestamp"] for r in got) == [900, 950, 999]
    assert "sortBy" not in router.calls[-1][1]


def board(n):
    return [{"rank": str(i + 1), "proxyWallet": f"0x{i:040x}", "userName": f"u{i}", "pnl": 1000 - i, "vol": i}
            for i in range(n)]


def test_leaderboard_pagination():
    rows = board(300)
    c, router = client(lambda p, q: (200, rows[int(q["offset"]):int(q["offset"]) + int(q["limit"])]))
    got = fetch_leaderboard(c, "MONTH", "PNL", depth=120)
    assert len(got) == 120
    assert [int(q["limit"]) for _, q in router.calls] == [50, 50, 20]


def test_universe_and_candidate_priority():
    def route(path, q):
        if q["category"] != "OVERALL":
            return 200, []
        if q["timePeriod"] == "MONTH" and q["orderBy"] == "PNL":
            return 200, board(10)[int(q["offset"]):][:int(q["limit"])]
        if q["timePeriod"] == "ALL" and q["orderBy"] == "VOL":
            return 200, list(reversed(board(10)))[int(q["offset"]):][:int(q["limit"])]
        return 200, []
    c, _ = client(route)
    uni = build_universe(c, depth=10, category_depth=5, extra_wallets=["0xMANUAL"], log=lambda m: None)
    assert len(uni) == 11
    top = f"0x{0:040x}"
    assert set(uni[top]["boards"]) == {"OVERALL:MONTH:PNL", "OVERALL:ALL:VOL"}
    assert uni[top]["name"] == "u0"
    picked = [e["wallet"] for e in select_candidates(uni, 3)]
    assert picked[0] == "0xmanual" and picked[1] == top


def test_client_retries_then_raises():
    seq = [(429, {}), (503, {}), (200, [1, 2])]
    c, router = client(lambda p, q: seq.pop(0))
    assert c.data("/x") == [1, 2]
    assert len(router.calls) == 3
    c2, _ = client(lambda p, q: (404, {"error": "nope"}))
    with pytest.raises(ApiError) as e:
        c2.data("/x")
    assert e.value.status == 404


def test_build_url():
    url = Client.build_url("https://h", "/p", {"a": True, "b": None, "c": [1, 2], "d": "x y"})
    assert url == "https://h/p?a=true&c=1&c=2&d=x+y"


def test_collect_is_resumable(tmp_path):
    from pmscout.synthetic import FakeTransport, World
    world = World(seed=3, scale=0.25)
    transport = FakeTransport(world)
    c = Client(transport=transport, rate=1e6, sleep=lambda s: None)
    kw = dict(days=90, depth=20, category_depth=0, max_wallets=0, workers=2, now=world.now, log=lambda m: None)
    collect(c, str(tmp_path), **kw)
    first = len(transport.calls)
    files = os.listdir(tmp_path / "raw" / "wallets")
    assert files
    collect(c, str(tmp_path), **kw)
    second = len(transport.calls) - first
    assert second == 6  # only the leaderboards are re-read; every wallet comes from cache
    collect(c, str(tmp_path), refresh=True, **kw)
    assert len(transport.calls) - first - second > second
