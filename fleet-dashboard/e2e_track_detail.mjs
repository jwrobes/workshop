#!/usr/bin/env node
// e2e_track_detail.mjs — END-TO-END test of the full TRACK DETAIL page: the
// user clicks a track's name on the repo board and lands on its own page, where
// the strands are laid out along the pipeline (spec'd..shipped) as chips, and
// clicking a chip opens its full detail (title, description, source, branch,
// GitHub link). See UNIFIED-CARD-MODEL.md.
//
// Walks the REAL path by CLICKING (per E2E-TESTING-SKILL.md) and asserts on the
// RENDERED DOM the user reads, not window.DATA.
//
// Usage: node e2e_track_detail.mjs [path/to/dashboard.html]

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
const p = await b.newPage({ viewport: { width: 1400, height: 1600 } });
await p.goto(pathToFileURL(HTML).href);
await p.waitForSelector('#app');
await p.waitForTimeout(150);

const TRACK = 'communications-hub-morning-briefing';

// --- Navigate the REAL path: fleet -> Magic Me -> claw-playbook -> expand
//     Completed -> CLICK the track NAME to open its full page. ---
await p.locator('[data-product="magic-me"]').first().click();
await p.waitForTimeout(150);
await p.locator('[data-repo="claw-playbook"]').first().click();
await p.waitForTimeout(150);
const completedHead = p.locator('[data-region="board"] >> text=Completed').first();
if (await completedHead.count()) { await completedHead.click(); await p.waitForTimeout(150); }

// Click the track name (the open-track affordance), NOT the chevron preview.
const nameBtn = p.locator(`[data-unified-track="${TRACK}"] [data-action="open-track"]`).first();
check('track name is clickable on the board', await nameBtn.count() > 0);
await nameBtn.click();
await p.waitForTimeout(150);

const onTrack = await p.evaluate((t) => STATE.level === 'track' && STATE.trackName === t, TRACK);
check('clicking the track name opens the full track page', onTrack);
check('track view is rendered', await p.locator(`[data-view="track"][data-track="${TRACK}"]`).count() === 1);

// --- The verdict slot (reserved for the Phase-3 LLM) is present. ---
check('reserved LLM analysis region is present', await p.locator('[data-region="track-verdict"]').count() === 1);

// --- Pipeline lanes: strands land in the correct stage lane. ---
const lanes = await p.evaluate(() => {
  const out = {};
  for (const l of document.querySelectorAll('[data-region="pipeline-lanes"] [data-lane]')) {
    out[l.getAttribute('data-lane')] = [...l.querySelectorAll('[data-strand-member]')]
      .map(c => c.getAttribute('data-strand-member'));
  }
  return out;
});
check('5 pipeline lanes rendered', Object.keys(lanes).length === 5, Object.keys(lanes).join(','));
check('  #115/#117/#119 (merged impl) sit in the SHIPPED lane',
  ['claw-playbook#115', 'claw-playbook#117', 'claw-playbook#119']
    .every(id => (lanes.shipped || []).includes(id)),
  `shipped=[${(lanes.shipped || []).join(', ')}]`);
check('  #118 (open spec-PR) sits in the IN-REVIEW lane',
  (lanes.review || []).includes('claw-playbook#118'),
  `review=[${(lanes.review || []).join(', ')}]`);
check('  #111/#112 (open issues) sit in the SPEC lane',
  ['claw-playbook#111', 'claw-playbook#112'].every(id => (lanes.spec || []).includes(id)),
  `spec=[${(lanes.spec || []).join(', ')}]`);

// --- Click a strand chip -> its detail panel opens with the helpful detail. ---
const chip118 = p.locator('[data-strand-member="claw-playbook#118"]').first();
await chip118.click();
await p.waitForTimeout(150);
const panel = await p.evaluate(() => {
  const el = document.querySelector('[data-strand-detail="claw-playbook#118"]');
  if (!el) return null;
  return {
    hasTitle: /Specs/i.test(el.textContent),
    hasSource: !!el.querySelector('[data-strand-source-tag]') || /source:/i.test(el.textContent),
    hasBodyRegion: !!el.querySelector('[data-strand-body]'),
    hasLink: !!el.querySelector('[data-strand-link]'),
    hasLlmSlot: !!el.querySelector('[data-strand-llm-slot]'),
    text: el.textContent.slice(0, 400),
  };
});
check('clicking a strand chip opens its detail panel', panel !== null);
check('  detail panel shows the full title', panel && panel.hasTitle);
check('  detail panel shows a description region (what it is trying to do)', panel && panel.hasBodyRegion);
check('  detail panel links out to GitHub', panel && panel.hasLink);
check('  detail panel reserves a per-strand LLM slot (Phase 3)', panel && panel.hasLlmSlot);

await p.screenshot({ path: join(homedir(), '.fleet', 'e2e-track-detail.png'), fullPage: true });
await b.close();

const failed = results.filter(r => !r.ok).length;
console.log(`\n${failed ? '✗' : '✓'} ${results.length - failed}/${results.length} e2e checks passed`);
process.exit(failed ? 1 : 0);
