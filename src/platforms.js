import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const DEFAULT_PATH = fileURLToPath(new URL('../config/platforms.json', import.meta.url));

export function loadPlatforms(path = DEFAULT_PATH) {
  const raw = JSON.parse(readFileSync(path, 'utf8'));
  return compilePlatforms(raw);
}

export function compilePlatforms(raw) {
  const venues = Object.entries(raw.venues || {}).map(([id, v]) => ({
    id,
    label: v.label || id,
    sources: new Set(v.sources || []),
    programIds: new Set(v.programIds || []),
  }));
  const frontends = Object.entries(raw.frontends || {}).map(([id, f]) => ({
    id,
    label: f.label || id,
    feeAccounts: new Set(f.feeAccounts || []),
  }));
  const labels = Object.fromEntries([...venues, ...frontends].map((p) => [p.id, p.label]));
  return { venues, frontends, labels };
}

function programIdsOf(tx) {
  const ids = new Set();
  for (const ix of tx.instructions || []) {
    ids.add(ix.programId);
    for (const inner of ix.innerInstructions || []) ids.add(inner.programId);
  }
  return ids;
}

function recipientsOf(tx) {
  const to = new Set();
  for (const t of tx.nativeTransfers || []) to.add(t.toUserAccount);
  for (const t of tx.tokenTransfers || []) to.add(t.toUserAccount);
  return to;
}

// Returns { venue, frontend } ids; 'other' / 'direct' when nothing matches.
export function classify(tx, platforms) {
  const programs = programIdsOf(tx);
  let venue = 'other';
  for (const v of platforms.venues) {
    if (v.sources.has(tx.source) || [...v.programIds].some((p) => programs.has(p))) {
      venue = v.id;
      break;
    }
  }
  const recipients = recipientsOf(tx);
  let frontend = 'direct';
  for (const f of platforms.frontends) {
    if ([...f.feeAccounts].some((a) => recipients.has(a))) {
      frontend = f.id;
      break;
    }
  }
  return { venue, frontend };
}
