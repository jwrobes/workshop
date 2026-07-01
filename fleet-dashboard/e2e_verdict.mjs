#!/usr/bin/env node
// e2e_verdict.mjs — END-TO-END test of PASS 2 (track-analysis verdict), driven
// by a CANNED per-track fixture (never the real claude CLI). Generates its own
// dashboard into a temp dir seeded from ~/.fleet. Proves, on the REAL rendered
// track-detail page the user navigates:
//   - the [data-region="track-verdict"] slot shows the headline + completion %
//     (the COMPUTED %, auditable) + the cleanup list + relationships;
//   - a LOW-confidence relationship renders as a QUESTION (⚠ … confirm), NOT an
//     asserted fact (the trust rule);
//   - each open strand's [data-strand-llm-slot] is filled with its per-strand
//     status (keep/close/…);
//   - the board unified card shows the verdict headline + %, distinct from facts;
//   - a track with NO cached verdict shows the "not run" placeholder (offline).
//
// Usage: node e2e_verdict.mjs

import { pathToFileURL, fileURLToPath } from 'url';
import { existsSync, mkdirSync, copyFileSync, rmSync, writeFileSync, readFileSync } from 'fs';
import { homedir, tmpdir } from 'os';
import { join, dirname } from 'path';
import { execSync } from 'child_process';

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = process.env.FLEET_OUT || join(homedir(), '.fleet');
const OUT = join(tmpdir(), 'fleet-e2e-verdict');
const FIXTURE = join(HERE, 'fixtures', 'e2e_analyze.json');
const TRACK = 'communications-hub-morning-briefing';

if (!existsSync(join(SRC, 'status.json'))) {
  console.error(`✗ no base fleet data at ${SRC}`); process.exit(1);
}

rmSync(OUT, { recursive: true, force: true });
mkdirSync(OUT, { recursive: true });
if (existsSync(join(SRC, 'tracks.json'))) copyFileSync(join(SRC, 'tracks.json'), join(OUT, 'tracks.json'));
let baseOvr = {};
try { baseOvr = JSON.parse(readFileSync(join(SRC, 'track-overrides.json'), 'utf8')); } catch { }
writeFileSync(join(OUT, 'track-overrides.json'), JSON.stringify(baseOvr, null, 2));

execSync(`python3 collector.py --out "${OUT}" --analyze-fixture "${FIXTURE}"`,
  { cwd: HERE, stdio: 'pipe' });

const HTML = join(OUT, 'dashboard.html');
if (!existsSync(HTML)) { console.error(`✗ no ${HTML}`); process.exit(1); }

const G = execSync('npm root -g', { encoding: 'utf8' }).trim();
const { chromium } = await import(pathToFileURL(join(G, '@playwright', 'test', 'index.mjs')).href);

const results = [];
const check = (n, ok, d = '') => { results.push({ n, ok }); console.log(`${ok ? '✓' : '✗'} ${n}${d ? ' — ' + d : ''}`); };

const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1500, height: 1900 } });
await p.goto(pathToFileURL(HTML).href);
await p.waitForSelector('#app');
await p.waitForTimeout(150);

// Navigate the REAL path to the track detail page.
await p.locator('[data-product="magic-me"]').first().click();
await p.waitForTimeout(150);
await p.locator('[data-repo="claw-playbook"]').first().click();
await p.waitForTimeout(180);

// The board unified card shows the verdict headline + % (distinct from facts).
const cardV = await p.evaluate(() => {
  const cv = document.querySelector('[data-unified-track="communications-hub-morning-briefing"] [data-region="card-verdict"]');
  return cv ? { headline: !!cv.querySelector('[data-verdict-headline]'), pct: !!cv.querySelector('[data-verdict-pct]'), text: cv.textContent } : null;
});
check('board unified card shows the LLM verdict headline + completion %',
  !!cardV && cardV.headline && cardV.pct, cardV ? cardV.text.trim().slice(0, 40) : 'missing');

// Open the track detail page by clicking the track name.
await p.locator('[data-unified-track="communications-hub-morning-briefing"] [data-action="open-track"]').first().click();
await p.waitForTimeout(200);
const onTrack = await p.evaluate((t) => STATE.level === 'track' && STATE.trackName === t, TRACK);
check('clicking the track name opens the track detail page', onTrack);

// The verdict region is FILLED (data-verdict="shown"), not the placeholder.
const vr = await p.evaluate(() => {
  const el = document.querySelector('[data-region="track-verdict"]');
  return el ? {
    shown: el.getAttribute('data-verdict') === 'shown',
    headline: (el.querySelector('[data-verdict-headline]') || {}).textContent || '',
    pct: (el.querySelector('[data-region="completion"]') || {}).getAttribute?.('data-pct'),
    cleanup: el.querySelectorAll('[data-cleanup-item]').length,
    rels: el.querySelectorAll('[data-relationship]').length,
  } : null;
});
check('track-verdict region is FILLED (not the "not run" placeholder)', !!vr && vr.shown);
check('verdict shows the headline "SHIPPED · needs cleanup"',
  !!vr && /SHIPPED/.test(vr.headline), vr && vr.headline);
check('verdict shows the COMPUTED completion % (auditable, = 75)',
  !!vr && vr.pct === '75', vr && `pct=${vr.pct}`);
check('verdict shows the cleanup list (close spec #118, …)', !!vr && vr.cleanup >= 2, vr && `${vr.cleanup} items`);
check('verdict shows relationships', !!vr && vr.rels >= 2, vr && `${vr.rels} rels`);

// A LOW-confidence relationship renders as a QUESTION (⚠ … confirm), distinct.
const lowRel = await p.evaluate(() => {
  const rels = [...document.querySelectorAll('[data-relationship]')];
  const competing = rels.find(r => r.getAttribute('data-relation') === 'competing');
  return competing ? competing.textContent : null;
});
check('a low-confidence relationship renders as a QUESTION (⚠ … confirm), not a fact',
  !!lowRel && /⚠/.test(lowRel) && /confirm/i.test(lowRel), lowRel ? lowRel.trim().slice(0, 50) : 'missing');

// Per-strand slot: open #118 (a 'close' strand) and #115 (a 'keep' strand).
await p.evaluate(() => { STATE.strandOpen['claw-playbook#118'] = true; STATE.strandOpen['claw-playbook#115'] = true; render(); });
await p.waitForTimeout(180);
const strandSlots = await p.evaluate(() => {
  const s118 = document.querySelector('[data-strand-detail="claw-playbook#118"] [data-strand-llm-slot]');
  const s115 = document.querySelector('[data-strand-detail="claw-playbook#115"] [data-strand-llm-slot]');
  return {
    s118: s118 ? s118.getAttribute('data-strand-status') : null,
    s115: s115 ? s115.getAttribute('data-strand-status') : null,
    s118text: s118 ? s118.textContent : '',
  };
});
check('per-strand slot for #118 shows status "close"', strandSlots.s118 === 'close', `status=${strandSlots.s118}`);
check('per-strand slot for #115 shows status "keep"', strandSlots.s115 === 'keep', `status=${strandSlots.s115}`);

await p.screenshot({ path: join(OUT, 'e2e-verdict.png'), fullPage: true });

// OFFLINE PATH: a track WITHOUT a cached verdict shows the "not run" placeholder.
const otherTrack = await p.evaluate(() => {
  const t = (DATA.tracks || []).find(x => x.name !== 'communications-hub-morning-briefing'
    && x.name !== 'email-triage' && (x.members || []).length >= 2);
  return t ? t.name : null;
});
if (otherTrack) {
  await p.evaluate((tn) => { const t = (DATA.tracks || []).find(x => x.name === tn); goTo('track', 'magic-me', tn, (t.members_detail && t.members_detail[0] && t.members_detail[0].id.split('#')[0])); }, otherTrack);
  await p.waitForTimeout(180);
  const placeholder = await p.evaluate(() =>
    (document.querySelector('[data-region="track-verdict"]') || {}).getAttribute?.('data-verdict'));
  check(`a track with NO verdict (${otherTrack}) shows the "not run" placeholder`, placeholder === 'none', `data-verdict=${placeholder}`);
} else {
  check('offline placeholder path', true, 'no unanalyzed track to check — skipped');
}

await b.close();
const failed = results.filter(r => !r.ok).length;
console.log(`\n${failed ? '✗' : '✓'} ${results.length - failed}/${results.length} e2e checks passed`);
process.exit(failed ? 1 : 0);
