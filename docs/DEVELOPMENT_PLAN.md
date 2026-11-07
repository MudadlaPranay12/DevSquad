# Development Plan — DEV-SQUAD v0.3

## Status summary

The MVP is implemented and tested locally. Switch integration is the only major
unfinished area, and it is blocked by upstream issues rather than by missing
application code.

| # | Milestone | Status |
|---|---|---|
| 1 | Verify Switch installation and environment | **Blocked** — installer verified, native Windows server fails (issue #1335); OpenCode 2.x rejected (issues #1421, #1426) |
| 2 | Create a Switch room and verify an agent | **Blocked** — no live Switch server |
| 3 | Verify two agents communicate | **Implemented locally** through the LocalRunner protocol; live Switch pending |
| 4 | Verify all four agents participate | **Implemented** — lead, console, network and application agents complete a full investigation |
| 5 | Build two demo websites | **Complete** — auth-failure (`:3001`) and stuck-spinner (`:3002`) |
| 6 | Playwright collector and JSON schema | **Complete** — schema v1 and v2, interaction capture, microsecond timestamps |
| 7 | Bridge with validation, redaction, replay | **Complete** — validation, two-pass redaction, deterministic correlation, SQLite, replay via stored bundles |
| 8 | Connect the bridge to Switch | **Adapter complete, live connection blocked** — `SwitchTransport` uses documented endpoints and refuses to fake unsupported operations |
| 9 | Investigation protocol | **Complete** — lead plan, specialist findings, challenge, one revision round, cited verdict |
| 10 | Chrome DevTools extension | **Complete** — Manifest V3 React/Vite panel with Capture, Investigate, Evidence, Timeline, Collaboration and Verdict views |
| 11 | End-to-end testing and demo | **Complete locally** — acceptance harness runs both scenarios against the real LocalRunner |

## What v0.3 delivers

### Evidence pipeline

- Playwright collector with v1/v2 output.
- Optional post-interaction DOM capture.
- Source-prefixed IDs and per-evidence `source`.
- Cookie metadata and storage key names only.
- Two-pass redaction.
- v1 migration with `legacy_id` and `legacy_id_map`.
- Deterministic timeline and coverage flags.

### Investigation

- Real four-agent LocalRunner using the OpenCode CLI.
- Shared investigation protocol with challenge/revision.
- Evidence rendered as untrusted data.
- Citation validation that rejects unknown IDs.
- Rule-derived confidence; agent self-confidence recorded but ignored.
- Insufficient-evidence override that forces “Not determined”.

### Interfaces

- FastAPI bridge with token auth, Host/Origin checks and extension-only CORS.
- Capture endpoints for the extension.
- Chrome DevTools panel with live polling and human decision controls.
- Acceptance harness (`tools/evaluate_demos.py`).

### Tests

- `bridge/test_bridge.py` — original v1 behavior.
- `bridge/test_v2_engine.py` — schema v2, migration, redaction, correlation,
  API security, capture target restrictions, four-agent workflow, citation
  validation and confidence.
- `python -m pytest bridge/test_bridge.py bridge/test_v2_engine.py -q`

## Blocked work

### Switch native Windows server

- The official `switch-console-v0.40.1` installer was downloaded, signature-
  verified and hash-verified.
- Native startup still fails during PostgreSQL `initdb.exe` (issue #1335).
- Docker is not allowed in this environment, so the Docker-based path is not an
  option.
- Switch Console installation requires manual GUI interaction.

### Switch + OpenCode 2.x

- OpenCode 2.0.26 is installed.
- Switch issues #1421 and #1426 report that Switch rejects OpenCode 2.x and that
  the pending fix pins OpenCode to 1.x.
- Silently downgrading OpenCode is not acceptable because it would hide a
  compatibility problem and risk breaking other work.

The `SwitchTransport` therefore remains an adapter with explicit capability
checks. It does not fabricate WebSocket events or verdicts. See
`switch/SETUP_GUIDE.md`.

## Next steps when Switch is available

1. Start a supported Switch server (Linux VM or a fixed Windows installer).
2. Install OpenCode 1.x in the Switch environment or adopt the upstream fix for
   2.x.
3. Create the `devsquad-incidents` room and register the four agents from
   `switch/prompts/`.
4. Set `DEV_SQUAD_TRANSPORT=switch` and provide the documented Switch
   credentials/room identifiers.
5. Replay the golden bundles and compare the Switch transcript with the local
   transcript.
6. Add WebSocket event ingestion once the documented stream is verified.
7. Record a live human decision in the Switch room.

## Rules for future work

- Do not create imaginary Switch configurations.
- Do not invent endpoints, schemas or commands.
- If a capability is not verified, say so.
- Never collect cookie values, Authorization headers, tokens or passwords.
- Never store request or response bodies.
- Agents suggest; humans approve. No automatic changes.
- Keep v1 evidence readable; never silently rewrite user data.
