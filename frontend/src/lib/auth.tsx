import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, currentUserId, setCurrentUserId } from "./api";
import type { Persona } from "./types";

interface Auth {
  user: Persona | null;
  ready: boolean;
  signIn: (id: string) => Promise<void>;
  signOut: () => void;
  can: (what: Capability) => boolean;
}

export type Capability = "approve" | "see_all" | "observe" | "request" | "negotiate";

const CAPS: Record<Capability, string[]> = {
  approve: ["coordinator"],
  see_all: ["coordinator", "hod", "dean"],
  observe: ["coordinator", "hod", "dean"],
  request: ["faculty", "hod", "guest_faculty", "lab_incharge", "student", "exam_cell", "coordinator"],
  negotiate: ["faculty", "hod", "guest_faculty"],
};

const AuthContext = createContext<Auth | null>(null);

/** Mock sign-in: the backend trusts the X-User header. Swap for the college
 * OIDC flow; the server already makes every authorisation decision. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Persona | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // Mock-auth convenience for demos: ?as=F-101 signs in as that person.
    const params = new URLSearchParams(window.location.search);
    const as = params.get("as");
    if (as) {
      params.delete("as");
      const rest = params.toString();
      window.history.replaceState(null, "", window.location.pathname + (rest ? `?${rest}` : ""));
      api
        .login(as)
        .then((p) => {
          setCurrentUserId(p.id);
          setUser(p);
        })
        .catch(() => setCurrentUserId(null))
        .finally(() => setReady(true));
      return;
    }
    if (!currentUserId()) {
      setReady(true);
      return;
    }
    api
      .me()
      .then(setUser)
      .catch(() => setCurrentUserId(null))
      .finally(() => setReady(true));
  }, []);

  const signIn = useCallback(async (id: string) => {
    const p = await api.login(id);
    setCurrentUserId(p.id);
    setUser(p);
  }, []);

  const signOut = useCallback(() => {
    setCurrentUserId(null);
    setUser(null);
  }, []);

  const can = useCallback((what: Capability) => !!user && CAPS[what].includes(user.role), [user]);

  const value = useMemo(() => ({ user, ready, signIn, signOut, can }), [user, ready, signIn, signOut, can]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): Auth {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
