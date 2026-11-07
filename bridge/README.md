# Python Bridge — DEV-SQUAD

FastAPI service that validates, migrates, redacts, correlates, stores and
investigates browser evidence. It binds to `127.0.0.1:8000` and requires a
pairing token on every endpoint except `/health`.

## Start

```powershell
cd E:\DevSquad
python -m bridge
```

Print the pairing token:

```powershell
python -m bridge --token
```

The token is stored in `bridge/.devsquad_token`. Tests use a deterministic token
from `conftest.py`.

## Modules

| File | Purpose |
|---|---|
| `bridge.py` | FastAPI app, auth, CORS, endpoints, capture dispatch |
| `schema.json` | v1 JSON Schema |
| `schema_v2.json` | v2 JSON Schema |
| `validator.py` | Schema detection and validation |
| `migration.py` | v1 → v2 migration with `legacy_id` |
| `normalizer.py` | ID/source normalization |
| `redact.py` | Second-stage redaction |
| `correlation.py` | Deterministic timeline and coverage |
| `storage.py` | SQLite persistence with parameterized SQL |
| `case_manager.py` | Ingest, timeline, decision, verdict lifecycle |
| `agents.py` | Four agent prompts, safe evidence rendering, response validation |
| `opencode_runner.py` | Real OpenCode CLI runner |
| `orchestrator.py` | Investigation protocol and live events |
| `verdict_validator.py` | Citation validation and rule-derived confidence |
| `transport/local.py` | LocalRunner transport |
| `transport/switch.py` | Documented Switch adapter; refuses to fake capabilities |
| `test_bridge.py` | Original v1 behavior tests |
| `test_v2_engine.py` | v2, security, workflow and confidence tests |

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Service/schema/transport/model status (no token) |
| POST | `/cases` | Ingest an evidence bundle |
| GET | `/cases` | List cases |
| GET | `/cases/{id}` | Stored bundle |
| GET | `/cases/{id}/detail` | Case, evidence, timeline, verdict, decision |
| GET | `/cases/{id}/status` | Investigation status |
| GET | `/cases/{id}/timeline` | Correlated timeline |
| GET | `/cases/{id}/events` | Events and agent messages |
| GET | `/cases/{id}/verdict` | Validated verdict |
| POST | `/cases/{id}/investigate` | Start the real four-agent investigation |
| POST | `/cases/{id}/decision` | Record a human decision |
| POST | `/capture/preview` | Run the collector and return a redacted preview |
| POST | `/capture` | Run the collector and ingest the bundle |

All non-health endpoints require:

```text
X-DevSquad-Token: <pairing token>
```

The bridge validates `Host` and `Origin`, rejects foreign origins, and restricts
CORS to Chrome extension origins plus localhost tooling.

## Ingest pipeline

1. Detect schema version (v1 or v2).
2. Validate against the matching JSON Schema.
3. Migrate v1 to v2, preserving old IDs in `legacy_id` and `legacy_id_map`.
4. Apply the second redaction pass.
5. Normalize source-prefixed IDs and per-item `source`.
6. Correlate a deterministic timeline.
7. Persist to SQLite and write the sanitized bundle under `bundles/`.

Invalid bundles return HTTP 400 with structured validation errors. The bridge
never rewrites the original v1 source file.

## Investigation

`POST /cases/{id}/investigate` queues a background investigation and returns 202.
The transport is selected by configuration:

- `local` (default): real OpenCode runner + four agents.
- `switch`: documented Switch endpoints only; live Switch is currently blocked.

The protocol is:

1. Lead plan.
2. Console, network and application findings.
3. Lead challenge.
4. Specialist revision (one round in this implementation, max two).
5. Lead verdict.
6. Bridge citation validation and deterministic confidence.

Live progress is available through `/events`; the final verdict through
`/verdict`. Agent self-confidence is recorded but ignored for the final category.

## Capture

`/capture/preview` and `/capture` accept:

```json
{
  "url": "http://localhost:3001/",
  "case_id": "DS-001",
  "schema_version": 2,
  "click": "#loginBtn",
  "incident_description": "Login click produces HTTP 401."
}
```

Only `localhost`, `127.0.0.1` and `::1` targets are allowed. The endpoint runs
`capture/capture.py` as a subprocess with a timeout and returns its bundle. A
preview is redacted but not stored; `/capture` ingests it.

## Security

- Localhost binding.
- Pairing token required.
- Host/Origin validation and extension-only CORS.
- Two redaction passes.
- No cookie values, authorization headers, request/response bodies, passwords or
  storage values.
- Evidence rendered to agents as untrusted delimited data.
- Verdicts citing unknown evidence are rejected.
- Insufficient evidence forces “Not determined”.

## Tests

```powershell
cd E:\DevSquad
python -m pytest bridge\test_bridge.py bridge\test_v2_engine.py -q
```

## Switch

The Switch adapter is present, but a live Switch server is not running here.
See `switch/SETUP_GUIDE.md` for the verified installer, the Windows
`initdb.exe` blocker (issue #1335) and the OpenCode 2.x sign-in issues
(#1421, #1426). The adapter does not fabricate WebSocket events or verdicts.
