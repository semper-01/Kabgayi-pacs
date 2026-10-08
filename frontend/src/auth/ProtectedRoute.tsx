import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "./AuthContext";

export function ProtectedRoute() {
  const { authorization } = useAuth();
  return authorization ? <Outlet /> : <Navigate to="/login" replace />;
}
