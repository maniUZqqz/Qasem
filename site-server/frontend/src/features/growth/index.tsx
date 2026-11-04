import { Navigate, Route, Routes } from "react-router-dom";

import { PageGate } from "../panel/FlagsContext";
import GrowthLayout from "./GrowthLayout";
import CampaignPage from "./pages/CampaignPage";
import DashboardPage from "./pages/DashboardPage";
import DiscoveryPage from "./pages/DiscoveryPage";
import LeadDetailPage from "./pages/LeadDetailPage";
import LeadsPage from "./pages/LeadsPage";
import OutreachPage from "./pages/OutreachPage";
import SettingsPage from "./pages/SettingsPage";
import SuppressionPage from "./pages/SuppressionPage";
import TemplatesPage from "./pages/TemplatesPage";

/**
 * «جذب مشتری» - mounted at /growth/* in App.tsx. Every page sits behind `PageGate` with its key from
 * `features/panel/registry.ts`, so switching a page off in the Django admin works here too.
 */
export default function GrowthRoutes() {
  return (
    <Routes>
      <Route element={<GrowthLayout />}>
        <Route index element={<PageGate k="growth_dashboard"><DashboardPage /></PageGate>} />
        <Route path="discovery" element={<PageGate k="growth_discovery"><DiscoveryPage /></PageGate>} />
        <Route path="leads" element={<PageGate k="growth_leads"><LeadsPage /></PageGate>} />
        <Route path="leads/:id" element={<PageGate k="growth_lead"><LeadDetailPage /></PageGate>} />
        <Route path="outreach" element={<PageGate k="growth_outreach"><OutreachPage /></PageGate>} />
        <Route path="outreach/:id" element={<PageGate k="growth_outreach"><CampaignPage /></PageGate>} />
        <Route path="templates" element={<PageGate k="growth_templates"><TemplatesPage /></PageGate>} />
        <Route path="do-not-contact" element={<PageGate k="growth_suppression"><SuppressionPage /></PageGate>} />
        <Route path="settings" element={<PageGate k="growth_settings"><SettingsPage /></PageGate>} />
        <Route path="*" element={<Navigate to="/growth" replace />} />
      </Route>
    </Routes>
  );
}
