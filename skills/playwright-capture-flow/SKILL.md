# Playwright: Capture Flow

Record an interactive Playwright MCP session and generate a reusable headless script from it.

## When to Use

After completing a successful Playwright MCP flow (login, navigate, click, type, etc.), the user says:
- "capture that as a script"
- "turn that into a reusable script"
- "graduate this to headless"
- "record that flow"
- "make that repeatable"

## How It Works

**Phase 1: Interactive exploration (MCP)** — The agent uses Playwright MCP to walk through a flow. It navigates pages, takes snapshots, clicks elements, fills forms. This is the discovery phase — figuring out selectors, page structure, and the sequence of actions.

**Phase 2: Capture (this skill)** — After the MCP flow succeeds, the agent reviews the Playwright actions it took and generates a headless Node.js script that replays the same flow.

## Procedure

### Step 1: Gather the MCP action log

Review the conversation for all Playwright MCP tool calls that were part of the successful flow. Extract in order:

- `browser_navigate` — URLs visited
- `browser_click` — Element refs and the Playwright code that was generated (the `getByRole`, `getByText`, etc.)
- `browser_type` — Element refs and text entered
- `browser_snapshot` — What was visible (for assertions)
- `browser_fill_form` — Form fields filled
- `browser_select_option` — Dropdowns selected

The key data is in the **"Ran Playwright code"** section of each MCP result — that's the actual Playwright API call that worked.

### Step 2: Identify parameterizable inputs

Look at the flow and determine what should be CLI arguments vs hard-coded:

| Hard-code | Parameterize |
|---|---|
| Selectors (role, name, placeholder) | User-provided text (messages, form values) |
| Navigation paths (relative URLs) | Account IDs, entity IDs |
| Wait conditions | Base URL (localhost vs staging) |
| Assertion patterns | Output file paths, screenshots |

### Step 3: Generate the script

Create a new file at `<your-playwright-flows-dir>/scripts/<flow-name>.js` following this template. (A common convention is `~/.local/playwright-flows/scripts/`, but use whatever path makes sense for your setup.)

```javascript
/**
 * <Description of what this flow does>
 *
 * Usage:
 *   node <flow-name>.js <required-args> [options]
 *
 * Output (JSON to stdout):
 *   { "success": true, "timestamp": "...", ... }
 */

const { chromium } = require('playwright');

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = {
    baseUrl: 'http://localhost:3000',
    headed: false,
    timeout: 30000,
    screenshotPath: null,
    // ... flow-specific defaults
  };

  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case '--base-url': opts.baseUrl = args[++i]; break;
      case '--headed': opts.headed = true; break;
      case '--timeout': opts.timeout = parseInt(args[++i], 10); break;
      case '--screenshot': opts.screenshotPath = args[++i]; break;
      // ... flow-specific args
    }
  }

  // Validate required args
  return opts;
}

async function runFlow(opts) {
  const timestamp = new Date().toISOString();
  const browser = await chromium.launch({ headless: !opts.headed });
  const context = await browser.newContext();
  const page = await context.newPage();

  try {
    // Paste the MCP "Ran Playwright code" steps here, adapted:
    // - Replace page.goto('http://localhost:3000/...') with template literals using opts.baseUrl
    // - Add waitFor() before interactions for reliability
    // - Add try/catch for assertions

    // Return structured result
    return { success: true, timestamp, /* ... flow-specific output */ };

  } catch (err) {
    if (opts.screenshotPath) {
      await page.screenshot({ path: opts.screenshotPath, fullPage: true }).catch(() => {});
    }
    return { success: false, timestamp, error: err.message, url: page.url() };
  } finally {
    await browser.close();
  }
}

(async () => {
  const opts = parseArgs();
  const result = await runFlow(opts);
  console.log(JSON.stringify(result, null, 2));
  process.exit(result.success ? 0 : 1);
})();
```

### Step 4: Register in the dispatcher

If your playwright tooling uses a dispatcher (e.g., `pw <flow-name>`), add the new command to its help text. A typical pattern is auto-discovery of `scripts/<name>.js` so no code change is required.

### Step 5: Test the generated script

Run it once headless, once headed to verify:

```bash
# Headless
node <your-playwright-flows-dir>/scripts/<flow-name>.js <args>

# Headed (visual verification)
node <your-playwright-flows-dir>/scripts/<flow-name>.js <args> --headed
```

### Step 6: Report to user

Show the user:
- The script path
- The command to run it
- The JSON output format
- What was parameterized vs hard-coded

## Translation Rules: MCP to Playwright Script

| MCP tool call | Script equivalent |
|---|---|
| `browser_navigate({ url })` | `await page.goto(url, { waitUntil: 'networkidle' })` |
| `browser_click({ ref })` + "Ran: `page.getByRole(...).click()`" | Copy the `getByRole` call directly, add `waitFor` before it |
| `browser_type({ ref, text })` + "Ran: `page.getByRole(...).fill(...)`" | Copy the `getByRole` + `fill` call directly |
| `browser_snapshot` showing text X visible | `await expect(page.getByText('X')).toBeVisible()` or `page.getByText('X').isVisible()` |
| `browser_wait_for({ time: N })` | `await page.waitForTimeout(N * 1000)` |
| `browser_press_key({ key })` | `await page.keyboard.press(key)` |

**Critical**: Always copy selectors from the "Ran Playwright code" output, not from the ref IDs. The refs are ephemeral — the `getByRole`/`getByText` calls are stable.

## Reference Pattern

A well-formed flow script typically demonstrates: argument parsing (positional + flag), explicit error handling, JSON-on-stdout for downstream tooling, optional screenshot support for visual verification, and a clean exit code (0 on success, 1 on failure).

## Naming Convention

Scripts are named by their action: `send-message.js`, `check-inbox.js`, `login-as-user.js`, `verify-notification.js`. Use kebab-case. If your dispatcher auto-discovers scripts by filename, the action name doubles as the command.
