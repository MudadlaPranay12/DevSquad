# DEV-SQUAD

**Collaborative AI browser debugging and incident investigation.**

> Don't just report errors. Investigate them together.

DEV-SQUAD turns a browser failure into a shared, evidence-cited investigation. A
Playwright collector captures console, network, DOM and application evidence; a
local Python bridge validates, redacts, correlates and stores it; four specialist
AI agents investigate the same evidence through a real model; and a human makes
the final decision in a Chrome DevTools panel.

This repository implements the **v0.3 MVP**. It runs entirely locally and does
not require Docker.

## What works today

| Capability | Status |
|---|---|
| Playwright collector (schema v1 and v2) | Implemented |
| Two-stage redaction in collector + bridge | Implemented |
| Schema v2 with `CON-`, `NET-`, `APP-`, `PERF-`, `SEC-`, `REC-`, `LH-` IDs | Implemented |
| v1 bundle migration and `legacy_id` preservation | Implemented |
| Deterministic timeline correlation | Implemented |
| SQLite case storage and human decision records | Implemented |
| FastAPI bridge with localhost-only binding and pairing token | Implemented |
| Real four-agent LocalRunner investigation through OpenCode | Implemented |
| Citation validation and rule-derived confidence | Implemented |
| Switch transport adapter | Implemented against documented endpoints; live Switch blocked (see below) |
| Chrome DevTools panel (Manifest V3, React, Vite) | Implemented and buildable |
| Auth-failure demo (determined verdict) | Verified end-to-end |
| Stuck-spinner demo (honest “Not determined”) | Verified end-to-end |

## Architecture

```text
Demo app (localhost:3001 / 3002)
    |
    v
capture/capture.py  (Playwright, schema v1/v2, browser-side redaction)
    |
    v
Sanitized JSON evidence bundle
    |
    v
bridge/ (FastAPI)
  validate -> migrate v1 -> redact -> correlate -> SQLite
    |
    +--> LocalRunner (OpenCode) -- four agents, challenge/revision
    |
    +--> SwitchTransport (documented Switch API; blocked in this environment)
    |
    v
Chrome DevTools panel / HTTP API
  Capture -> Preview -> Submit -> Investigate -> Evidence -> Timeline
  -> Collaboration -> Verdict -> Human decision
```

### Four agents

| Agent | Focus |
|---|---|
| `devsquad-lead` | Coordinates, resolves challenges, writes the final cited verdict |
| `console-agent` | Console errors, exceptions, stack traces, event order |
| `network-agent` | HTTP status codes, failed requests, timing |
| `application-agent` | DOM state, disabled controls, loading indicators, app observations |

Every formal finding must cite evidence IDs. The bridge validates citations and
rejects verdicts that cite evidence which does not exist. Agent self-confidence
is recorded but never trusted: the bridge derives **High / Medium / Low** from
source count, event ordering, capture coverage, unresolved challenges and whether
the conclusion requires an inferred causal step.

## Quick start

PowerShell is assumed. Run each command separately.

### 1. Start the bridge

```powershell
cd E:\DevSquad
python -m bridge
```

The bridge binds to `127.0.0.1:8000` and requires a pairing token. Print it with:

```powershell
python -m bridge --token
```

### 2. Start the demo apps

```powershell
cd E:\DevSquad\demo-apps\auth-failure
npm install
npm start
```

```powershell
cd E:\DevSquad\demo-apps\stuck-spinner
npm install
npm start
```

The auth-failure app runs on `http://localhost:3001`; the stuck-spinner app runs
on `http://localhost:3002`.

### 3. Capture evidence

```powershell
cd E:\DevSquad
python capture\capture.py --url http://localhost:3001/ --case-id DS-001 --click "#loginBtn" --incident-description "Login click produces HTTP 401 and the button stays disabled." --schema-version 2 --out bundles\DS-001-v2.json
```

```powershell
python capture\capture.py --url http://localhost:3002/ --case-id DS-002 --incident-description "The page displays a loading spinner indefinitely." --schema-version 2 --out bundles\DS-002-v2.json
```

### 4. Submit and investigate

Use the DevTools panel or the HTTP API:

```powershell
$token = python -m bridge --token
$headers = @{ "X-DevSquad-Token" = $token }
Invoke-RestMethod -Uri http://127.0.0.1:8000/cases -Method Post -Headers $headers -ContentType "application/json" -InFile bundles\DS-001-v2.json
Invoke-RestMethod -Uri http://127.0.0.1:8000/cases/DS-001/investigate -Method Post -Headers $headers
Invoke-RestMethod -Uri http://127.0.0.1:8000/cases/DS-001/verdict -Headers $headers
```

### 5. Build and load the Chrome DevTools panel

```powershell
cd E:\DevSquad\extension
npm install
npm run build
```

Open `chrome://extensions`, enable Developer mode, choose **Load unpacked**, and
select `E:\DevSquad\extension`. Open DevTools on a demo tab and select the
**DEV-SQUAD** panel (or use the toolbar popup). Paste the pairing token in
Settings.

The panel captures through the bridge (which runs the local Playwright collector),
shows a redacted preview before submission, starts the investigation, polls live
events, and records approve / reject / need-more-evidence decisions.

### 6. Run the acceptance harness

```powershell
cd E:\DevSquad
python tools\evaluate_demos.py
```

The harness re-ingests both bundles, runs the real LocalRunner investigation, and
asserts that DS-001 is determined with Medium confidence and that DS-002 reports
“Not determined” with Low confidence.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Service, schema, transport and model status |
| POST | `/cases` | Validate, migrate, redact, correlate and store a bundle |
| GET | `/cases` | List stored cases |
| GET | `/cases/{id}/detail` | Full case, evidence, timeline, verdict and decision |
| GET | `/cases/{id}/status` | Current investigation status and stage |
| GET | `/cases/{id}/timeline` | Deterministic correlated timeline |
| GET | `/cases/{id}/events` | Live events and agent messages |
| GET | `/cases/{id}/verdict` | Validated verdict and confidence factors |
| POST | `/cases/{id}/investigate` | Start the real four-agent investigation |
| POST | `/cases/{id}/decision` | Record a human decision |
| POST | `/capture/preview` | Run the collector and return a redacted preview |
| POST | `/capture` | Run the collector and ingest the bundle |

All endpoints except `/health` require `X-DevSquad-Token`. The bridge validates
`Host` and `Origin` and restricts CORS to the Chrome extension.

## Security rules

- Cookie values, `Authorization` headers, tokens and passwords are never stored.
- Request and response bodies are never stored.
- Only storage key names are collected, never values.
- Redaction runs once in the collector and again in the bridge.
- All browser evidence is treated as untrusted prompt-injection data.
- Agents may suggest fixes; they never apply changes.
- Human approval is required before any action based on a verdict.
- A verdict that cites unknown evidence is rejected.
- When evidence is insufficient, the bridge overrides the agents with
  “Not determined” rather than inventing a cause.

## Tests

```powershell
cd E:\DevSquad
python -m pytest bridge\test_bridge.py bridge\test_v2_engine.py -q
```

The suite covers v1 compatibility, v2 validation, migration, redaction,
correlation, API authentication, capture target restrictions, the four-agent
workflow, citation validation, confidence derivation and the insufficient-evidence
override.

## Switch status

Switch is the intended collaboration layer, and the adapter, room instructions
and four agent prompts are in `switch/`. A live Switch server is **not running**
in this environment, and this repository does not claim otherwise.

Verified facts:

- Official installer `switch-console-v0.40.1` was downloaded and its signature
  and SHA-256 digest matched the GitHub release.
- Switch 0.40 supports a native local server without Docker in principle.
- Windows native startup fails during PostgreSQL `initdb.exe` (Switch issue
  **#1335** is open).
- OpenCode 2.x is rejected by Switch sign-in (issues **#1421** and **#1426**).
  Downgrading OpenCode silently is not acceptable.
- Switch Console installation requires manual GUI interaction.

Because of these blockers, the MVP uses **LocalRunner**, which runs the same four
agents and the same challenge/revision protocol through the local bridge. The
`SwitchTransport` implements only documented endpoints and refuses to fabricate
WebSocket event ingestion or verdict retrieval. See `switch\SETUP_GUIDE.md` for
the exact setup path and blockers.

## Repository map

| Path | Purpose |
|---|---|
| `capture\` | Playwright collector, schema v1/v2 output, browser-side redaction |
| `bridge\` | FastAPI service, schema, migration, redaction, correlation, agents, storage |
| `extension\` | Manifest V3 Chrome DevTools panel (React + TypeScript + Vite) |
| `demo-apps\` | Auth-failure and stuck-spinner demo applications |
| `bundles\` | Golden v1/v2 evidence bundles used by tests and demos |
| `switch\` | Switch setup guide, room instructions and four agent prompts |
| `tools\` | Evaluation harness and helper scripts |
| `docs\` | Architecture, project overview and development plan |
| `DEMO_GUIDE.md` | Step-by-step demo runbook and expected results |

## Documentation

- [`DEMO_GUIDE.md`](DEMO_GUIDE.md) — demo runbook
- [`docs/PROJECT_OVERVIEW.md`](docs/PROJECT_OVERVIEW.md) — problem, roles, workflow
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — implemented architecture
- [`docs/DEVELOPMENT_PLAN.md`](docs/DEVELOPMENT_PLAN.md) — milestones and status
- [`switch/SETUP_GUIDE.md`](switch/SETUP_GUIDE.md) — Switch installation and blockers
