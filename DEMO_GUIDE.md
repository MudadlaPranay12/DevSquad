# DEV-SQUAD Demo Guide (v0.3)

This runbook takes you from a fresh terminal to a human-approved verdict for both
demo scenarios. It uses only local services and does not require Docker.

## Prerequisites

- Windows 10/11 with PowerShell
- Python 3.10+
- Node.js 20+
- Chrome
- OpenCode CLI v2.0.26 installed and signed in to a working model

The default LocalRunner model is `opencode/deepseek-v4.1-flash-free`. You can
change it in `bridge/config.py` or with the documented environment variable, but
the model must be available to OpenCode.

## 1. Start the bridge

```powershell
cd E:\DevSquad
python -m bridge
```

The bridge listens on `http://127.0.0.1:8000` and requires a pairing token.

**Important:** read the token from a second terminal:

```powershell
python -m bridge --token
```

The token is also stored in `E:\DevSquad\bridge\.devsquad_token`.

## 2. Start the demo apps

Auth-failure demo:

```powershell
cd E:\DevSquad\demo-apps\auth-failure
npm install
npm start
```

Stuck-spinner demo, in another terminal:

```powershell
cd E:\DevSquad\demo-apps\stuck-spinner
npm install
npm start
```

- Auth-failure: `http://localhost:3001`
- Stuck-spinner: `http://localhost:3002`

## 3. Build and load the Chrome DevTools panel

```powershell
cd E:\DevSquad\extension
npm install
npm run build
```

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Choose **Load unpacked** and select `E:\DevSquad\extension`.
4. Open DevTools on a demo tab and select the **DEV-SQUAD** panel, or click the
   toolbar icon to use the popup.
5. Open **Settings**, paste the pairing token, and save.

The panel stores the bridge URL and token in extension storage. The token is
sent only to the local bridge as `X-DevSquad-Token`.

## 4. Auth-failure investigation (DS-001)

### Capture and preview

In the **Capture** view:

| Field | Value |
|---|---|
| Demo URL | `http://localhost:3001/` |
| Case ID | `DS-001` |
| Schema version | `v2` |
| Interaction selector | `#loginBtn` |
| Incident description | Login click produces HTTP 401 and the button stays disabled. |

Click **Capture & preview**. The bridge runs the Playwright collector and returns
a redacted preview.

Expected preview:

- About 17 evidence items.
- Console error `CON-001`: authentication initialization failed.
- Network `GET /api/user` with HTTP 401 (`NET-008`).
- Application observation: login button disabled (`APP-005`).
- Application observation: loading indicator visible (`APP-006`).
- No cookie values, authorization headers, request bodies or storage values.

Review the preview, then click **Submit captured case**.

### Investigate

Open the **Investigate** view and click **Start investigation**. The real
LocalRunner starts four agents. This takes roughly 2–4 minutes.

Watch:

- **Investigate** — status, stage, agent rounds, live events.
- **Collaboration** — agent messages, evidence citations, challenge/revision.
- **Verdict** — final verdict once the investigation completes.

### Expected verdict behavior

The exact wording is model-generated, but the required properties are:

- `root_cause_determined: true`
- Root cause names an authentication failure and the 401 on `GET /api/user`
- Supporting evidence includes `CON-001`, `NET-008` and `APP-005`
- `confidence: "Medium"`
- `confidence_method: "rule-derived-v1"`
- A cited failure chain spanning console, network and application evidence
- Rejected hypotheses for alternatives such as page-load failure or server
  downtime
- Human decision controls are available

Medium confidence is correct because the conclusion spans three independent
sources and requires an inferred causal step.

### Record the decision

In **Verdict**, choose **Approve**, **Need more evidence**, or **Reject**. Add an
optional note. The decision is stored with the case and returned by
`GET /cases/DS-001/verdict`.

## 5. Stuck-spinner investigation (DS-002)

In the **Capture** view:

| Field | Value |
|---|---|
| Demo URL | `http://localhost:3002/` |
| Case ID | `DS-002` |
| Schema version | `v2` |
| Interaction selector | leave empty |
| Incident description | The page displays a loading spinner indefinitely. |

Click **Capture & preview**. Expected preview:

- About 8 evidence items.
- A warning: **Insufficient evidence** — no console errors, no actionable failed
  network responses and no DOM anomaly.
- The spinner observation is present, but there is no direct failure signal.

Submit, then start the investigation from **Investigate**.

### Expected verdict behavior

- `root_cause: "Not determined"`
- `root_cause_determined: false`
- `confidence: "Low"`
- `insufficient_evidence_override: true`
- A non-empty `missing_evidence` list
- No invented cause

This demonstrates that DEV-SQUAD refuses to guess when the evidence does not
support a conclusion.

## 6. HTTP API fallback

If you prefer the terminal, all panel actions have API equivalents.

```powershell
$token = python -m bridge --token
$headers = @{ "X-DevSquad-Token" = $token }

Invoke-RestMethod -Uri http://127.0.0.1:8000/cases -Method Post `
  -Headers $headers -ContentType "application/json" -InFile bundles\DS-001-v2.json

Invoke-RestMethod -Uri http://127.0.0.1:8000/cases/DS-001/investigate `
  -Method Post -Headers $headers

Invoke-RestMethod -Uri http://127.0.0.1:8000/cases/DS-001/status -Headers $headers
Invoke-RestMethod -Uri http://127.0.0.1:8000/cases/DS-001/detail -Headers $headers
Invoke-RestMethod -Uri http://127.0.0.1:8000/cases/DS-001/verdict -Headers $headers
```

Capture through the API:

```powershell
$body = @{
  url = "http://localhost:3001/"
  case_id = "DS-001"
  schema_version = 2
  click = "#loginBtn"
  incident_description = "Login click produces HTTP 401 and the button stays disabled."
} | ConvertTo-Json

Invoke-RestMethod -Uri http://127.0.0.1:8000/capture/preview -Method Post `
  -Headers $headers -ContentType "application/json" -Body $body
```

## 7. Command-line capture

```powershell
cd E:\DevSquad

python capture\capture.py `
  --url http://localhost:3001/ `
  --case-id DS-001 `
  --click "#loginBtn" `
  --click-wait 2000 `
  --incident-description "Login click produces HTTP 401 and the button stays disabled." `
  --schema-version 2 `
  --out bundles\DS-001-v2.json

python capture\capture.py `
  --url http://localhost:3002/ `
  --case-id DS-002 `
  --incident-description "The page displays a loading spinner indefinitely." `
  --schema-version 2 `
  --out bundles\DS-002-v2.json
```

v1 remains supported with `--schema-version 1`.

## 8. Acceptance harness

With the bridge and both demo apps running:

```powershell
cd E:\DevSquad
python tools\evaluate_demos.py
```

The harness:

1. Checks bridge health.
2. Re-ingests `bundles/DS-001-v2.json` and `bundles/DS-002-v2.json`.
3. Starts real LocalRunner investigations.
4. Waits for completion.
5. Asserts DS-001 is determined with Medium confidence and cites `CON-001`,
   `NET-008` and `APP-005`.
6. Asserts DS-002 is “Not determined” with Low confidence and the
   insufficient-evidence override.

It exits non-zero on any failure. Expect several minutes of runtime.

## Evidence ID conventions

| Prefix | Source | Typical evidence |
|---|---|---|
| `CON-` | console | console errors, page errors |
| `NET-` | network | requests, responses, failures |
| `APP-` | application | DOM and app observations |
| `PERF-` | performance | performance metrics |
| `SEC-` | security | security observations |
| `REC-` | recorder | recorder events |
| `LH-` | lighthouse | Lighthouse-style audits |

v1 uses `E001`, `E002`, … IDs. Migrated evidence keeps the original ID in
`legacy_id`.

## Verified in this build

- Both demo apps start and respond.
- Playwright capture produces valid v1 and v2 bundles.
- The v2 auth bundle contains 17 items; the spinner bundle contains 8.
- v1 → v2 migration and `legacy_id` mapping.
- Two-pass redaction.
- Deterministic correlation with ordering labels.
- Token auth, Host/Origin validation and extension-only CORS.
- Real four-agent LocalRunner investigation.
- Citation validation and rule-derived confidence.
- DS-001 determined with Medium confidence.
- DS-002 “Not determined” with Low confidence.
- Chrome DevTools panel builds and includes all six views.
- Python test suite passes.

## Known blockers

- **Switch native Windows server:** issue #1335; PostgreSQL `initdb.exe` fails.
  Use LocalRunner.
- **Switch + OpenCode 2.x:** issues #1421 and #1426; Switch sign-in rejects
  OpenCode 2.x. A silent downgrade is not acceptable.
- **Switch Console GUI:** installation requires manual user interaction.
- **Docker:** not used in this environment.

See `switch/SETUP_GUIDE.md` for the verified installer details and exact errors.

## Troubleshooting

| Symptom | Resolution |
|---|---|
| `Invalid or missing DEV-SQUAD pairing token` | Run `python -m bridge --token`, paste the token into extension Settings |
| `Host header not allowed` | Use `127.0.0.1` or `localhost`; the bridge binds locally only |
| `Origin not allowed` | Load the extension unpacked; the bridge allows only extension origins and localhost tooling |
| Capture fails with connection refused | Start the matching demo app on port 3001 or 3002 |
| Capture preview has no 401 | Use `#loginBtn` as the interaction selector for DS-001 |
| DS-002 preview has a warning | Expected: the capture is intentionally insufficient |
| Investigation stays at `challenge` | Wait; agents are still reasoning. Poll again |
| Investigation fails | Check the OpenCode model is available and the CLI is signed in |
| Extension cannot reach the bridge | Confirm `http://127.0.0.1:8000/health` works and reload the extension |
| Switch Console won't start | Windows `initdb.exe` blocker; use LocalRunner |

## Next steps when Switch is available

1. Start a supported Switch server.
2. Register the four agents from `switch/prompts/`.
3. Join the `devsquad-incidents` room.
4. Set `DEV_SQUAD_TRANSPORT=switch` and provide the documented credentials.
5. Replay the golden bundles and compare the Switch transcript with LocalRunner.
6. Record a live human decision in the room.
