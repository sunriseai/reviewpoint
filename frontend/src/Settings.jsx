import { useEffect, useState } from "react";
import { ReasonAction } from "./Reviews.jsx";
export default function Settings({ api, base, project, onSignOut }) {
  const [members, setMembers] = useState([]),
    [error, setError] = useState("");
  const load = () => api.all(base + "/memberships").then(setMembers);
  useEffect(() => {
    if (project.role === "owner") load().catch((e) => setError(e.message));
  }, [api, base, project.role]);
  return (
    <section className="panel">
      <h1>Settings</h1>
      <p>
        {project.name} · {project.role}
      </p>
      <p className="muted">
        Identity is simulated locally. External user records remain outside
        Reviewpoint.
      </p>
      <button onClick={onSignOut}>Sign out</button>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {project.role === "owner" && (
        <details>
          <summary>Project access</summary>
          {members.map((m) => (
            <Member
              key={m.actor_id + ":" + m.version}
              member={m}
              onSave={async (body) => {
                await api(base + "/memberships", "PUT", body);
                await load();
              }}
            />
          ))}
        </details>
      )}
    </section>
  );
}
function Member({ member: m, onSave }) {
  const [role, setRole] = useState(m.role),
    [active, setActive] = useState(!!m.active);
  return (
    <section className="editor-item">
      <p className="reference">{m.actor_id}</p>
      <label>
        Role
        <select value={role} onChange={(e) => setRole(e.target.value)}>
          {["reviewer", "approver", "owner"].map((r) => (
            <option key={r}>{r}</option>
          ))}
        </select>
      </label>
      <label>
        <input
          type="checkbox"
          checked={active}
          onChange={(e) => setActive(e.target.checked)}
        />
        Active access
      </label>
      <ReasonAction
        label="Reason for changing access"
        submitLabel="Save access"
        onSubmit={(reason) =>
          onSave({
            actor_id: m.actor_id,
            role,
            active,
            expected_version: m.version,
            reason,
          })
        }
      />
    </section>
  );
}
