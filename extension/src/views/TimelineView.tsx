import React from "react";
import { useDevSquad } from "../store/DevSquadContext";
import { TimelineList } from "../components/Ui";

export default function TimelineView() {
  const { caseId, setCaseId, timeline, detail, refresh, busy, error } = useDevSquad();
  const coverage = timeline?.coverage as Record<string, unknown> | undefined;

  return (
    <div className="view">
      <h2>Timeline</h2>
      <p className="muted">
        Deterministic chronological correlation. Relative times are computed from the
        earliest observation; no LLM is involved.
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
          Load timeline
        </button>
      </div>

      {error ? <div className="alert alert-error">{error}</div> : null}

      {timeline ? (
        <>
          <section className="panel">
            <div className="panel-head">
              <h3>Coverage</h3>
              <span className={`badge ${timeline.insufficient_evidence ? "badge-bad" : "badge-ok"}`}>
                {timeline.insufficient_evidence ? "insufficient evidence" : "direct failure observed"}
              </span>
            </div>
            <dl className="facts">
              <div>
                <dt>Events</dt>
                <dd>{timeline.events?.length ?? 0}</dd>
              </div>
              <div>
                <dt>Ordering verified</dt>
                <dd>{String(coverage?.ordering_verified ?? "—")}</dd>
              </div>
              <div>
                <dt>Capture complete</dt>
                <dd>{String(coverage?.capture_complete ?? "—")}</dd>
              </div>
              <div>
                <dt>Sources</dt>
                <dd>{Array.isArray(coverage?.sources) ? (coverage?.sources as string[]).join(", ") : "—"}</dd>
              </div>
            </dl>
            {timeline.warnings?.length ? (
              <ul className="warnings">
                {timeline.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            ) : null}
          </section>

          <section className="panel">
            <h3>Events</h3>
            <TimelineList timeline={timeline} />
            {detail ? <p className="muted small">Case: {detail.case_id}</p> : null}
          </section>
        </>
      ) : (
        <p className="muted">Load a case to view its timeline.</p>
      )}
    </div>
  );
}
