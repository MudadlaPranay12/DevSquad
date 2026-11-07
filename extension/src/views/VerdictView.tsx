import React from "react";
import { useDevSquad } from "../store/DevSquadContext";
import { StatusBadge, VerdictPanel } from "../components/Ui";

export default function VerdictView() {
  const {
    caseId,
    setCaseId,
    verdict,
    decision,
    status,
    refresh,
    decide,
    busy,
    error,
  } = useDevSquad();

  return (
    <div className="view">
      <h2>Verdict</h2>
      <p className="muted">
        Confidence is computed deterministically by the bridge from evidence sources,
        ordering, coverage and unresolved challenges. Agent self-confidence is ignored.
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
          Refresh verdict
        </button>
        <StatusBadge status={status?.status} />
      </div>

      {error ? <div className="alert alert-error">{error}</div> : null}

      <section className="panel">
        <VerdictPanel verdict={verdict} decision={decision} busy={busy} onDecide={decide} />
      </section>
    </div>
  );
}
