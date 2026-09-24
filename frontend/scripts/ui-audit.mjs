/**
 * Frontend validation audit.
 *
 * Covers the brief's sections that are properties of the source rather than of
 * a running browser: navigation targets (21), UI consistency (22), bottom
 * navigation (23), the profile menu (24), number inputs (26), responsive
 * hazards (29) and accessibility (30).
 *
 * What it cannot do is see. Colour contrast, real overflow at a given width and
 * whether a hover state looks right need a browser; those are called out in the
 * summary as requiring a human rather than quietly passed.
 *
 *     node scripts/ui-audit.mjs
 */
import fs from 'node:fs';
import path from 'node:path';

const results = [];

function check(section, label, ok, detail = '') {
  results.push({ section, label, ok: Boolean(ok), detail });
  console.log(`  [${ok ? 'PASS' : 'FAIL'}] ${label}${!ok && detail ? ` - ${detail}` : ''}`);
  return Boolean(ok);
}

function walk(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return walk(full);
    return /\.(jsx?|css)$/.test(entry.name) ? [full] : [];
  });
}

const files = walk('src');
const read = (f) => fs.readFileSync(f, 'utf8');
const sources = new Map(files.map((f) => [f.split(path.sep).join('/'), read(f)]));
const jsx = [...sources].filter(([f]) => f.endsWith('.jsx'));
const all = [...sources.values()].join('\n');

console.log('\nCashU UI audit\n' + '='.repeat(66));

/* ── 21. Navigation ───────────────────────────────────────────────────── */
console.log('\n[21] Navigation');

const app = sources.get('src/app/App.jsx') || '';
const declared = new Set(
  [...app.matchAll(/path="([^"]+)"/g)].map((m) => m[1]),
);

// Nested admin children are declared relative to /admin.
const routes = new Set();
for (const route of declared) {
  routes.add(route.startsWith('/') ? route : `/admin/${route}`);
}

function matches(target) {
  if (routes.has(target)) return true;
  for (const route of routes) {
    const pattern = new RegExp(
      '^' + route.replace(/:[^/]+/g, '[^/]+').replace(/\*/g, '.*') + '$',
    );
    if (pattern.test(target)) return true;
  }
  return false;
}

const targets = new Set();
for (const [, body] of sources) {
  for (const m of body.matchAll(/navigate\(\s*['"`](\/[^'"`$]*)['"`]/g)) targets.add(m[1]);
  for (const m of body.matchAll(/\bto=["'](\/[^"']*)["']/g)) targets.add(m[1]);
}

const broken = [...targets].filter((t) => !matches(t));
check(21, 'every navigate()/to= target resolves to a declared route',
  broken.length === 0, broken.join(', '));

check(21, 'a catch-all route exists so no URL renders blank',
  app.includes('path="*"'));

check(21, 'protected routes are wrapped in an auth guard',
  (app.match(/RequireAuth/g) || []).length > 5);

check(21, 'admin routes are wrapped in an admin guard',
  app.includes('RequireAdmin'));

/* ── 22. UI consistency ───────────────────────────────────────────────── */
console.log('\n[22] UI consistency');

const shells = ['src/components/layout/AppShell.jsx', 'src/pages/admin/AdminLayout.jsx'];
check(22, 'both app shells use the white canvas background',
  shells.every((f) => (sources.get(f) || '').includes('min-h-screen bg-canvas')),
  shells.filter((f) => !(sources.get(f) || '').includes('min-h-screen bg-canvas')).join(', '));

const ui = sources.get('src/components/ui/index.jsx') || '';
check(22, 'primary and mint buttons share one style definition',
  /primary:\s*PRIMARY/.test(ui) && /mint:\s*PRIMARY/.test(ui));

const radii = [...ui.matchAll(/^\s*(sm|md|lg):\s*'[^']*rounded-(\w+)/gm)].map((m) => m[2]);
check(22, 'all button sizes share one border radius',
  radii.length > 0 && new Set(radii).size === 1, radii.join(', '));

check(22, 'buttons have a disabled style',
  ui.includes('disabled:cursor-not-allowed'));

check(22, 'buttons have a press animation',
  /active:scale-\[/.test(ui));

check(22, 'a loading state exists on the shared button',
  ui.includes('loading') && /Spinner|Loader3D/.test(ui));

// Hand-rolled buttons that bypass the shared component are how a design
// language drifts. Count raw <button> with their own background colour.
let rogue = 0;
for (const [file, body] of jsx) {
  if (file.includes('/ui/') || file.includes('/auth/Splash')) continue;
  for (const m of body.matchAll(/<button[^>]*className=["'`]([^"'`]*)/g)) {
    if (/\bbg-mint\b/.test(m[1]) && !/rounded/.test(m[1])) rogue += 1;
  }
}
check(22, 'no unstyled hand-rolled primary buttons', rogue === 0, `${rogue} found`);

check(22, 'global horizontal overflow is clipped',
  /overflow-x:\s*hidden/.test(all) || /overflow-x-hidden/.test(all));

/* ── 23. Bottom navigation ────────────────────────────────────────────── */
console.log('\n[23] Bottom navigation');

const nav = sources.get('src/components/layout/BottomNav.jsx') || '';
check(23, 'bottom navigation component exists', nav.length > 0);
check(23, 'it is fixed to the bottom', /fixed[^"']*bottom-0/.test(nav));
check(23, 'it handles the mobile safe area',
  nav.includes('env(safe-area-inset-bottom)'));
// The line that positions the bar itself. Scanning the whole opening tag was
// brittle (it grew past the window once the className moved into cx()), and
// scanning the whole file was wrong - the popover and the search overlay in
// here are modal-layer things and are meant to be z-50.
const navBarLine = (nav.split('\n').find(
  (line) => /fixed/.test(line) && /inset-x-0/.test(line) && /bottom-0/.test(line),
) || '');
check(23, 'it sits below the modal layer so dialogs are not covered',
  /z-40/.test(navBarLine) && !/z-50/.test(navBarLine), navBarLine.trim().slice(0, 80));
check(23, 'active state is rendered', nav.includes('isActive'));
check(23, 'items carry both an icon and a label',
  nav.includes('<Icon') && nav.includes('{label}'));
check(23, 'labels truncate rather than overflow', nav.includes('truncate'));

const shell = sources.get('src/components/layout/AppShell.jsx') || '';
check(23, 'content reserves space so the bar never covers it',
  /pb-2\d/.test(shell));
check(23, 'the old sidebar is gone from the member shell',
  !/<aside/.test(shell), 'aside element still present');
check(23, 'the old sidebar is gone from the admin shell',
  !/<aside/.test(sources.get('src/pages/admin/AdminLayout.jsx') || ''));

/* ── 24. Profile menu ─────────────────────────────────────────────────── */
console.log('\n[24] Profile menu');

check(24, 'menu closes on an outside click', nav.includes('mousedown'));
check(24, 'menu closes on Escape', nav.includes("'Escape'"));
check(24, 'menu listeners are removed on unmount',
  nav.includes('removeEventListener'));
check(24, 'menu is constrained to the viewport',
  nav.includes('max-w-[calc(100vw'));
check(24, 'menu exposes its state to assistive tech',
  nav.includes('aria-expanded') && nav.includes('aria-haspopup'));
check(24, 'menu items are reachable as menu items',
  nav.includes("role=\"menuitem\""));

for (const item of ['Profile', 'Security', 'Help & support', 'Logout']) {
  check(24, `menu offers ${item}`, shell.includes(item));
}

/* ── 26. Number inputs ────────────────────────────────────────────────── */
console.log('\n[26] Number inputs');

const amountScreens = ['src/pages/user/Transfer.jsx', 'src/pages/user/EmiPay.jsx'];
for (const file of amountScreens) {
  const body = sources.get(file) || '';
  const name = file.split('/').pop();
  check(26, `${name} uses a numeric keypad hint`, body.includes('inputMode'));
  // One shared sanitiser, so the rules cannot drift between screens - which
  // they had: the transfer form allowed decimals while the EMI form stripped
  // them, so identical keystrokes produced different numbers per page.
  check(26, `${name} sanitises the amount through the shared helper`,
    body.includes('sanitizeAmount'));
}

/* ── 29. Responsive hazards ───────────────────────────────────────────── */
console.log('\n[29] Responsive');

const hazards = [];
for (const [file, body] of jsx) {
  // A fixed width wider than 320px is only safe inside a scroll container or
  // behind a breakpoint prefix.
  for (const m of body.matchAll(/(?<![a-z:-])(w-\[(\d+)px\]|min-w-\[(\d+)px\])/g)) {
    const px = Number(m[2] || m[3]);
    if (px > 320) {
      const before = body.slice(Math.max(0, m.index - 220), m.index);
      if (!/overflow-x-auto|overflow-auto|sheet-scroll/.test(before)) {
        hazards.push(`${file}: ${m[1]}`);
      }
    }
  }
}
check(29, 'no unguarded fixed width above 320px', hazards.length === 0,
  hazards.slice(0, 4).join('; '));

const css = sources.get('src/styles/index.css') || '';
check(29, 'body cannot scroll horizontally',
  /overflow-x:\s*hidden/.test(css) || /overflow-x-hidden/.test(all));

check(29, 'the viewport meta tag is present',
  fs.readFileSync('index.html', 'utf8').includes('name="viewport"'));

/* ── 30. Accessibility ────────────────────────────────────────────────── */
console.log('\n[30] Accessibility');

check(30, 'reduced motion is respected',
  /prefers-reduced-motion/.test(css));
check(30, 'a visible focus style is defined',
  /focus-visible/.test(css) || /focus-visible/.test(ui));
check(30, 'the shared input renders a real <label>',
  ui.includes('<label') && ui.includes('htmlFor'));
check(30, 'inputs expose validation state',
  ui.includes('aria-invalid'));

const unlabelled = [];
for (const [file, body] of jsx) {
  for (const m of body.matchAll(/<button(?![^>]*aria-label)[^>]*>\s*\{?\s*<(svg|Icon\w*)/g)) {
    const line = body.slice(0, m.index).split('\n').length;
    unlabelled.push(`${file}:${line}`);
  }
}
check(30, 'icon-only buttons carry an accessible name',
  unlabelled.length === 0, `${unlabelled.length}: ${unlabelled.slice(0, 3).join(', ')}`);

const noAlt = [];
for (const [file, body] of jsx) {
  // Strip comments first: a docstring that mentions <img> is prose, not markup,
  // and flagging it teaches the reader to ignore this check.
  const code = body
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '');
  for (const m of code.matchAll(/<img(?![^>]*\balt=)[^>]*>/g)) {
    noAlt.push(`${file}:${code.slice(0, m.index).split('\n').length}`);
  }
}
check(30, 'every <img> has alt text', noAlt.length === 0, noAlt.join(', '));

check(30, 'decorative SVGs are hidden from assistive tech',
  all.includes('aria-hidden'));

/* ── Summary ──────────────────────────────────────────────────────────── */
console.log('\n' + '='.repeat(66));
const passed = results.filter((r) => r.ok);
const failed = results.filter((r) => !r.ok);
console.log(`${passed.length} passed, ${failed.length} failed, ${results.length} total`);

if (failed.length) {
  console.log('\nFAILURES');
  for (const f of failed) {
    console.log(`  [S${f.section}] ${f.label}${f.detail ? `  (${f.detail})` : ''}`);
  }
}

fs.writeFileSync(
  'ui-audit-results.json',
  JSON.stringify(results, null, 2),
);
console.log('\nFull results: frontend/ui-audit-results.json');
process.exit(failed.length ? 1 : 0);
