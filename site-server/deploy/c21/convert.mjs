#!/usr/bin/env node
// NM: React/Tailwind component -> static HTML + scoped CSS (server side, no browser).
//
//   node convert.mjs <job.json> <out.json>
//
// job.json: { id, scope: "nbc21-abc123", entry: {path, code}, files: {"specifier": "code"}, aliases: {"@/components/ui/x": "/abs/repo/x.tsx"}, roots: ["/abs/repo/src", "/abs/repo"],
//             export: "auto" | "<name>", dir: "rtl" }
// out.json: { ok, html, css, warnings: [], error?, stats: {classes, css_bytes, html_bytes} }
//
// What it does (all offline, deterministic):
//   1. esbuild bundles the DEMO (usage) code + the component source it imports. "@/..." imports resolve against `roots` (the library repo) or a small
//      set of safe shims (shadcn-style ui primitives, cn(), next/image, next/link, framer-motion -> static elements, ...). Anything else that cannot be
//      resolved is an error (the component stays "catalogue only").
//   2. react-dom/server renders it (initial state; effects do not run).
//   3. Tailwind v4 (compile API, no browser) builds exactly the utilities the HTML uses; the shadcn colour variables are mapped to the SITE theme
//      variables (--brand, --ink, --bg ...), so the component takes the colours of the site it is inserted into.
//   4. postcss scopes every selector under .<scope>, unwraps @layer (unlayered site CSS must not beat the utilities), renames keyframes, drops anything
//      that loads files, and converts physical properties (margin-left, left, text-align:left ...) to logical ones so the component mirrors in RTL.
import { build } from 'esbuild';
import { compile, optimize } from '@tailwindcss/node';
import postcss from 'postcss';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { SHIM_SOURCES, UI_SOURCES } from './shims.mjs';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const [, , jobPath, outPath] = process.argv;
const job = JSON.parse(fs.readFileSync(jobPath, 'utf8'));
const SCOPE = job.scope || 'nbc21-x';
const warnings = [];
const EXT = ['.tsx', '.ts', '.jsx', '.js', '.mjs'];

const ALIAS_KEYS = new Set(['lib/utils', 'lib/cn', 'utils/cn', 'lib/classnames', 'utils', 'hooks/use-mobile', 'hooks/use-media-query']);

function tryFile(base) {
  for (const e of ['', ...EXT]) { const f = base + e; if (fs.existsSync(f) && fs.statSync(f).isFile()) return f; }
  for (const e of EXT) { const f = path.join(base, 'index' + e); if (fs.existsSync(f)) return f; }
  return null;
}

const plugin = {
  name: 'nm-c21',
  setup(b) {
    const virt = job.files || {};
    b.onResolve({ filter: /.*/ }, (args) => {
      const p = args.path;
      if (args.namespace === 'virt' && (p.startsWith('./') || p.startsWith('../'))) {
        const joined = path.posix.normalize(path.posix.join(path.posix.dirname(args.importer), p));
        for (const e of ['', ...EXT]) if (virt[joined + e] !== undefined) return { path: joined + e, namespace: 'virt' };
      }
      if (job.aliases && job.aliases[p]) return { path: job.aliases[p] };
      if (virt[p] !== undefined) return { path: p, namespace: 'virt' };
      if (p.startsWith('react-icons/')) { warnings.push('react-icons is not available: ' + p); return { path: 'react-icons', namespace: 'shim' }; }
      if (!p.startsWith('@/') && !p.startsWith('~/') && !p.startsWith('.') && !p.startsWith('/') && SHIM_SOURCES[p] && !ALIAS_KEYS.has(p)) return { path: p, namespace: 'shim' };
      if (p.startsWith('@/') || p.startsWith('~/')) {
        const rel = p.slice(2);
        for (const r of job.roots || []) { const f = tryFile(path.join(r, rel)); if (f) return { path: f }; }
        if (ALIAS_KEYS.has(rel)) return { path: rel, namespace: 'shim' };
        const m = rel.match(/^components\/(?:ui\/)?([\w-]+)$/);
        if (m && UI_SOURCES[m[1]]) return { path: 'ui:' + m[1], namespace: 'shim' };
        return { errors: [{ text: 'cannot resolve ' + p }] };
      }
      return undefined;
    });
    b.onLoad({ filter: /.*/, namespace: 'virt' }, (args) => ({ contents: virt[args.path], loader: args.path.endsWith('.ts') ? 'ts' : args.path.endsWith('.jsx') ? 'jsx' : 'tsx', resolveDir: HERE }));
    b.onLoad({ filter: /.*/, namespace: 'shim' }, (args) => ({ contents: args.path.startsWith('ui:') ? UI_SOURCES[args.path.slice(3)] : SHIM_SOURCES[args.path], loader: 'tsx', resolveDir: HERE }));
  },
};

function fail(error, extra = {}) {
  fs.writeFileSync(outPath, JSON.stringify({ ok: false, error: String(error).slice(0, 600), warnings, ...extra }));
  process.exit(0);
}

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'nm-c21-'));
process.on('exit', () => { try { fs.rmSync(tmp, { recursive: true, force: true }); } catch (e) { /* the sweeper of /tmp gets it */ } });   // every exit path (also fail()) cleans up
const entry = `
import * as React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import * as Mod from 'virtual:entry';
const names = ${JSON.stringify(job.export || 'auto')};
let C = null;
if (names !== 'auto') C = Mod[names] || Mod.default;
if (!C) C = Mod.default || Object.values(Mod).find((v) => typeof v === 'function');
if (!C) throw new Error('the demo exports no component');
export const html = renderToStaticMarkup(React.createElement('div', { id: 'c21-root' }, React.createElement(C)));
`;
const entryPath = '/__entry__.tsx';
let html = '';
try {
  const files = { ...(job.files || {}) };
  files['virtual:entry'] = job.entry.code;
  job.files = files;
  const virtualEntry = { name: 'virt-entry', setup(b) {
    b.onResolve({ filter: /^virtual:entry$/ }, () => ({ path: 'virtual:entry', namespace: 'virt' }));
    b.onResolve({ filter: /^\/__entry__\.tsx$/ }, () => ({ path: entryPath, namespace: 'entry' }));
    b.onLoad({ filter: /.*/, namespace: 'entry' }, () => ({ contents: entry, loader: 'tsx', resolveDir: HERE }));
  } };
  const out = path.join(tmp, 'bundle.cjs');
  await build({
    entryPoints: [entryPath], bundle: true, platform: 'node', format: 'cjs', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'react',
    nodePaths: [path.join(HERE, 'node_modules')], plugins: [virtualEntry, plugin], define: { 'process.env.NODE_ENV': '"production"' }, absWorkingDir: HERE, mainFields: ['module', 'main'],
    loader: { '.svg': 'dataurl', '.png': 'dataurl', '.jpg': 'dataurl', '.css': 'empty' }, banner: { js: 'globalThis.window=undefined;' },
  });
  const mod = require(out);
  html = mod.html;
} catch (e) {
  const msg = (e && e.errors && e.errors[0] && e.errors[0].text) || (e && e.message) || String(e);
  fail('bundle/render: ' + msg);
}

// ── Tailwind (v4 compile API) ───────────────────────────────────────────────
const classes = new Set();
for (const m of html.matchAll(/class="([^"]*)"/g)) for (const c of m[1].split(/\s+/)) if (c) classes.add(c);
const themeVars = `
  --background: var(--bg, #ffffff); --foreground: var(--ink, #111827); --card-foreground: var(--ink, #111827);
  --popover: var(--card, #ffffff); --popover-foreground: var(--ink, #111827); --primary: var(--brand, #126f85); --primary-foreground: var(--brand-ink, #ffffff);
  --secondary: color-mix(in srgb, var(--ink, #111827) 6%, var(--bg, #ffffff)); --secondary-foreground: var(--ink, #111827);
  --muted: color-mix(in srgb, var(--ink, #111827) 6%, var(--bg, #ffffff)); --muted-foreground: var(--ink-3, #6b7280);
  --accent: color-mix(in srgb, var(--brand, #126f85) 12%, var(--bg, #ffffff)); --accent-foreground: var(--ink, #111827);
  --destructive: #dc2626; --destructive-foreground: #ffffff; --border: var(--line, #e5e7eb); --input: var(--line, #e5e7eb); --ring: var(--brand, #126f85);
  --radius: var(--r, 12px); --chart-1: var(--brand, #126f85); --chart-2: #f59e0b; --chart-3: #10b981; --chart-4: #8b5cf6; --chart-5: #ef4444;
  --sidebar: var(--card, #ffffff); --sidebar-foreground: var(--ink, #111827); --sidebar-border: var(--line, #e5e7eb);`;
const input = `
@layer theme, base, components, utilities;
@import "tailwindcss/theme.css" layer(theme);
@import "tailwindcss/utilities.css" layer(utilities);
@custom-variant dark (&:where(.dark, .dark *));
@theme inline {
  --color-background: var(--background); --color-foreground: var(--foreground); --color-card: var(--card, #ffffff); --color-card-foreground: var(--card-foreground);
  --color-popover: var(--popover); --color-popover-foreground: var(--popover-foreground); --color-primary: var(--primary); --color-primary-foreground: var(--primary-foreground);
  --color-secondary: var(--secondary); --color-secondary-foreground: var(--secondary-foreground); --color-muted: var(--muted); --color-muted-foreground: var(--muted-foreground);
  --color-accent: var(--accent); --color-accent-foreground: var(--accent-foreground); --color-destructive: var(--destructive); --color-destructive-foreground: var(--destructive-foreground);
  --color-border: var(--border); --color-input: var(--input); --color-ring: var(--ring); --color-chart-1: var(--chart-1); --color-chart-2: var(--chart-2);
  --color-chart-3: var(--chart-3); --color-chart-4: var(--chart-4); --color-chart-5: var(--chart-5); --radius-sm: calc(var(--radius) - 4px); --radius-md: calc(var(--radius) - 2px);
  --radius-lg: var(--radius); --radius-xl: calc(var(--radius) + 4px);
}
${fs.readFileSync(path.join(HERE, 'extras.css'), 'utf8')}
`;
let css = '';
try {
  const compiler = await compile(input, { base: HERE, onDependency() {} });
  css = compiler.build([...classes]);
} catch (e) {
  fail('tailwind: ' + (e && e.message));
}

// ── postcss: scope + RTL + safety ───────────────────────────────────────────
const PHYS = {
  'margin-left': 'margin-inline-start', 'margin-right': 'margin-inline-end', 'padding-left': 'padding-inline-start', 'padding-right': 'padding-inline-end',
  'border-left': 'border-inline-start', 'border-right': 'border-inline-end', 'border-left-width': 'border-inline-start-width', 'border-right-width': 'border-inline-end-width',
  'border-left-color': 'border-inline-start-color', 'border-right-color': 'border-inline-end-color', 'border-left-style': 'border-inline-start-style',
  'border-right-style': 'border-inline-end-style', 'border-top-left-radius': 'border-start-start-radius', 'border-top-right-radius': 'border-start-end-radius',
  'border-bottom-left-radius': 'border-end-start-radius', 'border-bottom-right-radius': 'border-end-end-radius', left: 'inset-inline-start', right: 'inset-inline-end',
  'scroll-margin-left': 'scroll-margin-inline-start', 'scroll-margin-right': 'scroll-margin-inline-end', 'scroll-padding-left': 'scroll-padding-inline-start',
  'scroll-padding-right': 'scroll-padding-inline-end',
};
const root = postcss.parse(css);
const kf = new Map();
root.walkAtRules('keyframes', (r) => { kf.set(r.params, r.params + '-' + SCOPE.slice(-6)); });
const hoisted = [];
// unwrap @layer
for (let again = true; again;) {
  again = false;
  root.walkAtRules('layer', (r) => {
    again = true;
    if (r.nodes && r.nodes.length) r.replaceWith(r.nodes); else r.remove();
  });
}
root.walkAtRules('import', (r) => r.remove());
root.walkAtRules('property', (r) => { hoisted.push(r.clone()); r.remove(); });
root.walkAtRules('font-face', (r) => r.remove());
root.walkAtRules('keyframes', (r) => { r.params = kf.get(r.params) || r.params; });
const scopeSel = (sel) => {
  sel = sel.trim();
  if (!sel || /::backdrop/.test(sel)) return null;
  if (/^(:root|:host|html|body)\b/.test(sel)) return sel.replace(/^(:root|:host|html|body)/, '.' + SCOPE);
  if (sel === '*' || sel === '::before' || sel === '::after' || sel === '::file-selector-button') return '.' + SCOPE + ' ' + sel;
  return '.' + SCOPE + ' ' + sel.replace(/^&\s*/, '');
};
const insideRule = (n) => { for (let p = n.parent; p; p = p.parent) if (p.type === 'rule') return true; return false; };
root.walkRules((rule) => {
  if (rule.parent && rule.parent.type === 'atrule' && /keyframes$/.test(rule.parent.name)) return;
  if (insideRule(rule)) return;      // Tailwind v4 variants are nested (`.x { &:hover { @media (hover:hover) {...} } }`): the outer rule is scoped, the inner ones keep their `&`
  const sels = rule.selectors.map(scopeSel).filter(Boolean);
  if (!sels.length) { rule.remove(); return; }
  rule.selectors = sels;
});
root.walkDecls((d) => {
  // `left-1/2 -translate-x-1/2` (centring) must stay physical: with logical insets the translate pushes the box the wrong way in RTL.
  if ((d.prop === 'left' || d.prop === 'right') && /^(50%|calc\(\s*1\s*\/\s*2\s*\*\s*100%\s*\))$/.test(d.value.trim())) { /* keep */ }
  else if (PHYS[d.prop]) d.prop = PHYS[d.prop];
  else if (d.prop === 'text-align' && /^(left|right)$/.test(d.value)) d.value = d.value === 'left' ? 'start' : 'end';
  else if (d.prop === 'float' && /^(left|right)$/.test(d.value)) d.value = d.value === 'left' ? 'inline-start' : 'inline-end';
  else if (d.prop === 'clear' && /^(left|right)$/.test(d.value)) d.value = d.value === 'left' ? 'inline-start' : 'inline-end';
  if (/url\(\s*['"]?(?!data:image\/svg|#)/i.test(d.value) && !/url\(\s*['"]?(#|data:)/i.test(d.value)) { warnings.push('dropped url() in ' + d.prop); d.remove(); return; }
  for (const [from, to] of kf) {
    if ((d.prop === 'animation' || d.prop === 'animation-name' || d.prop.startsWith('--animate')) && new RegExp('(^|[\\s,:])' + from.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&') + '(?=[\\s,;]|$)').test(d.value)) {
      d.value = d.value.replace(new RegExp('(^|[\\s,:])' + from.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&') + '(?=[\\s,;]|$)', 'g'), '$1' + to);
    }
  }
});
const reset = `
.${SCOPE}{${themeVars.replace(/\s+/g, ' ')}display:block;box-sizing:border-box;text-align:start;font-family:inherit;line-height:1.5;color:var(--ink,#111827)}
.${SCOPE} *,.${SCOPE} ::before,.${SCOPE} ::after{box-sizing:border-box;border:0 solid;margin:0;padding:0}
.${SCOPE} h1,.${SCOPE} h2,.${SCOPE} h3,.${SCOPE} h4,.${SCOPE} h5,.${SCOPE} h6{font-size:inherit;font-weight:inherit}
.${SCOPE} a{color:inherit;text-decoration:inherit}
.${SCOPE} ul,.${SCOPE} ol,.${SCOPE} menu{list-style:none}
.${SCOPE} img,.${SCOPE} svg,.${SCOPE} video,.${SCOPE} canvas{display:block;max-width:100%}
.${SCOPE} img,.${SCOPE} video{height:auto}
.${SCOPE} button,.${SCOPE} input,.${SCOPE} select,.${SCOPE} textarea{font:inherit;color:inherit;letter-spacing:inherit;background:transparent;border-radius:0}
.${SCOPE} button{cursor:pointer}
.${SCOPE} p,.${SCOPE} h1,.${SCOPE} h2,.${SCOPE} h3,.${SCOPE} h4{overflow-wrap:break-word}
`;
const outCss = hoisted.map((r) => r.toString()).join('\n') + '\n' + reset.trim() + '\n' + root.toString();
if (/@import|expression\(|<\/style|javascript:/i.test(outCss)) fail('unsafe css');
let finalCss = outCss.replace(/\n{2,}/g, '\n');
try { finalCss = optimize(finalCss, { minify: true }).code; } catch (e) { warnings.push('minify skipped: ' + (e && e.message)); }
fs.writeFileSync(outPath, JSON.stringify({ ok: true, html, css: finalCss, warnings, stats: { classes: classes.size, css_bytes: finalCss.length, html_bytes: html.length } }));
fs.rmSync(tmp, { recursive: true, force: true });
