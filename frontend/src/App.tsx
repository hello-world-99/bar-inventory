import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { Layout } from "./components/Layout";
import type { Permission } from "./lib/types";
import { DashboardPage } from "./pages/DashboardPage";
import { DocumentsPage } from "./pages/documents/DocumentsPage";
import { InventoryCountPage } from "./pages/inventory/InventoryCountPage";
import { InventoryListPage } from "./pages/inventory/InventoryListPage";
import { JournalPage } from "./pages/JournalPage";
import { LocationsPage } from "./pages/LocationsPage";
import { LoginPage } from "./pages/LoginPage";
import { ProductsPage } from "./pages/ProductsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { StockPage } from "./pages/StockPage";
import { UsersPage } from "./pages/UsersPage";

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const { t } = useTranslation();
  const location = useLocation();
  if (loading) return <div className="grid min-h-screen place-items-center text-sm text-zinc-500">{t("common.loading")}</div>;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <>{children}</>;
}

function RequirePerm({ perm, children }: { perm: Permission; children: ReactNode }) {
  const { can } = useAuth();
  return can(perm) ? <>{children}</> : <Navigate to="/" replace />;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="stock" element={<StockPage />} />
        <Route path="receipts" element={<DocumentsPage key="receipt" type="receipt" />} />
        <Route path="write-offs" element={<DocumentsPage key="write_off" type="write_off" />} />
        <Route path="transfers" element={<DocumentsPage key="transfer" type="transfer" />} />
        <Route path="inventory" element={<InventoryListPage />} />
        <Route path="inventory/:id" element={<InventoryCountPage />} />
        <Route path="journal" element={<JournalPage />} />
        <Route path="products" element={<ProductsPage />} />
        <Route path="locations" element={<LocationsPage />} />
        <Route
          path="users"
          element={
            <RequirePerm perm="manage_users">
              <UsersPage />
            </RequirePerm>
          }
        />
        <Route
          path="settings"
          element={
            <RequirePerm perm="manage_settings">
              <SettingsPage />
            </RequirePerm>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
