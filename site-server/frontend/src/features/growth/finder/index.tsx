import { Route, Routes } from "react-router-dom";

import { PageGate } from "../../panel/FlagsContext";
import FinderLayout from "./FinderLayout";
import DraftsPage from "./pages/DraftsPage";
import MissionsPage from "./pages/MissionsPage";
import PipelinePage from "./pages/PipelinePage";
import ResultsPage from "./pages/ResultsPage";

/** «مشتری‌یاب» - mounted at /growth/finder/* by `features/growth/index.tsx`; each page has its own admin switch (panel registry). */
export default function FinderRoutes() {
  return (
    <Routes>
      <Route element={<FinderLayout />}>
        <Route index element={<PageGate k="growth_finder"><MissionsPage /></PageGate>} />
        <Route path="results" element={<PageGate k="growth_finder_results"><ResultsPage /></PageGate>} />
        <Route path="pipeline" element={<PageGate k="growth_finder_pipeline"><PipelinePage /></PageGate>} />
        <Route path="drafts" element={<PageGate k="growth_finder_drafts"><DraftsPage /></PageGate>} />
      </Route>
    </Routes>
  );
}
