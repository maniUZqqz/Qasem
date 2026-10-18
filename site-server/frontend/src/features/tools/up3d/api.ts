import axios from "axios";

import { api, errorMessage } from "../../../api/client";
import { fa } from "../../../components/ui";
import type {
  Asset,
  Catalog,
  Dashboard,
  EditResponse,
  Estimate,
  Issue,
  Job,
  JobKind,
  Project,
  ProjectLite,
  SceneDoc,
  SceneResponse,
  Status,
  Template,
  TokenInfo,
  UploadResult,
  Worker,
} from "./types";

/**
 * دسترسی به بک‌اندِ «ویدیوی سه‌بعدی».
 *
 * همهٔ JSON زیرِ `/api/v1/up3d/` است و با همان `api` (JWT ِ پنل) می‌رود.
 * فایل‌هایی که مرورگر خودش بار می‌کند — ویدئو، پوستر، GLB، تصویرِ دارایی — زیرِ `/3d/` ِ جنگو/nginx
 * می‌مانند و سرآیند نمی‌خواهند؛ نشانی‌شان در خودِ JSON می‌آید (`files`, `poster`).
 */

/** جایی که index.tsx سوار می‌شود (App.tsx: `/tools/3d/*`). لینک‌های داخلی همه از همین ساخته می‌شوند. */
export const BASE = "/tools/3d";

export const P = {
  dashboard: () => BASE,
  newProject: () => `${BASE}/new`,
  project: (id: number | string) => `${BASE}/p/${id}`,
  jobs: () => `${BASE}/jobs`,
  job: (id: number | string) => `${BASE}/jobs/${id}`,
  viewer: (id: number | string) => `${BASE}/jobs/${id}/viewer`,
  assets: () => `${BASE}/assets`,
  workers: () => `${BASE}/workers`,
  docs: () => `${BASE}/docs`,
  token: () => `${BASE}/token`,
};

/** تصویر/پیش‌نمایشِ دارایی‌ها — عمومی، زیرِ /3d/ (urls.py). */
export const ASSET_FILE = "/3d/asset-file";

export type NewProjectBody = {
  brief: Record<string, unknown>;
  mode: "ai" | "template";
  template: string;
  title?: string;
};

export const up3d = {
  dashboard: () => api.get<Dashboard>("/up3d/dashboard/").then((r) => r.data),
  status: () => api.get<Status>("/up3d/status/").then((r) => r.data),
  templates: () => api.get<Template[]>("/up3d/templates/").then((r) => r.data),
  catalog: () => api.get<Catalog>("/up3d/catalog/").then((r) => r.data),

  projects: () => api.get<ProjectLite[]>("/up3d/video-projects/").then((r) => r.data),
  createProject: (body: NewProjectBody) =>
    api.post<{ project: ProjectLite; job: Job }>("/up3d/video-projects/", body).then((r) => r.data),
  project: (id: number | string) => api.get<Project>(`/up3d/video-projects/${id}/`).then((r) => r.data),
  deleteProject: (id: number | string) => api.delete(`/up3d/video-projects/${id}/`),
  plan: (id: number | string, body: { mode: "ai" | "template"; template?: string; brief?: Record<string, unknown> }) =>
    api.post<Job>(`/up3d/video-projects/${id}/plan/`, body).then((r) => r.data),
  scene: (id: number | string, version?: number) =>
    api
      .get<{ version: number | null; document: SceneDoc | null; report: unknown }>(
        `/up3d/video-projects/${id}/scene/`,
        { params: version ? { version } : undefined },
      )
      .then((r) => r.data),
  saveScene: (id: number | string, body: { document: SceneDoc; repair: boolean; source: string; note: string }) =>
    api.put<SceneResponse>(`/up3d/video-projects/${id}/scene/`, body).then((r) => r.data),
  aiEdit: (id: number | string, instruction: string) =>
    api.post<EditResponse>(`/up3d/video-projects/${id}/edit/`, { instruction }).then((r) => r.data),
  /** preview | render | export | contact — همان نام‌های api.py */
  startJob: (id: number | string, action: "preview" | "render" | "export" | "contact", body: Record<string, unknown>) =>
    api.post<Job>(`/up3d/video-projects/${id}/${action}/`, body).then((r) => r.data),
  validate: (document: SceneDoc) =>
    api.post<{ ok: boolean; errors: number; warnings: number; issues: Issue[] }>("/up3d/validate/", { document }).then((r) => r.data),
  estimate: (profile: string, project: number | string) =>
    api.get<Estimate>("/up3d/estimate/", { params: { profile, project } }).then((r) => r.data),

  jobs: (active = false) =>
    api.get<Job[]>("/up3d/jobs/", { params: active ? { active: 1 } : undefined }).then((r) => r.data),
  job: (id: number | string) => api.get<Job>(`/up3d/jobs/${id}/`).then((r) => r.data),
  cancelJob: (id: number | string) => api.post<Job>(`/up3d/jobs/${id}/cancel/`).then((r) => r.data),

  thumbnails: (kind: string, ids?: string[]) =>
    api.post<{ queued: number; message: string }>("/up3d/assets/thumbnails/", { kind, ids }).then((r) => r.data),

  workers: () => api.get<{ workers: Worker[]; server: string }>("/up3d/workers/").then((r) => r.data),
  addWorker: (name: string, profiles: string[]) =>
    api.post<{ worker: Worker; created: boolean; message: string }>("/up3d/workers/", { name, profiles }).then((r) => r.data),
  toggleWorker: (id: number) => api.post<Worker>(`/up3d/workers/${id}/toggle/`).then((r) => r.data),
  /** فایلِ .bat و بستهٔ zip سرآیندِ JWT می‌خواهند؛ پس blob می‌گیریم و خودمان ذخیره می‌کنیم. */
  downloadBat: async (w: Worker) => {
    const { data } = await api.get<Blob>(`/up3d/workers/${w.id}/start-worker.bat`, { responseType: "blob" });
    saveBlob(data, `start-worker-${w.name}.bat`);
  },
  downloadBundle: async () => {
    const { data } = await api.get<Blob>("/up3d/workers/bundle.zip", { responseType: "blob" });
    saveBlob(data, "up3d-worker-bundle.zip");
  },

  upload: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return api.post<UploadResult>("/up3d/upload/", body).then((r) => r.data);
  },
  token: () => api.get<TokenInfo>("/up3d/token/").then((r) => r.data),
};

// ───────────────────────── کمک‌ها

export { fa };

/** ثانیه ⇐ «۳ دقیقه و ۱۰ ثانیه» */
export function dur(sec: number | null | undefined): string {
  if (sec == null || Number.isNaN(sec)) return "—";
  const s0 = Math.max(0, Math.round(sec));
  const h = Math.floor(s0 / 3600);
  const m = Math.floor((s0 % 3600) / 60);
  const s = s0 % 60;
  if (h) return `${fa(h)} ساعت و ${fa(m)} دقیقه`;
  if (m) return `${fa(m)} دقیقه${s && m < 10 ? ` و ${fa(s)} ثانیه` : ""}`;
  return `${fa(s)} ثانیه`;
}

/** تاریخ-ساعتِ کوتاهِ فارسی. */
export function when(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("fa-IR", { dateStyle: "short", timeStyle: "short" });
}

/** «۵ دقیقه پیش» */
export function ago(value: string | null | undefined): string {
  if (!value) return "—";
  const diff = Math.max(0, (Date.now() - new Date(value).getTime()) / 1000);
  if (diff < 60) return "لحظاتی پیش";
  if (diff < 3600) return `${fa(Math.floor(diff / 60))} دقیقه پیش`;
  if (diff < 86400) return `${fa(Math.floor(diff / 3600))} ساعت پیش`;
  return `${fa(Math.floor(diff / 86400))} روز پیش`;
}

/** نامِ فارسیِ دارایی (label از سرور؛ وگرنه name.fa/en؛ وگرنه id). */
export function label(a: Asset | null | undefined): string {
  if (!a) return "—";
  return a.label || a.name?.fa || a.name?.en || a.id;
}

export function desc(a: Asset | null | undefined): string {
  return a?.description?.fa || "";
}

export function thumbUrl(kind: string, a: Asset | null | undefined): string | null {
  return a && a.has_thumbnail ? `${ASSET_FILE}/${kind}/${a.id}/thumbnail.jpg` : null;
}

export function previewUrl(kind: string, a: Asset | null | undefined): string | null {
  return a && a.has_preview ? `${ASSET_FILE}/${kind}/${a.id}/preview.mp4` : null;
}

/** پیامِ خطای خوانا: `error` یا `detail` ِ سرور، وگرنه پیامِ عمومیِ client.ts */
export function errMsg(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const data = err.response?.data as Record<string, unknown> | undefined;
    if (data) {
      if (typeof data.error === "string") return data.error;
      if (typeof data.detail === "string") return data.detail;
      if (Array.isArray(data) && typeof data[0] === "string") return data[0];
      const first = Object.values(data)[0];
      if (typeof first === "string") return first;
      if (Array.isArray(first) && typeof first[0] === "string") return first[0];
    }
  }
  return errorMessage(err);
}

export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 4000);
}

export function clone<T>(x: T): T {
  return JSON.parse(JSON.stringify(x)) as T;
}

/** نوعِ کار ⇐ نامِ اکشن در API (انیمیک/پیش‌نمایش ⇐ preview، بقیه ⇐ render) */
export function actionFor(kind: JobKind, profile?: string): "preview" | "render" | "export" | "contact" {
  if (kind === "render") return profile === "animatic" || profile === "preview" ? "preview" : "render";
  if (kind === "export") return "export";
  return "contact";
}
