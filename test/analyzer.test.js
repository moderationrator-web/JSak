import assert from 'node:assert/strict';
import { test } from 'node:test';
import { generateDemo } from '../src/demo.js';
import { discoverFromMints } from '../src/discover.js';
import { WSOL, extractTrade } from '../src/extract.js';
import { Helius } from '../src/helius.js';
import { analyzeWallet } from '../src/metrics.js';
import { compilePlatforms } from '../src/platforms.js';
import { buildPositions } from '../src/pnl.js';
import { buildAppZip, createZip } from '../src/zip.js';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { bundleEngine, renderApp } from '../src/report.js';

const W = 'Wa11et1111111111111111111111111111111111111';
const MINT = 'Mint111111111111111111111111111111111111pump';
const PHANTOM_FEE = 'PhantomFee11111111111111111111111111111111';

const platforms = compilePlatforms({
  venues: { pumpfun: { label: 'Pump.fun', sources: ['PUMP_FUN'], programIds: ['6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P'] } },
  frontends: { phantom: { label: 'Phantom', feeAccounts: [PHANTOM_FEE] } },
});

// Minimal Helius enhanced transaction: wallet's SOL change plus token balance changes.
function tx({ sig = 's', ts = 1000, lamports, mint = MINT, amount, decimals = 6, wallet = W, source = 'PUMP_FUN', extra = {} }) {
  return {
    signature: sig,
    timestamp: ts,
    source,
    feePayer: wallet,
    accountData: [
      {
        account: wallet,
        nativeBalanceChange: lamports,
        tokenBalanceChanges: [{ userAccount: wallet, mint, rawTokenAmount: { tokenAmount: String(amount * 10 ** decimals), decimals } }],
      },
    ],
    ...extra,
  };
}

test('extracts a pump.fun buy from balance deltas', () => {
  const t = extractTrade(tx({ lamports: -1.5e9, amount: 1000 }), W, platforms);
  assert.equal(t.side, 'buy');
  assert.equal(t.mint, MINT);
  assert.equal(t.qty, 1000);
  assert.equal(t.sol, 1.5);
  assert.equal(t.venue, 'pumpfun');
  assert.equal(t.frontend, 'direct');
});

test('counts wrapped SOL as SOL and detects frontend via fee account', () => {
  const t = extractTrade(
    {
      signature: 'x',
      timestamp: 1,
      source: 'JUPITER',
      nativeTransfers: [{ fromUserAccount: W, toUserAccount: PHANTOM_FEE, amount: 1e6 }],
      accountData: [
        {
          account: W,
          nativeBalanceChange: -5000,
          tokenBalanceChanges: [
            { userAccount: W, mint: WSOL, rawTokenAmount: { tokenAmount: '2000000000', decimals: 9 } },
            { userAccount: W, mint: MINT, rawTokenAmount: { tokenAmount: '-500000000', decimals: 6 } },
          ],
        },
      ],
    },
    W,
    platforms,
  );
  assert.equal(t.side, 'sell');
  assert.ok(Math.abs(t.sol - 1.999995) < 1e-9);
  assert.equal(t.frontend, 'phantom');
  assert.equal(t.venue, 'other');
});

test('ignores failed txs, plain transfers and token-for-token swaps', () => {
  assert.equal(extractTrade({ ...tx({ lamports: -1e9, amount: 5 }), transactionError: { x: 1 } }, W), null);
  assert.equal(extractTrade(tx({ lamports: -5000, amount: -5 }), W), null);
  const twoTokens = tx({ lamports: -5000, amount: 5 });
  twoTokens.accountData[0].tokenBalanceChanges.push({ userAccount: W, mint: 'Other', rawTokenAmount: { tokenAmount: '-1', decimals: 0 } });
  assert.equal(extractTrade(twoTokens, W), null);
});

test('FIFO PnL with partial sells and unmatched sells', () => {
  const [p] = buildPositions([
    { ts: 0, side: 'buy', mint: 'A', qty: 100, sol: 1 },
    { ts: 10, side: 'buy', mint: 'A', qty: 100, sol: 2 },
    { ts: 20, side: 'sell', mint: 'A', qty: 150, sol: 3 },
    { ts: 30, side: 'sell', mint: 'A', qty: 100, sol: 2 }, // only 50 left; 50 unmatched
  ]);
  // Matched: 100@0.01 + 100@0.02 = 3 cost. Proceeds: 150*0.02 + 50*0.02 = 4.
  assert.ok(Math.abs(p.matchedCost - 3) < 1e-9);
  assert.ok(Math.abs(p.realized - 1) < 1e-9);
  assert.ok(Math.abs(p.unmatchedProceeds - 1) < 1e-9);
  assert.equal(p.closed, true);
});

test('wallet metrics, flags and score', () => {
  const trades = [];
  for (let i = 0; i < 12; i++) {
    const mint = 'M' + i;
    trades.push({ ts: i * 86400, side: 'buy', mint, qty: 10, sol: 1, venue: 'pumpfun', frontend: 'fomo' });
    trades.push({ ts: i * 86400 + 3600, side: 'sell', mint, qty: 10, sol: i < 9 ? 2 : 0.5, venue: 'pumpfun', frontend: 'fomo' });
  }
  const r = analyzeWallet(W, trades);
  assert.equal(r.closedPositions, 12);
  assert.equal(r.winRate, 0.75);
  assert.ok(Math.abs(r.realizedPnlSol - 7.5) < 1e-9);
  assert.equal(r.profitFactor, 6);
  assert.equal(r.medianHoldSec, 3600);
  assert.deepEqual(r.flags, []);
  assert.ok(r.score > 50);
  assert.equal(r.frontends.fomo, r.volumeSol);

  const bot = analyzeWallet(W, trades.map((t) => (t.side === 'sell' ? { ...t, ts: t.ts - 3595 } : t)));
  assert.ok(bot.flags.includes('bot'));
  assert.ok(bot.score < r.score * 0.5);

  assert.equal(analyzeWallet(W, [{ ts: 0, side: 'buy', mint: 'A', qty: 1, sol: 1 }]).score, 0);
});

test('discover ranks repeat early buyers first', () => {
  const buy = (wallet, ts, mint) => tx({ sig: wallet + ts, ts, wallet, mint, lamports: -1e9, amount: 10 });
  const res = discoverFromMints({
    A: [buy('early', 1, 'A'), buy('late', 5, 'A'), buy('once', 3, 'A')],
    B: [buy('late', 9, 'B'), buy('early', 2, 'B')],
  });
  assert.deepEqual(res.map((r) => r.wallet), ['early', 'late', 'once']);
  assert.equal(res[0].hits, 2);
  assert.equal(res[0].avgEntryPercentile, 0);
});

test('helius client paginates, follows continuation cursors and stops at the window', async () => {
  const calls = [];
  const pages = {
    head: { ok: true, body: [{ signature: 'a', timestamp: 300 }, { signature: 'b', timestamp: 250 }] },
    b: { ok: false, status: 404, body: 'Failed to find events. query the API again with the `before` parameter set to cccccccccccccccccccccccccccccccccc.' },
    cccccccccccccccccccccccccccccccccc: { ok: true, body: [{ signature: 'd', timestamp: 200 }, { signature: 'e', timestamp: 50 }] },
  };
  const fetchImpl = async (url) => {
    const before = url.searchParams.get('before') || 'head';
    calls.push(before);
    const p = pages[before];
    return { ok: p.ok, status: p.status || 200, json: async () => p.body, text: async () => p.body };
  };
  const h = new Helius({ apiKey: 'k', cacheDir: null, fetchImpl });
  const txs = await h.collect('addr', { sinceTs: 100 });
  assert.deepEqual(txs.map((t) => t.signature), ['a', 'b', 'd']);
  assert.deepEqual(calls, ['head', 'b', 'cccccccccccccccccccccccccccccccccc']);
});

test('demo data renders into a self-contained report', () => {
  const results = generateDemo({ days: 90, now: 1_750_000_000 }).map(({ wallet, archetype, trades }) => ({ ...analyzeWallet(wallet, trades), archetype }));
  assert.ok(results.length >= 20);
  assert.ok(results.some((r) => r.flags.includes('bot')));
  const html = renderApp({ generatedAt: 'x', days: 90, demo: true, labels: platforms.labels, frontendIds: ['phantom'], wallets: results });
  assert.match(html, /^<!doctype html>/);
  assert.match(html, /Synthetic demo data/);
  assert.doesNotMatch(html, /__(DATA|TITLE|ENGINE|PLATFORMS)__/);
  assert.match(renderApp(null, { standalone: false }), /^<title>/);
});

test('bundled engine runs outside Node modules and matches the CLI', () => {
  const ENGINE = new Function(bundleEngine() + '\nreturn ENGINE;')();
  const trades = generateDemo({ now: 1_750_000_000 })[0].trades;
  assert.deepEqual(ENGINE.analyzeWallet('w', trades), analyzeWallet('w', trades));
});

test('zip archive extracts with standard tools', () => {
  const dir = mkdtempSync(join(tmpdir(), 'wallet-scout-'));
  const html = renderApp(null);
  writeFileSync(join(dir, 'WalletScout.zip'), buildAppZip(html));
  const python = `import zipfile,sys; z=zipfile.ZipFile(sys.argv[1]); assert z.testzip() is None; z.extractall(sys.argv[2]); print(*z.namelist(), sep='|')`;
  const names = execFileSync('python3', ['-c', python, join(dir, 'WalletScout.zip'), dir], { encoding: 'utf8' }).trim();
  assert.equal(names, 'Wallet Scout/Wallet Scout.html|Wallet Scout/How to open.txt');
  assert.equal(readFileSync(join(dir, 'Wallet Scout', 'Wallet Scout.html'), 'utf8'), html);
  assert.equal(createZip([]).length, 22);
});
