# Evidence Bundles — DEV-SQUAD

Sanitized JSON evidence bundles produced by the Playwright collector and accepted
by the Python bridge.

## Golden bundles

| File | Purpose |
|---|---|
| `DS-001-v2.json` | Auth-failure demo, schema v2, 17 items, 401 and stuck button |
| `DS-002-v2.json` | Stuck-spinner demo, schema v2, 8 items, insufficient evidence |
| `DS-001-auth-failure.json` | Original v1 auth bundle (preserved) |
| `DS-002-stuck-spinner.json` | Original v1 spinner bundle (preserved) |
| `check/DS-001-v1-check.json` | v1 compatibility check bundle |
| `DS-001.json`, `DS-002.json` | Sanitized bundles written by the bridge at ingest |

## Schema v2 example

```json
{
  "schema_version": 2,
  "case_id": "DS-001",
  "timestamp": "2026-11-06T04:23:35Z",
  "capture_source": "playwright",
  "page_url": "http://localhost:3001/",
  "incident_description": "Login click produces HTTP 401.",
  "evidence": [
    {
      "id": "CON-001",
      "source": "console",
      "type": "console_error",
      "timestamp": "2026-11-06T04:23:35.027130Z",
      "message": "Authentication initialization failed"
    },
    {
      "id": "NET-008",
      "source": "network",
      "type": "network_response",
      "timestamp": "2026-11-06T04:23:37.138143Z",
      "method": "GET",
      "url": "http://localhost:3001/api/user",
      "status": 401
    }
  ]
}
```

v1 uses `E001`-style IDs and remains readable. Migration assigns v2 IDs and keeps
the original in `legacy_id`.

## Redaction

Bundles stored here must already be sanitized. Cookie values, authorization
headers, tokens, passwords, request/response bodies and storage values are never
stored. The bridge applies a second redaction pass before persistence.
