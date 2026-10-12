import { Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { AdministratorRoute } from "./auth/AdministratorRoute";
import { ProtectedRoute } from "./auth/ProtectedRoute";
import { PublicRoute } from "./auth/PublicRoute";
import { AppLayout } from "./components/layout/AppLayout";
import { LoginPage } from "./pages/LoginPage";
import { AdministrationPage } from "./pages/AdministrationPage";
import { StudyDetailPage } from "./pages/StudyDetailPage";
import { StudyWorklistPage } from "./pages/StudyWorklistPage";
import { StudyViewerPage } from "./pages/StudyViewerPage";
import "./styles/global.css";

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route element={<PublicRoute />}>
          <Route path="/login" element={<LoginPage />} />
        </Route>
        <Route element={<ProtectedRoute />}>
          <Route element={<AppLayout />}>
            <Route path="/" element={<StudyWorklistPage />} />
            <Route path="/studies/:studyId" element={<StudyDetailPage />} />
            <Route path="/viewer/:studyId" element={<StudyViewerPage />} />
            <Route element={<AdministratorRoute />}>
              <Route path="/admin" element={<AdministrationPage />} />
            </Route>
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  );
}
