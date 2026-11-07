# Switch Console Setup Guide — DEV-SQUAD

## Verified installer

- **Release:** `switch-console-v0.40.1` x64
- **Path:** `C:\Users\PRANAY\AppData\Local\Temp\opencode\switch-installer\switch-console-x64.exe`
- **Publisher:** `CN=SandboxAQ, O=SandboxAQ, L=Tarrytown, S=New York, C=US`
- **SHA-256:** `575262e7971cf2046ce04f968e33d6cd6c3ff795d695061c5a1443b6e79a2332`
- **Digest:** matches the official GitHub release exactly

The installer was **not** run to completion. Switch is not installed or running
on this machine.

## Installation blocker: Windows native server

- **Issue:** Windows PostgreSQL `initdb.exe` failure
- **Reference:** Switch issue **#1335** remains open.
- **Symptom:** Switch Console startup proceeds ("server listening on ...") but
  `initdb.exe` fails on Windows, so the local server never becomes usable.
- **Workaround:** Linux VM or remote server. Docker is not allowed for this
  project.
- **Status:** Native Windows server is **not operational**. This repository does
  not claim a live Switch connection.

## OpenCode compatibility

- **Issue #1421:** OpenCode 2.x prints `server listening on ...` while Console
  waits for `opencode server listening`; `/global/health` and `/provider` return
  HTML instead of JSON.
- **Issue #1426:** Pending fix pins OpenCode installs to 1.x and refuses 2.x.
- **Current:** OpenCode `v2.0.26` is installed and works for LocalRunner, but
  Switch Console sign-in compatibility is not available.

Silently downgrading OpenCode is not acceptable. That would hide a real upstream
compatibility problem and could break other work.

## Recommended local workflow (no Docker)

1. Start the Python bridge:

   ```powershell
   cd E:\DevSquad
   python -m bridge
   ```

2. Print the pairing token:

   ```powershell
   python -m bridge --token
   ```

3. Leave `DEV_SQUAD_TRANSPORT` unset or set it to `local`.

4. Use the OpenCode LocalRunner:

   ```text
   opencode run --format json --model opencode/deepseek-v4.1-flash-free --agent devsquad-analyst
   ```

5. Use the DevTools panel or HTTP API to capture, preview, submit and investigate.

The four-agent protocol, challenge/revision rounds, citation validation and
human decision are all exercised locally.

## When Switch becomes available

1. Start a supported Switch server (Linux VM, remote server, or a fixed Windows
   installer).
2. Install OpenCode 1.x in the Switch environment or adopt the upstream fix.
3. Create the `devsquad-incidents` room.
4. Register the four agents from `prompts/` and join the room.
5. Configure:
   - `SWITCH_BASE_URL=http://127.0.0.1:8080` (or the Console host)
   - `SWITCH_ROOM_ID=devsquad-incidents`
   - `SWITCH_REGISTRATION_KEY` once, or `SWITCH_AGENT_ID` +
     `SWITCH_AGENT_API_KEY`
   - `DEV_SQUAD_TRANSPORT=switch`
6. Start an investigation with `POST /cases/{case_id}/investigate`.

### What the current Switch adapter does

`bridge/transport/switch.py` implements only the documented HTTP operations:

- `GET /health` — probe the server.
- `POST /agents` — register `devsquad-bridge`.
- `POST /agents/{agent_id}/message` — post the sanitized case and timeline into
  the configured room.

It intentionally does **not** fake live WebSocket event ingestion or verdict
retrieval. After submitting a case, the adapter returns a `submitted` status and
states that verdict retrieval requires a verified WebSocket listener. Until that
listener is implemented and tested against a running Switch server, use
LocalRunner for the complete investigation demo.

## Credentials

Switch credentials are read from environment variables or
`bridge/data/switch_agent.json` (gitignored). They are never stored in the
extension or in source.

## References

- Switch project: https://github.com/sandbox-quantum/switch
- Switch documentation: https://docs.switchagents.ai
- Issue #1335: Windows native server / `initdb.exe`
- Issue #1421: OpenCode 2.x event format
- Issue #1426: OpenCode 1.x pin
