#!/usr/bin/env node
// e2e_llm_runlog.mjs — END-TO-END test of the "Since last analysis" change-log
// panel (Pass 1). After a triage run with changes, the FLEET LANDING (where the
// user starts) shows a [data-region="llm-runlog"] panel that:
//   - lists the AUTO change (already applied — visually distinct: "✓ applied"),
//   - lists the SUGGESTIONS (pending review — "? attach/archive/…"),
//   - carries correct counts, and can be DISMISSED (stays gone until next run).
// Driven by a CANNED fixture (no live claude). Generates its own dashboard into
// a temp dir seeded from ~/.fleet so it never touches the real overrides.
//
// Usage: node e2e_llm_runlog.mjs

import { pathToFileURL } from 'url';
import { existsSync, mkdirSync, copyFileSync, rmSync, writeFileSync, readFileSync } from 'fs';
import { homedir, tmpdir } from 'os';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import { execSync } from 'child_process';

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = process.env.FLEET_OUT || join(homedir(), '.fleet');
const OUT = join(tmpdir(), 'fleet-e2e-runlog');
const FIXTURE = join(HERE, 'fixtures', 'e2e_triage.json');

if (!existsSync(join(SRC, 'status.json'))) {
  console.error(`✗ no base fleet data at ${SRC} — run the collector first`);
  process.exit(1);
}

rmSync(OUT, { recursive: true, force: true });
mkdirSync(OUT, { recursive: true });
if (existsSync(join(SRC, 'tracks.json'))) copyFileSync(join(SRC, 'tracks.json'), join(OUT, 'tracks.json'));
let baseOvr = {};
try { baseOvr = JSON.parse(readFileSync(join(SRC, 'track-overrides.json'), 'utf8')); } catch { }
writeFileSync(join(OUT, 'track-overrides.json'), JSON.stringify(baseOvr, null, 2));

execSync(`python3 collector.py --out "${OUT}" --triage-fixture "${FIXTURE}"`,
  { cwd: HERE, stdio: 'pipe' });

const HTML = join(OUT, 'dashboard.html');
if (!existsSync(HTML)) { console.error(`✗ collector did not produce ${HTML}`); process.exit(1); }

const G = execSync('npm root -g', { encoding: 'utf8' }).trim();
const { chromium } = await import(pathToFileURL(join(G, '@playwright', 'test', 'index.mjs')).href);

const results = [];
const check = (n, ok, d = '') => { results.push({ n, ok }); console.log(`${ok ? '✓' : '✗'} ${n}${d ? ' — ' + d : ''}`); };

const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1500, height: 1600 } });
// Fresh page context: no prior dismissal in localStorage.
await p.goto(pathToFileURL(HTML).href);
await p.waitForSelector('#app');
await p.waitForTimeout(150);

// We START on the fleet landing — the panel must be right there (no navigation).
const onFleet = await p.evaluate(() => STATE.level === 'fleet');
check('start on the fleet landing (where the user lands)', onFleet);

const panel = p.locator('[data-region="llm-runlog"]');
check('the "Since last analysis" panel is present on the fleet landing',
  await panel.count() === 1, `found ${await panel.count()}`);

// Counts on the panel match the run (1 auto attach, 2 suggestions in the fixture).
const counts = await p.evaluate(() => {
  const el = document.querySelector('[data-region="llm-runlog"]');
  return el ? { auto: +el.getAttribute('data-auto'), sugg: +el.getAttribute('data-suggestions') } : null;
});
check('panel reports the AUTO count (1 auto-attach applied)', counts && counts.auto === 1, `auto=${counts && counts.auto}`);
check('panel reports the SUGGESTION count (2 to review)', counts && counts.sugg === 2, `suggestions=${counts && counts.sugg}`);

// AUTO vs SUGGESTION are VISUALLY DISTINGUISHED (different change-kind badges).
const kinds = await p.evaluate(() => {
  const el = document.querySelector('[data-region="llm-runlog"]');
  return {
    auto: el.querySelectorAll('[data-change-kind="auto"]').length,
    suggest: el.querySelectorAll('[data-change-kind="suggest"]').length,
  };
});
check('AUTO change rendered with an "applied" badge (distinct from suggestions)', kinds.auto === 1, `auto badges=${kinds.auto}`);
check('SUGGESTION changes rendered with a distinct "proposal" badge', kinds.suggest === 2, `suggest badges=${kinds.suggest}`);

// The auto-attach row names the fuzzy stray + its track.
const autoRow = await p.evaluate(() => {
  const el = document.querySelector('[data-region="llm-runlog"] [data-change="claw-playbook#84"]');
  return el ? el.textContent : null;
});
check('the auto-attach row names #84 → email-triage',
  !!autoRow && /claw-playbook#84/.test(autoRow) && /email-triage/.test(autoRow), autoRow ? autoRow.trim().slice(0, 60) : 'missing');

// A "Review in Work-tracks" jump exists (the panel doubles as the review queue).
check('panel offers a "Review in Work-tracks" jump',
  await p.locator('[data-region="llm-runlog"] [data-action="review-suggestions"]').count() === 1);

await p.screenshot({ path: join(OUT, 'e2e-llm-runlog.png'), fullPage: true });

// === DISMISS: clicking dismiss removes the panel; it stays gone on re-render. ===
await p.locator('[data-region="llm-runlog"] [data-action="dismiss-runlog"]').first().click();
await p.waitForTimeout(150);
check('dismissing removes the panel', await p.locator('[data-region="llm-runlog"]').count() === 0);

// Re-render (navigate away and back) — still dismissed (persisted for this run).
await p.evaluate(() => goTo('tracks'));
await p.waitForTimeout(120);
await p.evaluate(() => goTo('fleet'));
await p.waitForTimeout(150);
check('panel stays dismissed across re-render (persisted by run timestamp)',
  await p.locator('[data-region="llm-runlog"]').count() === 0);

await b.close();

const failed = results.filter(r => !r.ok).length;
console.log(`\n${failed ? '✗' : '✓'} ${results.length - failed}/${results.length} e2e checks passed`);
process.exit(failed ? 1 : 0);
