import React from "react";
import { useDevSquad } from "../store/DevSquadContext";
import { EvidenceTable } from "../components/Ui";

export default function EvidenceView() {
  const { caseId, setCaseId, detail, refresh, busy, error } = useDevSquad();

  return (
    <div className="view">
      <h2>Evidence</h2>
      <p className="muted">
        Evidence is redacted twice — in the collector and again in the bridge. Cookie
        values, authorization headers and passwords are never stored.
      </p>

      <div className="actions">
        <label className="inline">
          Case
          <input
            value={caseId}
            onChange={(event) => setCaseId(event.target.value)}
            placeholder="DS-001"
          />
        </label>
        <button disabled={busy} onClick={() => void refresh()}>
          Load case
        </button>
      </div>

      {error ? <div className="alert alert-error">{error}</div> : null}

      {detail ? (
        <>
          <section className="panel">
            <div className="panel-head">
              <h3>{detail.case_id}</h3>
              <span className="badge badge-neutral">schema v{detail.schema_version || 1}</span>
              <span className="badge badge-neutral">{detail.capture_source || "playwright"}</span>
              <span className="badge badge-ok">{detail.evidence_count} items</span>
            </div>
            <dl className="facts">
              <div>
                <dt>Page</dt>
                <dd>{detail.page_url || "—"}</dd>
              </div>
              <div>
                <dt>Status</dt>
                <dd>{detail.status}</dd>
              </div>
              <div>
                <dt>Transport</dt>
                <dd>{detail.transport || "—"}</dd>
              </div>
            </dl>
            {detail.incident_description ? (
              <p>
                <strong>Incident:</strong> {detail.incident_description}
              </p>
            ) : null}
            {detail.warnings?.length ? (
              <ul className="warnings">
                {detail.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            ) : null}
          </section>

          <section className="panel">
            <h3>Evidence items</h3>
            <EvidenceTable items={detail.evidence} />
          </section>
        </>
      ) : (
        <p className="muted">Load a case to view its evidence.</p>
      )}
    </div>
  );
}
