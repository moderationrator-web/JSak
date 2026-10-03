// Builds the single-file JSak app: the UI in app.html plus the analysis engine
// (the same modules the CLI uses), inlined so the file works offline and from file://.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const here = (f) => fileURLToPath(new URL(f, import.meta.url));

// Dependency order: each module may only use names exported by the ones before it.
const ENGINE_MODULES = ['platforms.js', 'extract.js', 'pnl.js', 'metrics.js', 'discover.js', 'helius.js', 'demo.js', 'zip.js'];

// Wraps each ES module in its own scope and publishes its exports on a shared JSAK object.
// Node built-in imports become empty bindings; they're only reached on CLI-only paths.
export function bundleEngine() {
  const parts = ENGINE_MODULES.map((file) => {
    const exported = [];
    const body = readFileSync(here(file), 'utf8')
      .replace(/^import \{([^}]*)\} from '([^']+)';$/gm, (_, names, from) =>
        from.startsWith('node:') ? `const {${names}} = {};` : `const {${names}} = JSAK;`)
      .replace(/^export (async function\*?|function\*?|class|const|let) (\w+)/gm, (_, kind, name) => {
        exported.push(name);
        return `${kind} ${name}`;
      });
    if (/^\s*(import|export)\b/m.test(body)) throw new Error(`${file}: unsupported import/export form`);
    return `// ${file}\nObject.assign(JSAK, (() => {\n${body}\nreturn { ${exported.join(', ')} };\n})());`;
  });
  return `const JSAK = {};\n${parts.join('\n')}`;
}

// standalone: wrap in a full document for a file people open directly.
// Without it the output is page content for an Artifact publish, which adds its own skeleton.
export function renderApp(analysis, { standalone = true } = {}) {
  const json = (v) => JSON.stringify(v, (_, x) => (x === Infinity ? 'Infinity' : x)).replace(/</g, '\\u003c');
  const slim = analysis && {
    ...analysis,
    wallets: analysis.wallets.map((w) => ({ ...w, positions: w.positions.slice(0, 60) })),
  };
  const platforms = JSON.parse(readFileSync(here('../config/platforms.json'), 'utf8'));
  const page = readFileSync(here('app.html'), 'utf8')
    .replace('__TITLE__', () => 'JSak Wallet Scout')
    .replace('__ENGINE__', () => bundleEngine().replace(/<\/script/gi, '<\\/script'))
    .replace('__PLATFORMS__', () => json(platforms))
    .replace('__DATA__', () => json(slim ?? null));
  if (!standalone) return page;
  return `<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n</head>\n<body>\n${page}\n</body>\n</html>\n`;
}

export const renderReport = renderApp;
