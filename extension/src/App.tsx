import React, { useEffect, useState } from "react";
import CaptureForm from "./views/CaptureForm";
import InvestigateView from "./views/InvestigateView";
import EvidenceView from "./views/EvidenceView";
import TimelineView from "./views/TimelineView";
import CollaborationView from "./views/CollaborationView";
import VerdictView from "./views/VerdictView";
import { DevSquadProvider, useDevSquad } from "./store/DevSquadContext";

type Tab = "capture" | "investigate" | "evidence" | "timeline" | "collaboration" | "verdict";

const TABS: Array<{ id: Tab; label: string }> = [
  { id: "capture", label: "Capture" },
  { id: "investigate", label: "Investigate" },
  { id: "evidence", label: "Evidence" },
  { id: "timeline", label: "Timeline" },
  { id: "collaboration", label: "Collaboration" },
  { id: "verdict", label: "Verdict" },
];

function SettingsBar() {
  const { settings, settingsReady, updateSettings, caseId } = useDevSquad();
  const [open, setOpen] = useState(!settings.token);
  const [bridgeUrl, setBridgeUrl] = useState(settings.bridgeUrl);
  const [token, setToken] = useState(settings.token);

  useEffect(() => {
    setBridgeUrl(settings.bridgeUrl);
    setToken(settings.token);
  }, [settings]);

  return (
    <div className="settings">
      <button className="link" onClick={() => setOpen((value) => !value)}>
        {open ? "Hide settings" : "Settings"}
      </button>
      <span className="muted">
        case <strong>{caseId || "—"}</strong>
        {settings.token ? " · token saved" : " · token missing"}
        {settingsReady ? "" : " · loading…"}
      </span>
      {open ? (
        <div className="settings-body">
          <label>
            Bridge URL
            <input
              value={bridgeUrl}
              onChange={(event) => setBridgeUrl(event.target.value)}
              placeholder="http://127.0.0.1:8000"
            />
          </label>
          <label>
            Pairing token
            <input
              type="password"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder="run: python -m bridge --token"
            />
          </label>
          <button onClick={() => void updateSettings({ bridgeUrl, token })}>Save</button>
          <p className="muted small">
            The token stays in extension storage. It is sent only to the local bridge as{" "}
            <code>X-DevSquad-Token</code>.
          </p>
        </div>
      ) : null}
    </div>
  );
}

function Shell() {
  const [tab, setTab] = useState<Tab>("capture");

  return (
    <div className="app">
      <header className="app-header">
        <div>
          <h1>DEV-SQUAD</h1>
          <p className="muted">Collaborative AI browser incident investigation</p>
        </div>
        <nav>
          {TABS.map((item) => (
            <button
              key={item.id}
              className={tab === item.id ? "active" : ""}
              onClick={() => setTab(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>
      </header>

      <SettingsBar />

      <main>
        {tab === "capture" ? <CaptureForm /> : null}
        {tab === "investigate" ? <InvestigateView /> : null}
        {tab === "evidence" ? <EvidenceView /> : null}
        {tab === "timeline" ? <TimelineView /> : null}
        {tab === "collaboration" ? <CollaborationView /> : null}
        {tab === "verdict" ? <VerdictView /> : null}
      </main>
    </div>
  );
}

export default function App() {
  return (
    <DevSquadProvider>
      <Shell />
    </DevSquadProvider>
  );
}
