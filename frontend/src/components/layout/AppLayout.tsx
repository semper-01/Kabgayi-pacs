import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext";

export function AppLayout() {
  const { logout } = useAuth();

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">K</span>
          <div>
            <p className="brand-hospital">Kabgayi Level 2 Teaching Hospital</p>
            <p className="brand-product">Radiology PACS</p>
          </div>
        </div>
        <nav className="main-nav" aria-label="Main navigation">
          <NavLink to="/" end className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>
            Studies
          </NavLink>
        </nav>
        <button className="button button-quiet logout-button" type="button" onClick={() => void logout()}>
          Sign out
        </button>
      </header>
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  );
}
