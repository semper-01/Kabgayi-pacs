import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "./AuthContext";

export function PublicRoute() {
  const { authorization } = useAuth();
  return authorization ? <Navigate to="/" replace /> : <Outlet />;
}
