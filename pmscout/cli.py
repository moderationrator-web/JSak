"""Command line interface: ``pmscout run | collect | analyze | report | demo``."""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import List, Optional

from .analysis import run_analysis
from .api import Client
from .collect import collect, read_json
from .report import write_report


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _collect_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--days", type=int, default=90, help="analysis window in days (default 90)")
    p.add_argument("--depth", type=int, default=100,
                   help="wallets taken from each OVERALL leaderboard (WEEK/MONTH/ALL x PNL/VOL); max 1000")
    p.add_argument("--category-depth", type=int, default=50,
                   help="wallets taken from each category's MONTH PnL leaderboard (0 disables)")
    p.add_argument("--max-wallets", type=int, default=500,
                   help="cap on wallets analysed in depth, best leaderboard ranks first (0 = no cap)")
    p.add_argument("--wallet", action="append", default=[], metavar="0x...",
                   help="extra wallet to include (repeatable)")
    p.add_argument("--workers", type=int, default=6, help="parallel wallet downloads")
    p.add_argument("--rate", type=float, default=8.0, help="max API requests per second")
    p.add_argument("--max-age-hours", type=float, default=12.0, help="reuse wallet files younger than this")
    p.add_argument("--refresh", action="store_true", help="ignore cached wallet files")
    p.add_argument("--max-activity", type=int, default=15000, help="activity rows kept per wallet")


def _out_arg(p: argparse.ArgumentParser, default: str = "out") -> None:
    p.add_argument("--out", default=default, help=f"output directory (default ./{default})")


def _do_collect(args, client: Client) -> None:
    collect(client, args.out, days=args.days, depth=args.depth, category_depth=args.category_depth,
            max_wallets=args.max_wallets, extra_wallets=args.wallet, workers=args.workers,
            max_age_hours=args.max_age_hours, refresh=args.refresh,
            wallet_cfg={"max_activity": args.max_activity}, log=_log)


def _do_analyze(args, client: Optional[Client], synthetic: bool = False):
    return run_analysis(args.out, enrich_client=client if getattr(args, "enrich_tags", False) else None,
                        synthetic=synthetic, log=_log)


def _do_report(args, analysis=None) -> None:
    if analysis is None:
        analysis = read_json(os.path.join(args.out, "analysis.json"))
    paths = write_report(analysis, args.out)
    s = analysis["summary"]
    _log(f"\n{s['n_wallets']} wallets analysed, {s['n_profitable']} profitable over the window.")
    top = analysis["wallets"][:10]
    if top:
        _log(f"{'#':>3}  {'wallet':<24} {'style':<17} {'90d PnL':>14} {'win%':>6} {'score':>6}")
        for w in top:
            label = (w["name"] or w["wallet"])[:24]
            wr = f"{w['win_rate'] * 100:.0f}%" if w["win_rate"] is not None else "-"
            _log(f"{w['rank']:>3}  {label:<24} {w['style']:<17} {w['pnl_90d']:>14,.0f} {wr:>6} "
                 f"{w['consistency'] or 0:>6.0f}")
    _log("")
    for k, v in paths.items():
        _log(f"{k:>14}: {v}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="pmscout", description="Analyse top Polymarket wallets over a rolling window.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="collect + analyze + report")
    _collect_args(p_run)
    _out_arg(p_run)
    p_run.add_argument("--enrich-tags", action="store_true", help="look up Gamma event tags for categories")

    p_col = sub.add_parser("collect", help="download leaderboards and wallet histories")
    _collect_args(p_col)
    _out_arg(p_col)

    p_an = sub.add_parser("analyze", help="compute metrics from downloaded data")
    _out_arg(p_an)
    p_an.add_argument("--enrich-tags", action="store_true", help="look up Gamma event tags for categories")
    p_an.add_argument("--rate", type=float, default=8.0)

    p_rep = sub.add_parser("report", help="render dashboard.html and CSVs from analysis.json")
    _out_arg(p_rep)

    p_demo = sub.add_parser("demo", help="run the full pipeline against a synthetic, offline simulator")
    _out_arg(p_demo, "out-demo")
    p_demo.add_argument("--seed", type=int, default=7)

    args = ap.parse_args(argv)
    t0 = time.time()

    if args.cmd == "demo":
        from .synthetic import FakeTransport, World
        world = World(seed=args.seed)
        client = Client(transport=FakeTransport(world), rate=1e6, sleep=lambda s: None)
        collect(client, args.out, days=90, depth=50, category_depth=25, max_wallets=0, workers=4,
                refresh=True, now=world.now, log=_log)
        analysis = run_analysis(args.out, enrich_client=client, synthetic=True, log=_log)
        _do_report(args, analysis)
    elif args.cmd == "run":
        client = Client(rate=args.rate)
        _do_collect(args, client)
        _do_report(args, _do_analyze(args, client))
    elif args.cmd == "collect":
        _do_collect(args, Client(rate=args.rate))
    elif args.cmd == "analyze":
        _do_analyze(args, Client(rate=args.rate))
    elif args.cmd == "report":
        _do_report(args)
    _log(f"done in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
