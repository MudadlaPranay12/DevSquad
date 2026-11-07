import React from "react";
import type {
  AgentMessage,
  Decision,
  EvidenceItem,
  Timeline,
  Verdict,
} from "../lib/types";

export function StatusBadge({ status }: { status?: string | null }) {
  const value = (status || "idle").toLowerCase();
  const tone =
    value === "completed"
      ? "ok"
      : value === "investigating" || value === "queued"
        ? "running"
        : value === "failed" || value === "timed_out"
          ? "bad"
          : "neutral";
  return <span className={`badge badge-${tone}`}>{status || "idle"}</span>;
}

function summarizeEvidence(item: EvidenceItem): string {
  if (item.message) return item.message;
  if (item.url) {
    const status = item.status !== undefined ? ` → ${item.status}` : "";
    return `${item.method || "GET"} ${item.url}${status}`;
  }
  if (item.observation) {
    return `${item.selector ? `${item.selector}: ` : ""}${item.observation}`;
  }
  if (item.cookie_name) return `cookie metadata: ${item.cookie_name}`;
  return item.type;
}

export function EvidenceTable({ items }: { items: EvidenceItem[] }) {
  if (!items.length) {
    return <p className="muted">No evidence loaded yet.</p>;
  }
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Source</th>
            <th>Type</th>
            <th>Observed</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <td>
                <code>{item.id}</code>
                {item.legacy_id ? <span className="legacy"> ({item.legacy_id})</span> : null}
              </td>
              <td>{item.source || "—"}</td>
              <td>{item.type}</td>
              <td className="summary">{summarizeEvidence(item)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function TimelineList({ timeline }: { timeline: Timeline | null }) {
  if (!timeline || !timeline.events?.length) {
    return <p className="muted">No timeline loaded yet.</p>;
  }
  return (
    <ol className="timeline">
      {timeline.events.map((event) => (
        <li
          key={`${event.evidence_id}-${event.relative || "untimed"}`}
          className={event.is_error ? "timeline-error" : ""}
        >
          <span className="timeline-time">{event.relative ?? "[no timestamp]"}</span>
          <code>{event.evidence_id}</code>
          <span className={`timeline-source source-${event.source || "unknown"}`}>
            {event.source || "unknown"}
          </span>
          <span className="timeline-summary">{event.summary}</span>
          {event.ordering && event.ordering !== "timestamp" ? (
            <span className="ordering">{event.ordering}</span>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

export function MessageList({ messages }: { messages: AgentMessage[] }) {
  if (!messages.length) {
    return <p className="muted">No agent messages yet. Start an investigation.</p>;
  }
  return (
    <div className="messages">
      {messages.map((message) => {
        const content = message.content || {};
        const summary =
          typeof content.summary === "string"
            ? content.summary
            : typeof content.focus === "string"
              ? content.focus
              : typeof content.reason === "string"
                ? content.reason
                : "—";
        const needed = typeof content.needed === "string" ? content.needed : null;
        return (
          <article key={message.message_id} className="message">
            <header>
              <strong>{message.agent_id}</strong>
              <span className={`msg-type type-${message.message_type.toLowerCase()}`}>
                {message.message_type}
              </span>
              {typeof message.round === "number" ? (
                <span className="muted">round {message.round}</span>
              ) : null}
              {message.accepted === false ? <span className="badge badge-bad">rejected</span> : null}
            </header>
            <p>{summary}</p>
            {needed ? (
              <p className="muted">
                <strong>Needed:</strong> {needed}
              </p>
            ) : null}
            {message.evidence_ids?.length ? (
              <p className="citations">
                {message.evidence_ids.map((id) => (
                  <code key={id}>{id}</code>
                ))}
              </p>
            ) : null}
          </article>
        );
      })}
    </div>
  );
}

export function VerdictPanel({
  verdict,
  decision,
  busy,
  onDecide,
}: {
  verdict: Verdict | null;
  decision: Record<string, unknown> | null;
  busy: boolean;
  onDecide: (decision: Decision, note: string) => void;
}) {
  const [note, setNote] = React.useState("");
  if (!verdict) {
    return <p className="muted">No verdict yet. The investigation may still be running.</p>;
  }
  const confidence = verdict.confidence || verdict.reported_confidence || "Unknown";
  const determined = Boolean(verdict.root_cause_determined);
  return (
    <div className="verdict">
      <div className="verdict-head">
        <h3>{verdict.root_cause}</h3>
        <span className={`badge ${determined ? "badge-ok" : "badge-neutral"}`}>
          {determined ? "determined" : "not determined"}
        </span>
        <span className={`badge confidence-${String(confidence).toLowerCase()}`}>
          confidence: {confidence}
        </span>
      </div>
      {verdict.summary ? <p>{verdict.summary}</p> : null}
      {verdict.confidence_reason ? (
        <p className="muted">{verdict.confidence_reason}</p>
      ) : null}
      {verdict.confidence_method ? (
        <p className="muted small">method: {verdict.confidence_method}</p>
      ) : null}

      {verdict.supporting_evidence?.length ? (
        <section>
          <h4>Supporting evidence</h4>
          <p className="citations">
            {verdict.supporting_evidence.map((id) => (
              <code key={id}>{id}</code>
            ))}
          </p>
        </section>
      ) : null}

      {verdict.failure_chain?.length ? (
        <section>
          <h4>Failure chain</h4>
          <ol className="chain">
            {verdict.failure_chain.map((step, index) => (
              <li key={`${step.step}-${index}`}>
                {step.step}
                <span className="citations">
                  {(step.evidence_ids || []).map((id) => (
                    <code key={id}>{id}</code>
                  ))}
                </span>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      {verdict.rejected_hypotheses?.length ? (
        <section>
          <h4>Rejected hypotheses</h4>
          <ul>
            {verdict.rejected_hypotheses.map((hypothesis, index) => (
              <li key={`${hypothesis.hypothesis}-${index}`}>
                <strong>{hypothesis.hypothesis}</strong> — {hypothesis.reason}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {!determined && verdict.missing_evidence?.length ? (
        <section>
          <h4>Missing evidence</h4>
          <ul>
            {verdict.missing_evidence.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {verdict.suggested_next_action ? (
        <p>
          <strong>Suggested next action:</strong> {verdict.suggested_next_action}
        </p>
      ) : null}
      {verdict.suggested_fix ? (
        <section>
          <h4>Suggested fix / remediation</h4>
          <p className="muted">{verdict.suggested_fix}</p>
          <p className="muted small">
            Agents suggest; humans decide. No code changes are applied automatically.
          </p>
        </section>
      ) : null}

      <section className="decision">
        <h4>Human decision</h4>
        {decision ? (
          <p>
            Recorded: <strong>{String(decision.decision || "")}</strong>
            {decision.note ? ` — ${String(decision.note)}` : ""}
          </p>
        ) : (
          <>
            <textarea
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="Optional note for the decision record"
              rows={2}
            />
            <div className="decision-actions">
              <button disabled={busy} onClick={() => onDecide("approve", note)}>
                Approve
              </button>
              <button className="secondary" disabled={busy} onClick={() => onDecide("need_more_evidence", note)}>
                Need more evidence
              </button>
              <button className="danger" disabled={busy} onClick={() => onDecide("reject", note)}>
                Reject
              </button>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
