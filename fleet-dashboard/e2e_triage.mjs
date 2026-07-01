#!/usr/bin/env node
// e2e_triage.mjs — END-TO-END test of PASS 1 (LLM triage), driven by a CANNED
// fixture (never the real claude CLI — offline + deterministic, per the plan's
// verification discipline). Generates its OWN dashboard into a temp dir seeded
// from ~/.fleet so it never mutates the user's real overrides file.
//
// Proves, on the REAL rendered dashboard the user navigates:
//   1. a FUZZY stray (no closes-ref, auto-named branch — deterministic attach
//      can't catch it) becomes a track MEMBER after high-confidence auto-attach;
//   2. an ARCHIVED stray is GONE from Ungrouped AND the board, but STILL present
//      in status.json (soft-hide), and returns when unarchived;
//   3. medium/low + create/archive proposals surface as SUGGESTIONS (accept/
//      dismiss), NOT auto-applied to membership.
//
// Usage: node e2e_triage.mjs

import { pathToFileURL } from 'url';
import { existsSync, mkdirSync, copyFileSync, rmSync, writeFileSync, readFileSync } from 'fs';
import { homedir, tmpdir } from 'os';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import { execSync } from 'child_process';

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = process.env.FLEET_OUT || join(homedir(), '.fleet');
const OUT = join(tmpdir(), 'fleet-e2e-triage');
const FIXTURE = join(HERE, 'fixtures', 'e2e_triage.json');

// The strays we assert on (must be genuinely ungrouped in the base data).
const FUZZY = 'claw-playbook#84';     // -> high-conf auto-attach to email-triage
const ARCHIVED = 'yogada-shop#7';      // -> archived (applied via seed overrides)
const TRACK = 'email-triage';

if (!existsSync(join(SRC, 'status.json'))) {
  console.error(`✗ no base fleet data at ${SRC} — run the collector first`);
  process.exit(1);
}

// --- Seed a temp output dir with the cached tracks + a base overrides file that
//     ALREADY archives the target (so the applied-archive path is exercised). ---
rmSync(OUT, { recursive: true, force: true });
mkdirSync(OUT, { recursive: true });
if (existsSync(join(SRC, 'tracks.json'))) copyFileSync(join(SRC, 'tracks.json'), join(OUT, 'tracks.json'));
// Base overrides: carry over the real reassigns AND pre-apply the archive so
// the e2e can assert the archived card is dropped from the live surfaces.
let baseOvr = {};
try { baseOvr = JSON.parse(readFileSync(join(SRC, 'track-overrides.json'), 'utf8')); } catch { }
baseOvr.archive = [...new Set([...(baseOvr.archive || []), ARCHIVED])];
writeFileSync(join(OUT, 'track-overrides.json'), JSON.stringify(baseOvr, null, 2));

// --- Generate the dashboard through the REAL triage code path (fixture runner). ---
execSync(`python3 collector.py --out "${OUT}" --triage-fixture "${FIXTURE}"`,
  { cwd: HERE, stdio: 'pipe' });

const HTML = join(OUT, 'dashboard.html');
if (!existsSync(HTML)) { console.error(`✗ collector did not produce ${HTML}`); process.exit(1); }

const G = execSync('npm root -g', { encoding: 'utf8' }).trim();
const { chromium } = await import(pathToFileURL(join(G, '@playwright', 'test', 'index.mjs')).href);

const results = [];
const check = (n, ok, d = '') => { results.push({ n, ok }); console.log(`${ok ? '✓' : '✗'} ${n}${d ? ' — ' + d : ''}`); };

const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1500, height: 1900 } });
await p.goto(pathToFileURL(HTML).href);
await p.waitForSelector('#app');
await p.waitForTimeout(150);

// === 1. Fuzzy stray became a MEMBER (auto-attach + re-stamp). ===
const memberInfo = await p.evaluate(({ track, fuzzy }) => {
  const t = (DATA.tracks || []).find(x => x.name === track);
  return {
    isMember: !!(t && (t.members || []).includes(fuzzy)),
    source: (DATA.tracks || []).find(x => x.name === track)?.source,
  };
}, { track: TRACK, fuzzy: FUZZY });
check(`fuzzy stray ${FUZZY} is now a MEMBER of "${TRACK}" (auto-attach)`, memberInfo.isMember);

// REGRESSION GUARD: a DETERMINISTIC stray (attached by branch/closes, not in
// tracks.json) must SURVIVE the auto-attach rebuild. The collector builds tracks
// twice when an auto-attach fires; a bug once dropped #113 from the briefing
// track on that second build (it kept a dangling stamp but left the members).
const straySurvives = await p.evaluate(() => {
  const t = (DATA.tracks || []).find(x => x.name === 'communications-hub-morning-briefing');
  return !!(t && (t.members || []).includes('magic-me#113'));
});
check('a deterministic stray (#113) SURVIVES the triage rebuild (not dropped)', straySurvives);

// It must NOT still be listed as Ungrouped (navigate the REAL Work-tracks view).
await p.evaluate(() => goTo('tracks'));
await p.waitForTimeout(200);
const ungroupedHasFuzzy = await p.evaluate((id) =>
  !!document.querySelector(`[data-ungrouped-card="${CSS.escape(id)}"]`), FUZZY);
check(`fuzzy stray ${FUZZY} is NO LONGER in Ungrouped (it attached)`, ungroupedHasFuzzy === false);

// === 2. Archived stray is GONE from Ungrouped + board, PRESENT in status.json. ===
const archStillInData = await p.evaluate((id) => {
  const [scope, num] = id.split('#');
  return (DATA.kanban || []).some(c => {
    const s = c.repo || c.product;
    return s === scope && String((c.github || {}).number) === num && c.archived === true;
  });
}, ARCHIVED);
check(`archived ${ARCHIVED} is STILL in status.json (soft-hide, not deleted) with archived:true`, archStillInData);

const archInUngrouped = await p.evaluate((id) =>
  !!document.querySelector(`[data-ungrouped-card="${CSS.escape(id)}"]`), ARCHIVED);
check(`archived ${ARCHIVED} is GONE from Ungrouped`, archInUngrouped === false);

// The Archived section lists it (expand it first).
await p.locator('[data-action="toggle-archived"]').first().click();
await p.waitForTimeout(120);
const archListed = await p.evaluate((id) =>
  !!document.querySelector(`[data-archived-card="${CSS.escape(id)}"]`), ARCHIVED);
check(`archived ${ARCHIVED} IS listed in the Archived section (with unarchive)`, archListed);
const hasUnarchive = await p.evaluate(() =>
  !!document.querySelector('[data-region="archived"] [data-action="unarchive"]'));
check('Archived section offers an "unarchive" control', hasUnarchive);

// Archived card must also be absent from the repo BOARD (the surface the user
// looks at). Navigate to the yogada-shop board and confirm no card for it.
const archOnBoard = await p.evaluate((id) => {
  const [scope, num] = id.split('#');
  return (DATA.kanban || []).some(c => {
    const s = c.repo || c.product;
    return s === scope && String((c.github || {}).number) === num && !c.archived;
  });
}, ARCHIVED);
check(`archived ${ARCHIVED} is not a LIVE (unarchived) card anywhere`, archOnBoard === false);

// === 3. Medium/low + archive proposals surface as SUGGESTIONS (not auto). ===
const suggInfo = await p.evaluate(() => {
  const box = document.querySelector('[data-region="triage-suggestions"]');
  const rows = box ? [...box.querySelectorAll('[data-suggestion]')] : [];
  return {
    present: !!box,
    ids: rows.map(r => r.getAttribute('data-suggestion')),
    hasAccept: !!(box && box.querySelector('[data-action="accept-suggestion"]')),
    hasDismiss: !!(box && box.querySelector('[data-action="dismiss-suggestion"]')),
  };
});
check('Triage suggestions section is present with the medium/create/archive proposals',
  suggInfo.present && suggInfo.ids.length >= 1, `${suggInfo.ids.length} suggestions`);
check('a medium-confidence attach (#85) is a SUGGESTION, not auto-applied',
  suggInfo.ids.includes('claw-playbook#85'));
check('suggestions have accept + dismiss controls', suggInfo.hasAccept && suggInfo.hasDismiss);

// #85 (the medium suggestion) must NOT be a track member (suggestion ≠ applied).
const mediumNotMember = await p.evaluate(() =>
  !(DATA.tracks || []).some(t => (t.members || []).includes('claw-playbook#85')));
check('#85 (medium suggestion) is NOT a member of any track', mediumNotMember);

await p.screenshot({ path: join(OUT, 'e2e-triage.png'), fullPage: true });
await b.close();

const failed = results.filter(r => !r.ok).length;
console.log(`\n${failed ? '✗' : '✓'} ${results.length - failed}/${results.length} e2e checks passed`);
process.exit(failed ? 1 : 0);
