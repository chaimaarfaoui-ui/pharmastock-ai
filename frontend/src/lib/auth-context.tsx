"use client";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { auth, tokenStore, type User } from "./api";

interface AuthState { user: User | null; loading: boolean; logout: () => void; refreshUser: () => Promise<void> }
const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const refreshUser = useCallback(async () => {
    if (!tokenStore.get()) { setUser(null); setLoading(false); return; }
    try { setUser(await auth.me()); } catch { setUser(null); }
    setLoading(false);
  }, []);

  useEffect(() => { void refreshUser(); }, [refreshUser]);

  const logout = useCallback(() => { auth.logout(); setUser(null); }, []);
  return <Ctx.Provider value={{ user, loading, logout, refreshUser }}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth must be used inside AuthProvider");
  return v;
}
