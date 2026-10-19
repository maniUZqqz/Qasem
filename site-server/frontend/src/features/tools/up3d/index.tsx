import { Navigate, Route, Routes } from "react-router-dom";

import "./up3d.css";
import { P } from "./api";
import AssetsPage from "./AssetsPage";
import DashboardPage from "./DashboardPage";
import DocsPage from "./DocsPage";
import JobPage from "./JobPage";
import JobsPage from "./JobsPage";
import NewProjectPage from "./NewProjectPage";
import ProjectPage from "./ProjectPage";
import Shell from "./Shell";
import TokenPage from "./TokenPage";
import ViewerPage from "./ViewerPage";
import WorkersPage from "./WorkersPage";

/**
 * «ویدیوی سه‌بعدی» (UpMarket 3D) داخلِ همین پنل.
 *
 * در App.tsx زیرِ Layout سوار می‌شود:  <Route path="/tools/3d/*" element={<Up3dRoutes />} />
 * مسیرها نسبی‌اند؛ لینک‌های داخلی از `P` (api.ts) ساخته می‌شوند که روی همان /tools/3d می‌نشیند.
 */
export default function Up3dRoutes() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<DashboardPage />} />
        <Route path="new" element={<NewProjectPage />} />
        <Route path="p/:id" element={<ProjectPage />} />
        <Route path="jobs" element={<JobsPage />} />
        <Route path="jobs/:id" element={<JobPage />} />
        <Route path="jobs/:id/viewer" element={<ViewerPage />} />
        <Route path="assets" element={<AssetsPage />} />
        <Route path="workers" element={<WorkersPage />} />
        <Route path="docs" element={<DocsPage />} />
        <Route path="token" element={<TokenPage />} />
        <Route path="*" element={<Navigate to={P.dashboard()} replace />} />
      </Route>
    </Routes>
  );
}
