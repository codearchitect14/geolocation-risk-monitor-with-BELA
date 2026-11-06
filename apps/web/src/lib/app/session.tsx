"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "@/lib/api";

export type Role = "viewer" | "analyst" | "manager" | "tenant_admin" | "finance_analyst" | "platform_admin";

export type Me = {
  kind: "user" | "api_key";
  id: string;
  role: Role;
  tenant_id: string | null;
  email: string;
  display_name: string;
  mfa_enabled: boolean;
  permissions: string[];
  notifications?: { email: boolean };
};

const TENANT_RANK: Record<string, number> = { viewer: 0, analyst: 1, manager: 2, tenant_admin: 3 };

/** True when the role is a tenant role at or above `min`. Platform roles never act inside a tenant. */
export function atLeast(
  role: Role | undefined,
  min: "viewer" | "analyst" | "manager" | "tenant_admin",
): boolean {
  if (!role || !(role in TENANT_RANK)) return false;
  return (TENANT_RANK[role] as number) >= (TENANT_RANK[min] as number);
}

export const isPlatform = (role: Role | undefined) => role === "platform_admin" || role === "finance_analyst";

type Ctx = { me: Me; reload: () => Promise<void> };
const SessionContext = createContext<Ctx | null>(null);

export function useSession(): Ctx {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession used outside the application shell");
  return ctx;
}

/** Loads the signed-in user. Without a session the visitor is sent to sign in. */
export function SessionProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const load = useCallback(async () => {
    try {
      setMe(await api<Me>("/auth/me"));
    } catch {
      setMe(null);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    if (me === null) window.location.href = "/login";
  }, [me]);
  const value = useMemo(() => (me ? { me, reload: load } : null), [me, load]);
  if (!value) {
    return (
      <div className="grid min-h-dvh place-items-center text-slate-600" role="status">
        Checking your session
      </div>
    );
  }
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}
