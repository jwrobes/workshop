#!/usr/bin/env node
// e2e_unified_card.mjs — END-TO-END test that a TRACK renders as ONE unified
// card on the repo board (not N separate rows), showing the shape of the work.
//
// The lesson behind this file (see E2E-TESTING-SKILL.md): the data grouped the
// briefing PRs into a track, but the repo board — the view the user navigates
// to — still rendered #115/#117/#119 as 3 separate rows in Completed. The data
// being right while the board is wrong is exactly the SHIPPED-0 class of bug.
// So this test walks the REAL path by CLICKING and asserts on the RENDERED
// board DOM (not window.DATA): one unified card, expandable to a strand map.
//
// Usage: node e2e_unified_card.mjs [path/to/dashboard.html]
// Exit 0 = all pass; 1 = a requirement failed.

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

// --- Navigate the REAL user path: fleet -> Magic Me -> claw-playbook (clicks). ---
check('start on fleet view', await p.evaluate(() => STATE.level) === 'fleet');
await p.locator('[data-product="magic-me"]').first().click();
await p.waitForTimeout(150);
await p.locator('[data-repo="claw-playbook"]').first().click();
await p.waitForTimeout(150);
const onRepo = await p.evaluate(() => STATE.level === 'repo' && STATE.repoId === 'claw-playbook');
check('clicked into claw-playbook repo board', onRepo);

// --- Expand the Completed column (the briefing work is shipped). ---
const completedHead = p.locator('[data-region="board"] >> text=Completed').first();
if (await completedHead.count()) { await completedHead.click(); await p.waitForTimeout(150); }

// The track under test. Members after overrides:
//   #118 open spec-PR, #111/#112 open issues, #115/#117/#119 merged impl-PRs.
const TRACK = 'communications-hub-morning-briefing';

// --- ASSERTION 1: exactly ONE unified card for this track on the board. ---
const uni = p.locator(`[data-view="repo"] [data-unified-track="${TRACK}"]`);
const uniCount = await uni.count();
check('exactly ONE unified card for the briefing track (not N rows)',
  uniCount === 1, `found ${uniCount}`);

// The briefing members must NOT appear as separate top-level card rows: any
// [data-plan-id] card row whose title matches a briefing strand and is NOT
// inside the unified card means the collapse failed (the old 3-rows bug).
const looseBriefingRows = await p.evaluate(() => {
  const board = document.querySelector('[data-view="repo"]');
  if (!board) return -1;
  const pat = /(briefing curation Stages|tag Digest emails for briefing|Communications Hub)/i;
  return [...board.querySelectorAll('[data-plan-id]')]
    .filter(n => pat.test(n.textContent) && !n.closest('[data-unified-track]'))
    .length;
});
check('briefing strands are NOT rendered as separate loose card rows',
  looseBriefingRows === 0, `${looseBriefingRows} loose rows`);

// --- ASSERTION 2: expand the unified card -> strand map. ---
if (uniCount === 1) {
  // The card is expandable: click its header/toggle.
  const toggle = uni.locator('[data-action="toggle-track"]').first();
  if (await toggle.count()) { await toggle.click(); await p.waitForTimeout(120); }
}
const strands = await p.evaluate((track) => {
  const card = document.querySelector(`[data-unified-track="${track}"]`);
  if (!card) return null;
  const out = {};
  for (const s of card.querySelectorAll('[data-strand-member]')) {
    out[s.getAttribute('data-strand-member')] = {
      role: s.getAttribute('data-strand-role'),
      state: s.getAttribute('data-strand-state'),
      source: s.getAttribute('data-strand-source'),
      stage: s.getAttribute('data-strand-stage'),
    };
  }
  return out;
}, TRACK);

check('unified card exposes strand members', strands && Object.keys(strands).length >= 4,
  strands ? `${Object.keys(strands).length} strands` : 'no strands');

// --- ASSERTION 3: each key strand has role + state + source + stage. ---
const want = {
  'claw-playbook#115': { role: 'impl-PR', state: 'merged', stage: 'shipped' },
  'claw-playbook#117': { role: 'impl-PR', state: 'merged', stage: 'shipped' },
  'claw-playbook#119': { role: 'impl-PR', state: 'merged', stage: 'shipped' },
  'claw-playbook#118': { role: 'spec-PR', state: 'open' },
};
for (const [id, exp] of Object.entries(want)) {
  const got = strands && strands[id];
  const ok = got && got.role === exp.role && got.state === exp.state
    && (exp.stage ? got.stage === exp.stage : true)
    && got.source != null;  // source is present (may be '—' when undetectable)
  check(`  strand ${id}: role=${exp.role} state=${exp.state}` + (exp.stage ? ` stage=${exp.stage}` : ''),
    ok, got ? `role=${got.role} state=${got.state} source=${got.source} stage=${got.stage}` : 'missing');
}

// #118 is an OPEN spec-PR inside the SAME unified card, not a separate card.
const specInsideSameCard = await p.evaluate((track) => {
  const card = document.querySelector(`[data-unified-track="${track}"]`);
  return !!(card && card.querySelector('[data-strand-member="claw-playbook#118"]'));
}, TRACK);
check('open spec-PR #118 lives inside the same unified card', specInsideSameCard);

await p.screenshot({ path: join(homedir(), '.fleet', 'e2e-unified-card.png'), fullPage: true });
await b.close();

const failed = results.filter(r => !r.ok).length;
console.log(`\n${failed ? '✗' : '✓'} ${results.length - failed}/${results.length} e2e checks passed`);
process.exit(failed ? 1 : 0);
