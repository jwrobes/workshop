#!/usr/bin/env node
// e2e_repo_board.mjs — END-TO-END test of the path a USER actually takes.
//
// The lesson behind this file: an earlier verifier jumped straight to the
// (convenient) Work-tracks view and "passed", while the user navigating
// fleet -> claw-playbook saw SHIPPED: 0 and none of the merged briefing work.
// A test that checks the convenient view isn't a test. This one walks the real
// journey by CLICKING, and asserts the shipped work is visible WHERE the user
// lands — on the repo board.
//
// Usage: node e2e_repo_board.mjs [path/to/dashboard.html]
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
const p = await b.newPage({ viewport: { width: 1400, height: 1400 } });
await p.goto(pathToFileURL(HTML).href);
await p.waitForSelector('#app');
await p.waitForTimeout(150);

// --- 1. Start at the fleet view (where a user lands). ---
check('start on fleet view', await p.evaluate(() => STATE.level) === 'fleet');

// --- 2. CLICK Magic Me (real click, not goTo). ---
await p.locator('[data-product="magic-me"]').first().click();
await p.waitForTimeout(150);
check('clicked into Magic Me product', await p.evaluate(() => STATE.level) === 'product');

// --- 3. CLICK the claw-playbook repo card. ---
await p.locator('[data-repo="claw-playbook"]').first().click();
await p.waitForTimeout(150);
const onRepo = await p.evaluate(() => STATE.level === 'repo' && STATE.repoId === 'claw-playbook');
check('clicked into claw-playbook repo board', onRepo);

// --- 4. THE REAL ASSERTION: the pipeline SHIPPED count is NOT 0. ---
// Read the rendered SHIPPED stage number from the pipeline map on this board.
const shippedCount = await p.evaluate(() => {
  // Find the SHIPPED stop and read its count. The map renders stage counts;
  // recompute from the same logic the UI uses to be robust to layout.
  const rplans = (window.kanban ? window.kanban() : (DATA.kanban || []))
    .filter(c => c.product === 'magic-me' && (c.repo === 'claw-playbook'));
  const shipped = rplans.filter(c => c.shipped || c.status === 'shipped'
    || c.status === 'completed' || c.status === 'done');
  return shipped.length;
});
check('claw-playbook has shipped work in the data', shippedCount > 0, `${shippedCount} shipped`);

// The number the USER sees in the pipeline SHIPPED stop must be > 0.
const shippedShown = await p.evaluate(() => {
  const stops = [...document.querySelectorAll('[data-stage="shipped"]')];
  for (const s of stops) {
    const m = s.textContent.match(/(\d+)/);
    if (m) return parseInt(m[1], 10);
  }
  return null;
});
check('pipeline SHIPPED stop shows a non-zero count (not "0")',
  shippedShown !== null && shippedShown > 0, `shown=${shippedShown}`);

// --- 5. The specific briefing PRs are FINDABLE on this board. ---
// Expand Completed, then EXPAND the briefing unified track card (the briefing
// PRs are now strands inside one track card, not loose rows — see
// UNIFIED-CARD-MODEL.md). Then look for #119 / #117 / #115 by rendered text.
const completedHead = p.locator('[data-region="board"] >> text=Completed').first();
if (await completedHead.count()) { await completedHead.click(); await p.waitForTimeout(150); }
const brief = p.locator('[data-unified-track="communications-hub-morning-briefing"]');
if (await brief.count()) {
  const toggle = brief.locator('[data-action="toggle-track"]').first();
  if (await toggle.count()) { await toggle.click(); await p.waitForTimeout(120); }
}
const boardText = await p.locator('[data-view="repo"]').innerText();
const found = {
  briefingCuration: /briefing curation Stages/i.test(boardText),
  emailTriageTag: /tag Digest emails for briefing/i.test(boardText),
  commsHub: /Communications Hub/i.test(boardText),
};
check('  #119 "briefing curation Stages 2–5" findable on the repo board', found.briefingCuration);
check('  #117 "tag Digest emails for briefing" findable on the repo board', found.emailTriageTag);
check('  #115 "Communications Hub" findable on the repo board', found.commsHub);

await p.screenshot({ path: join(homedir(), '.fleet', 'e2e-repo-board.png'), fullPage: true });
await b.close();

const failed = results.filter(r => !r.ok).length;
console.log(`\n${failed ? '✗' : '✓'} ${results.length - failed}/${results.length} e2e checks passed`);
process.exit(failed ? 1 : 0);
