import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, refreshSession, setAccessToken, setSessionExpiredHandler } from "@/lib/api";
import type { Permission, TokenOut, User } from "@/lib/types";

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  can: (perm: Permission) => boolean;
  reloadUser: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const qc = useQueryClient();

  const reset = useCallback(() => {
    setAccessToken(null);
    setUser(null);
    qc.clear();
  }, [qc]);

  const reloadUser = useCallback(async () => {
    setUser(await api<User>("/auth/me"));
  }, []);

  useEffect(() => {
    setSessionExpiredHandler(reset);
    // Restore the session from the refresh cookie on page load.
    refreshSession()
      .then((ok) => (ok ? reloadUser() : undefined))
      .catch(() => reset())
      .finally(() => setLoading(false));
  }, [reset, reloadUser]);

  const login = useCallback(
    async (username: string, password: string) => {
      const t = await api<TokenOut>("/auth/login", { method: "POST", body: { username, password } });
      setAccessToken(t.access_token);
      await reloadUser();
    },
    [reloadUser],
  );

  const logout = useCallback(async () => {
    try {
      await api("/auth/logout", { method: "POST", noRetry: true });
    } finally {
      reset();
    }
  }, [reset]);

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      login,
      logout,
      reloadUser,
      can: (perm) => !!user?.permissions.includes(perm),
    }),
    [user, loading, login, logout, reloadUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
