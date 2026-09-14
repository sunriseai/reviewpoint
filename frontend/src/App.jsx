import { useState } from "react";
import { createApi } from "./api.js";
import Reviews from "./Reviews.jsx";
import Guidelines from "./Guidelines.jsx";
import Settings from "./Settings.jsx";

export default function App() {
  const [session, setSession] = useState(null),
    [token, setToken] = useState("");
  const [page, setPage] = useState("reviews"),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function login(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const api = createApi(token.trim());
      const projects = await api.all("/api/v1/projects");
      if (!projects.length) throw Error("This identity has no project access.");
      let host = null;
      try {
        host = await api("/example-host");
      } catch (e) {
        if (e.status !== 404) throw e;
      }
      const project = await api(
        "/api/v1/projects/" +
          encodeURIComponent(host?.project_id || projects[0].project_id),
      );
      setSession({ api, project, host });
      setToken("");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  const base = session
    ? "/api/v1/projects/" + encodeURIComponent(session.project.project_id)
    : "";
  return (
    <>
      <header className="brandbar">
        <span className="brand">Reviewpoint</span>
        <span className="badge">Local reference demo</span>
      </header>
      <main className="shell">
        {!session ? (
          <form onSubmit={login} className="panel login">
            <h1>A clear decision, with context.</h1>
            <p>
              Review proposed work against the consequences and requirements
              that matter.
            </p>
            <label>
              Demo credential
              <input
                type="password"
                autoComplete="off"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                required
              />
            </label>
            <p className="muted">
              Use an owner, approver or reviewer credential from the private
              file shown by the demo command. Identity is simulated.
            </p>
            {error && (
              <p role="alert" className="error">
                {error}
              </p>
            )}
            <button className="primary" disabled={busy}>
              {busy ? "Opening…" : "Open workspace"}
            </button>
          </form>
        ) : (
          <>
            <nav className="nav" aria-label="Main navigation">
              <button
                aria-current={page === "reviews" ? "page" : undefined}
                onClick={() => setPage("reviews")}
              >
                Reviews
              </button>
              <button
                aria-current={page === "guidelines" ? "page" : undefined}
                onClick={() => setPage("guidelines")}
              >
                Risk guidelines
              </button>
              <button
                className="settings"
                aria-current={page === "settings" ? "page" : undefined}
                onClick={() => setPage("settings")}
              >
                Settings
              </button>
            </nav>
            {page === "reviews" && <Reviews {...session} base={base} />}
            {page === "guidelines" && <Guidelines {...session} base={base} />}
            {page === "settings" && (
              <Settings
                {...session}
                base={base}
                onSignOut={() => {
                  setSession(null);
                  setPage("reviews");
                  setError("");
                }}
              />
            )}
          </>
        )}
      </main>
      <footer className="footer">
        Reviewpoint records the judgment. The host owns the action.
      </footer>
    </>
  );
}
