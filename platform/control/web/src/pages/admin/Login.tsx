import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../../auth";

export default function Login() {
  const { login, username } = useAuth();
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();
  const loc = useLocation();
  const from = (loc.state as { from?: string } | null)?.from ?? "/admin";

  if (username) {
    nav(from, { replace: true });
    return null;
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await login(u, p);
      nav(from, { replace: true });
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-shell">
      <form className="card login-card" onSubmit={submit}>
        <div className="brand brand-large">
          <img src="/static/kct-logo.png" alt="" />
          <strong>
            Kos<span>Sim</span>
          </strong>
        </div>
        <p className="subtitle">Operator sign in</p>
        {err && <div className="alert alert-danger">{err}</div>}
        <label className="field">
          <span>Username</span>
          <input value={u} onChange={(e) => setU(e.target.value)} autoComplete="username" required autoFocus />
        </label>
        <label className="field">
          <span>Password</span>
          <input
            type="password"
            value={p}
            onChange={(e) => setP(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
