import { classify } from './platforms.js';

export const WSOL = 'So11111111111111111111111111111111111111112';
const LAMPORTS_PER_SOL = 1e9;
const EPS = 1e-12;

// Turns one Helius enhanced transaction into the wallet's SOL<->token trade, if it is one.
// Works from balance deltas rather than the swap event so it handles every venue the same way.
// The SOL delta includes network fees and token-account rent, so costs are slightly conservative.
export function extractTrade(tx, wallet, platforms) {
  if (tx.transactionError) return null;

  let sol = 0;
  const tokens = new Map();
  for (const acct of tx.accountData || []) {
    if (acct.account === wallet) sol += (acct.nativeBalanceChange || 0) / LAMPORTS_PER_SOL;
    for (const change of acct.tokenBalanceChanges || []) {
      if (change.userAccount !== wallet) continue;
      const { tokenAmount, decimals } = change.rawTokenAmount;
      const amount = Number(tokenAmount) / 10 ** decimals;
      if (change.mint === WSOL) sol += amount;
      else tokens.set(change.mint, (tokens.get(change.mint) || 0) + amount);
    }
  }

  const moved = [...tokens].filter(([, amount]) => Math.abs(amount) > EPS);
  if (moved.length !== 1 || Math.abs(sol) < EPS) return null;
  const [mint, amount] = moved[0];
  // A buy spends SOL for tokens, a sell the reverse; same-sign moves are transfers or airdrops.
  if (Math.sign(amount) === Math.sign(sol)) return null;

  const { venue, frontend } = platforms ? classify(tx, platforms) : { venue: 'other', frontend: 'direct' };
  return {
    signature: tx.signature,
    ts: tx.timestamp,
    side: amount > 0 ? 'buy' : 'sell',
    mint,
    qty: Math.abs(amount),
    sol: Math.abs(sol),
    venue,
    frontend,
  };
}

export function extractTrades(txs, wallet, platforms) {
  const trades = [];
  for (const tx of txs) {
    const trade = extractTrade(tx, wallet, platforms);
    if (trade) trades.push(trade);
  }
  return trades.sort((a, b) => a.ts - b.ts);
}
