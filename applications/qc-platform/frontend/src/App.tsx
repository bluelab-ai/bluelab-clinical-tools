import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "./contexts/AuthContext";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import QCHomePage from "./pages/QCHomePage";
import TFLListingQCPage from "./pages/TFLListingQCPage";
import InnerTableQCPage from "./pages/InnerTableQCPage";
import ProtocolTableQCPage from "./pages/ProtocolTableQCPage";
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
                <QCHomePage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/qc/table-listing-cross"
            element={
              <ProtectedRoute>
                <TFLListingQCPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/qc/table-internal"
            element={
              <ProtectedRoute>
                <InnerTableQCPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/qc/protocol-table"
            element={
              <ProtectedRoute>
                <ProtocolTableQCPage />
              </ProtectedRoute>
            }
          />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
