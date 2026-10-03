// Synthetic trade data for previewing the dashboard without an API key.
// Every address is prefixed "DEMo" so it can't be mistaken for a real wallet.

const B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';

function rng(seed) {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const ARCHETYPES = [
  { name: 'swing', count: 8, tokens: [30, 80], size: [0.5, 4], winP: 0.55, win: [0.3, 4], loss: [-0.7, -0.15], hold: [600, 86400], parts: 2 },
  { name: 'sniper-bot', count: 4, tokens: [300, 900], size: [0.2, 1.5], winP: 0.6, win: [0.05, 0.6], loss: [-0.4, -0.05], hold: [2, 15], parts: 1 },
  { name: 'gambler', count: 6, tokens: [15, 40], size: [1, 10], winP: 0.15, win: [0.5, 3], loss: [-0.95, -0.4], hold: [300, 20000], parts: 1, jackpot: true },
  { name: 'degen-loser', count: 8, tokens: [20, 120], size: [0.2, 3], winP: 0.3, win: [0.1, 1.5], loss: [-0.9, -0.3], hold: [120, 7200], parts: 1 },
  { name: 'whale', count: 4, tokens: [10, 30], size: [20, 80], winP: 0.5, win: [0.2, 1.5], loss: [-0.5, -0.1], hold: [3600, 7 * 86400], parts: 3 },
];

export function generateDemo({ days = 90, seed = 7, now = Math.floor(Date.now() / 1000) } = {}) {
  const r = rng(seed);
  const between = ([a, b]) => a + r() * (b - a);
  const id = (prefix, suffix = '') => prefix + Array.from({ length: 40 - prefix.length - suffix.length }, () => B58[Math.floor(r() * B58.length)]).join('') + suffix;
  const pick = (weights) => {
    let x = r() * weights.reduce((s, [, w]) => s + w, 0);
    for (const [v, w] of weights) if ((x -= w) <= 0) return v;
    return weights[0][0];
  };
  const start = now - days * 86400;
  const mints = Array.from({ length: 400 }, () => id('DEMo', 'pump'));
  const wallets = [];

  for (const a of ARCHETYPES) {
    for (let n = 0; n < a.count; n++) {
      const wallet = id('DEMo');
      const frontend = pick([['phantom', 4], ['fomo', 3], ['direct', 3]]);
      const trades = [];
      const tokenCount = Math.round(between(a.tokens));
      for (let k = 0; k < tokenCount; k++) {
        const mint = mints[Math.floor(r() * mints.length)];
        const ts = Math.floor(start + r() * (days * 86400 - 86400));
        const size = between(a.size);
        const qty = size * 1e6 * between([0.5, 2]);
        let roi = r() < a.winP ? between(a.win) : between(a.loss);
        if (a.jackpot && r() < 0.04) roi = between([20, 80]);
        const venue = pick([['pumpfun', 7], ['jupiter', 2], ['raydium', 1]]);
        const fe = r() < 0.85 ? frontend : 'direct';
        const sig = () => id('DEMo');
        trades.push({ signature: sig(), ts, side: 'buy', mint, qty, sol: size, venue, frontend: fe });
        // Leave ~10% of positions open to exercise open-position handling.
        if (r() < 0.1) continue;
        let left = qty;
        let t = ts;
        for (let p = 0; p < a.parts; p++) {
          const last = p === a.parts - 1;
          const q = last ? left : left * between([0.3, 0.6]);
          left -= q;
          t += Math.floor(between(a.hold) / a.parts);
          trades.push({ signature: sig(), ts: t, side: 'sell', mint, qty: q, sol: (q / qty) * size * (1 + roi), venue, frontend: fe });
        }
      }
      wallets.push({ wallet, archetype: a.name, trades: trades.sort((x, y) => x.ts - y.ts) });
    }
  }
  return wallets;
}
