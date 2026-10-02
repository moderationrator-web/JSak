# JSak · pmscout

**pmscout** analyses every top Polymarket wallet over a rolling 90-day window. It renders the results as a single, self-contained HTML dashboard plus CSV exports.

It answers:

- **Who actually made money in the last 90 days?** It ranks wallets by 90-day PnL (realized plus unrealized on positions opened in the window), not by lifetime totals.
- **How do they make it?** Every wallet gets a trading style (market maker, whale, favorite grinder, longshot hunter, swing trader, specialist, generalist) and tags such as *One big hit*, *Scalper* and *Gone quiet*.
- **Is it repeatable?** A 0–100 *consistency* score combines profitable weeks, profit factor, dependence on a single win, sample size and drawdown. A *copy score* discounts it for things a follower can't replicate.
- **What does smart money hold right now?** *Consensus* lists open positions shared by several top wallets. *Contested* lists markets where top wallets sit on opposite sides. *Market heat* shows where the top wallets traded most.
- **Who might be the same operator?** *Linked wallets* lists pairs with heavily overlapping markets and near-simultaneous entries.

Standard library only (Python 3.9+). Everything comes from Polymarket's public, unauthenticated APIs.

## Quick start

```bash
pip install -e .            # or skip and use `python -m pmscout ...`
pmscout run                 # ~10–20 min for ~500 wallets at the default 8 req/s
open out/dashboard.html
```

Try it offline first. `pmscout demo` runs the whole pipeline against a built-in simulator. Every wallet, market and person in it is fictional, and the dashboard says so in a banner:

```bash
pmscout demo && open out-demo/dashboard.html
```

### Network access

`pmscout run` needs outbound HTTPS to:

- `data-api.polymarket.com` (leaderboards, activity, positions)
- `gamma-api.polymarket.com` (event tags, only with `--enrich-tags`)

In a sandboxed environment with an egress allowlist, such as a Claude Code cloud environment, add both domains to the allowed hosts first.

## Commands

| Command | What it does |
|---|---|
| `pmscout run` | collect + analyze + report in one go |
| `pmscout collect` | download leaderboards and per-wallet history into `out/raw/` |
| `pmscout analyze [--enrich-tags]` | compute metrics into `out/analysis.json` |
| `pmscout report` | render `out/dashboard.html`, `out/wallets.csv`, `out/consensus.csv` |
| `pmscout demo` | full pipeline against the offline simulator into `out-demo/` |

Useful options for `run` / `collect`:

| Option | Default | Meaning |
|---|---|---|
| `--days` | 90 | window length |
| `--depth` | 100 | wallets taken from each overall leaderboard (week, month and all-time, ranked by PnL and by volume) |
| `--category-depth` | 50 | wallets from each category's monthly PnL board (politics, sports, crypto…); 0 disables |
| `--max-wallets` | 500 | cap on wallets analysed in depth, best leaderboard ranks first (0 = everyone) |
| `--wallet 0x…` | | add a specific wallet (repeatable) |
| `--rate` | 8 | max requests per second (Polymarket's documented limits are well above this) |
| `--workers` | 6 | parallel wallet downloads |
| `--max-age-hours` | 12 | reuse downloaded wallet files younger than this (runs are resumable) |
| `--refresh` | | ignore cached wallet files |
| `--enrich-tags` | | categorise markets with Gamma event tags instead of keyword rules alone |

## Method

### Universe

Polymarket has no 90-day leaderboard. pmscout takes the union of the overall WEEK, MONTH and ALL boards (by PnL and by volume) plus every category's MONTH PnL board. That catches wallets that are hot right now as well as long-run winners that stayed active. It then re-ranks all of them on the actual 90-day window.

### 90-day PnL

| Field | Definition |
|---|---|
| `realized_90d` | Positions closed inside the window (`/closed-positions`), plus resolved-but-unredeemed positions (`/positions`, `redeemable`) whose market end date falls in the window |
| `upnl_window` | Unrealized PnL of still-open positions the wallet bought into during the window. Positions untouched since before the window are excluded because their gains accrued earlier. |
| `pnl_90d` | `realized_90d + upnl_window`. This is the ranking metric. |
| `net_cash_90d` | Cross-check from the raw ledger: sells + redemptions + merges + rewards − buys − splits |
| `pnl_ex_best` | `pnl_90d` without the single best bet. When it is ≤ 0 the wallet is tagged *One big hit*. |

### Scores

- **Consistency (0–100)**: 30% share of profitable weeks, 25% profit factor (1 → 0, ≥ 4 → full), 20% (1 − largest win / gross wins), 15% sample size (60+ closed positions = full), 10% (1 − drawdown / peak). The score is halved if realized PnL ≤ 0.
- **Copy score**: consistency × penalties for market making (×0.25), median hold < 2h (×0.6), average buy price ≥ 93¢ (×0.7), < 10 trades (×0.5), inactive 14+ days (×0.7), negative PnL (×0.5).

### Styles

Styles are assigned in this order, and a wallet takes the first one that matches:

1. **Market Maker**: ≥ 80 trades per active day, or ≥ 35% of markets bought on both sides with 1,500+ trades
2. **Whale**: median trade ≥ $5k across ≤ 60 markets
3. **Favorite Grinder**: ≥ 50% of buy volume at ≥ 85¢
4. **Longshot Hunter**: ≥ 35% of buy volume at ≤ 20¢
5. **Swing Trader**: sells ≥ 50% of buy volume, median hold ≤ 72h
6. **Specialist**: ≥ 70% of buy volume in one category
7. **Generalist**: everything else

### Caveats

- **Download caps.** Very active wallets can hit the per-wallet caps (`--max-activity`, default 15,000 rows). Activity is fetched newest-first, so a capped wallet's oldest trades in the window are missing. The dashboard marks these wallets "partial history".
- **Proxy wallets.** Leaderboard wallets are Polymarket proxy wallets, and one person can run several of them.
- **Market makers.** Their PnL includes rebates and inventory effects, so compare them to directional wallets with care.
- **Not advice.** Ninety days is a short sample, and none of this is financial advice.

## Data access details

The Data API's offset pagination is capped (e.g. `/activity` at offset 5,000). When a wallet exceeds the cap, pmscout moves the `end` timestamp back to the oldest row it has seen and restarts at offset 0. It de-duplicates rows that share the boundary timestamp, so no row is skipped or counted twice. Requests share a token-bucket rate limiter and retry on 429/5xx, honouring `Retry-After`.

Each wallet's slimmed history is written to `out/raw/wallets/<address>.json.gz`, which makes runs resumable and re-analysis free.

## Development

```bash
pip install -e '.[dev]'
pytest
```

The tests cover the metric maths on hand-built fixtures and the pagination edge cases (offset caps, boundary duplicates, unsupported sort fallback, retries). They also run an end-to-end pass of the whole pipeline against the simulator, which enforces the real endpoints' limit/offset caps.
