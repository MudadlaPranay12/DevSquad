# Tools — DEV-SQUAD

Small helper scripts. Keep them readable and dependency-light.

## `evaluate_demos.py`

End-to-end acceptance harness for the two demo scenarios. It talks to a running
bridge over HTTP, re-ingests the golden bundles, starts real LocalRunner
investigations, and asserts the required verdicts.

```powershell
cd E:\DevSquad
python tools\evaluate_demos.py
```

Requirements:

- The bridge is running on `http://127.0.0.1:8000`.
- The OpenCode model used by LocalRunner is available.
- The pairing token is in `$DEV_SQUAD_TOKEN`, `bridge/.devsquad_token`, or passed
  with `--token`.

Options:

```text
--bridge URL        Bridge base URL (default http://127.0.0.1:8000)
--token TOKEN       Pairing token
--timeout SECONDS   Per-case timeout (default 900)
--bundle ID=PATH    Override a bundle, e.g. DS-001=bundles/custom.json
```

The harness fails with a non-zero exit code if either scenario violates its
expected behavior:

- **DS-001** must be determined, cite `CON-001`, `NET-008` and `APP-005`, use at
  least two independent sources, and receive **Medium** confidence.
- **DS-002** must be **Not determined**, **Low** confidence, with the
  insufficient-evidence override and a non-empty missing-evidence list.

No findings are mocked. The harness only reads what the bridge and agents store.
