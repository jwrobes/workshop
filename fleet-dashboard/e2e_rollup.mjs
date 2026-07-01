#!/usr/bin/env node
// e2e_rollup.mjs — END-TO-END test of PASS 3 (product/fleet rollup), driven by a
// CANNED analyze fixture + --rollup (never the live claude CLI). Generates its
// own dashboard into a temp dir seeded from ~/.fleet. Proves, on the REAL
// rendered views the user navigates:
//   - the FLEET landing "Where things stand" shows the rollup: a bucket
//     distribution + per-track completion rows;
//   - the near-done/stuck/early buckets are placed correctly (a shipped-but-
//     needs-cleanup track is "stuck"/needs-a-decision, not near-done);
//   - the PRODUCT page (Magic Me) shows a rollup scoped to its tracks;
//   - clicking a rollup row opens that track's detail page.
//
// Usage: node e2e_rollup.mjs

import { pathToFileURL, fileURLToPath } from 'url';
import { existsSync, mkdirSync, copyFileSync, rmSync, writeFileSync, readFileSync } from 'fs';
import { homedir, tmpdir } from 'os';
import { join, dirname } from 'path';
import { execSync } from 'child_process';

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = process.env.FLEET_OUT || join(homedir(), '.fleet');
const OUT = join(tmpdir(), 'fleet-e2e-rollup');
const FIXTURE = join(HERE, 'fixtures', 'e2e_analyze.json');

if (!existsSync(join(SRC, 'status.json'))) { console.error(`✗ no base fleet data at ${SRC}`); process.exit(1); }

rmSync(OUT, { recursive: true, force: true });
mkdirSync(OUT, { recursive: true });
if (existsSync(join(SRC, 'tracks.json'))) copyFileSync(join(SRC, 'tracks.json'), join(OUT, 'tracks.json'));
let baseOvr = {};
try { baseOvr = JSON.parse(readFileSync(join(SRC, 'track-overrides.json'), 'utf8')); } catch { }
writeFileSync(join(OUT, 'track-overrides.json'), JSON.stringify(baseOvr, null, 2));

// --analyze-fixture + --rollup: analyze the two fixture tracks, then roll up.
execSync(`python3 collector.py --out "${OUT}" --analyze-fixture "${FIXTURE}" --rollup`,
  { cwd: HERE, stdio: 'pipe' });

const HTML = join(OUT, 'dashboard.html');
if (!existsSync(HTML)) { console.error(`✗ no ${HTML}`); process.exit(1); }

const G = execSync('npm root -g', { encoding: 'utf8' }).trim();
const { chromium } = await import(pathToFileURL(join(G, '@playwright', 'test', 'index.mjs')).href);

const results = [];
const check = (n, ok, d = '') => { results.push({ n, ok }); console.log(`${ok ? '✓' : '✗'} ${n}${d ? ' — ' + d : ''}`); };

const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1500, height: 1700 } });
await p.goto(pathToFileURL(HTML).href);
await p.waitForSelector('#app');
await p.waitForTimeout(180);

// We START on the fleet landing — the rollup must be there.
const fleet = await p.evaluate(() => {
  const el = document.querySelector('[data-region="rollup"]');
  if (!el) return null;
  return {
    tracks: +el.getAttribute('data-track-count'),
    rows: el.querySelectorAll('[data-rollup-track]').length,
    dist: !!el.querySelector('[data-region="rollup-distribution"]'),
    stuck: el.querySelectorAll('[data-rollup-track][data-bucket="stuck"]').length,
    early: el.querySelectorAll('[data-rollup-track][data-bucket="early"]').length,
  };
});
check('fleet "Where things stand" shows the rollup', !!fleet, fleet ? `${fleet.tracks} tracks` : 'missing');
check('rollup renders a bucket distribution bar', !!fleet && fleet.dist);
check('rollup lists a row per track', !!fleet && fleet.rows === fleet.tracks, fleet ? `${fleet.rows} rows` : '');
check('a shipped-but-needs-cleanup track is bucketed "stuck" (needs a decision)',
  !!fleet && fleet.stuck >= 2, fleet ? `${fleet.stuck} stuck` : '');
check('un-analyzed tracks are bucketed "early" (honest — no verdict)',
  !!fleet && fleet.early >= 1, fleet ? `${fleet.early} early` : '');

// The completion %s show on the analyzed rows.
const briefRow = await p.evaluate(() => {
  const el = document.querySelector('[data-rollup-track="communications-hub-morning-briefing"]');
  return el ? el.textContent : null;
});
check('the briefing track row shows its completion % (75%)',
  !!briefRow && /75%/.test(briefRow), briefRow ? briefRow.trim().replace(/\s+/g, ' ').slice(0, 60) : 'missing');

// PRODUCT page (Magic Me) shows a scoped rollup.
await p.locator('[data-product="magic-me"]').first().click();
await p.waitForTimeout(200);
const prod = await p.evaluate(() => {
  const el = document.querySelector('[data-view="product"] [data-region="rollup"]');
  return el ? { rows: el.querySelectorAll('[data-rollup-track]').length } : null;
});
check('the product page (Magic Me) shows a rollup scoped to its tracks',
  !!prod && prod.rows >= 1, prod ? `${prod.rows} rows` : 'missing');

// Clicking a rollup row opens that track's detail page.
await p.locator('[data-view="product"] [data-region="rollup"] [data-rollup-track="communications-hub-morning-briefing"]').first().click();
await p.waitForTimeout(200);
const onTrack = await p.evaluate(() => STATE.level === 'track' && STATE.trackName === 'communications-hub-morning-briefing');
check('clicking a rollup row opens that track detail page', onTrack);

await p.evaluate(() => goTo('fleet'));
await p.waitForTimeout(150);
await p.screenshot({ path: join(OUT, 'e2e-rollup.png'), fullPage: true });
await b.close();

const failed = results.filter(r => !r.ok).length;
console.log(`\n${failed ? '✗' : '✓'} ${results.length - failed}/${results.length} e2e checks passed`);
process.exit(failed ? 1 : 0);
