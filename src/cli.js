#!/usr/bin/env node
import { readFileSync } from 'node:fs';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { discoverFromMints } from './discover.js';
import { extractTrades } from './extract.js';
import { Helius, mapPool } from './helius.js';
import { analyzeWallet, rankWallets } from './metrics.js';
import { compilePlatforms } from './platforms.js';
import { renderApp, renderReport } from './report.js';
import { buildAppZip } from './zip.js';

const USAGE = `wallet-scout — rank Solana memecoin wallets by realized performance

Usage:
  wallet-scout discover --mints <file> [--days 90] [--max-pages 10] [--top 200] [--out data/candidates.json]
      Find wallets that bought several of the listed winning tokens (one mint per line).
  wallet-scout analyze --wallets <file> [--days 90] [--max-pages 50] [--concurrency 4]
               [--out data/analysis.json] [--html data/report.html]
      Pull each wallet's swaps, compute FIFO PnL, score and rank. <file> is a
      newline list of addresses or the candidates.json written by discover.
  wallet-scout report --in data/analysis.json [--out data/report.html]
  wallet-scout app [--out data/wallet-scout.html]   (also writes WalletScout.zip next to it)
      Build the standalone app: open it in a browser, paste a Helius key and
      wallets or winning tokens, and it runs the scan itself. Opens on demo data.

Options:
  --platforms <file>   Venue / frontend config (default config/platforms.json)

Env:
  HELIUS_API_KEY       Required for discover and analyze.`;

function loadPlatforms(path = fileURLToPath(new URL('../config/platforms.json', import.meta.url))) {
  return compilePlatforms(JSON.parse(readFileSync(path, 'utf8')));
}

async function write(path, content) {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, content);
  console.error(`wrote ${path}`);
}

async function readAddresses(path) {
  const text = await readFile(path, 'utf8');
  if (path.endsWith('.json')) {
    const parsed = JSON.parse(text);
    const list = Array.isArray(parsed) ? parsed : parsed.candidates;
    return list.map((c) => (typeof c === 'string' ? c : c.wallet));
  }
  return text.split(/\s+/).map((s) => s.trim()).filter((s) => s && !s.startsWith('#'));
}

function buildAnalysis(results, days, platforms, extra = {}) {
  return {
    generatedAt: new Date().toISOString(),
    days,
    labels: platforms.labels,
    frontendIds: platforms.frontends.map((f) => f.id),
    ...extra,
    wallets: rankWallets(results),
  };
}

async function main() {
  const { positionals, values } = parseArgs({
    allowPositionals: true,
    options: {
      mints: { type: 'string' },
      wallets: { type: 'string' },
      in: { type: 'string' },
      out: { type: 'string' },
      html: { type: 'string' },
      platforms: { type: 'string' },
      days: { type: 'string', default: '90' },
      'max-pages': { type: 'string' },
      concurrency: { type: 'string', default: '4' },
      top: { type: 'string', default: '200' },
      help: { type: 'boolean', short: 'h' },
    },
  });
  const cmd = positionals[0];
  if (!cmd || values.help) return console.log(USAGE);

  const days = Number(values.days);
  const sinceTs = Math.floor(Date.now() / 1000) - days * 86400;
  const platforms = loadPlatforms(values.platforms);
  const concurrency = Number(values.concurrency);
  const client = () => new Helius({ apiKey: process.env.HELIUS_API_KEY });

  if (cmd === 'app' || cmd === 'demo') {
    // With no embedded results the app builds its demo data on open.
    const out = values.out || 'data/wallet-scout.html';
    const html = renderApp(null);
    await write(out, html);
    await write(join(dirname(out), 'WalletScout.zip'), buildAppZip(html));
    return;
  }

  if (cmd === 'discover') {
    if (!values.mints) throw new Error('--mints <file> is required');
    const mints = await readAddresses(values.mints);
    const helius = client();
    const maxPages = Number(values['max-pages'] || 10);
    const txsByMint = {};
    await mapPool(mints, concurrency, async (mint) => {
      txsByMint[mint] = await helius.collect(mint, { sinceTs, maxPages });
      console.error(`${mint}: ${txsByMint[mint].length} txs`);
    });
    const candidates = discoverFromMints(txsByMint).slice(0, Number(values.top));
    await write(values.out || 'data/candidates.json', JSON.stringify({ generatedAt: new Date().toISOString(), days, mints, candidates }, null, 2));
    return;
  }

  if (cmd === 'analyze') {
    if (!values.wallets) throw new Error('--wallets <file> is required');
    const wallets = [...new Set(await readAddresses(values.wallets))];
    const helius = client();
    const maxPages = Number(values['max-pages'] || 50);
    let done = 0;
    const results = await mapPool(wallets, concurrency, async (wallet) => {
      try {
        const txs = await helius.collect(wallet, { sinceTs, maxPages });
        const result = analyzeWallet(wallet, extractTrades(txs, wallet, platforms));
        if (txs.length >= maxPages * 100) result.flags.push('truncated');
        console.error(`[${++done}/${wallets.length}] ${wallet} trades=${result.trades} pnl=${result.realizedPnlSol.toFixed(2)} SOL`);
        return result;
      } catch (err) {
        console.error(`[${++done}/${wallets.length}] ${wallet} failed: ${err.message}`);
        return null;
      }
    });
    const analysis = buildAnalysis(results.filter(Boolean), days, platforms);
    await write(values.out || 'data/analysis.json', JSON.stringify(analysis, (_, v) => (v === Infinity ? 'Infinity' : v)));
    await write(values.html || 'data/report.html', renderReport(analysis));
    return;
  }

  if (cmd === 'report') {
    if (!values.in) throw new Error('--in <analysis.json> is required');
    const analysis = JSON.parse(await readFile(values.in, 'utf8'));
    await write(values.out || 'data/report.html', renderReport(analysis));
    return;
  }

  throw new Error(`unknown command "${cmd}"\n\n${USAGE}`);
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});
