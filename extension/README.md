# DEV-SQUAD Chrome DevTools Panel

Manifest V3 | TypeScript | React | Vite

The panel is the human interface for a DEV-SQUAD investigation. It captures
browser evidence through the local bridge, shows a redacted preview, starts the
four-agent investigation, streams progress, and records the final human decision.

## How capture works

The panel does not use `chrome.debugger`. It sends a capture request to the local
Python bridge, which runs the Playwright collector against a **localhost only**
demo URL. The bridge returns a redacted bundle for preview; nothing is stored
until the user submits it.

This keeps browser and model credentials out of the extension and guarantees that
the same collector, redaction and validation path is used everywhere.

## Install

```powershell
cd E:\DevSquad\extension
npm install
npm run build
```

Then:

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Choose **Load unpacked** and select `E:\DevSquad\extension`.
4. Open DevTools on a demo tab and select the **DEV-SQUAD** panel, or click the
   toolbar icon.
5. Open **Settings**, paste the pairing token from
   `python -m bridge --token`, and save.

The bridge must be running at `http://127.0.0.1:8000` before capture or
investigation.

## Views

| View | Purpose |
|---|---|
| Capture | URL, case ID, schema version, interaction selector, incident description; capture, preview and submit |
| Investigate | Start an investigation, watch status, stage, agent rounds and live events |
| Evidence | Browse the stored evidence with IDs, sources and summaries |
| Timeline | Deterministic chronological events with relative times and ordering labels |
| Collaboration | Agent messages, findings, challenges and revisions |
| Verdict | Root cause, confidence factors, failure chain, rejected hypotheses, missing evidence and human decision controls |

Settings are available in the bar under the header and persist in extension
storage.

## Development

```powershell
npm run typecheck
npm run build
npm run dev
```

`npm run dev` serves the React app in a browser for UI work. Extension APIs are
guarded with a `localStorage` fallback, so settings still work outside Chrome.

## Structure

```text
extension/
  manifest.json         Manifest V3, DevTools panel + popup
  devtools.html         Registers the DevTools panel
  devtools.js           chrome.devtools.panels.create(...)
  index.html            Vite entry
  src/
    App.tsx             Tab shell and settings bar
    main.tsx            React entry
    index.css           Panel styling
    lib/
      bridge.ts         Typed bridge client and error handling
      settings.ts       chrome.storage / localStorage wrapper
      types.ts          API and evidence types
    store/
      DevSquadContext.tsx  Shared state, capture, polling, decisions
    components/
      Ui.tsx            Badges, evidence table, timeline, messages, verdict
    views/
      CaptureForm.tsx
      InvestigateView.tsx
      EvidenceView.tsx
      TimelineView.tsx
      CollaborationView.tsx
      VerdictView.tsx
  dist/                 Built output
```

## Security

- Pairing token sent only to the local bridge as `X-DevSquad-Token`.
- Bridge URL and token stored in extension storage, never in source.
- Capture restricted to localhost / 127.0.0.1.
- No cookie values, authorization headers, request bodies or storage values.
- The panel shows a redacted preview before submission.
- Agents suggest; the human approves or rejects in the Verdict view.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Token missing | Run `python -m bridge --token`, paste into Settings |
| Capture connection refused | Start the demo app on port 3001 or 3002 |
| Capture fails validation | Check the bridge terminal output; only localhost URLs are allowed |
| No verdict | The investigation may still be running; check Investigate |
| Panel does not appear | Reload the extension and reopen DevTools |
