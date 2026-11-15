---
name: enforce-integration-test
description: "Plan and validate end-to-end integration tests before running them. Prevents mock-heavy tests from masquerading as integration tests. Use when the user asks for an integration test, e2e test, or says 'test this for real'."
disable_model_invocation: true
---

# Enforce Integration Test

Stop before writing any test code. An integration test exercises the REAL
system — if you're mocking the thing being tested, it's a unit test.

## The Rule

> If the test doesn't start a real process and send it real input, it is
> not an integration test. Naming it `test_e2e_*` doesn't change that.

## Before writing ANY test code

Answer these questions explicitly and show them to the user. Do not
proceed until every answer is confirmed.

### 1. What is the system under test?

State the exact process/service that must be running. Not a class, not a
function — the deployed artifact.

```
System under test: _______________
How to start it:   _______________
How to verify it's up: ___________
```

### 2. What is the real input?

What does a real caller send? An HTTP request? A CLI command? A message
on a queue? State the exact command or call.

```
Input method: _______________
Example:      _______________
```

### 3. What is the real output?

What should exist after the test runs? A file on disk? A row in a DB?
An HTTP response body? State what you will assert on.

```
Expected output: _______________
Where to find it: ______________
How to verify:    ______________
```

### 4. What is mocked vs real?

List every component and mark it REAL or MOCKED. **The system under test
must be REAL.** External services the system calls may be mocked IF they
are not the thing being validated.

```
| Component              | Real or Mocked | Justification              |
|------------------------|----------------|----------------------------|
| (service/process)      | REAL           | This IS the thing we test  |
| (database)             | ___            | ___                        |
| (external API)         | ___            | ___                        |
| (file system)          | ___            | ___                        |
| ...                    | ___            | ___                        |
```

**Red flag**: If the system under test appears in the "Mocked" column,
this is not an integration test. Redesign it.

### 5. What are the steps?

Write the numbered steps as shell commands. Every step must be
copy-pasteable. No pseudocode.

```bash
# 1. Start the system
_______________

# 2. Verify it's up
_______________

# 3. Send real input
_______________

# 4. Verify output exists
_______________

# 5. Assert correctness
_______________

# 6. Cleanup
_______________
```

## Present the plan, then wait

Show the filled-in answers to the user. Ask:

> "Here's my integration test plan. The system under test is ___, it will
> be REAL (not mocked). These components are mocked: ___. Does this match
> what you mean by integration test?"

**Do not write test code until the user confirms.**

## Common traps to avoid

1. **"I'll mock the network call to avoid hitting production."**
   If the network call IS the thing being tested, you can't mock it.
   Stand up a local instance instead.

2. **"I'll call the internal function directly instead of HTTP."**
   That's a unit test. Integration means going through the real entry
   point (HTTP, CLI, queue consumer).

3. **"I'll construct the expected output by hand and verify parsing."**
   That tests your parser, not your system. The system must produce the
   output.

4. **"The test is too slow with a real server."**
   Then use a small dataset. Slow and real beats fast and fake.

5. **"I'll patch just this one thing..."**
   Every patch weakens the test. If you must patch, justify it in the
   table above and get confirmation.

## After running

Report back with:

```
Integration test result: PASS / FAIL
System under test was:   REAL (started at ___, verified via ___)
Input was:               REAL (sent via ___)
Output verified at:      ___
Components mocked:       ___ (or "none")
```

If it failed, show the actual error — don't retry with more mocks.
