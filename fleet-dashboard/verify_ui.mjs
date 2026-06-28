#!/usr/bin/env node
// verify_ui.mjs — headless UI regression guard for the Fleet Dashboard.
//
// Loads the generated dashboard.html in chromium (via Playwright), drives the
// SPA, and asserts the RENDERED DOM matches the requirements we agreed on —
// the things pytest (which only sees status.json) can't see.
//
// Usage:
//   node verify_ui.mjs [path/to/dashboard.html]
//   (defaults to $FLEET_OUT/dashboard.html or ~/.fleet/dashboard.html)
//
// Requires Playwright on the module path. fleet-dashboard is a pure-Python tool
// (no package.json), so this imports from the GLOBAL @playwright/test install.
// run_verify.sh sets NODE_PATH to the global modules dir before calling node.
//
// Exit 0 = all checks pass. Exit 1 = a requirement failed (prints which).
// Writes a screenshot next to the html for human confirmation.

import { pathToFileURL } from 'url';
import { existsSync } from 'fs';
import { homedir } from 'os';
import { join, dirname } from 'path';
import { execSync } from 'child_process';

// fleet-dashboard is a Python tool (no package.json), so Playwright is taken
// from the GLOBAL node install. ESM ignores NODE_PATH for bare specifiers, so
// resolve the global module dir and import @playwright/test by absolute URL.
const GLOBAL_MODS = execSync('npm root -g', { encoding: 'utf8' }).trim();
const pwEntry = join(GLOBAL_MODS, '@playwright', 'test', 'index.mjs');
const pwPath = existsSync(pwEntry)
  ? pwEntry : join(GLOBAL_MODS, '@playwright', 'test', 'index.js');
const { chromium } = await import(pathToFileURL(pwPath).href);

const argPath = process.argv[2];
const outDir = process.env.FLEET_OUT || join(homedir(), '.fleet');
const HTML = argPath || join(outDir, 'dashboard.html');
if (!existsSync(HTML)) {
  console.error(`✗ dashboard not found: ${HTML} (run ./run.sh first)`);
  process.exit(1);
}

const results = [];
function check(name, cond, detail = '') {
  results.push({ name, ok: !!cond, detail });
  console.log(`${cond ? '✓' : '✗'} ${name}${detail ? ' — ' + detail : ''}`);
}

// Each requirement is a function (page) => Promise. They run in order; the SPA
// is reset to the fleet view between groups via goTo('fleet').
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
await page.goto(pathToFileURL(HTML).href);
await page.waitForSelector('#app', { state: 'attached' });
await page.waitForTimeout(150); // let the initial render settle

// Helper: navigate via the SPA's own router so we don't depend on layout.
async function goTo(level, productId = null, planId = null, repoId = null) {
  await page.evaluate(([l, p, pl, r]) => window.goTo(l, p, pl, r),
    [level, productId, planId, repoId]);
  await page.waitForTimeout(120);
}

// ----- REQ 1: the fleet view renders products incl. Magic Me ----------------
await goTo('fleet');
const hasMagicMe = await page.locator('[data-product="magic-me"]').count();
check('fleet view shows Magic Me product', hasMagicMe > 0, `${hasMagicMe} card(s)`);

// ----- REQ 2 (Phase 1 lock): the communications-hub plan, under Magic Me /
// claw-playbook, has PR #113 attached — NOT scattered as a remote-only card.
// We read the inlined DATA to assert the attachment at the data level (the UI
// renders from it), which is the precise Phase-1 contract.
const planAttach = await page.evaluate(() => {
  const cards = (window.DATA && window.DATA.kanban) || [];
  const plan = cards.find(c =>
    c.slug === 'communications-hub-morning-briefing' && c.level === 'product');
  if (!plan) return { found: false };
  return {
    found: true,
    product: plan.product,
    ghNumber: plan.github && plan.github.number,
  };
});
check('communications-hub plan card exists at product level',
  planAttach.found, planAttach.found ? `product=${planAttach.product}` : 'MISSING');
check('  → PR #113 is ATTACHED to it (not a remote-only orphan)',
  planAttach.ghNumber === 113, `github.number=${planAttach.ghNumber}`);
check('  → it is under the magic-me product',
  planAttach.product === 'magic-me', `product=${planAttach.product}`);

// ----- REQ 3: navigate Magic Me → claw-playbook renders a repo board --------
await goTo('product', 'magic-me');
const onProduct = await page.locator('[data-view="product"][data-product="magic-me"]').count();
check('Magic Me product view renders', onProduct > 0);
const clawRepo = await page.locator('[data-repo="claw-playbook"]').count();
check('claw-playbook repo card shows under Magic Me', clawRepo > 0);

// ----- REQ 4 (Phase 3): a member repo with local activity but no plans
// (yogada — a dirty clone) still surfaces in the grid, case-insensitively. ----
const yogadaRepo = await page.locator('[data-repo="yogada"]').count();
check('yogada member repo surfaces (dirty clone, no plans)', yogadaRepo > 0,
  `${yogadaRepo} card(s)`);

// ----- REQ 5 (Phase 3): no default-branch (main/master) checkout is flagged
// `unprotected` — that false alarm buried the real actionable items. Assert at
// the data level (the flag the UI reads), which is the precise contract. -------
const badUnprotected = await page.evaluate(() => {
  const wts = (window.DATA && window.DATA.worktrees) || [];
  return wts
    .filter(w => (w.flags || []).includes('unprotected')
      && (w.branch === 'main' || w.branch === 'master'))
    .map(w => `${w.repo}:${w.branch}`);
});
check('no main/master checkout flagged `unprotected`',
  badUnprotected.length === 0,
  badUnprotected.length ? badUnprotected.join(', ') : 'none');

// ----- REQ 6 (Phase 4a): merged impl PRs produce a `shipped` signal — the
// pipeline must no longer read SHIPPED 0 when real work has merged. -----------
const shipInfo = await page.evaluate(() => {
  const cards = (window.DATA && window.DATA.kanban) || [];
  const shipped = cards.filter(c => c.shipped);
  return {
    count: shipped.length,
    sample: shipped.slice(0, 3).map(c => `${c.slug}#${c.shipped_pr}`),
    everyShippedHasPr: shipped.every(c => c.shipped_pr != null),
  };
});
check('merged impl PRs mark cards `shipped` (pipeline SHIPPED > 0)',
  shipInfo.count > 0, `${shipInfo.count} shipped; e.g. ${shipInfo.sample.join(', ')}`);
check('  every shipped card carries its merged PR number',
  shipInfo.everyShippedHasPr);

// Screenshot for human confirmation.
const shot = join(dirname(HTML), 'verify-magic-me.png');
await goTo('product', 'magic-me');
await page.screenshot({ path: shot, fullPage: true });
console.log(`\n📸 screenshot: ${shot}`);

await browser.close();

const failed = results.filter(r => !r.ok);
console.log(`\n${failed.length ? '✗' : '✓'} ${results.length - failed.length}/${results.length} UI checks passed`);
process.exit(failed.length ? 1 : 0);
