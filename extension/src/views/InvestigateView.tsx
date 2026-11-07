import React from "react";
import { useDevSquad } from "../store/DevSquadContext";
import { StatusBadge } from "../components/Ui";

export default function InvestigateView() {
  const {
    caseId,
    setCaseId,
    status,
    events,
    detail,
    investigate,
    refresh,
    busy,
    error,
    notice,
    polling,
  } = useDevSquad();

  const agentStatus = events?.events
    ?.filter((event) => event.event_type === "agent_status")
    .slice(-8)
    .reverse();

  return (
    <div className="view">
      <h2>Investigation</h2>
      <p className="muted">
        Start the real four-agent investigation (lead, console, network, application)
        through the local bridge. LocalRunner uses OpenCode; no mocked findings.
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
        <button
          disabled={busy || !/^DS-\d{3}$/.test(caseId) || status?.status === "investigating"}
          onClick={() => void investigate()}
        >
          {status?.status === "investigating" ? "Investigation running…" : "Start investigation"}
        </button>
        <button className="secondary" disabled={busy} onClick={() => void refresh()}>
          Refresh
        </button>
      </div>

      {error ? <div className="alert alert-error">{error}</div> : null}
      {notice ? <div className="alert alert-ok">{notice}</div> : null}

      <section className="panel">
        <div className="panel-head">
          <h3>Status</h3>
          <StatusBadge status={status?.status} />
          {polling ? <span className="badge badge-running">live polling</span> : null}
        </div>
        <dl className="facts">
          <div>
            <dt>Case</dt>
            <dd>{caseId}</dd>
          </div>
          <div>
            <dt>Stage</dt>
            <dd>{status?.stage || "—"}</dd>
          </div>
          <div>
            <dt>Transport</dt>
            <dd>{status?.transport || "—"}</dd>
          </div>
          <div>
            <dt>Agent rounds</dt>
            <dd>{status?.agent_rounds ?? 0}</dd>
          </div>
          <div>
            <dt>Evidence</dt>
            <dd>{detail?.evidence_count ?? "—"}</dd>
          </div>
          <div>
            <dt>Verdict</dt>
            <dd>{status?.verdict_available ? "available" : "pending"}</dd>
          </div>
        </dl>
        {status?.error ? <p className="alert alert-error">{status.error}</p> : null}
      </section>

      <section className="panel">
        <h3>Agent activity</h3>
        {agentStatus?.length ? (
          <ul className="agent-status">
            {agentStatus.map((event) => {
              const data = event.data as Record<string, unknown>;
              return (
                <li key={event.event_id}>
                  <strong>{String(data.agent_id || "agent")}</strong>
                  <span>{String(data.status || "")}</span>
                  {data.message_type ? <em>{String(data.message_type)}</em> : null}
                  {data.stage ? <span className="muted">{String(data.stage)}</span> : null}
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="muted">No agent activity reported yet.</p>
        )}
      </section>

      <section className="panel">
        <h3>Event stream</h3>
        {events?.events?.length ? (
          <ol className="events">
            {events.events.slice(-12).map((event) => (
              <li key={event.event_id}>
                <span className="muted">{event.timestamp}</span>
                <strong>{event.event_type}</strong>
                <span className="summary">
                  {String((event.data as Record<string, unknown>).message || "")}
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="muted">No events yet.</p>
        )}
      </section>
    </div>
  );
}
