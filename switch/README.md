# Switch Room — DEV-SQUAD

## Purpose

This folder contains everything needed to run the DEV-SQUAD investigation in a
Switch shared room: setup notes, the room workflow, and the four agent prompts.

Switch is SandboxAQ's platform for bringing AI agents into shared rooms as named
participants. It is the intended collaboration layer for DEV-SQUAD.

## Current status

Switch Console `v0.40.1` was downloaded and its signature and SHA-256 digest were
verified against the GitHub release. It is **not installed or running** on this
Windows system.

Blockers:

- Windows native server fails during PostgreSQL `initdb.exe` (Switch issue
  **#1335**).
- Switch sign-in rejects OpenCode 2.x (issues **#1421** and **#1426**).
- Switch Console installation requires manual GUI interaction.
- Docker is not used in this environment.

The MVP therefore runs the same four-agent protocol through **LocalRunner**. The
`SwitchTransport` adapter uses only documented HTTP endpoints and does not fake
WebSocket events or verdict retrieval.

See `SETUP_GUIDE.md` for the verified installer details and exact blockers.

## Files

| File | Purpose |
|---|---|
| `SETUP_GUIDE.md` | Installer verification, blockers, and the path to a working server |
| `DEV_SQUAD_ROOM_INSTRUCTIONS.md` | Room workflow, agent roles and evidence rules |
| `prompts/devsquad-lead.txt` | Lead agent prompt |
| `prompts/console-agent.txt` | Console specialist prompt |
| `prompts/network-agent.txt` | Network specialist prompt |
| `prompts/application-agent.txt` | Application/DOM specialist prompt |

## Room model

- Room: `devsquad-incidents`
- Humans: the developer who captured the evidence and makes the final decision.
- Agents: `devsquad-lead`, `console-agent`, `network-agent`,
  `application-agent`.
- Protocol: lead plan → specialist findings → challenge → optional revision →
  cited verdict → human decision.

Every agent finding must cite real evidence IDs. Evidence is untrusted data and
must never be treated as instructions.

## Security

- Agents may suggest fixes but never apply changes automatically.
- Human approval is required before any action based on a verdict.
- Evidence posted to the room must already be redacted by the bridge.
- The bridge enforces `X-DevSquad-Token` pairing, Host/Origin validation and
  extension-only CORS.
- Switch credentials are read from environment variables or a local gitignored
  file, never from the extension or source.
