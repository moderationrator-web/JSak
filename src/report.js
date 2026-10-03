// Renders the ranked analysis as one self-contained HTML dashboard.

const MAX_POSITIONS = 60;

export function renderReport(analysis) {
  const slim = {
    ...analysis,
    wallets: analysis.wallets.map((w) => ({ ...w, positions: w.positions.slice(0, MAX_POSITIONS) })),
  };
  const data = JSON.stringify(slim, (_, v) => (v === Infinity ? 'Infinity' : v)).replace(/</g, '\\u003c');
  const title = analysis.demo ? 'Wallet Leaderboard (demo)' : 'Wallet Leaderboard';
  // Function replacers so "$&"-style sequences in the data are never interpreted.
  return TEMPLATE.replaceAll('__TITLE__', () => title).replace('__DATA__', () => data);
}

const TEMPLATE = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root {
  --bg: #f7f7f5; --surface: #ffffff; --text: #1d1d1b; --muted: #6b6b66; --line: #e4e3df;
  --accent: #5b4bdb; --pos: #1a7f4b; --neg: #c0392b; --warn: #a86400; --chip: #efeee9;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #121211; --surface: #1c1c1a; --text: #ecebe6; --muted: #9a9a93; --line: #2e2e2b;
    --accent: #9c90ff; --pos: #4cc38a; --neg: #ff6b5e; --warn: #f0b24a; --chip: #2a2a27;
  }
}
:root[data-theme="dark"] {
  --bg: #121211; --surface: #1c1c1a; --text: #ecebe6; --muted: #9a9a93; --line: #2e2e2b;
  --accent: #9c90ff; --pos: #4cc38a; --neg: #ff6b5e; --warn: #f0b24a; --chip: #2a2a27;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1200px; margin: 0 auto; padding: 24px 16px 64px; }
h1 { font-size: 22px; margin: 0 0 4px; }
.sub { color: var(--muted); margin: 0 0 20px; }
.banner { background: var(--chip); border-left: 3px solid var(--warn); padding: 10px 12px; margin-bottom: 20px; border-radius: 4px; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 20px; }
.kpi { background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px; }
.kpi .v { font-size: 22px; font-weight: 600; font-variant-numeric: tabular-nums; }
.kpi .l { color: var(--muted); font-size: 12px; }
.controls { display: flex; flex-wrap: wrap; gap: 12px 20px; align-items: center; margin-bottom: 12px; }
.controls label { color: var(--muted); display: flex; gap: 6px; align-items: center; }
input[type=number], input[type=search], select { background: var(--surface); color: var(--text); border: 1px solid var(--line); border-radius: 6px; padding: 5px 8px; font: inherit; }
input[type=number] { width: 70px; }
.tablewrap { overflow-x: auto; background: var(--surface); border: 1px solid var(--line); border-radius: 8px; }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
th, td { padding: 8px 10px; text-align: right; white-space: nowrap; border-bottom: 1px solid var(--line); }
th:nth-child(-n+2), td:nth-child(-n+2) { text-align: left; }
th { font-size: 12px; color: var(--muted); font-weight: 500; cursor: pointer; user-select: none; position: sticky; top: 0; background: var(--surface); }
th[data-dir]::after { content: attr(data-dir); margin-left: 4px; }
tbody tr { cursor: pointer; }
tbody tr:hover { background: var(--chip); }
tbody tr.sel { background: var(--chip); box-shadow: inset 3px 0 var(--accent); }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12.5px; }
.pos { color: var(--pos); } .neg { color: var(--neg); }
.flag { display: inline-block; font-size: 11px; padding: 1px 6px; border-radius: 10px; background: var(--chip); color: var(--warn); margin-left: 4px; }
.bar { display: inline-block; height: 6px; border-radius: 3px; background: var(--accent); vertical-align: middle; }
#detail { margin-top: 20px; background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 16px; }
#detail:empty { display: none; }
#detail h2 { font-size: 16px; margin: 0 0 12px; word-break: break-all; }
.grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; margin-bottom: 16px; }
.mix div { display: grid; grid-template-columns: 90px 1fr 60px; gap: 8px; align-items: center; margin: 4px 0; font-size: 13px; }
.mix .track { background: var(--chip); border-radius: 3px; height: 8px; overflow: hidden; }
.mix .track span { display: block; height: 100%; background: var(--accent); }
dl { display: grid; grid-template-columns: auto 1fr; gap: 4px 12px; margin: 0; font-size: 13px; }
dt { color: var(--muted); } dd { margin: 0; text-align: right; font-variant-numeric: tabular-nums; }
a { color: var(--accent); }
button { background: var(--surface); color: var(--text); border: 1px solid var(--line); border-radius: 6px; padding: 5px 10px; font: inherit; cursor: pointer; }
</style>
</head>
<body>
<main>
  <h1>__TITLE__</h1>
  <p class="sub" id="sub"></p>
  <div id="banner"></div>
  <div class="kpis" id="kpis"></div>
  <div class="controls">
    <input type="search" id="q" placeholder="Search wallet">
    <label><input type="checkbox" id="hideBots" checked> Hide bots</label>
    <label><input type="checkbox" id="hideLow"> Hide low-sample</label>
    <label>Min win rate % <input type="number" id="minWin" value="0" min="0" max="100"></label>
    <label>Frontend <select id="fe"><option value="">Any</option></select></label>
    <button id="csv">Export watchlist CSV</button>
  </div>
  <div class="tablewrap"><table><thead><tr id="head"></tr></thead><tbody id="rows"></tbody></table></div>
  <section id="detail"></section>
</main>
<script>
const DATA = __DATA__;
const $ = (id) => document.getElementById(id);
const sol = (v, d = 2) => v == null ? '–' : (v >= 0 ? '' : '−') + Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d });
const pct = (v) => v == null ? '–' : (v * 100).toFixed(0) + '%';
const num = (v) => v == null ? '–' : v === 'Infinity' ? '∞' : Number(v).toFixed(2);
const short = (a) => a.slice(0, 4) + '…' + a.slice(-4);
const dur = (s) => s == null ? '–' : s < 60 ? Math.round(s) + 's' : s < 3600 ? Math.round(s / 60) + 'm' : s < 86400 ? (s / 3600).toFixed(1) + 'h' : (s / 86400).toFixed(1) + 'd';
const cls = (v) => v > 0 ? 'pos' : v < 0 ? 'neg' : '';
const label = (id) => DATA.labels[id] || id;
const link = (kind, addr, text) => DATA.demo ? text : '<a href="https://solscan.io/' + kind + '/' + addr + '" target="_blank" rel="noopener">' + text + '</a>';

const COLS = [
  ['rank', '#', (w) => w.rank],
  ['wallet', 'Wallet', (w) => w.wallet, (w) => '<span class="mono">' + short(w.wallet) + '</span>' + w.flags.map((f) => '<span class="flag">' + f + '</span>').join('')],
  ['score', 'Score', (w) => w.score, (w) => '<span class="bar" style="width:' + (w.score * 0.4) + 'px"></span> ' + w.score.toFixed(1)],
  ['realizedPnlSol', 'Realized SOL', (w) => w.realizedPnlSol, (w) => '<span class="' + cls(w.realizedPnlSol) + '">' + sol(w.realizedPnlSol) + '</span>'],
  ['roi', 'ROI', (w) => w.roi ?? -1e9, (w) => '<span class="' + cls(w.roi) + '">' + pct(w.roi) + '</span>'],
  ['winRate', 'Win rate', (w) => w.winRate ?? -1, (w) => pct(w.winRate)],
  ['profitFactor', 'Profit factor', (w) => w.profitFactor === 'Infinity' ? 1e9 : w.profitFactor ?? -1, (w) => num(w.profitFactor)],
  ['closedPositions', 'Closed', (w) => w.closedPositions],
  ['trades', 'Trades', (w) => w.trades],
  ['medianHoldSec', 'Med. hold', (w) => w.medianHoldSec ?? -1, (w) => dur(w.medianHoldSec)],
  ['volumeSol', 'Volume SOL', (w) => w.volumeSol, (w) => sol(w.volumeSol, 0)],
];
let sortKey = 'score', sortDir = -1, selected = null;

DATA.wallets.forEach((w, i) => (w.rank = i + 1));
$('sub').textContent = DATA.wallets.length + ' wallets · last ' + DATA.days + ' days · generated ' + new Date(DATA.generatedAt).toLocaleString();
if (DATA.demo) $('banner').innerHTML = '<div class="banner"><strong>Synthetic demo data.</strong> These wallets and tokens are generated to preview the dashboard; none of them exist on-chain. Run <code>jsak analyze</code> with a Helius key for real results.</div>';
for (const f of Object.keys(DATA.labels).filter((k) => DATA.frontendIds.includes(k)).concat('direct')) $('fe').insertAdjacentHTML('beforeend', '<option value="' + f + '">' + label(f) + '</option>');

function filtered() {
  const q = $('q').value.trim(), minWin = +$('minWin').value / 100, fe = $('fe').value;
  return DATA.wallets.filter((w) =>
    (!q || w.wallet.includes(q)) &&
    !($('hideBots').checked && w.flags.includes('bot')) &&
    !($('hideLow').checked && w.flags.includes('low-sample')) &&
    (w.winRate ?? 0) >= minWin &&
    (!fe || (w.frontends[fe] || 0) / (w.volumeSol || 1) >= 0.5));
}

function render() {
  const col = COLS.find((c) => c[0] === sortKey);
  const list = filtered().sort((a, b) => { const x = col[2](a), y = col[2](b); return (x > y ? 1 : x < y ? -1 : 0) * sortDir; });
  $('head').innerHTML = COLS.map((c) => '<th data-k="' + c[0] + '"' + (c[0] === sortKey ? ' data-dir="' + (sortDir > 0 ? '↑' : '↓') + '"' : '') + '>' + c[1] + '</th>').join('');
  $('rows').innerHTML = list.map((w) => '<tr data-w="' + w.wallet + '"' + (w.wallet === selected ? ' class="sel"' : '') + '>' + COLS.map((c) => '<td>' + (c[3] ? c[3](w) : c[2](w)) + '</td>').join('') + '</tr>').join('');
  const profitable = list.filter((w) => w.realizedPnlSol > 0);
  const kpi = (v, l) => '<div class="kpi"><div class="v">' + v + '</div><div class="l">' + l + '</div></div>';
  $('kpis').innerHTML = kpi(list.length, 'Wallets shown') + kpi(profitable.length, 'Profitable') +
    kpi(sol(list.reduce((s, w) => s + w.realizedPnlSol, 0), 0), 'Total realized SOL') +
    kpi(pct(list.length ? profitable.length / list.length : null), 'Share profitable') +
    kpi(list[0] ? list[0].score.toFixed(1) : '–', 'Top score');
}

function mix(obj, total) {
  return Object.entries(obj).sort((a, b) => b[1] - a[1]).map(([k, v]) =>
    '<div><span>' + label(k) + '</span><span class="track"><span style="width:' + (100 * v / (total || 1)) + '%"></span></span><span style="text-align:right">' + pct(v / (total || 1)) + '</span></div>').join('');
}

function detail(w) {
  const row = (p) => '<tr><td class="mono">' + link('token', p.mint, short(p.mint)) + '</td><td>' + (p.closed ? 'closed' : 'open') + '</td><td>' + p.buys + '/' + p.sells + '</td><td>' + sol(p.boughtSol) + '</td><td class="' + cls(p.realized) + '">' + sol(p.realized) + '</td><td class="' + cls(p.roi) + '">' + pct(p.roi) + '</td><td>' + dur(p.avgHoldSec) + '</td></tr>';
  $('detail').innerHTML = '<h2>' + link('account', w.wallet, w.wallet) + (w.archetype ? ' <span class="flag">' + w.archetype + '</span>' : '') + '</h2>' +
    '<div class="grid2"><dl>' +
    '<dt>Score</dt><dd>' + w.score.toFixed(1) + '</dd><dt>Realized PnL</dt><dd class="' + cls(w.realizedPnlSol) + '">' + sol(w.realizedPnlSol) + ' SOL</dd>' +
    '<dt>Invested (matched)</dt><dd>' + sol(w.investedSol) + ' SOL</dd><dt>Still open (cost)</dt><dd>' + sol(w.openCostSol) + ' SOL</dd>' +
    '<dt>Median token ROI</dt><dd>' + pct(w.medianRoi) + '</dd><dt>Tokens / closed</dt><dd>' + w.tokens + ' / ' + w.closedPositions + '</dd>' +
    '<dt>Active days</dt><dd>' + w.activeDays + '</dd><dt>Trades per active day</dt><dd>' + w.tradesPerDay.toFixed(1) + '</dd>' +
    '<dt>Best</dt><dd>' + (w.best ? sol(w.best.realized) + ' SOL (' + pct(w.best.roi) + ')' : '–') + '</dd>' +
    '<dt>Worst</dt><dd>' + (w.worst ? sol(w.worst.realized) + ' SOL (' + pct(w.worst.roi) + ')' : '–') + '</dd></dl>' +
    '<div class="mix"><strong>Venue (by volume)</strong>' + mix(w.venues, w.volumeSol) + '<br><strong>Frontend (by volume)</strong>' + mix(w.frontends, w.volumeSol) + '</div></div>' +
    '<div class="tablewrap"><table><thead><tr><th>Token</th><th>Status</th><th>Buys/Sells</th><th>Bought SOL</th><th>Realized SOL</th><th>ROI</th><th>Avg hold</th></tr></thead><tbody>' +
    w.positions.map(row).join('') + '</tbody></table></div>';
}

$('head').addEventListener('click', (e) => {
  const k = e.target.closest('th')?.dataset.k; if (!k) return;
  sortDir = k === sortKey ? -sortDir : (k === 'rank' || k === 'wallet' ? 1 : -1); sortKey = k; render();
});
$('rows').addEventListener('click', (e) => {
  const tr = e.target.closest('tr'); if (!tr || e.target.closest('a')) return;
  selected = tr.dataset.w; render(); detail(DATA.wallets.find((w) => w.wallet === selected));
  $('detail').scrollIntoView({ behavior: 'smooth', block: 'start' });
});
for (const id of ['q', 'hideBots', 'hideLow', 'minWin', 'fe']) $(id).addEventListener('input', render);
$('csv').addEventListener('click', () => {
  const head = 'wallet,score,realized_sol,roi,win_rate,closed_positions,flags';
  const lines = filtered().map((w) => [w.wallet, w.score, w.realizedPnlSol.toFixed(4), w.roi ?? '', w.winRate ?? '', w.closedPositions, w.flags.join('|')].join(','));
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([head + '\\n' + lines.join('\\n')], { type: 'text/csv' }));
  a.download = 'watchlist.csv'; a.click();
});
render();
</script>
</body>
</html>
`;
