import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/auth/AuthContext";
import { Alert, Badge, Button, Card, Field, Input, PageHeader, Select } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { Role, User } from "@/lib/types";

interface Draft {
  username: string;
  full_name: string;
  password: string;
  role: Role;
}

const empty: Draft = { username: "", full_name: "", password: "", role: "staff" };

function UserForm({ initial, onDone }: { initial?: User; onDone: () => void }) {
  const { t } = useTranslation();
  const { user: me } = useAuth();
  const qc = useQueryClient();
  const [d, setD] = useState<Draft>(initial ? { ...empty, username: initial.username, full_name: initial.full_name, role: initial.role } : empty);
  const self = initial?.id === me?.id;

  const save = useMutation({
    mutationFn: () =>
      initial
        ? api<User>(`/users/${initial.id}`, {
            method: "PATCH",
            body: { full_name: d.full_name, role: d.role, ...(d.password ? { password: d.password } : {}) },
          })
        : api<User>("/users", { method: "POST", body: d }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["users"] });
      onDone();
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate();
  }

  return (
    <Card className="mb-6">
      <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
        {save.error && (
          <div className="sm:col-span-2">
            <Alert>{errorMessage(save.error, t)}</Alert>
          </div>
        )}
        <Field label={t("auth.username")}>
          <Input value={d.username} disabled={!!initial} onChange={(e) => setD({ ...d, username: e.target.value })} required minLength={3} autoCapitalize="none" />
        </Field>
        <Field label={t("users.fullName")}>
          <Input value={d.full_name} onChange={(e) => setD({ ...d, full_name: e.target.value })} />
        </Field>
        <Field label={t("users.role")}>
          <Select value={d.role} disabled={self} onChange={(e) => setD({ ...d, role: e.target.value as Role })}>
            <option value="staff">{t("role.staff")}</option>
            <option value="admin">{t("role.admin")}</option>
          </Select>
        </Field>
        {!self && (
          <Field label={initial ? t("users.newPassword") : t("auth.password")} hint={t("users.passwordHint")}>
            <Input type="password" autoComplete="new-password" value={d.password} onChange={(e) => setD({ ...d, password: e.target.value })} required={!initial} minLength={8} />
          </Field>
        )}
        <div className="flex gap-2 sm:col-span-2">
          <Button type="submit" disabled={save.isPending}>
            {initial ? t("common.save") : t("common.create")}
          </Button>
          <Button variant="secondary" onClick={onDone}>
            {t("common.cancel")}
          </Button>
        </div>
      </form>
    </Card>
  );
}

export function UsersPage() {
  const { t } = useTranslation();
  const { user: me } = useAuth();
  const qc = useQueryClient();
  const [editing, setEditing] = useState<User | "new" | null>(null);
  const users = useQuery({ queryKey: ["users"], queryFn: () => api<User[]>("/users") });

  const toggle = useMutation({
    mutationFn: (u: User) => api<User>(`/users/${u.id}`, { method: "PATCH", body: { is_active: !u.is_active } }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["users"] }),
  });

  return (
    <>
      <PageHeader title={t("users.title")} actions={editing === null && <Button onClick={() => setEditing("new")}>{t("users.new")}</Button>} />
      {editing && <UserForm key={editing === "new" ? "new" : editing.id} initial={editing === "new" ? undefined : editing} onDone={() => setEditing(null)} />}
      {toggle.error && (
        <div className="mb-4">
          <Alert>{errorMessage(toggle.error, t)}</Alert>
        </div>
      )}
      <div className="overflow-x-auto rounded-xl border border-zinc-200 bg-white">
        <table className="w-full min-w-[560px] text-sm">
          <thead className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500">
            <tr>
              <th className="px-4 py-3 font-medium">{t("auth.username")}</th>
              <th className="px-4 py-3 font-medium">{t("users.fullName")}</th>
              <th className="px-4 py-3 font-medium">{t("users.role")}</th>
              <th className="px-4 py-3 font-medium">{t("users.status")}</th>
              <th className="px-4 py-3 text-right font-medium">{t("common.actions")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100">
            {users.isLoading && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-zinc-500">
                  {t("common.loading")}
                </td>
              </tr>
            )}
            {users.data?.map((u) => (
              <tr key={u.id}>
                <td className="px-4 py-3 font-medium">{u.username}</td>
                <td className="px-4 py-3">{u.full_name}</td>
                <td className="px-4 py-3">{t(`role.${u.role}`)}</td>
                <td className="px-4 py-3">
                  <Badge tone={u.is_active ? "green" : "neutral"}>{u.is_active ? t("common.active") : t("common.inactive")}</Badge>
                </td>
                <td className="px-4 py-3 text-right">
                  <div className="inline-flex gap-1">
                    <Button variant="ghost" onClick={() => setEditing(u)}>
                      {t("common.edit")}
                    </Button>
                    {u.id !== me?.id && (
                      <Button variant="ghost" disabled={toggle.isPending} onClick={() => toggle.mutate(u)}>
                        {u.is_active ? t("users.deactivate") : t("users.activate")}
                      </Button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
