# JSak

`jsak` ranks Solana memecoin traders (Pump.fun, Fomo, Phantom) by **realized** performance over a lookback window (default 90 days). It produces a sortable HTML leaderboard and a CSV watchlist you can copy-trade or monitor.

Data comes from the [Helius](https://dashboard.helius.dev) enhanced-transactions API (a free key is enough to start).

## The app

`dist/jsak.html` is the whole tool in one file. Download it, double-click to open it in your browser, and:

1. Pick **Winning tokens** (paste the mints of top Pump.fun runners) or **Wallet list**.
2. Paste your Helius API key. It's saved only in that browser.
3. Click **Run scan**. It finds the buyers, pulls each wallet's history, and ranks them.

It opens on synthetic demo data so you can explore first. Results export as a CSV watchlist or JSON. Rebuild it with `npm run app`.

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
