/**
 * Harness for the real-browser check of «تصویر به کد» (backend/apps/img2code/tests_browser.py).
 * Nothing here ships to the panel: it renders the real page with the real CSS; axios answers through `window.mock_api`
 * (a Python function that calls the real Django views with the test client).
 */
import { createRoot } from "react-dom/client";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

import { api } from "../../../src/api/client";
import ImageToCodePage from "../../../src/features/tools/img2code/ImageToCodePage";
import "../../../src/index.css";

declare global {
  interface Window {
    mock_api: (method: string, url: string, params: unknown, data: unknown) => Promise<{ status: number; data: unknown; b64?: string; ctype?: string }>;
  }
}

async function packFormData(fd: FormData) {
  const fields: Record<string, string> = {};
  const files: Record<string, { name: string; type: string; b64: string }> = {};
  for (const [k, v] of fd.entries()) {
    if (typeof v === "string") fields[k] = v;
    else {
      const buf = new Uint8Array(await v.arrayBuffer());
      let bin = "";
      for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000));
      files[k] = { name: v.name, type: v.type, b64: btoa(bin) };
    }
  }
  return { __multipart: true, fields, files };
}

api.defaults.adapter = async (config) => {
  let body: unknown = null;
  if (config.data instanceof FormData) body = await packFormData(config.data);
  else if (config.data) body = JSON.parse(String(config.data));
  const res = await window.mock_api((config.method ?? "get").toLowerCase(), `${config.baseURL ?? ""}${config.url ?? ""}`, config.params ?? null, body);
  let data: unknown = res.data;
  if (res.b64 !== undefined) {
    const bin = atob(res.b64);
    data = new Blob([Uint8Array.from(bin, (c) => c.charCodeAt(0))], { type: res.ctype || "application/octet-stream" });
  }
  const out = { data, status: res.status, statusText: String(res.status), headers: {}, config, request: {} };
  if (res.status >= 400) {
    throw Object.assign(new Error("Request failed with status code " + res.status), { isAxiosError: true, response: out, config });
  }
  return out;
};

function Where() {
  const loc = useLocation();
  return <div data-testid="routed">{loc.pathname}</div>;
}

const q = new URLSearchParams(location.search);
document.documentElement.dataset.theme = q.get("theme") || "light";
document.documentElement.setAttribute("dir", "rtl");
document.documentElement.setAttribute("lang", "fa");

createRoot(document.getElementById("root")!).render(
  <MemoryRouter initialEntries={[`/tools/image-to-code?store=${q.get("store") || ""}`]}>
    <div style={{ padding: 16 }}>
      <Routes>
        <Route path="/tools/image-to-code" element={<ImageToCodePage />} />
        <Route path="*" element={<Where />} />
      </Routes>
    </div>
  </MemoryRouter>,
);
