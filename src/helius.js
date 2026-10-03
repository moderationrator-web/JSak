import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const BASE = 'https://api.helius.xyz/v0';
const CONTINUE_RE = /`before` parameter set to ([1-9A-HJ-NP-Za-km-z]{32,})/;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Thin client for Helius' enhanced transaction history (parsed swaps, balance changes).
export class Helius {
  constructor({ apiKey, cacheDir = '.cache/helius', fetchImpl = globalThis.fetch, retries = 5 } = {}) {
    if (!apiKey) throw new Error('HELIUS_API_KEY is required (free key at https://dashboard.helius.dev)');
    this.apiKey = apiKey;
    this.cacheDir = cacheDir;
    this.fetch = fetchImpl;
    this.retries = retries;
  }

  // Pages after the newest are immutable, so only those are cached.
  async page(address, before) {
    const cacheFile = before && this.cacheDir && join(this.cacheDir, `${address}_${before}.json`);
    if (cacheFile) {
      try {
        return JSON.parse(await readFile(cacheFile, 'utf8'));
      } catch {}
    }

    const url = new URL(`${BASE}/addresses/${address}/transactions`);
    url.searchParams.set('api-key', this.apiKey);
    url.searchParams.set('limit', '100');
    if (before) url.searchParams.set('before', before);

    for (let attempt = 0; ; attempt++) {
      const res = await this.fetch(url);
      if (res.ok) {
        const result = { txs: await res.json() };
        if (cacheFile) {
          await mkdir(this.cacheDir, { recursive: true });
          await writeFile(cacheFile, JSON.stringify(result));
        }
        return result;
      }
      const body = await res.text();
      // Sparse histories make Helius stop early and hand back a cursor to keep going.
      const cont = body.match(CONTINUE_RE);
      if (cont) return { txs: [], continueBefore: cont[1] };
      if ((res.status === 429 || res.status >= 500) && attempt < this.retries) {
        await sleep(500 * 2 ** attempt);
        continue;
      }
      throw new Error(`Helius ${res.status} for ${address}: ${body.slice(0, 200)}`);
    }
  }

  async *history(address, { sinceTs = 0, maxPages = 50 } = {}) {
    let before;
    for (let pageNo = 0; pageNo < maxPages; pageNo++) {
      const { txs, continueBefore } = await this.page(address, before);
      if (continueBefore) {
        before = continueBefore;
        continue;
      }
      if (!txs.length) return;
      for (const tx of txs) {
        if (tx.timestamp < sinceTs) return;
        yield tx;
      }
      before = txs[txs.length - 1].signature;
    }
  }

  async collect(address, opts) {
    const out = [];
    for await (const tx of this.history(address, opts)) out.push(tx);
    return out;
  }
}

export async function mapPool(items, concurrency, fn) {
  const results = new Array(items.length);
  let next = 0;
  const worker = async () => {
    while (next < items.length) {
      const i = next++;
      results[i] = await fn(items[i], i);
    }
  };
  await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, worker));
  return results;
}
