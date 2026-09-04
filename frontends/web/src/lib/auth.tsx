import {
  createContext, useContext, useEffect, useState, type ReactNode,
} from "react";
import { api, type AuthMe } from "./api";

interface AuthState {
  user: AuthMe | null;
  loading: boolean;
  businessId: string | null;
  setBusinessId: (id: string | null) => void;
  refresh: () => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthMe | null>(null);
  const [loading, setLoading] = useState(true);
  const [businessId, setBusinessIdState] = useState<string | null>(
    () => localStorage.getItem("business_id")
  );

  async function refresh() {
    setLoading(true);
    try {
      const me = await api.me();
      setUser(me);
      if (me.businesses.length === 1) {
        setBusinessIdState(me.businesses[0]);
      } else if (businessId && !me.businesses.includes(businessId)) {
        setBusinessIdState(null);
      }
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }

  function setBusinessId(id: string | null) {
    if (id) localStorage.setItem("business_id", id);
    else localStorage.removeItem("business_id");
    setBusinessIdState(id);
  }

  function logout() {
    document.cookie = "chatbot_email=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/";
    localStorage.removeItem("business_id");
    setUser(null);
    setBusinessIdState(null);
  }

  useEffect(() => { refresh(); }, []);

  return (
    <AuthContext.Provider value={{ user, loading, businessId, setBusinessId, refresh, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

export function AdminGuard({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (user?.is_admin) return <>{children}</>;
  return null;
}
