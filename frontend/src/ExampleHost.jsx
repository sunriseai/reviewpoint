import { useRef, useState } from "react";

export function revisedSubmission(previous, work) {
  return {
    case_ref: {
      host_id: "example-host",
      workflow_id: "work-review",
      external_case_id: "WORK-001",
      checkpoint_key: "release",
    },
    expected_submission_id: previous.submission_id,
    host_revision: `revision-${previous.revision + 1}`,
    work_type: previous.work_type,
    summary: previous.summary || "WORK-001 · Work release",
    proposed_action: previous.action,
    work,
    context: previous.context,
    evidence: [
      {
        id: "source",
        title: "Supplied work snapshot",
        media_type: "application/json",
        source_uri: "example:WORK-001",
        captured_at: new Date().toISOString(),
        content: JSON.stringify(work),
      },
    ],
  };
}
export default function ExampleHost({
  api,
  review,
  submission,
  onRefresh,
  canEdit,
}) {
  const [work, setWork] = useState(() => structuredClone(submission.work));
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState("");
  const pending = useRef(null),
    pendingHandoff = useRef(null);
  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const signature = JSON.stringify(work);
      if (pending.current?.signature !== signature)
        pending.current = {
          signature,
          body: revisedSubmission(submission, work),
        };
      await api("/example-host/submissions", "POST", pending.current.body);
      pending.current = null;
      setNotice(
        "Revised work submitted. Select guidelines and request an evaluation.",
      );
      await onRefresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function handoff() {
    setBusy(true);
    setError("");
    try {
      if (
        pendingHandoff.current?.decision_id !==
        review.current_decision.decision_id
      )
        pendingHandoff.current = {
          submission_id: review.submission_id,
          decision_id: review.current_decision.decision_id,
          occurred_at: new Date().toISOString(),
        };
      await api("/example-host/handoff", "POST", pendingHandoff.current);
      setNotice(
        "The example host reported a simulated handoff. No real action was performed.",
      );
      await onRefresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel">
      <h2>Example host</h2>
      <p className="muted">
        This panel represents the application supplying work. It never makes a
        human decision.
      </p>
      <details>
        <summary>Revise the work</summary>
        <form onSubmit={submit}>
          <label>
            Work summary
            <textarea
              value={work.summary ?? ""}
              onChange={(e) => setWork({ ...work, summary: e.target.value })}
              disabled={!canEdit || busy}
            />
          </label>
          <div className="row">
            {[
              ["expected_items", "Expected items"],
              ["supplied_items", "Supplied items"],
            ].map(([key, label]) => (
              <label key={key}>
                {label}
                <input
                  type="number"
                  min="0"
                  step="1"
                  value={work[key] ?? ""}
                  onChange={(e) =>
                    setWork({
                      ...work,
                      [key]:
                        e.target.value === "" ? null : Number(e.target.value),
                    })
                  }
                  disabled={!canEdit || busy}
                />
              </label>
            ))}
          </div>
          <button disabled={!canEdit || busy} type="submit">
            Submit revision
          </button>
        </form>
      </details>
      <details>
        <summary>Simulate the next step</summary>
        <p className="muted">
          The host checks the exact current approval before reporting a
          simulated handoff.
        </p>
        <button
          disabled={!canEdit || busy || review.state !== "approved"}
          onClick={handoff}
        >
          Simulate handoff
        </button>
      </details>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="notice">
          {notice}
        </p>
      )}
    </section>
  );
}
