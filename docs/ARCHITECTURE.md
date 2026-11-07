# Architecture — DEV-SQUAD v0.3

This document describes what is implemented, not a plan. Anything still blocked
is labeled explicitly.

## Data flow

```text
Demo app (localhost:3001 / 3002)
    |
    v
capture/capture.py  (Playwright)
  - console/page errors, network, DOM, cookie names, storage keys
  - first redaction pass
    |
    v
JSON evidence bundle (schema v1 or v2)
    |
    v
bridge/ (FastAPI on 127.0.0.1:8000)
  - pairing-token auth, Host/Origin validation
  - schema validation
  - v1 -> v2 migration (legacy_id preserved)
  - second redaction pass
  - deterministic correlation
  - SQLite persistence
    |
    +--> LocalTransport -> OpenCode LocalRunner -> four agents
    |
    +--> SwitchTransport -> documented Switch endpoints (live Switch blocked)
    |
    v
Chrome DevTools panel / HTTP API
  Capture -> Preview -> Submit -> Investigate -> Evidence
  -> Timeline -> Collaboration -> Verdict -> Human decision
```

## Components

### 1. Playwright collector (`capture/capture.py`)

Captures:

- Console errors/warnings and uncaught page errors.
- Network requests, responses and failures (status, method, URL, timing,
  resource type, initiator). Headers are redacted; body content is never stored.
- DOM observations at initial load and after an optional interaction
  (`--click`, `--click-wait`).
- Application observations: selectors, disabled state, visibility, text,
  title, readyState.
- Cookie **metadata only** (name, flags) in v2; storage **key names only** in v2.

Timestamps are ISO-8601 UTC. Schema v2 uses microsecond precision so callback
ordering is preserved; v1 keeps second precision. The collector warns when the
capture contains no console error, no actionable network failure and no DOM
anomaly.

Schema v2 IDs are source-prefixed:

| Prefix | Source |
|---|---|
| `CON-` | console |
| `NET-` | network |
| `APP-` | application/DOM |
| `PERF-` | performance |
| `SEC-` | security observation |
| `REC-` | recorder |
| `LH-` | Lighthouse-style observation |

### 2. Evidence bundles (`bundles/`, `bridge/schema*.json`)

`bridge/schema.json` remains the v1 schema. `bridge/schema_v2.json` adds
`source`, source-prefixed IDs, `legacy_id`, incident description and structured
observations.

v1 bundles are still accepted. Migration:

- assigns v2 IDs;
- preserves the original v1 ID in `legacy_id`;
- stores a `legacy_id_map`;
- maps v1-only types to their v2 equivalents.

`bundles/DS-001-v2.json` and `bundles/DS-002-v2.json` are the golden bundles.
`bundles/check/DS-001-v1-check.json` verifies v1 compatibility.

### 3. Bridge (`bridge/`)

FastAPI application bound to `127.0.0.1`. Responsibilities:

- **Authentication.** Every endpoint except `/health` requires
  `X-DevSquad-Token`. The token is generated locally and stored in
  `bridge/.devsquad_token`.
- **Network validation.** Only `127.0.0.1`, `localhost` and `testserver` hosts
  are accepted. Foreign `Origin` headers are rejected. CORS is restricted to
  the Chrome extension.
- **Validation.** v1 and v2 bundles are validated against their JSON schema.
- **Redaction.** A second pass removes authorization headers, cookies, tokens,
  JWTs, sensitive query parameters, emails, passwords and storage values.
- **Correlation.** A deterministic timeline with relative times, explicit
  ordering labels (`timestamp`, `same_timestamp`, `sequence_only`), candidate
  relationships and coverage flags. No LLM is involved.
- **Storage.** SQLite with parameterized SQL. Cases, evidence, timeline,
  messages, events, verdicts and human decisions are persisted.
- **Capture.** `POST /capture/preview` and `POST /capture` run the local
  Playwright collector against a localhost URL, so the DevTools panel can
  capture, preview and submit without storing credentials in the extension.
- **Orchestration.** Starts the four-agent investigation and streams live
  events.
- **Verdict validation.** Rejects unknown evidence citations and computes
  confidence deterministically.

### 4. Agents (`bridge/agents.py`, `bridge/orchestrator.py`)

| Agent | Role |
|---|---|
| `devsquad-lead` | Plans the investigation, resolves challenges, writes the verdict |
| `console-agent` | Console errors, exceptions, stack traces, ordering |
| `network-agent` | HTTP failures, status codes, timing |
| `application-agent` | DOM state, controls, loading indicators, app observations |

Protocol:

1. The lead receives the correlated timeline and writes a plan.
2. The three specialists receive the same evidence and return cited findings.
3. The lead challenges unsupported or contradictory findings.
4. Specialists may revise once. The implementation performs one challenge
   round, within the maximum of two.
5. The lead writes a verdict with a failure chain and rejected hypotheses.
6. The bridge validates citations and computes confidence.

Evidence is rendered inside explicit untrusted-data delimiters. Agents are told
that evidence text is data, never instructions.

`LocalRunner` invokes the real OpenCode CLI:

```text
opencode run --format json --model <configured-model> --agent devsquad-analyst
```

No findings are mocked in production paths. Tests inject a fake runner only to
exercise the orchestration protocol deterministically.

### 5. Confidence

Agent self-confidence is recorded as `reported_confidence` and ignored for the
final category. `bridge/verdict_validator.py` derives confidence:

| Condition | Result |
|---|---|
| Cause not determined, or insufficient evidence | Low |
| Fewer than two independent evidence sources | Low |
| Ordering not verified | Low |
| Unresolved challenge | Low |
| Capture incomplete | Low |
| Multiple sources but an inferred causal step | Medium |
| Directly observed cause, multiple sources, verified ordering, complete coverage | High |

The auth-failure demo yields **Medium** because the conclusion spans console,
network and application evidence and requires an inferred causal step. The
stuck-spinner demo yields **Low / Not determined** because no direct failure was
captured.

### 6. Transport abstraction (`bridge/transport/`)

- `LocalTransport` runs the investigation through OpenCode and persists events.
- `SwitchTransport` implements only documented Switch HTTP endpoints. It
  explicitly refuses to fabricate WebSocket event ingestion, verdict retrieval
  or room state that it cannot observe.

Switch is the preferred collaboration layer, but a live Switch server is not
running in this environment. See `switch/SETUP_GUIDE.md`.

### 7. Chrome DevTools panel (`extension/`)

- Manifest V3, React, TypeScript, Vite.
- Registered as a DevTools panel (`devtools_page`) and a toolbar popup.
- Views: Capture, Investigate, Evidence, Timeline, Collaboration, Verdict.
- Capture calls the bridge, shows a redacted preview, then submits.
- Live polling displays stages, agent messages and eventually the verdict.
- The verdict view records approve / reject / need-more-evidence decisions.
- Bridge URL and pairing token are stored in extension storage; the token is
  sent only to the local bridge as `X-DevSquad-Token`.

The panel is a UI over the local bridge. The Playwright collector performs the
actual browser capture; the extension does not use `chrome.debugger`.

### 8. Human decision

The human can approve, reject or request more evidence. The decision, note and
timestamp are stored with the case and returned by `/cases/{id}/verdict`.
Agents never apply code changes.

## Security model

- Bridge binds to localhost.
- Pairing token required on every non-health endpoint.
- Host and Origin validation; extension-only CORS.
- Capture URLs restricted to localhost/127.0.0.1.
- Two redaction passes before storage.
- No cookie values, authorization headers, bodies, passwords or storage values.
- All evidence treated as untrusted prompt-injection data.
- Citation validation prevents hallucinated evidence IDs.
- Insufficient evidence forces “Not determined”.
- Human approval is mandatory before action.

## Known limitations

- Live Switch server is blocked by Windows PostgreSQL and OpenCode 2.x issues.
- LocalRunner requires the OpenCode CLI and the configured model to be
  available. If the model is unavailable, the investigation fails explicitly;
  it does not fall back to fabricated results.
- The collector targets the two local demo apps. Capture is intentionally
  restricted to localhost.
