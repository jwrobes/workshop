#!/usr/bin/env node
// e2e_pipeline_tracks.mjs — END-TO-END test that the PIPELINE MAP is track-aware:
// a track shows as ONE chip at its track_stage (all its strands count once), and
// its individual strands do NOT appear as loose chips scattered across stops.
// This keeps the pipeline map consistent with the track-aware board.
//
// Track stage rule: all spec'd -> spec'd; all shipped -> shipped; else the
// furthest-along of the UNSHIPPED strands. The briefing track (impl-PRs shipped,
// spec-PR #118 in-review, issues spec'd) -> IN-REVIEW.
//
// Walks the REAL path by CLICKING (per E2E-TESTING-SKILL.md).
// Usage: node e2e_pipeline_tracks.mjs [path/to/dashboard.html]

import { pathToFileURL } from 'url';
import { existsSync } from 'fs';
import { homedir } from 'os';
import { join } from 'path';
import { execSync } from 'child_process';

const HTML = process.argv[2]
  || join(process.env.FLEET_OUT || join(homedir(), '.fleet'), 'dashboard.html');
if (!existsSync(HTML)) { console.error(`✗ no dashboard: ${HTML}`); process.exit(1); }

const G = execSync('npm root -g', { encoding: 'utf8' }).trim();
const { chromium } = await import(
  pathToFileURL(join(G, '@playwright', 'test', 'index.mjs')).href);

const results = [];
const check = (n, ok, d = '') => { results.push({ n, ok }); console.log(`${ok ? '✓' : '✗'} ${n}${d ? ' — ' + d : ''}`); };

const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1500, height: 1600 } });
await p.goto(pathToFileURL(HTML).href);
await p.waitForSelector('#app');
await p.waitForTimeout(150);

const TRACK = 'communications-hub-morning-briefing';

// Navigate to the claw-playbook repo board (has the pipeline map on top).
await p.locator('[data-product="magic-me"]').first().click();
await p.waitForTimeout(150);
await p.locator('[data-repo="claw-playbook"]').first().click();
await p.waitForTimeout(180);

// Open the in-review + shipped stops so their chips render.
await p.locator('[data-stage="review"]').first().click();
await p.waitForTimeout(120);
await p.locator('[data-stage="shipped"]').first().click();
await p.waitForTimeout(150);

// --- The briefing track is ONE chip in the IN-REVIEW stop. ---
const briefChip = p.locator('[data-stage-cards="review"] [data-pm-track="' + TRACK + '"]');
check('briefing track is ONE track chip in the IN-REVIEW stop',
  await briefChip.count() === 1, `found ${await briefChip.count()}`);

// --- Its merged impl strands do NOT appear as loose plan chips anywhere. ---
const looseStrands = await p.evaluate(() => {
  const map = document.querySelector('[data-region="pipeline-map"]');
  if (!map) return -1;
  const pat = /(briefing curation Stages|tag Digest emails for briefing|feat\(bosque\): Communications Hub)/i;
  // A loose strand = a per-card chip ([data-plan]) matching a briefing strand
  // title. (Track chips are [data-pm-track], not [data-plan].)
  return [...map.querySelectorAll('[data-plan]')].filter(c => pat.test(c.textContent)).length;
});
check('briefing strands are NOT loose chips in the pipeline map',
  looseStrands === 0, `${looseStrands} loose strand chips`);

// --- A fully-shipped track shows as one chip in the SHIPPED stop. ---
const shippedTrackChips = await p.evaluate(() =>
  document.querySelectorAll('[data-stage-cards="shipped"] [data-pm-track]').length);
check('fully-shipped tracks show as track chips in the SHIPPED stop',
  shippedTrackChips > 0, `${shippedTrackChips} shipped track chips`);

// --- SHIPPED count is track-aware (tracks count once) but still non-zero. ---
const shippedShown = await p.evaluate(() => {
  for (const s of document.querySelectorAll('[data-stage="shipped"]')) {
    const m = s.textContent.match(/(\d+)/);
    if (m) return parseInt(m[1], 10);
  }
  return null;
});
check('pipeline SHIPPED count is non-zero (tracks counted as units)',
  shippedShown !== null && shippedShown > 0, `shown=${shippedShown}`);

// --- Clicking the track chip opens the TRACK detail page. ---
await briefChip.first().click();
await p.waitForTimeout(150);
const onTrack = await p.evaluate((t) => STATE.level === 'track' && STATE.trackName === t, TRACK);
check('clicking a pipeline track chip opens the track detail page', onTrack);

await p.screenshot({ path: join(homedir(), '.fleet', 'e2e-pipeline-tracks.png'), fullPage: true });
await b.close();

const failed = results.filter(r => !r.ok).length;
console.log(`\n${failed ? '✗' : '✓'} ${results.length - failed}/${results.length} e2e checks passed`);
process.exit(failed ? 1 : 0);
