import { Navigate, Route, Routes } from "react-router-dom";

import { BASE } from "./api";
import AiHomePage from "./AiHomePage";
import AiProposalPage from "./AiProposalPage";
import AiSettingsPage from "./AiSettingsPage";
import AppDetailPage from "./AppDetailPage";
import BackendPage from "./BackendPage";
import FieldEditPage from "./FieldEditPage";
import FilesPage from "./FilesPage";
import FrontendPage from "./FrontendPage";
import HistoryPage from "./HistoryPage";
import ImportPage from "./ImportPage";
import ImportReportPage from "./ImportReportPage";
import ModelEditPage from "./ModelEditPage";
import PageEditPage from "./PageEditPage";
import PreviewPage from "./PreviewPage";
import ProjectCreatePage from "./ProjectCreatePage";
import ProjectDetailPage from "./ProjectDetailPage";
import ProjectListPage from "./ProjectListPage";
import RouteEditPage from "./RouteEditPage";
import RoutesPage from "./RoutesPage";
import SettingsPage from "./SettingsPage";
import SharedEditPage from "./SharedEditPage";
import StudioShell, { ProjectShell } from "./shell";
import ViewEditPage from "./ViewEditPage";

/**
 * سایت‌ساز — در App.tsx زیرِ `/tools/studio/*` و داخلِ Layout سوار می‌شود:
 *   <Route path="/tools/studio/*" element={<StudioRoutes />} />
 * همهٔ مسیرها نسبی‌اند؛ لینک‌های داخلِ صفحه‌ها با `pUrl()` از api.ts ساخته می‌شوند.
 */
export default function StudioRoutes() {
  return (
    <Routes>
      <Route element={<StudioShell />}>
        <Route index element={<ProjectListPage />} />
        <Route path="new" element={<ProjectCreatePage />} />
        <Route path="import" element={<ImportPage />} />
        <Route path="ai/settings" element={<AiSettingsPage />} />
        <Route path="p/:slug" element={<ProjectShell />}>
          <Route index element={<ProjectDetailPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="backend" element={<BackendPage />} />
          <Route path="app/:pk" element={<AppDetailPage />} />
          <Route path="model/:pk" element={<ModelEditPage />} />
          <Route path="field/:pk" element={<FieldEditPage />} />
          <Route path="view/:pk" element={<ViewEditPage />} />
          <Route path="urls" element={<RoutesPage />} />
          <Route path="urls/:pk" element={<RouteEditPage />} />
          <Route path="frontend" element={<FrontendPage />} />
          <Route path="page/:pk" element={<PageEditPage />} />
          <Route path="shared/:kind" element={<SharedEditPage />} />
          <Route path="files" element={<FilesPage />} />
          <Route path="history" element={<HistoryPage />} />
          <Route path="preview" element={<PreviewPage />} />
          <Route path="ai" element={<AiHomePage />} />
          <Route path="ai/proposal/:pk" element={<AiProposalPage />} />
          <Route path="import-report" element={<ImportReportPage />} />
        </Route>
        <Route path="*" element={<Navigate to={BASE} replace />} />
      </Route>
    </Routes>
  );
}
