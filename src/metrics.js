import { buildPositions } from './pnl.js';

const DAY = 86400;

// Bots and MEV wallets look great on raw PnL but can't be copied by a human.
const BOT_TRADES_PER_DAY = 150;
const BOT_MEDIAN_HOLD_SEC = 20;
const MIN_CLOSED_FOR_CONFIDENCE = 10;
const ONE_HIT_SHARE = 0.8;

function median(values) {
  if (!values.length) return null;
  const s = [...values].sort((a, b) => a - b);
  const mid = s.length >> 1;
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

function tally(trades, key) {
  const out = {};
  for (const t of trades) out[t[key]] = (out[t[key]] || 0) + t.sol;
  return out;
}

export function analyzeWallet(wallet, trades) {
  const positions = buildPositions(trades);
  const closed = positions.filter((p) => p.closed);
  const realizedPositions = positions.filter((p) => p.matchedCost > 0);

  const realizedPnl = realizedPositions.reduce((s, p) => s + p.realized, 0);
  const invested = realizedPositions.reduce((s, p) => s + p.matchedCost, 0);
  const grossWin = realizedPositions.filter((p) => p.realized > 0).reduce((s, p) => s + p.realized, 0);
  const grossLoss = -realizedPositions.filter((p) => p.realized < 0).reduce((s, p) => s + p.realized, 0);
  const wins = closed.filter((p) => p.realized > 0).length;

  const best = realizedPositions.reduce((a, p) => (!a || p.realized > a.realized ? p : a), null);
  const worst = realizedPositions.reduce((a, p) => (!a || p.realized < a.realized ? p : a), null);

  const firstTs = trades.length ? trades[0].ts : null;
  const lastTs = trades.length ? trades[trades.length - 1].ts : null;
  const activeDays = new Set(trades.map((t) => Math.floor(t.ts / DAY))).size;
  const tradesPerDay = activeDays ? trades.length / activeDays : 0;
  const medianHoldSec = median(closed.map((p) => p.avgHoldSec).filter((v) => v != null));

  const flags = [];
  if (tradesPerDay > BOT_TRADES_PER_DAY || (medianHoldSec != null && medianHoldSec < BOT_MEDIAN_HOLD_SEC)) flags.push('bot');
  if (closed.length < MIN_CLOSED_FOR_CONFIDENCE) flags.push('low-sample');
  if (grossWin > 0 && best && best.realized / grossWin > ONE_HIT_SHARE && realizedPositions.length > 1) flags.push('one-hit');

  const summary = {
    wallet,
    trades: trades.length,
    tokens: positions.length,
    closedPositions: closed.length,
    openPositions: positions.length - closed.length,
    volumeSol: trades.reduce((s, t) => s + t.sol, 0),
    investedSol: invested,
    realizedPnlSol: realizedPnl,
    roi: invested > 0 ? realizedPnl / invested : null,
    winRate: closed.length ? wins / closed.length : null,
    profitFactor: grossLoss > 0 ? grossWin / grossLoss : grossWin > 0 ? Infinity : null,
    medianRoi: median(closed.map((p) => p.roi).filter((v) => v != null)),
    medianHoldSec,
    activeDays,
    tradesPerDay,
    openCostSol: positions.reduce((s, p) => s + p.openCost, 0),
    best: best && { mint: best.mint, realized: best.realized, roi: best.roi },
    worst: worst && { mint: worst.mint, realized: worst.realized, roi: worst.roi },
    venues: tally(trades, 'venue'),
    frontends: tally(trades, 'frontend'),
    firstTs,
    lastTs,
    flags,
  };
  summary.score = scoreWallet(summary);
  return { ...summary, positions: positions.sort((a, b) => b.realized - a.realized) };
}

// 0-100. Rewards size of profit (log-scaled), consistency (win rate, profit factor)
// and sample size, then discounts patterns a person can't realistically copy.
export function scoreWallet(s) {
  if (!(s.realizedPnlSol > 0)) return 0;
  const clamp = (v) => Math.max(0, Math.min(1, v));
  const pnl = clamp(Math.log10(1 + s.realizedPnlSol) / 3); // 999 SOL caps the term
  const win = clamp(s.winRate ?? 0);
  const pf = clamp((Number.isFinite(s.profitFactor) ? s.profitFactor : 5) / 5);
  const sample = clamp(s.closedPositions / 50);
  let score = 100 * (0.35 * pnl + 0.25 * win + 0.2 * pf + 0.2 * sample);
  if (s.flags.includes('bot')) score *= 0.3;
  if (s.flags.includes('one-hit')) score *= 0.6;
  return Math.round(score * 10) / 10;
}

export function rankWallets(results) {
  return [...results].sort((a, b) => b.score - a.score || b.realizedPnlSol - a.realizedPnlSol);
}
