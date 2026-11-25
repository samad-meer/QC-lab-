import { Navigate, Route, Routes } from "react-router-dom";
import { homeFor, LAB_REGISTER_VIEWS, useAuth } from "./auth";
import Layout from "./components/Layout";
import { NotificationsProvider } from "./components/Notifications";
import { ToastProvider } from "./components/Toast";
import Analytics from "./pages/admin/Analytics";
import CertificateTemplates from "./pages/admin/CertificateTemplates";
import NotificationRules from "./pages/admin/NotificationRules";
import Products from "./pages/admin/Products";
import CheckpointKinds from "./pages/admin/CheckpointKinds";
import BatchDetailPage from "./pages/BatchDetail";
import Batches from "./pages/Batches";
import ProductDetail from "./pages/ProductDetail";
import AuditTrail from "./pages/admin/AuditTrail";
import QualityRules from "./pages/admin/QualityRules";
import SampleSources from "./pages/admin/SampleSources";
import Sections from "./pages/admin/Sections";
import Settings from "./pages/admin/Settings";
import SignIns from "./pages/admin/SignIns";
import Roles from "./pages/admin/Roles";
import Users from "./pages/admin/Users";
import Workflows from "./pages/admin/Workflows";
import CertificatePage from "./pages/CertificatePage";
import Dashboard from "./pages/Dashboard";
import AssignWork from "./pages/AssignWork";
import FrontDesk from "./pages/FrontDesk";
import Login from "./pages/Login";
import Profile from "./pages/Profile";
import Queue from "./pages/Queue";
import Review from "./pages/Review";
import SampleDetailPage from "./pages/SampleDetailPage";
import Samples from "./pages/Samples";
import Tasks from "./pages/Tasks";
import ChangePassword from "./pages/ChangePassword";
import Worklist from "./pages/Worklist";
import LabRecordPage from "./pages/lab/LabRecord";
import LabRegisterPage from "./pages/lab/LabRegister";
import InvestigationPage from "./pages/quality/InvestigationPage";
import NewInvestigation from "./pages/quality/NewInvestigation";
import ReportDocumentPage from "./pages/reports/ReportDocumentPage";
import ReportPage from "./pages/reports/ReportPage";
import ReportsHome from "./pages/reports/ReportsHome";
import type { Permission } from "./types";
import { useTheme } from "./theme";

/** Hides a route the user has no permission for: one key, or any of several. The API enforces it too. */
function Guarded({ need, children }: { need: Permission | Permission[]; children: React.ReactNode }) {
  const { can, user } = useAuth();
  if (!(Array.isArray(need) ? need : [need]).some(can)) return <Navigate to={user ? homeFor(user) : "/"} replace />;
  return <>{children}</>;
}

/** The Reports module, and the one report a page belongs to. */
function ReportGuard({ report, children }: { report: Permission; children: React.ReactNode }) {
  return <Guarded need="report.view"><Guarded need={report}>{children}</Guarded></Guarded>;
}

export default function App() {
  const { user, loading } = useAuth();
  useTheme(); // applies the saved/system theme to <html> before anything renders

  if (loading) {
    return (
      <div style={{ display: "grid", placeItems: "center", minHeight: "100vh" }}>
        <div className="sk" style={{ width: 180, height: 14 }} />
      </div>
    );
  }
  if (!user) {
    return (
      <Routes>
        <Route path="*" element={<Login />} />
      </Routes>
    );
  }
  if (user.must_change_password) return <ChangePassword />;
  return (
    <ToastProvider>
      <NotificationsProvider>
      <Layout>
        <Routes>
          <Route path="/" element={<Navigate to={homeFor(user)} replace />} />
          <Route path="/frontdesk" element={<Guarded need="sample.register"><FrontDesk /></Guarded>} />
          <Route path="/assign" element={<Guarded need="sample.assign"><AssignWork /></Guarded>} />
          <Route path="/worklist" element={<Guarded need="result.enter"><Worklist /></Guarded>} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/queue" element={<Queue />} />
          {/* Everyone has tasks — the server decides what is in them. */}
          <Route path="/tasks" element={<Tasks />} />
          <Route path="/samples" element={<Samples />} />
          <Route path="/batches" element={<Batches />} />
          <Route path="/batches/:id" element={<BatchDetailPage />} />
          <Route path="/products/:id" element={<ProductDetail />} />
          <Route path="/samples/:id" element={<SampleDetailPage />} />
          <Route path="/samples/:id/review" element={<Review />} />
          <Route path="/certificates/:id" element={<CertificatePage />} />
          {/* Everyone has a profile — no permission guard. */}
          <Route path="/profile" element={<Profile />} />
          <Route path="/reports" element={<Guarded need="report.view"><ReportsHome /></Guarded>} />
          {/* A record's history page goes with the report it opens from. */}
          <Route path="/reports/sample-history/:id" element={<ReportGuard report="report.open.sample-register"><ReportDocumentPage key="sample" kind="sample" /></ReportGuard>} />
          <Route path="/reports/batch/:id" element={<ReportGuard report="report.open.batches"><ReportDocumentPage key="batch" kind="batch" /></ReportGuard>} />
          <Route path="/reports/product/:id" element={<ReportGuard report="report.open.product-history"><ReportDocumentPage key="product" kind="product" /></ReportGuard>} />
          <Route path="/reports/:reportKey" element={<Guarded need="report.view"><ReportPage /></Guarded>} />
          <Route path="/investigations/new" element={<Guarded need="investigation.manage"><NewInvestigation /></Guarded>} />
          <Route path="/investigations/:id" element={<InvestigationPage />} />
          {/* Each register is seen with its own permission; the server lists only those and says who may change them. */}
          <Route path="/lab" element={<Guarded need={LAB_REGISTER_VIEWS}><LabRegisterPage /></Guarded>} />
          <Route path="/lab/:register" element={<Guarded need={LAB_REGISTER_VIEWS}><LabRegisterPage /></Guarded>} />
          <Route path="/lab/:register/:id" element={<Guarded need={LAB_REGISTER_VIEWS}><LabRecordPage /></Guarded>} />
          <Route path="/admin/quality-rules" element={<Guarded need="investigation.approve"><QualityRules /></Guarded>} />
          <Route path="/admin/users" element={<Guarded need="user.manage"><Users /></Guarded>} />
          <Route path="/admin/sign-in" element={<Guarded need="user.manage"><SignIns /></Guarded>} />
          <Route path="/admin/roles" element={<Guarded need="role.manage"><Roles /></Guarded>} />
          <Route path="/admin/products" element={<Products />} />
          {/* Test templates were removed: tests are written in each specification's draft. */}
          <Route path="/admin/test-templates" element={<Navigate to="/admin/products" replace />} />
          <Route path="/admin/checkpoint-kinds" element={<Guarded need="product.manage"><CheckpointKinds /></Guarded>} />
          <Route path="/admin/certificate-templates" element={<Guarded need="template.manage"><CertificateTemplates /></Guarded>} />
          <Route path="/admin/notification-rules" element={<Guarded need="notification.manage"><NotificationRules /></Guarded>} />
          <Route path="/admin/workflows" element={<Guarded need="workflow.manage"><Workflows /></Guarded>} />
          <Route path="/admin/audit" element={<Guarded need="audit.view"><AuditTrail /></Guarded>} />
          <Route path="/admin/analytics" element={<Guarded need="audit.view"><Analytics /></Guarded>} />
          <Route path="/admin/sections" element={<Guarded need="config.manage"><Sections /></Guarded>} />
          <Route path="/admin/received-from" element={<Guarded need="config.manage"><SampleSources /></Guarded>} />
          <Route path="/admin/settings" element={<Guarded need="config.manage"><Settings /></Guarded>} />
          <Route path="/admin/lab" element={<Navigate to="/admin/settings" replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
      </NotificationsProvider>
    </ToastProvider>
  );
}
