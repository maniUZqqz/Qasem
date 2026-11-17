import { api } from "../../../api/client";

/** «تصویر به کد» — همان شکلِ backend/apps/img2code/services.py (item_dict، options، engine_status) */

export type State = "QUEUED" | "RUNNING" | "READY" | "FAILED" | "CANCELLED";
export type Mode = "exact" | "responsive";
export type Lang = "auto" | "fa" | "en";

export type Score = {
  key: string;
  label: string;
  value: number | string;
  display: string;
  verdict: "good" | "ok" | "weak";
  verdict_fa: string;
  hint: string;
};

export type Draft = { project_slug: string; page_id: number; url: string; at: string | null };

export type Item = {
  id: number;
  title: string;
  source_kind: "upload" | "url";
  source_label: string;
  source_url: string;
  mode: Mode;
  mode_label: string;
  lang: Lang;
  lang_label: string;
  width: number;
  state: State;
  state_label: string;
  active: boolean;
  step: string;
  progress: number;
  message: string;
  error: string;
  size: [number, number];
  created_at: string;
  finished_at: string | null;
  scores: Score[];
  warnings: string[];
  draft: Draft | null;
  files: { original: boolean; rendered: boolean; html: boolean; tree: boolean };
  seconds: number | null;
  ocr: string | null;
  queue_position?: number;
  /** «باز کردن در طراحیِ UI»؛ ``path`` وقتی هست که سندِ UI قبلاً ساخته شده (null ⇒ دکمه اول می‌سازد) */
  ui_design?: { path: string | null; label: string } | null;
};

export type Options = {
  modes: { key: Mode; label: string; hint: string }[];
  langs: { key: Lang; label: string }[];
  widths: { key: number; label: string }[];
  limits: { max_upload_mb: number; max_megapixels: number; history: number };
};

export type Engine = { ready: boolean; ocr: boolean; url_ok: boolean; compare_ok: boolean; version: string; messages: string[] };

export type Overview = {
  items: Item[];
  options: Options;
  engine: Engine;
  can_draft: boolean;
  steps: { key: string; label: string }[];
};

export type Code = { html: string; css: string; tree: string; truncated: boolean };
export type Target = { slug: string; name: string; pages: number };
export type DraftResult = {
  project_slug: string;
  page_id: number;
  url: string;
  created_project: boolean;
  warnings: string[];
  stats: Record<string, number>;
  item: Item;
};

export type UiDesignResult = { doc_id: number; url: string; created: boolean; warnings: string[]; stats: Record<string, number>; item: Item };

export type StoreRow = { id: number; name: string };

const P = (store: string | number) => `/stores/${store}/image-to-code/`;

export const i2cApi = {
  // /stores/ صفحه‌بندی‌شده است ({results}) ولی گاهی آرایهٔ ساده؛ هر دو را بپذیر
  stores: () => api.get<StoreRow[] | { results: StoreRow[] }>("/stores/").then((r) => (Array.isArray(r.data) ? r.data : (r.data.results ?? []))),
  overview: (store: string | number) => api.get<Overview>(P(store)).then((r) => r.data),
  get: (store: string | number, id: number) => api.get<{ item: Item }>(`${P(store)}${id}/`).then((r) => r.data.item),
  createUpload: (store: string | number, file: File, body: { mode: Mode; lang: Lang; title: string }) => {
    const fd = new FormData();
    fd.append("image", file);
    fd.append("mode", body.mode);
    fd.append("lang", body.lang);
    if (body.title) fd.append("title", body.title);
    return api.post<{ item: Item }>(P(store), fd).then((r) => r.data.item);
  },
  createUrl: (store: string | number, body: { url: string; mode: Mode; lang: Lang; width: number; dom_text: boolean; title: string }) =>
    api.post<{ item: Item }>(P(store), body).then((r) => r.data.item),
  remove: (store: string | number, id: number) => api.delete(`${P(store)}${id}/`),
  cancel: (store: string | number, id: number) => api.post<{ item: Item }>(`${P(store)}${id}/cancel/`).then((r) => r.data.item),
  again: (store: string | number, id: number, mode: Mode) => api.post<{ item: Item }>(`${P(store)}${id}/again/`, { mode }).then((r) => r.data.item),
  code: (store: string | number, id: number) => api.get<Code>(`${P(store)}${id}/code/`).then((r) => r.data),
  blob: (store: string | number, id: number, name: string) => api.get<Blob>(`${P(store)}${id}/files/${name}`, { responseType: "blob" }).then((r) => r.data),
  targets: (store: string | number, id: number) => api.get<{ targets: Target[] }>(`${P(store)}${id}/site-targets/`).then((r) => r.data.targets),
  siteDraft: (store: string | number, id: number, project: string) =>
    api.post<DraftResult>(`${P(store)}${id}/site-draft/`, { project }).then((r) => r.data),
  uiDesign: (store: string | number, id: number) => api.post<UiDesignResult>(`${P(store)}${id}/ui-design/`, {}).then((r) => r.data),
};

/** دانلودِ یک فایل با ورودِ کاربر (لینکِ ساده توکن را نمی‌فرستد). */
export async function downloadFile(store: string | number, id: number, name: string, saveAs: string) {
  const blob = await i2cApi.blob(store, id, name);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = saveAs;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 4000);
}
