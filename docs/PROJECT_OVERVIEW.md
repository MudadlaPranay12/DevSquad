# Project Overview — DEV-SQUAD

## Problem

When a website breaks, the investigation is fragmented:

1. A user or QA engineer reports a symptom ("login doesn't work", "the page
   spins forever").
2. A developer tries to reproduce it without enough context.
3. Logs, screenshots and HAR files are pasted into different tools.
4. Someone asks for the console output, and the process starts over.

The result is slow resolution, repeated back-and-forth, and evidence that lives
apart from the people investigating it.

## Solution

DEV-SQUAD collects the browser evidence once, sanitizes it, and gives the same
evidence to a human developer and four specialist AI agents. The agents work in
a shared investigation, cite evidence IDs, challenge each other, and produce a
verdict. The human reviews the verdict and records the final decision.

The MVP runs locally without Docker. It uses a real OpenCode-backed LocalRunner
for agent reasoning. Switch is the intended collaboration layer; its live server
is blocked in this environment, so the same protocol is exercised locally and
the Switch adapter remains ready for a working server.

## Roles

### Human developer

- Reproduces the bug on a demo app.
- Reviews the redacted evidence before submission.
- Starts the investigation.
- Watches live agent progress and challenges.
- Approves, rejects, or requests more evidence.
- Makes the final decision.

### `devsquad-lead`

- Plans the investigation.
- Delegates focused tasks to the specialists.
- Challenges unsupported findings.
- Produces the final verdict with a cited failure chain.
- May not invent evidence or apply changes.

### `console-agent`

- Investigates console errors, exceptions, stack traces and event order.
- Every finding cites console evidence such as `CON-001`.

### `network-agent`

- Investigates HTTP status codes, failed requests, timing and request/
  response relationships.
- Every finding cites network evidence such as `NET-008`.

### `application-agent`

- Investigates DOM state: disabled controls, loading indicators, visible
  errors, document title, readyState and application observations.
- Every finding cites application evidence such as `APP-005`.

## Investigation workflow

1. **Reproduce.** Run a demo app and trigger the failure.
2. **Capture.** Playwright records console, network, DOM and application
   evidence. Sensitive values are redacted in the browser.
3. **Review.** The bridge redacts again and the DevTools panel shows a preview
   before submission.
4. **Correlate.** The bridge builds a deterministic timeline with relative times
   and explicit ordering labels.
5. **Investigate.** The lead plans; console, network and application agents
   investigate in parallel and cite evidence IDs.
6. **Challenge.** The lead challenges unsupported or contradictory findings;
   specialists may revise once.
7. **Validate.** The bridge rejects unknown citations and computes confidence
   from evidence properties, not agent claims.
8. **Decide.** The human approves, rejects, or asks for more evidence.
9. **Report.** The verdict, confidence factors, missing evidence and human
   decision are stored with the case.

## Demo scenarios

### Auth failure (`http://localhost:3001`)

A login button triggers `GET /api/user`, which returns HTTP 401. The console
logs an authentication initialization error and a login failure; the button
remains disabled with a loading indicator.

Expected result:

- Root cause determined.
- Supporting evidence includes `CON-001`, `NET-008`, `APP-005`, among others.
- Confidence **Medium**, because the conclusion spans three sources and needs an
  inferred causal step.

### Stuck spinner (`http://localhost:3002`)

The page loads successfully and shows a spinner. No console error, failed
request or direct application failure is captured.

Expected result:

- Root cause **Not determined**.
- Confidence **Low**.
- The bridge forces an insufficient-evidence override and lists what evidence is
  missing. The agents must not invent a cause.

## Evidence model

- Schema v1 uses `E###` IDs and remains supported.
- Schema v2 uses `CON-`, `NET-`, `APP-`, `PERF-`, `SEC-`, `REC-`, `LH-` IDs.
- Migrated v1 evidence keeps its old ID in `legacy_id`.
- Evidence is untrusted input. Agents see it inside data delimiters and are told
  never to follow instructions found inside it.

## Why Switch

Switch is a shared room where humans and named AI agents work from the same
conversation, context and decisions:

- Agents join as participants and are addressed by name.
- Context stays in the room.
- Switch is self-hostable and brings no models of its own; DEV-SQUAD brings the
  agents and the model.
- Rooms and permissions fit the human-approval model.

A live Switch server is not running here. See `switch/SETUP_GUIDE.md` for the
verified installer, the Windows native-server blocker, and the OpenCode 2.x
compatibility issues. The repository does not claim a working Switch connection.

## Principles

- Evidence over guesses.
- Every formal finding cites a real evidence ID.
- Deterministic where possible; AI only where judgment is needed.
- Redact twice; store the minimum.
- Agents suggest; humans decide.
- Clearly label what works and what is blocked.

## Sources

- Switch project: https://github.com/sandbox-quantum/switch
- Switch documentation: https://docs.switchagents.ai
- Switch website: https://www.switchagents.ai
