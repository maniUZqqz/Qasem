/**
 * Harness for the real-browser check of the new panel pages (design sources, style picker, 21st browser).
 * The REAL components run in Chromium; axios is wired to `window.mock_api`, a Python function that answers with the real Django views
 * (apps/projects/browser_checks/check_panel_pages.py).  Nothing here ships to the panel.
 */
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";

import { api } from "../../src/api/client";
import C21stBrowser from "../../src/features/tools/studio/C21stBrowser";
import DesignSourcesPage from "../../src/features/tools/studio/DesignSourcesPage";
import { StylePicker } from "../../src/features/tools/studio/builder/designKit";
import type { ThemeOptions, ThemeT } from "../../src/features/tools/studio/builder/types";

declare global {
  interface Window {
    mock_api: (method: string, url: string, params: unknown, data: unknown) => Promise<{ status: number; data: unknown; b64?: string }>;
    __added: string[];
    __applied: string[];
    __view: string;
    __opts: ThemeOptions;
    __slug: string;
  }
}

api.defaults.adapter = async (config) => {
  const res = await window.mock_api((config.method ?? "get").toLowerCase(), `${config.baseURL ?? ""}${config.url ?? ""}`, config.params ?? null, config.data ? JSON.parse(String(config.data)) : null);
  let data: unknown = res.data;
  if (res.b64 !== undefined) {
    const bin = atob(res.b64);
    data = new Blob([Uint8Array.from(bin, (c) => c.charCodeAt(0))], { type: "image/webp" });
  }
  const out = { data, status: res.status, statusText: String(res.status), headers: {}, config, request: {} };
  if (res.status >= 400) {
    const err = Object.assign(new Error("Request failed with status code " + res.status), { isAxiosError: true, response: out, config });
    throw err;
  }
  return out;
};

function Picker() {
  const [theme, setTheme] = useState<ThemeT>({ colors: window.__opts.styles?.[0]?.theme.colors ?? ({} as never), font_body: "vazirmatn", font_head: "vazirmatn", button: "round", radius: 14, width: 1120 } as ThemeT);
  return (
    <div style={{ maxWidth: 420 }}>
      <StylePicker slug={window.__slug} theme={theme} doc={{ v: 1, blocks: [] } as never} target="page" options={window.__opts} onApply={(t) => { window.__applied.push(t.style ?? ""); setTheme(t); }} />
    </div>
  );
}

function App() {
  window.__added = [];
  window.__applied = [];
  if (window.__view === "sources") return <MemoryRouter><DesignSourcesPage /></MemoryRouter>;
  if (window.__view === "picker") return <Picker />;
  return (
    <div style={{ maxWidth: 520 }}>
      <C21stBrowser mode="manual" slug={window.__slug} theme={{ colors: {} } as ThemeT} onAddC21={(key) => { window.__added.push(key); }} onAddNearest={() => undefined} />
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
