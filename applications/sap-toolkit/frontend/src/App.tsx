import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "./contexts/AuthContext";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import HomePage from "./pages/HomePage";
import Phase1Page from "./pages/Phase1Page";
import CatalogEditorPage from "./pages/CatalogEditorPage";
import Phase2Page from "./pages/Phase2Page";
import PromptsEditorPage from "./pages/PromptsEditorPage";
import ReviewEditorPage from "./pages/ReviewEditorPage";
import ProtectedRoute from "./components/ProtectedRoute";

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route
            path="/home"
            element={
              <ProtectedRoute>
                <HomePage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/project/:id/phase1"
            element={
              <ProtectedRoute>
                <Phase1Page />
              </ProtectedRoute>
            }
          />
          <Route
            path="/project/:id/catalog"
            element={
              <ProtectedRoute>
                <CatalogEditorPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/project/:id/prompts"
            element={
              <ProtectedRoute>
                <PromptsEditorPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/project/:id/phase2"
            element={
              <ProtectedRoute>
                <Phase2Page />
              </ProtectedRoute>
            }
          />
          <Route
            path="/project/:id/review"
            element={
              <ProtectedRoute>
                <ReviewEditorPage />
              </ProtectedRoute>
            }
          />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
