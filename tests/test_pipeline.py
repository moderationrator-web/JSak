"""End-to-end: simulator -> collect -> analyze -> report."""

import json
import re

import pytest

from pmscout.analysis import run_analysis
from pmscout.api import Client
from pmscout.collect import collect, read_json
from pmscout.report import render_html, write_report
from pmscout.synthetic import FakeTransport, World


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    out = tmp_path_factory.mktemp("demo")
    world = World(seed=11)
    transport = FakeTransport(world, fail_first=2)  # first two requests are rate-limited
    client = Client(transport=transport, rate=1e6, sleep=lambda s: None)
    meta = collect(client, str(out), days=90, depth=50, category_depth=25, max_wallets=0, workers=3,
                   now=world.now, log=lambda m: None)
    analysis = run_analysis(str(out), enrich_client=client, synthetic=True, log=lambda m: None)
    return world, out, meta, analysis


def test_collected_data_matches_simulator(run):
    world, out, meta, _ = run
    assert meta["failures"] == 0
    uni = read_json(str(out / "raw" / "universe.json"))
    start, end = uni["meta"]["window_start"], uni["meta"]["window_end"]
    assert len(uni["candidates"]) == len(world.profiles)
    for w in uni["candidates"]:
        rec = read_json(str(out / "raw" / "wallets" / f"{w}.json.gz"))
        expected = [r for r in world.activity[w] if start <= r["timestamp"] <= end]
        assert len(rec["activity"]) == len(expected), w
        assert len(rec["closed"]) == len([r for r in world.closed[w] if r["timestamp"] >= start]), w
        assert len(rec["positions"]) == len([p for p in world.positions[w] if p["size"] >= 1]), w


def test_market_makers_cross_the_activity_cap(run):
    world, _, _, analysis = run
    mms = [w for w in analysis["wallets"] if world.profiles[w["wallet"]]["arch"] == "mm"]
    assert mms and all(w["style"] == "Market Maker" for w in mms)
    assert all(w["n_trades"] > 5000 for w in mms)
    assert all(w["copy_score"] < w["consistency"] for w in mms)


def test_archetypes_are_recognised(run):
    world, _, _, analysis = run
    arch = {w["wallet"]: world.profiles[w["wallet"]]["arch"] for w in analysis["wallets"]}
    styles = {w["wallet"]: w["style"] for w in analysis["wallets"]}
    grinders = [w for w, a in arch.items() if a == "grinder"]
    assert sum(styles[w] == "Favorite Grinder" for w in grinders) >= len(grinders) - 1
    quiet = [w for w in analysis["wallets"] if arch[w["wallet"]] == "quiet"]
    assert all("Gone quiet" in w["tags"] for w in quiet)


def test_ranked_by_pnl(run):
    pnl = [w["pnl_90d"] for w in run[3]["wallets"]]
    assert pnl == sorted(pnl, reverse=True)
    assert [w["rank"] for w in run[3]["wallets"]] == list(range(1, len(pnl) + 1))


def test_cross_wallet_views(run):
    world, _, _, analysis = run
    twins = {w for w, p in world.profiles.items() if p["arch"] == "twin"}
    top = analysis["linked"][0]
    assert {top["a"], top["b"]} == twins and top["co_entries"] > 10
    assert analysis["consensus"] and all(c["n_wallets"] >= 2 for c in analysis["consensus"])
    mm = {w for w, p in world.profiles.items() if p["arch"] == "mm"}
    assert not any(h["wallet"] in mm for c in analysis["consensus"] for h in c["holders"])
    assert analysis["heat"] and analysis["categories"]["totals"]
    assert analysis["meta"]["tags_enriched"]


def test_report_files(run):
    _, out, _, analysis = run
    paths = write_report(analysis, str(out))
    html = open(paths["dashboard"], encoding="utf-8").read()
    assert "/*__PMSCOUT_DATA__*/null" not in html
    payload = re.search(r"const DATA = (.*?);\n\(function", html, re.S).group(1)
    assert json.loads(payload)["summary"]["n_wallets"] == len(analysis["wallets"])
    header = open(paths["wallets_csv"], encoding="utf-8").readline()
    assert header.startswith("rank,wallet,name,style")


def test_html_payload_cannot_break_out_of_script():
    evil = {"meta": {}, "summary": {}, "wallets": [{"name": "</script><script>alert(1)</script><!--"}]}
    html = render_html(evil)
    script = html.split("const DATA = ", 1)[1].split("\n(function", 1)[0]
    assert "</script" not in script and "<!--" not in script
