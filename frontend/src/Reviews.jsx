import { useCallback, useEffect, useRef, useState } from "react";
import ReviewCard from "./ReviewCard.jsx";
import { presentReview } from "./presentation.js";
import ExampleHost from "./ExampleHost.jsx";

export function ReasonAction({ label, submitLabel, onSubmit }) {
  const [reason, setReason] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError("");
        try {
          await onSubmit(reason.trim());
          setReason("");
        } catch (e) {
          setError(e.message);
        } finally {
          setBusy(false);
        }
      }}
    >
      <label>
        {label}
        <textarea
          required
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          disabled={busy}
        />
      </label>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <button disabled={busy || !reason.trim()}>
        {busy ? "Saving…" : submitLabel}
      </button>
    </form>
  );
}
export default function Reviews({ api, base, project, host }) {
  const [cases, setCases] = useState([]),
    [selected, setSelected] = useState(host?.case_id || ""),
    [data, setData] = useState(null),
    [error, setError] = useState("");
  const [reason, setReason] = useState(""),
    [profileChoice, setProfileChoice] = useState(""),
    [busy, setBusy] = useState(false);
  const sequence = useRef(0);
  const load = useCallback(async () => {
    const request = ++sequence.current;
    const rows = await api.all(base + "/cases");
    if (request !== sequence.current) return;
    setCases(rows);
    const id = selected || rows[0]?.case_id;
    if (!id) {
      setData(null);
      return;
    }
    const path = base + "/cases/" + id;
    const review = await api(path + "/review");
    const [submission, profile, profiles, events] = await Promise.all([
      review.evidence_url ? api(review.evidence_url) : null,
      review.profile_ref
        ? api(
            base +
              "/profiles/" +
              review.profile_ref.id +
              "/versions/" +
              review.profile_ref.version,
          )
        : null,
      api.all(base + "/profiles"),
      api.all(base + "/events?case_id=" + encodeURIComponent(id)),
    ]);
    if (request !== sequence.current) return;
    setData({
      id,
      path,
      review,
      submission,
      profile,
      profiles,
      events,
      externalId: rows.find((r) => r.case_id === id)?.external_case_id,
    });
    setError("");
  }, [api, base, selected]);
  useEffect(() => {
    load().catch((e) => setError(e.message));
    return () => {
      sequence.current++;
    };
  }, [load]);
  useEffect(() => {
    if (data?.review.evaluation_status !== "pending") return;
    const t = setTimeout(() => load().catch((e) => setError(e.message)), 800);
    return () => clearTimeout(t);
  }, [data, load]);
  async function evaluate() {
    setBusy(true);
    setError("");
    try {
      const p = data.profiles.find(
        (p) =>
          p.profile_id ===
          (profileChoice ||
            data.profile?.profile_id ||
            data.profiles[0]?.profile_id),
      );
      if (!p) throw Error("Create guidelines before evaluating.");
      await api(data.path + "/assessments", "POST", {
        submission_id: data.review.submission_id,
        profile_ref: { id: p.profile_id, version: p.version },
        expected_review_token: data.review.review_token,
      });
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="intro">
        <h1>Work ready for your judgment</h1>
        <p>Inspect the evidence, consider the consequences, then decide.</p>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}{" "}
          <button onClick={() => load().catch((e) => setError(e.message))}>
            Refresh
          </button>
        </p>
      )}
      {cases.length > 1 && (
        <label>
          Work item
          <select
            value={data?.id || ""}
            onChange={(e) => {
              setSelected(e.target.value);
              setReason("");
              setProfileChoice("");
              setData(null);
            }}
          >
            {cases.map((c) => (
              <option key={c.case_id} value={c.case_id}>
                {c.summary || c.external_case_id}
              </option>
            ))}
          </select>
        </label>
      )}
      {!data ? (
        <p className="muted">
          {cases.length ? "Loading review…" : "No submissions yet."}
        </p>
      ) : (
        <div className="review-grid">
          <div>
            <ReviewCard
              key={data.review.review_token}
              {...presentReview(
                data.review,
                data.submission,
                data.profile,
                data.externalId,
              )}
              initialReason={reason}
              onReasonChange={setReason}
              onRefresh={load}
              onDecision={async ({ answer, rationale }) => {
                await api(data.path + "/decisions", "POST", {
                  assessment_id: data.review.assessment_id,
                  expected_review_token: data.review.review_token,
                  supersedes_decision_id:
                    data.review.current_decision?.decision_id || null,
                  answer,
                  rationale,
                  exceptions: [],
                  conditions: [],
                });
                setReason("");
                await load();
              }}
            />
          </div>
          <div>
            <section className="panel">
              <div className="row spread">
                <h2>Review context</h2>
                <span className="badge">
                  {data.review.state.replaceAll("_", " ")}
                </span>
              </div>
              <p className="muted">
                Work revision {data.submission?.revision} ·{" "}
                {data.profile
                  ? `${data.profile.name} · v${data.profile.version}`
                  : "No guidelines selected"}
              </p>
              {data.review.current_decision && (
                <div className="notice">
                  <strong>
                    {data.review.current_decision.kind === "revocation"
                      ? "Decision withdrawn"
                      : data.review.current_decision.answer === "yes"
                        ? "Human decision: Proceed"
                        : "Human decision: Hold"}
                  </strong>
                  <p>{data.review.current_decision.rationale}</p>
                  <p className="reference">
                    {data.review.current_decision.actor_id} ·{" "}
                    {new Date(
                      data.review.current_decision.recorded_at,
                    ).toLocaleString()}
                  </p>
                </div>
              )}
              <button onClick={() => load().catch((e) => setError(e.message))}>
                Refresh review
              </button>
              {data.review.allowed_actions.includes("evaluate") && (
                <details open={!data.review.assessment_id}>
                  <summary>Select guidelines and evaluate</summary>
                  <label>
                    Guideline version
                    <select
                      value={
                        profileChoice ||
                        data.profile?.profile_id ||
                        data.profiles[0]?.profile_id ||
                        ""
                      }
                      onChange={(e) => setProfileChoice(e.target.value)}
                    >
                      {data.profiles.map((p) => (
                        <option key={p.profile_id} value={p.profile_id}>
                          {p.name} · v{p.version}
                        </option>
                      ))}
                    </select>
                  </label>
                  <p className="muted">
                    This creates a new evaluation. Previous assessments and
                    decisions stay in history.
                  </p>
                  <button
                    disabled={busy || !data.profiles.length}
                    onClick={evaluate}
                  >
                    Request evaluation
                  </button>
                </details>
              )}
              {data.review.allowed_actions.includes("revoke_decision") && (
                <details>
                  <summary>Withdraw decision</summary>
                  <ReasonAction
                    label="Reason for withdrawal"
                    submitLabel="Record withdrawal"
                    onSubmit={async (rationale) => {
                      await api(
                        data.path +
                          "/decisions/" +
                          data.review.current_decision.decision_id +
                          "/revocations",
                        "POST",
                        {
                          expected_review_token: data.review.review_token,
                          rationale,
                        },
                      );
                      await load();
                    }}
                  />
                </details>
              )}
              <details>
                <summary>Findings, questions and limits</summary>
                <pre>
                  {JSON.stringify(
                    data.review.result ||
                      data.review.error || {
                        status: data.review.evaluation_status,
                      },
                    null,
                    2,
                  )}
                </pre>
              </details>
              <details>
                <summary>Concerns · {data.review.concerns.length}</summary>
                {data.review.concerns.map((c) => (
                  <div className="editor-item" key={c.concern_id}>
                    <p>{c.payload.message}</p>
                    <small>
                      {c.resolved ? "Resolved" : "Open"} · {c.actor_id}
                    </small>
                    {c.responses.map((r) => (
                      <p key={r.event_id}>{r.payload.message}</p>
                    ))}
                    {!c.resolved && (
                      <ReasonAction
                        label="Response"
                        submitLabel="Add response"
                        onSubmit={async (message) => {
                          await api(
                            base + "/concerns/" + c.concern_id + "/responses",
                            "POST",
                            {
                              expected_concern_version: c.version,
                              message,
                              resolve: false,
                            },
                          );
                          await load();
                        }}
                      />
                    )}
                    {!c.resolved &&
                      ["owner", "approver"].includes(project.role) && (
                        <ReasonAction
                          label="Resolution reason"
                          submitLabel="Resolve concern"
                          onSubmit={async (message) => {
                            await api(
                              base + "/concerns/" + c.concern_id + "/responses",
                              "POST",
                              {
                                expected_concern_version: c.version,
                                message,
                                resolve: true,
                              },
                            );
                            await load();
                          }}
                        />
                      )}
                  </div>
                ))}
                {data.review.allowed_actions.includes("raise_concern") && (
                  <ReasonAction
                    label="What should be reconsidered?"
                    submitLabel="Raise concern"
                    onSubmit={async (message) => {
                      await api(base + "/concerns", "POST", {
                        case_id: data.id,
                        category: "interpretation",
                        message,
                      });
                      await load();
                    }}
                  />
                )}
              </details>
              <details>
                <summary>Decision and host history</summary>
                {data.events.map((event) => (
                  <div className="history-item" key={event.event_id}>
                    <strong>
                      {event.event_type
                        .replaceAll(".", " · ")
                        .replaceAll("_", " ")}
                    </strong>
                    <small>
                      {new Date(event.recorded_at).toLocaleString()} ·{" "}
                      {event.actor_id}
                    </small>
                    <details>
                      <summary>Inspect record</summary>
                      <pre>{JSON.stringify(event, null, 2)}</pre>
                    </details>
                  </div>
                ))}
              </details>
            </section>
            {host && data.submission && (
              <ExampleHost
                key={data.submission.submission_id}
                api={api}
                review={data.review}
                submission={data.submission}
                onRefresh={load}
                canEdit={["owner", "approver"].includes(project.role)}
              />
            )}
          </div>
        </div>
      )}
    </>
  );
}
