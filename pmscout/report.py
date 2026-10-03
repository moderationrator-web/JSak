"""Render ``analysis.json`` into a self-contained HTML dashboard and CSV exports."""

from __future__ import annotations

import csv
import json
import os
from importlib import resources
from typing import Any, Dict, List

WALLET_COLUMNS = [
    "rank", "wallet", "name", "style", "tags", "pnl_90d", "realized_90d", "upnl_window", "net_cash_90d",
    "roi", "win_rate", "profit_factor", "n_resolved", "wins", "losses", "pct_up_weeks", "sharpe", "max_dd",
    "concentration", "top_win_share", "volume", "n_trades", "active_days", "trades_per_day", "median_trade",
    "n_markets", "avg_buy_price", "fav_share", "long_share", "sell_ratio", "two_sided", "median_hold_h",
    "top_cat", "top_cat_share", "open_value", "upnl_all", "n_open", "consistency", "copy_score",
    "lb_month_rank", "lb_month_pnl", "lb_all_rank", "lb_all_pnl", "last_trade", "truncated",
]


def _template() -> str:
    return resources.files("pmscout").joinpath("templates/dashboard.html").read_text(encoding="utf-8")


def render_html(analysis: Dict[str, Any]) -> str:
    payload = json.dumps(analysis, separators=(",", ":"), allow_nan=False)
    payload = payload.replace("</", "<\\/").replace("<!--", "<\\!--")
    html = _template()
    marker = "/*__PMSCOUT_DATA__*/null"
    if marker not in html:
        raise RuntimeError("dashboard template is missing the data marker")
    return html.replace(marker, payload, 1)


def _csv_value(v: Any) -> Any:
    if isinstance(v, list):
        return "; ".join(str(x) for x in v)
    if isinstance(v, bool):
        return "yes" if v else "no"
    return "" if v is None else v


def write_csv(path: str, rows: List[dict], columns: List[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(columns)
        for r in rows:
            wr.writerow([_csv_value(r.get(c)) for c in columns])


def write_report(analysis: Dict[str, Any], out_dir: str) -> Dict[str, str]:
    os.makedirs(out_dir, exist_ok=True)
    paths = {
        "dashboard": os.path.join(out_dir, "dashboard.html"),
        "wallets_csv": os.path.join(out_dir, "wallets.csv"),
        "consensus_csv": os.path.join(out_dir, "consensus.csv"),
    }
    with open(paths["dashboard"], "w", encoding="utf-8") as f:
        f.write(render_html(analysis))
    write_csv(paths["wallets_csv"], analysis["wallets"], WALLET_COLUMNS)
    cons = [dict(c, holders="; ".join(f"{h['name']} (${h['value']:,.0f} @ {h['avg']})" for h in c["holders"]))
            for c in analysis["consensus"]]
    write_csv(paths["consensus_csv"], cons,
              ["n_wallets", "title", "outcome", "category", "value", "avg_entry", "cur", "edge", "conviction",
               "against_n", "against_value", "end", "eventSlug", "c", "holders"])
    return paths
