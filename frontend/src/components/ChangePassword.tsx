import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { api, setAccessToken } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { Modal } from "./Modal";
import { Alert, Button, Field, Input } from "./ui";

/** Own password change. Other devices of this user are signed out; this one gets a new token. */
export function ChangePasswordDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const mismatch = repeat !== "" && next !== repeat;
  const m = useMutation({
    mutationFn: () => api<{ access_token: string }>("/auth/change-password", { method: "POST", body: { current_password: current, new_password: next } }),
    onSuccess: (r) => setAccessToken(r.access_token),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!mismatch && next.length >= 8) m.mutate();
  };

  return (
    <Modal title={t("auth.changePassword")} onClose={onClose}>
      {m.isSuccess ? (
        <>
          <Alert tone="green">{t("auth.passwordChanged")}</Alert>
          <div className="mt-4">
            <Button onClick={onClose}>{t("common.close")}</Button>
          </div>
        </>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <Field label={t("auth.currentPassword")}>
            <Input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
          </Field>
          <Field label={t("auth.newPassword")} hint={t("auth.passwordRule")}>
            <Input type="password" autoComplete="new-password" minLength={8} value={next} onChange={(e) => setNext(e.target.value)} required />
          </Field>
          <Field label={t("auth.repeatPassword")} error={mismatch ? t("auth.passwordsDiffer") : undefined}>
            <Input type="password" autoComplete="new-password" value={repeat} onChange={(e) => setRepeat(e.target.value)} required />
          </Field>
          {m.error && <Alert>{errorMessage(m.error, t)}</Alert>}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={m.isPending || mismatch || next.length < 8}>
              {t("common.save")}
            </Button>
            <Button type="button" variant="secondary" onClick={onClose}>
              {t("common.cancel")}
            </Button>
          </div>
        </form>
      )}
    </Modal>
  );
}
