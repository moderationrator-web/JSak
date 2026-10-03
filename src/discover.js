import { extractTrade } from './extract.js';

// Finds wallets that bought several of the given winning tokens, and how early they got in.
// txsByMint: { mint: heliusTx[] } — the history of each token's mint address.
export function discoverFromMints(txsByMint) {
  const wallets = new Map();
  for (const [mint, txs] of Object.entries(txsByMint)) {
    const buyers = [];
    const seen = new Set();
    for (const tx of [...txs].sort((a, b) => a.timestamp - b.timestamp)) {
      const wallet = tx.feePayer;
      if (!wallet || seen.has(wallet)) continue;
      const trade = extractTrade(tx, wallet);
      if (trade?.side !== 'buy' || trade.mint !== mint) continue;
      seen.add(wallet);
      buyers.push({ wallet, ts: trade.ts, sol: trade.sol });
    }
    buyers.forEach((b, i) => {
      let w = wallets.get(b.wallet);
      if (!w) wallets.set(b.wallet, (w = { wallet: b.wallet, hits: 0, entryPercentiles: [], solIn: 0, mints: [] }));
      w.hits++;
      w.entryPercentiles.push(buyers.length > 1 ? i / (buyers.length - 1) : 0);
      w.solIn += b.sol;
      w.mints.push(mint);
    });
  }
  return [...wallets.values()]
    .map((w) => ({
      wallet: w.wallet,
      hits: w.hits,
      avgEntryPercentile: w.entryPercentiles.reduce((a, b) => a + b, 0) / w.entryPercentiles.length,
      solIn: w.solIn,
      mints: w.mints,
    }))
    .sort((a, b) => b.hits - a.hits || a.avgEntryPercentile - b.avgEntryPercentile);
}
