import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "./AuthContext";

export function AdministratorRoute() {
  const { user } = useAuth();
  return user?.account_type === "administrator"
    ? <Outlet />
    : <Navigate to="/" replace />;
}
