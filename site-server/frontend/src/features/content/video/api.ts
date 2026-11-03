import { api } from "../../../api/client";
import type { ToolInfo } from "../ToolPicker";

/** API ِ ادیتورِ ویدیو — همان شکلِ backend/apps/content/views_editing.py و views_timeline.py */

export type Finding = { what: string; note: string; value: number };
export type Param = string | number | boolean;

export type PlanOp = {
  tool: string;
  title: string;
  params: Record<string, Param>;
  reason: string;
  notes: string[];
};

/** یک کارِ قابل‌ویرایش در فهرست (تیک، تنظیمات، برداشتن) */
export type EditableOp = PlanOp & { on: boolean };

export type AiInfo = {
  asked: boolean;
  ok: boolean;
  via: "node" | "api" | "";
  model: string;
  fell_back: boolean;
  fallback_reason: string;
  error_code: string;
  error: string;
  used_fallback_plan?: boolean;
  kept_previous?: boolean;
};

export type Plan = {
  mode: string;
  ai: AiInfo | null;
  operations: PlanOp[];
  refusals: string[];
  findings: Finding[];
  habits: string[];
};

export type MediaItem = {
  ref: string;
  title: string;
  kind: "video" | "image" | "audio";
  source: string;
  duration: number;
  has_audio: boolean;
  width: number;
  height: number;
  url: string;
  auth: boolean;
  proxy: "ready" | "needed" | "not_needed";
  proxy_url: string | null;
};

export type Bin = { videos: MediaItem[]; audio: MediaItem[]; images: MediaItem[] };

export type ProjectRow = {
  id: number;
  title: string;
  state: "DRAFT" | "RENDERING" | "READY" | "FAILED";
  error: string;
  render_info: { seconds?: number; bytes?: number; quality?: string; refusals?: string[]; program_tools?: string[]; size?: string };
  output_url: string | null;
  updated_at: string;
};

export type Check = { ok: boolean; error: string; length?: number; gaps?: { start: number; end: number }[]; size?: string };

const base = (store: string) => `/stores/${store}/editor`;

export const videoApi = {
  tools: (store: string) => api.get<{ tools: ToolInfo[] }>(`/stores/${store}/videos/`).then((r) => r.data.tools),
  bin: (store: string) => api.get<Bin>(`${base(store)}/bin/`).then((r) => r.data),
  proxy: (store: string, ref: string) =>
    api.post<{ job_id: number | null; proxy: string; proxy_url?: string }>(`${base(store)}/proxy/`, { ref }).then((r) => r.data),
  subtitles: (store: string, ref: string) =>
    api.post<{ lines: { start: number; end: number; text: string }[] }>(`${base(store)}/subtitles/`, { ref }).then((r) => r.data.lines),
  projects: (store: string) => api.get<{ projects: ProjectRow[] }>(`${base(store)}/projects/`).then((r) => r.data.projects),
  createProject: (store: string, title: string, data: unknown) =>
    api.post<{ project: ProjectRow & { data: unknown }; check: Check | null }>(`${base(store)}/projects/`, { title, data }).then((r) => r.data),
  project: (store: string, id: number) =>
    api.get<{ project: ProjectRow & { data: unknown }; check: Check | null }>(`${base(store)}/projects/${id}/`).then((r) => r.data),
  saveProject: (store: string, id: number, body: { title?: string; data?: unknown }) =>
    api.put<{ project: ProjectRow; check: Check | null }>(`${base(store)}/projects/${id}/`, body).then((r) => r.data),
  deleteProject: (store: string, id: number) => api.delete(`${base(store)}/projects/${id}/`),
  render: (store: string, id: number, quality: "draft" | "final") =>
    api.post<{ job_id: number }>(`${base(store)}/projects/${id}/render/`, { quality }).then((r) => r.data),
};
