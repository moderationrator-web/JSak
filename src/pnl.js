// FIFO cost-basis accounting per token, all values in SOL.
// Sells beyond what the wallet bought inside the window (pre-window buys, transfers in)
// are tracked as "unmatched" and kept out of realized PnL rather than counted as free profit.

const DUST_FRACTION = 0.01;

export function buildPositions(trades) {
  const byMint = new Map();
  for (const t of [...trades].sort((a, b) => a.ts - b.ts)) {
    let p = byMint.get(t.mint);
    if (!p) {
      p = {
        mint: t.mint,
        lots: [],
        held: 0,
        peakHeld: 0,
        buys: 0,
        sells: 0,
        boughtSol: 0,
        soldSol: 0,
        matchedCost: 0,
        matchedProceeds: 0,
        unmatchedProceeds: 0,
        holdWeight: 0,
        matchedQty: 0,
        firstTs: t.ts,
        lastTs: t.ts,
      };
      byMint.set(t.mint, p);
    }
    p.lastTs = t.ts;

    if (t.side === 'buy') {
      p.buys++;
      p.boughtSol += t.sol;
      p.lots.push({ qty: t.qty, cpu: t.sol / t.qty, ts: t.ts });
      p.held += t.qty;
      p.peakHeld = Math.max(p.peakHeld, p.held);
      continue;
    }

    p.sells++;
    p.soldSol += t.sol;
    const ppu = t.sol / t.qty;
    let remaining = t.qty;
    while (remaining > 0 && p.lots.length) {
      const lot = p.lots[0];
      const take = Math.min(remaining, lot.qty);
      p.matchedCost += take * lot.cpu;
      p.matchedProceeds += take * ppu;
      p.holdWeight += take * (t.ts - lot.ts);
      p.matchedQty += take;
      lot.qty -= take;
      remaining -= take;
      if (lot.qty <= 1e-12) p.lots.shift();
    }
    p.held = Math.max(0, p.held - (t.qty - remaining));
    if (remaining > 0) p.unmatchedProceeds += remaining * ppu;
  }

  return [...byMint.values()].map((p) => {
    const openCost = p.lots.reduce((sum, lot) => sum + lot.qty * lot.cpu, 0);
    const realized = p.matchedProceeds - p.matchedCost;
    const closed = p.matchedQty > 0 && p.held <= p.peakHeld * DUST_FRACTION;
    return {
      mint: p.mint,
      buys: p.buys,
      sells: p.sells,
      boughtSol: p.boughtSol,
      soldSol: p.soldSol,
      matchedCost: p.matchedCost,
      realized,
      roi: p.matchedCost > 0 ? realized / p.matchedCost : null,
      unmatchedProceeds: p.unmatchedProceeds,
      openCost,
      closed,
      avgHoldSec: p.matchedQty > 0 ? p.holdWeight / p.matchedQty : null,
      firstTs: p.firstTs,
      lastTs: p.lastTs,
    };
  });
}
