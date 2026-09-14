import { useEffect, useState } from "react";

export function canEditRequirement(req, fields) {
  const known = (pointer) => fields.some((f) => f.pointer === pointer);
  if (req.check.id === "required_values")
    return (
      req.check.parameters.pointers?.length === 1 &&
      known(req.check.parameters.pointers[0])
    );
  if (req.check.id === "equal_values")
    return (
      known(req.check.parameters.left) && known(req.check.parameters.right)
    );
  return false;
}
export function newDefinition() {
  return {
    scope: { work_types: ["work_item"], action_types: ["release_work"] },
    risks: [
      {
        id: "incomplete",
        title: "Incomplete work",
        consequence: "Incomplete work reaches the next step",
        applies_to: "proceed",
      },
    ],
    requirements: [],
  };
}
export function validateDraft(draft) {
  if (!draft.name.trim() || !draft.reason.trim())
    return "A name and publication reason are required.";
  const { risks, requirements } = draft.definition;
  if (!risks.length || !requirements.length)
    return "Add at least one risk and one requirement.";
  if (risks.some((r) => !r.title.trim() || !r.consequence.trim()))
    return "Each risk needs a label and consequence.";
  if (
    requirements.some(
      (r) =>
        !r.description.trim() ||
        !r.risk_ids.length ||
        r.risk_ids.some((id) => !risks.some((risk) => risk.id === id)),
    )
  )
    return "Each requirement needs a description and at least one existing risk.";
  if (
    requirements.some(
      (r) =>
        r.check.id === "equal_values" &&
        r.check.parameters.left === r.check.parameters.right,
    )
  )
    return "Values agree must compare two different fields.";
  return "";
}
export function ProfileEditor({ profile, fields, onSave, onCancel, ownerId }) {
  const [draft, setDraft] = useState(() => ({
    name: profile?.name || "New work guidelines",
    owner_id: profile?.owner_id || ownerId,
    reason: "",
    definition: structuredClone(profile?.definition || newDefinition()),
  }));
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const edit = (key, value) => setDraft((d) => ({ ...d, [key]: value }));
  const setList = (key, value) =>
    setDraft((d) => ({ ...d, definition: { ...d.definition, [key]: value } }));
  const update = (key, i, patch) =>
    setList(
      key,
      draft.definition[key].map((r, index) =>
        index === i ? { ...r, ...patch } : r,
      ),
    );
  const { risks, requirements } = draft.definition;
  const fieldSelect = (label, value, onChange) => (
    <label>
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {fields.map((f) => (
          <option key={f.pointer} value={f.pointer}>
            {f.label}
          </option>
        ))}
      </select>
    </label>
  );
  function addRequirement() {
    setList("requirements", [
      ...requirements,
      {
        id: crypto.randomUUID(),
        description: "A required value is present",
        risk_ids: [risks[0].id],
        check: {
          id: "required_values",
          parameters: { pointers: [fields[0].pointer] },
        },
      },
    ]);
  }
  async function save(e) {
    e.preventDefault();
    const invalid = validateDraft(draft);
    if (invalid) {
      setError(invalid);
      return;
    }
    setBusy(true);
    setError("");
    try {
      await onSave(draft);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={save} className="panel">
      <h2>{profile ? `Revise ${profile.name}` : "Create guidelines"}</h2>
      <p className="muted">
        Changes stay in this form until published. Existing reviews keep their
        original guideline version.
      </p>
      <fieldset disabled={busy} style={{ border: 0, padding: 0, margin: 0 }}>
        <label>
          Guideline name
          <input
            required
            value={draft.name}
            onChange={(e) => edit("name", e.target.value)}
          />
        </label>
        <h3>Consequences, in priority order</h3>
        <p className="muted">
          Priority directs attention. It does not waive a requirement.
        </p>
        {risks.map((r, i) => (
          <section
            className="editor-item"
            key={r.id}
            aria-label={`Risk ${i + 1}`}
          >
            <div className="row spread">
              <h3>Priority {i + 1}</h3>
              <div className="row">
                <button
                  type="button"
                  aria-label={`Move ${r.title} up`}
                  disabled={!i}
                  onClick={() => {
                    const next = [...risks];
                    [next[i - 1], next[i]] = [next[i], next[i - 1]];
                    setList("risks", next);
                  }}
                >
                  ↑
                </button>
                <button
                  type="button"
                  aria-label={`Move ${r.title} down`}
                  disabled={i === risks.length - 1}
                  onClick={() => {
                    const next = [...risks];
                    [next[i + 1], next[i]] = [next[i], next[i + 1]];
                    setList("risks", next);
                  }}
                >
                  ↓
                </button>
                <button
                  type="button"
                  disabled={requirements.some((req) =>
                    req.risk_ids.includes(r.id),
                  )}
                  onClick={() =>
                    setList(
                      "risks",
                      risks.filter((x) => x.id !== r.id),
                    )
                  }
                >
                  Remove risk
                </button>
              </div>
            </div>
            <div className="row">
              <label>
                Risk label
                <input
                  required
                  value={r.title}
                  onChange={(e) =>
                    update("risks", i, { title: e.target.value })
                  }
                />
              </label>
              <label>
                Applies to
                <select
                  value={r.applies_to}
                  onChange={(e) =>
                    update("risks", i, { applies_to: e.target.value })
                  }
                >
                  <option value="proceed">Proceed</option>
                  <option value="hold">Hold</option>
                  <option value="both">Both</option>
                </select>
              </label>
            </div>
            <label>
              Consequence
              <textarea
                required
                value={r.consequence}
                onChange={(e) =>
                  update("risks", i, { consequence: e.target.value })
                }
              />
            </label>
            {requirements.some((req) => req.risk_ids.includes(r.id)) && (
              <small>
                To remove this risk, first update the requirements that refer to
                it.
              </small>
            )}
          </section>
        ))}
        <button
          type="button"
          disabled={risks.length >= 30}
          onClick={() =>
            setList("risks", [
              ...risks,
              {
                id: crypto.randomUUID(),
                title: "",
                consequence: "",
                applies_to: "both",
              },
            ])
          }
        >
          Add risk
        </button>
        <h3 style={{ marginTop: 28 }}>Requirements</h3>
        {requirements.map((req, i) =>
          !canEditRequirement(req, fields) ? (
            <section className="editor-item" key={req.id}>
              <h3>{req.description}</h3>
              <p className="muted">
                API-managed requirement · preserved unchanged
              </p>
              <details>
                <summary>Inspect requirement</summary>
                <pre>{JSON.stringify(req, null, 2)}</pre>
              </details>
            </section>
          ) : (
            <section
              className="editor-item"
              key={req.id}
              aria-label={`Requirement ${i + 1}`}
            >
              <label>
                Requirement description
                <input
                  required
                  value={req.description}
                  onChange={(e) =>
                    update("requirements", i, { description: e.target.value })
                  }
                />
              </label>
              <label>
                Check
                <select
                  value={req.check.id}
                  onChange={(e) =>
                    update("requirements", i, {
                      check: {
                        id: e.target.value,
                        parameters:
                          e.target.value === "required_values"
                            ? { pointers: [fields[0].pointer] }
                            : {
                                left: fields[0].pointer,
                                right: fields[0].pointer,
                              },
                      },
                    })
                  }
                >
                  <option value="required_values">Required value</option>
                  <option value="equal_values">Values agree</option>
                </select>
              </label>
              <div className="row">
                {req.check.id === "required_values" ? (
                  fieldSelect(
                    "Required field",
                    req.check.parameters.pointers[0],
                    (v) =>
                      update("requirements", i, {
                        check: { ...req.check, parameters: { pointers: [v] } },
                      }),
                  )
                ) : (
                  <>
                    {fieldSelect(
                      "First field",
                      req.check.parameters.left,
                      (v) =>
                        update("requirements", i, {
                          check: {
                            ...req.check,
                            parameters: { ...req.check.parameters, left: v },
                          },
                        }),
                    )}
                    {fieldSelect(
                      "Second field",
                      req.check.parameters.right,
                      (v) =>
                        update("requirements", i, {
                          check: {
                            ...req.check,
                            parameters: { ...req.check.parameters, right: v },
                          },
                        }),
                    )}
                  </>
                )}
              </div>
              <p className="muted">Associated risks</p>
              <div className="risk-options">
                {risks.map((r) => (
                  <label key={r.id}>
                    <input
                      type="checkbox"
                      checked={req.risk_ids.includes(r.id)}
                      onChange={(e) =>
                        update("requirements", i, {
                          risk_ids: e.target.checked
                            ? [...req.risk_ids, r.id]
                            : req.risk_ids.filter((id) => id !== r.id),
                        })
                      }
                    />
                    {r.title || "Untitled risk"}
                  </label>
                ))}
              </div>
              <button
                type="button"
                onClick={() =>
                  setList(
                    "requirements",
                    requirements.filter((r) => r.id !== req.id),
                  )
                }
              >
                Remove requirement
              </button>
            </section>
          ),
        )}
        <button
          type="button"
          disabled={
            !risks.length || !fields.length || requirements.length >= 100
          }
          onClick={addRequirement}
        >
          Add requirement
        </button>
        {!fields.length && (
          <p className="muted">
            This integration has no guided field catalog; requirements are
            managed through the API.
          </p>
        )}
        <label style={{ marginTop: 24 }}>
          Reason for publishing
          <textarea
            required
            value={draft.reason}
            onChange={(e) => edit("reason", e.target.value)}
          />
        </label>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <div className="row">
          <button className="primary" type="submit">
            {busy ? "Publishing…" : "Publish version"}
          </button>
          <button type="button" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </fieldset>
    </form>
  );
}
export default function Guidelines({ api, base, project, host }) {
  const [profiles, setProfiles] = useState([]),
    [editing, setEditing] = useState(null),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  async function load() {
    setProfiles(await api.all(base + "/profiles"));
  }
  useEffect(() => {
    let active = true;
    api
      .all(base + "/profiles")
      .then((p) => {
        if (active) setProfiles(p);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [api, base]);
  const ownerId = project.actor_id;
  async function publish(draft) {
    const existing = editing !== "new";
    await api(
      base +
        "/profiles" +
        (existing ? "/" + editing.profile_id + "/versions" : ""),
      "POST",
      {
        ...draft,
        ...(existing ? { expected_latest_version: editing.version } : {}),
      },
    );
    setEditing(null);
    setNotice(
      "Guidelines published. Existing reviews retain their original version; select the new version when requesting an evaluation.",
    );
    await load();
  }
  return (
    <>
      <div className="intro">
        <h1>What consequences matter most?</h1>
        <p>Define the risks and requirements that guide each review.</p>
      </div>
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
      {editing ? (
        <ProfileEditor
          key={editing === "new" ? "new" : editing.profile_id}
          profile={editing === "new" ? null : editing}
          fields={host?.fields || []}
          ownerId={ownerId}
          onSave={publish}
          onCancel={() => setEditing(null)}
        />
      ) : (
        <>
          {profiles.map((p) => (
            <section className="panel" key={p.profile_id}>
              <div className="row spread">
                <h2>{p.name}</h2>
                <span className="badge">Version {p.version}</span>
              </div>
              <ol>
                {p.definition.risks.map((r) => (
                  <li key={r.id}>
                    <strong>{r.title}</strong> · {r.applies_to}
                    <p className="muted">{r.consequence}</p>
                  </li>
                ))}
              </ol>
              <details>
                <summary>
                  Requirements · {p.definition.requirements.length}
                </summary>
                {p.definition.requirements.map((r) => (
                  <p key={r.id}>{r.description}</p>
                ))}
              </details>
              {project.role === "owner" && (
                <button
                  onClick={() => {
                    setEditing(p);
                    setNotice("");
                  }}
                >
                  Edit guidelines
                </button>
              )}
            </section>
          ))}
          {project.role === "owner" && (
            <button
              className="primary"
              disabled={!ownerId}
              onClick={() => {
                setEditing("new");
                setNotice("");
              }}
            >
              Create guidelines
            </button>
          )}
        </>
      )}
    </>
  );
}
