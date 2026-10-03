import math

import pytest

from pmscout.categorize import Categorizer, classify_tags, classify_text
from pmscout.metrics import (DAY, analyze_wallet, classify_style, consistency_score, max_drawdown,
                             parse_end_date)

START = 1_780_000_000
END = START + 90 * DAY
ISO_IN = "2026-06-15T00:00:00Z"  # inside [START, END]
assert START <= parse_end_date(ISO_IN) <= END


def act(t, ty="TRADE", sd="BUY", p=0.5, u=100.0, c="m1", a="a1", oi=0):
    return {"t": t, "ty": ty, "sd": sd, "p": p, "sz": u / p if p else 0, "u": u, "c": c, "a": a, "oi": oi}


def closed(a, c, pnl, t, tb=200.0, avg=0.5, oi=0):
    return {"a": a, "c": c, "oi": oi, "avg": avg, "tb": tb, "pnl": pnl, "cur": 1.0, "t": t, "end": ""}


def pos(a, c, cpnl, red=False, end="", cv=100.0, iv=80.0, avg=0.4, oi=0, rpnl=0.0):
    return {"a": a, "c": c, "oi": oi, "sz": 200.0, "avg": avg, "cur": cv / 200.0, "iv": iv, "cv": cv,
            "cpnl": cpnl, "rpnl": rpnl, "tb": 0.0, "red": red, "end": end, "neg": False}


MARKETS = {
    "m1": {"title": "Lakers vs. Celtics", "slug": "nba-lal-bos", "eventSlug": "nba-lal-bos", "outcomes": {"0": "Lakers", "1": "Celtics"}},
    "m2": {"title": "Will Bitcoin be above $150k?", "slug": "btc-150k", "eventSlug": "btc-150k", "outcomes": {}},
    "m3": {"title": "Fed rate cut in December?", "slug": "fed-dec", "eventSlug": "fed-dec", "outcomes": {}},
    "m4": {"title": "Will the Senate pass the bill?", "slug": "senate-bill", "eventSlug": "senate-bill", "outcomes": {}},
}


@pytest.fixture
def record():
    t = START + 10 * DAY
    return {
        "wallet": "0x" + "ab" * 20,
        "profile": {"name": "tester"},
        "markets": MARKETS,
        "activity": [
            act(t, a="a1", c="m1", p=0.5, u=100),                  # buy, later closed +100
            act(t + 5 * DAY, sd="SELL", a="a1", c="m1", p=1.0, u=200),
            act(t + DAY, a="a2", c="m2", p=0.9, u=180),            # favourite buy, closed -40
            act(t + 2 * DAY, a="a2b", c="m2", p=0.1, u=20, oi=1),  # other side of m2 -> two-sided
            act(t + 3 * DAY, a="a5", c="m3", p=0.3, u=60),         # open position bought in window
            act(t + 4 * DAY, ty="REDEEM", sd="", p=0, u=50, c="m4", a=""),
            act(t + 4 * DAY, ty="REWARD", sd="", p=0, u=5, c="", a=""),
            act(t + 4 * DAY, ty="SPLIT", sd="", p=0, u=10, c="m4", a=""),
            act(t + 4 * DAY, ty="MERGE", sd="", p=0, u=7, c="m4", a=""),
            act(START - DAY, a="a9", c="m1", p=0.5, u=999),         # before window: ignored
        ],
        "closed": [
            closed("a1", "m1", 100.0, t + 5 * DAY),
            closed("a2", "m2", -40.0, t + 6 * DAY, tb=200, avg=0.9),
            closed("old", "m1", 1000.0, START - 5 * DAY),           # closed before window
        ],
        "positions": [
            pos("a3", "m4", -30.0, red=True, end=ISO_IN, iv=30.0, cv=0.0),   # resolved loser in window
            pos("a1", "m1", 55.0, red=True, end=ISO_IN),                    # duplicate of closed a1
            pos("a4", "m4", -70.0, red=True, end="2020-01-01"),             # resolved before window
            pos("a5", "m3", 20.0, cv=80.0, iv=60.0),                       # open, bought in window
            pos("a6", "m3", 500.0, cv=900.0, iv=400.0),                    # open, untouched in window
        ],
        "truncated": {"activity": False, "closed": False, "positions": False},
    }


def test_pnl_attribution(record):
    r = analyze_wallet(record, START, END, Categorizer())
    s = r["summary"]
    assert s["realized_90d"] == pytest.approx(100 - 40 - 30)
    assert s["upnl_window"] == pytest.approx(20)
    assert s["upnl_all"] == pytest.approx(520)
    assert s["pnl_90d"] == pytest.approx(50)
    assert s["n_resolved"] == 3
    assert (s["wins"], s["losses"]) == (1, 2)
    assert s["win_rate"] == pytest.approx(1 / 3, abs=1e-4)
    assert s["profit_factor"] == pytest.approx(100 / 70, abs=0.01)
    # cost basis: 200*0.5 + 200*0.9 + 30 (initialValue fallback)
    assert s["roi"] == pytest.approx(30 / 310, abs=1e-3)
    assert s["max_win"] == pytest.approx(100)
    # best bet is the +100 close; without it the wallet is at -50
    assert s["pnl_ex_best"] == pytest.approx(-50)
    assert "One big hit" in s["tags"]


def test_cash_flow_and_behaviour(record):
    s = analyze_wallet(record, START, END, Categorizer())["summary"]
    # sells 200 + redeem 50 + merge 7 + reward 5 - buys (100+180+20+60) - split 10
    assert s["net_cash_90d"] == pytest.approx(200 + 50 + 7 + 5 - 360 - 10)
    assert s["n_trades"] == 5 and s["volume"] == pytest.approx(560)
    assert s["n_markets"] == 3
    assert s["two_sided"] == pytest.approx(1 / 3, abs=1e-3)   # m2 bought on both outcomes
    assert s["fav_share"] == pytest.approx(180 / 360, abs=1e-3)
    assert s["long_share"] == pytest.approx(20 / 360, abs=1e-3)
    assert s["median_hold_h"] == pytest.approx(5 * 24, abs=0.1)  # a1: 5d; a2: 5d
    assert s["top_cat"] == "Crypto"


def test_detail_series(record):
    r = analyze_wallet(record, START, END, Categorizer())
    d = r["detail"]
    assert len(d["curve"]) == 90 and d["curve"][-1] == pytest.approx(30, abs=1)
    assert sum(d["weekly"]) == pytest.approx(30, abs=1)
    assert sum(d["price_hist"]) == pytest.approx(360, abs=1)
    assert sum(d["hours"]) == 5
    assert [o["title"] for o in d["open"]] == ["Fed rate cut in December?"] * 2
    assert d["open"][0]["in_window"] is False and d["open"][1]["in_window"] is True


def test_window_excludes_everything_outside():
    rec = {"wallet": "0x" + "cd" * 20, "markets": {}, "activity": [act(START - 10)], "positions": [],
           "closed": [closed("x", "m", 50.0, END + 10)]}
    s = analyze_wallet(rec, START, END, Categorizer())["summary"]
    assert s["n_trades"] == 0 and s["n_resolved"] == 0 and s["pnl_90d"] == 0
    assert s["style"] == "Inactive"


def test_max_drawdown():
    assert max_drawdown([0, 10, 5, 12, 3, 8]) == (9, pytest.approx(0.75))
    assert max_drawdown([0, -5, -2]) == (5, 1.0)
    assert max_drawdown([1, 2, 3]) == (0, 0)


def _m(**kw):
    base = dict(n_trades=200, trades_per_day=5, two_sided=0.0, median_trade=300, n_markets=80,
                fav_share=0.1, long_share=0.1, sell_ratio=0.1, median_hold_h=100, top_cat="Sports",
                top_cat_share=0.4, top_win_share=0.2, pnl_90d=1000, pnl_ex_best=500, n_contrib=40,
                n_resolved=40, win_rate=0.55, last_trade=END - DAY, window_end=END, profit_factor=1.5,
                concentration=0.2, pct_up_weeks=0.6, rel_dd=0.3, realized_pnl=1000, avg_buy_price=0.5)
    base.update(kw)
    return base


@pytest.mark.parametrize("kw,style", [
    ({"n_trades": 0}, "Inactive"),
    ({"trades_per_day": 120}, "Market Maker"),
    ({"two_sided": 0.5, "n_trades": 3000}, "Market Maker"),
    ({"median_trade": 8000, "n_markets": 20}, "Whale"),
    ({"fav_share": 0.7}, "Favorite Grinder"),
    ({"long_share": 0.5}, "Longshot Hunter"),
    ({"sell_ratio": 0.8, "median_hold_h": 10}, "Swing Trader"),
    ({"top_cat_share": 0.85}, "Specialist"),
    ({}, "Generalist"),
])
def test_classify_style(kw, style):
    assert classify_style(_m(**kw))[0] == style


def test_tags():
    _, tags = classify_style(_m(median_hold_h=1, last_trade=END - 20 * DAY, win_rate=0.8, top_cat_share=0.65))
    assert {"Scalper", "Gone quiet", "High hit rate", "Sports focus"} <= set(tags)


def test_consistency_score_bounds():
    assert 0 <= consistency_score(_m()) <= 100
    perfect = _m(pct_up_weeks=1.0, profit_factor=math.inf, concentration=0.0, n_resolved=100, rel_dd=0.0)
    assert consistency_score(perfect) == pytest.approx(100)
    assert consistency_score(dict(perfect, realized_pnl=-1)) == pytest.approx(50)


def test_parse_end_date():
    assert parse_end_date("2026-01-02") == 1767312000
    assert parse_end_date("2026-01-02T00:00:00Z") == 1767312000
    assert parse_end_date("2026-01-02T00:00:00+00:00") == 1767312000
    assert parse_end_date("") is None and parse_end_date("garbage") is None


@pytest.mark.parametrize("title,cat", [
    ("Will Bitcoin be above $120,000 on Oct 3?", "Crypto"),
    ("Lakers vs. Celtics", "Sports"),
    ("T1 vs Gen.G - LCK Finals", "Esports"),
    ("Fed decision in December?", "Economics"),
    ('Will Trump say "crypto" during the speech?', "Mentions"),
    ("Highest temperature in NYC on Oct 2?", "Weather"),
    ("Who will win the Oscar for Best Picture?", "Culture"),
    ("Will Zelensky meet Putin in 2026?", "Politics"),
    ("Will OpenAI release GPT-6 in 2026?", "Tech"),
    ("Something entirely unrelated", "Other"),
])
def test_classify_text(title, cat):
    assert classify_text(title) == cat


def test_tags_override_keywords():
    assert classify_tags(["Featured", "NBA"]) == "Sports"
    c = Categorizer({"ev": ["Politics"]})
    assert c({"title": "Lakers vs. Celtics", "eventSlug": "ev"}) == "Politics"
    assert c({"title": "Lakers vs. Celtics", "eventSlug": "other"}) == "Sports"
