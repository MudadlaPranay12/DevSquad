import React, { useState } from "react";
import { useDevSquad } from "../store/DevSquadContext";
import { EvidenceTable } from "../components/Ui";

export default function CaptureForm() {
  const { caseId, setCaseId, preview, runPreview, runSubmit, busy, error, notice } =
    useDevSquad();
  const [url, setUrl] = useState("http://localhost:3001/");
  const [schemaVersion, setSchemaVersion] = useState<1 | 2>(2);
  const [clickSelector, setClickSelector] = useState("#loginBtn");
  const [incidentDescription, setIncidentDescription] = useState(
    "Login click produces HTTP 401 and the button stays in a loading state.",
  );

  const buildRequest = () => ({
    url: url.trim(),
    case_id: caseId.trim(),
    schema_version: schemaVersion,
    click: clickSelector.trim() || null,
    incident_description: incidentDescription.trim() || null,
  });

  const valid = /^DS-\d{3}$/.test(caseId.trim()) && /^https?:\/\//i.test(url.trim());

  return (
    <div className="view">
      <h2>Capture browser evidence</h2>
      <p className="muted">
        Capture runs the local Playwright collector against a demo app. Nothing is
        stored until you review the redacted preview and submit it.
      </p>

      <div className="grid two">
        <label>
          Demo URL
          <input
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="http://localhost:3001/"
          />
        </label>
        <label>
          Case ID
          <input
            value={caseId}
            onChange={(event) => setCaseId(event.target.value)}
            placeholder="DS-001"
          />
        </label>
        <label>
          Schema version
          <select
            value={schemaVersion}
            onChange={(event) => setSchemaVersion(Number(event.target.value) === 1 ? 1 : 2)}
          >
            <option value={2}>v2 — source-prefixed IDs (CON/NET/APP)</option>
            <option value={1}>v1 — legacy E### IDs</option>
          </select>
        </label>
        <label>
          Interaction selector (optional)
          <input
            value={clickSelector}
            onChange={(event) => setClickSelector(event.target.value)}
            placeholder="#loginBtn"
          />
        </label>
      </div>

      <label>
        Incident description (v2 only)
        <textarea
          value={incidentDescription}
          onChange={(event) => setIncidentDescription(event.target.value)}
          rows={2}
        />
      </label>

      <div className="actions">
        <button disabled={!valid || busy} onClick={() => void runPreview(buildRequest())}>
          {busy ? "Capturing…" : "Capture & preview"}
        </button>
        <span className="muted">
          Examples: auth-failure on <code>localhost:3001</code> with{" "}
          <code>#loginBtn</code>; stuck-spinner on <code>localhost:3002</code> with no click.
        </span>
      </div>

      {error ? <div className="alert alert-error">{error}</div> : null}
      {notice ? <div className="alert alert-ok">{notice}</div> : null}

      {preview ? (
        <section className="panel">
          <div className="panel-head">
            <h3>Redacted preview</h3>
            <span className="badge badge-ok">
              {preview.evidence_count} evidence items
            </span>
            <span className="badge badge-neutral">schema v{preview.schema_version}</span>
          </div>
          <p className="muted">{preview.note}</p>
          {preview.warnings.length ? (
            <ul className="warnings">
              {preview.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          ) : (
            <p className="muted">No capture warnings.</p>
          )}
          <EvidenceTable items={preview.bundle.evidence} />
          <div className="actions">
            <button disabled={busy} onClick={() => void runSubmit(buildRequest())}>
              {busy ? "Submitting…" : "Submit captured case"}
            </button>
          </div>
        </section>
      ) : null}
    </div>
  );
}
