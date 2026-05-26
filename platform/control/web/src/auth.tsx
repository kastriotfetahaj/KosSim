import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { admin, HttpError } from "./api";

type AuthState = {
  loading: boolean;
  username: string | null;
};

type AuthCtx = AuthState & {
  refresh: () => Promise<void>;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ loading: true, username: null });

  const refresh = useCallback(async () => {
    try {
      const me = await admin.me();
      setState({ loading: false, username: me.authenticated ? me.username ?? null : null });
    } catch {
      setState({ loading: false, username: null });
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const login = useCallback(async (username: string, password: string) => {
    try {
      await admin.login(username, password);
    } catch (e) {
      if (e instanceof HttpError && e.status === 401) {
        throw new Error("Invalid credentials");
      }
      throw e;
    }
    await refresh();
  }, [refresh]);

  const logout = useCallback(async () => {
    try {
      await admin.logout();
    } finally {
      setState((s) => ({ ...s, username: null }));
    }
  }, []);

  return <Ctx.Provider value={{ ...state, refresh, login, logout }}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}
