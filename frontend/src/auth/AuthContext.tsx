import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useNavigate } from "react-router-dom";
import { authenticate } from "../api/auth";
import { setUnauthorizedHandler } from "../api/client";

interface AuthContextValue {
  authorization: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [authorization, setAuthorization] = useState<string | null>(null);
  const navigate = useNavigate();

  const logout = useCallback(() => {
    setAuthorization(null);
    navigate("/login", { replace: true });
  }, [navigate]);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setAuthorization(null);
      navigate("/login", {
        replace: true,
        state: { message: "Your session is no longer valid. Please sign in again." },
      });
    });
    return () => setUnauthorizedHandler(undefined);
  }, [navigate]);

  const login = useCallback(async (username: string, password: string) => {
    const token = await authenticate(username, password);
    setAuthorization(token);
  }, []);

  const value = useMemo(
    () => ({ authorization, login, logout }),
    [authorization, login, logout],
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
