import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { Alert, Button, Field, Input } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { errorMessage } from "@/lib/errors";

export function LoginPage() {
  const { t } = useTranslation();
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from ?? "/";
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to={from} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username.trim(), password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? t("auth.invalid") : errorMessage(err, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-screen place-items-center px-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-5 rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm sm:p-8">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{t("app.name")}</h1>
          <p className="mt-1 text-sm text-zinc-500">{t("auth.subtitle")}</p>
        </div>
        {error && <Alert>{error}</Alert>}
        <Field label={t("auth.username")}>
          <Input autoComplete="username" autoCapitalize="none" value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
        </Field>
        <Field label={t("auth.password")}>
          <Input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </Field>
        <Button type="submit" disabled={busy} className="w-full">
          {t("auth.signIn")}
        </Button>
      </form>
    </div>
  );
}
