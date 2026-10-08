import { useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { getErrorMessage } from "../api/client";

interface LoginLocationState {
  message?: string;
}

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const notice = (location.state as LoginLocationState | null)?.message;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(username.trim(), password);
      setPassword("");
      navigate("/", { replace: true });
    } catch (loginError) {
      setError(getErrorMessage(loginError, "Unable to sign in."));
      setPassword("");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-panel" aria-labelledby="login-title">
        <div className="login-brand">
          <span className="brand-mark brand-mark-large" aria-hidden="true">K</span>
          <p className="eyebrow">Kabgayi Level 2 Teaching Hospital</p>
        </div>
        <h1 id="login-title">Radiology PACS</h1>
        <p className="login-intro">Sign in to access the hospital study worklist.</p>
        {notice && <p className="notice-message" role="status">{notice}</p>}
        {error && <p className="error-message" role="alert">{error}</p>}
        <form onSubmit={submit} className="login-form">
          <label className="field">
            <span>Username</span>
            <input
              type="text"
              name="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              required
              autoFocus
            />
          </label>
          <label className="field">
            <span>Password</span>
            <input
              type="password"
              name="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
          <button className="button button-primary login-submit" type="submit" disabled={loading}>
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </section>
    </main>
  );
}
