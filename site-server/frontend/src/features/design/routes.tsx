import { Navigate, Route, Routes } from "react-router-dom";

import { PageGate } from "../panel/FlagsContext";
import DocEditor from "./DocEditor";
import { DesignGuidePage, DesignHomePage, DesignListPage } from "./DesignPages";
import PresenterPage from "./PresenterPage";
import UiEditor from "./UiEditor";

/** «استودیوی طراحی»: /stores/:id/design/… — هر صفحه پشتِ کلیدِ خودش در registry.ts است. */
export default function DesignRoutes() {
  return (
    <Routes>
      <Route index element={<PageGate k="design_home"><DesignHomePage /></PageGate>} />
      <Route path="catalog" element={<PageGate k="design_catalog"><DesignListPage kind="catalog" /></PageGate>} />
      <Route path="catalog/:docId" element={<PageGate k="design_catalog"><DocEditor kind="catalog" /></PageGate>} />
      <Route path="deck" element={<PageGate k="design_deck"><DesignListPage kind="deck" /></PageGate>} />
      <Route path="deck/:docId" element={<PageGate k="design_deck"><DocEditor kind="deck" /></PageGate>} />
      <Route path="deck/:docId/present" element={<PageGate k="design_deck"><PresenterPage /></PageGate>} />
      <Route path="ui" element={<PageGate k="design_ui"><DesignListPage kind="ui" /></PageGate>} />
      <Route path="ui/:docId" element={<PageGate k="design_ui"><UiEditor /></PageGate>} />
      <Route path="guide" element={<PageGate k="design_guide"><DesignGuidePage /></PageGate>} />
      <Route path="*" element={<Navigate to="." replace />} />
    </Routes>
  );
}
