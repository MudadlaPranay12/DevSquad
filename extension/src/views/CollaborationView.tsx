import React from "react";
import { useDevSquad } from "../store/DevSquadContext";
import { MessageList, StatusBadge } from "../components/Ui";

export default function CollaborationView() {
  const { caseId, setCaseId, events, detail, status, refresh, busy, error } = useDevSquad();
  const messages = events?.messages || [];
  const transport = status?.transport || detail?.transport || "local";

  return (
    <div className="view">
      <h2>Collaboration</h2>
      <p className="muted">
        Four specialist agents investigate the same evidence and challenge each other.
        Every formal finding cites real evidence IDs, which the bridge validates.
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
          Refresh discussion
        </button>
      </div>

      {error ? <div className="alert alert-error">{error}</div> : null}

      <section className="panel">
        <div className="panel-head">
          <h3>Room status</h3>
          <StatusBadge status={status?.status} />
          <span className="badge badge-neutral">{transport}</span>
        </div>
        {transport === "local" ? (
          <p className="notice">
            LocalRunner mode: agents run through the local bridge because the Switch
            native Windows server is blocked (see <code>switch/SETUP_GUIDE.md</code>).
            The collaboration protocol is identical; only the transport differs.
          </p>
        ) : (
          <p className="muted">Switch transport selected. Room: devsquad-incidents.</p>
        )}
        <dl className="facts">
          <div>
            <dt>Messages</dt>
            <dd>{messages.length}</dd>
          </div>
          <div>
            <dt>Agent rounds</dt>
            <dd>{status?.agent_rounds ?? 0}</dd>
          </div>
          <div>
            <dt>Stage</dt>
            <dd>{status?.stage || "—"}</dd>
          </div>
        </dl>
      </section>

      <section className="panel">
        <h3>Agent discussion</h3>
        <MessageList messages={messages} />
      </section>
    </div>
  );
}
