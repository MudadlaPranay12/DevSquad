# Browser Evidence Collector — DEV-SQUAD

Playwright-based collector that captures browser debugging evidence and writes a
sanitized JSON bundle for the Python bridge.

## Files

| File | Purpose |
|---|---|
| `capture.py` | Collector (schema v1 and v2) |
| `replay.py` | Load a saved bundle and print a readable incident report |

## Install

```powershell
pip install playwright
python -m playwright install chromium
```

## Run

```powershell
cd E:\DevSquad
python capture\capture.py --url http://localhost:3001/ --case-id DS-001 --click "#loginBtn" --click-wait 2000 --incident-description "Login click produces HTTP 401." --schema-version 2 --out bundles\DS-001-v2.json
```

Arguments:

| Argument | Meaning |
|---|---|
| `--url` | Local demo URL (required) |
| `--case-id` | `DS-###` case identifier (required) |
| `--out` | Output bundle path |
| `--schema-version` | `1` or `2` (default: `1`; use `2` for new captures) |
| `--click` | Optional CSS selector to click |
| `--click-wait` | Milliseconds to wait after the click (default: 1500) |
| `--incident-description` | Human summary (v2 only) |

## Output

Schema v2:

- `CON-` console evidence
- `NET-` network requests, responses and failures
- `APP-` DOM/application observations
- Optional `PERF-`, `SEC-`, `REC-`, `LH-` prefixes

Each item carries `id`, `source`, `type`, `timestamp` and its domain-specific
fields. Timestamps use microsecond precision to preserve callback ordering.

Schema v1 uses `E###` IDs and remains available with `--schema-version 1`.

## Captured (sanitized)

- Console errors/warnings and uncaught page errors.
- Network requests, responses and failures: URL, method, status, timing,
  resource type, initiator. Headers are redacted.
- DOM observations: title, readyState, selectors, disabled state, visibility,
  text, loading indicators.
- Cookie **metadata only**: name, domain, secure/httpOnly/sameSite flags.
- Storage **key names only** (v2).
- Optional post-interaction DOM snapshot.

## Never captured

- Cookie values
- Authorization headers, tokens, API keys or JWTs
- Passwords or form input values
- Request or response bodies
- Complete localStorage or IndexedDB contents

## Insufficient evidence

The collector adds a warning when it observes no console error, no actionable
network failure and no DOM anomaly. The bridge and the verdict validator then
require a “Not determined” verdict instead of allowing an invented cause.

`/favicon.ico` 404 is treated as known, non-actionable browser noise.

## Replay

```powershell
python capture\replay.py bundles\DS-001-v2.json
```

The collector is independent of Switch; its output is validated by the bridge
against `bridge/schema.json` or `bridge/schema_v2.json`.
