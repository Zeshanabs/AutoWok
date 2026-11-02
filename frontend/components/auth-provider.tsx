"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";

import { ApiError, apiRequest } from "@/lib/api";
import type { CurrentUser, User, Workspace } from "@/lib/auth-types";

type AuthStatus = "loading" | "authenticated" | "unauthenticated" | "unavailable";

type AuthContextValue = {
  user: User | null;
  workspaces: Workspace[];
  selectedWorkspace: Workspace | null;
  status: AuthStatus;
  error: string | null;
  refreshUser: () => Promise<void>;
  selectWorkspace: (workspaceId: string) => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  register: (fullName: string, email: string, password: string) => Promise<void>;
  logout: (allSessions?: boolean) => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);
const SELECTED_WORKSPACE_KEY = "autowok.selected-workspace";

function getStoredWorkspace(): string | null {
  try {
    return window.sessionStorage.getItem(SELECTED_WORKSPACE_KEY);
  } catch {
    return null;
  }
}

function storeWorkspace(workspaceId: string | null): void {
  try {
    if (workspaceId) {
      window.sessionStorage.setItem(SELECTED_WORKSPACE_KEY, workspaceId);
    } else {
      window.sessionStorage.removeItem(SELECTED_WORKSPACE_KEY);
    }
  } catch {
    return;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedWorkspace, setSelectedWorkspace] = useState<Workspace | null>(
    null,
  );
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [error, setError] = useState<string | null>(null);

  const loadUser = useCallback(async () => {
    const selectedId = getStoredWorkspace();

    try {
      const query = selectedId
        ? `?workspace_id=${encodeURIComponent(selectedId)}`
        : "";
      let data: CurrentUser;
      try {
        data = await apiRequest<CurrentUser>(`/auth/me${query}`);
      } catch (loadError) {
        if (!(loadError instanceof ApiError) || loadError.status !== 404) {
          throw loadError;
        }
        storeWorkspace(null);
        data = await apiRequest<CurrentUser>("/auth/me");
      }

      const chosen =
        data.selected_workspace ??
        data.workspaces.find((workspace) => workspace.id === selectedId) ??
        data.workspaces[0] ??
        null;
      setUser(data.user);
      setError(null);
      setWorkspaces(data.workspaces);
      setSelectedWorkspace(chosen);
      if (chosen) {
        storeWorkspace(chosen.id);
      }
      setStatus("authenticated");
    } catch (loadError) {
      if (loadError instanceof ApiError && loadError.status === 401) {
        setUser(null);
        setWorkspaces([]);
        setSelectedWorkspace(null);
        setStatus("unauthenticated");
        return;
      }
      setError(
        loadError instanceof Error
          ? loadError.message
          : "Unable to restore your session.",
      );
      setStatus("unavailable");
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadUser(), 0);
    return () => window.clearTimeout(timer);
  }, [loadUser]);

  useEffect(() => {
    const handleExpiredSession = () => {
      void loadUser();
    };
    window.addEventListener("autowok:session-expired", handleExpiredSession);
    return () =>
      window.removeEventListener(
        "autowok:session-expired",
        handleExpiredSession,
      );
  }, [loadUser]);

  const selectWorkspace = useCallback(
    async (workspaceId: string) => {
      const data = await apiRequest<CurrentUser>(
        `/auth/me?workspace_id=${encodeURIComponent(workspaceId)}`,
      );
      setUser(data.user);
      setWorkspaces(data.workspaces);
      setSelectedWorkspace(data.selected_workspace);
      storeWorkspace(workspaceId);
    },
    [],
  );

  const login = useCallback(
    async (email: string, password: string) => {
      await apiRequest("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      await loadUser();
      router.replace("/dashboard");
    },
    [loadUser, router],
  );

  const register = useCallback(
    async (fullName: string, email: string, password: string) => {
      await apiRequest("/auth/register", {
        method: "POST",
        body: JSON.stringify({
          full_name: fullName,
          email,
          password,
        }),
      });
      await loadUser();
      router.replace("/dashboard");
    },
    [loadUser, router],
  );

  const logout = useCallback(
    async (allSessions = false) => {
      let revoked = false;
      try {
        await apiRequest(allSessions ? "/auth/logout-all" : "/auth/logout", {
          method: "POST",
        });
        revoked = true;
      } catch (logoutError) {
        if (logoutError instanceof ApiError && logoutError.status === 401) {
          revoked = true;
        } else {
          await loadUser();
          throw logoutError;
        }
      }
      if (revoked) {
        setUser(null);
        setWorkspaces([]);
        setSelectedWorkspace(null);
        setStatus("unauthenticated");
        storeWorkspace(null);
      }
      router.replace("/login");
    },
    [loadUser, router],
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      workspaces,
      selectedWorkspace,
      status,
      error,
      refreshUser: loadUser,
      selectWorkspace,
      login,
      register,
      logout,
    }),
    [
      user,
      workspaces,
      selectedWorkspace,
      status,
      error,
      loadUser,
      selectWorkspace,
      login,
      register,
      logout,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider.");
  }
  return context;
}
