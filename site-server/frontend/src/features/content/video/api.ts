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
  /** استیکرها: "emoji" | "badge" */
  group?: string;
};

export type Bin = { videos: MediaItem[]; audio: MediaItem[]; images: MediaItem[]; stickers: MediaItem[] };

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

// ───────────── کاتالوگِ ادیتورِ حرفه‌ای (GET editor/catalogue/)
export type Choice = { key: string; title: string } & Record<string, unknown>;
/** waiting = سرورِ پردازش ثبت شده ولی الان خاموش است: درخواست در صفِ ماندگار می‌ماند و با روشن شدنش انجام می‌شود (ناموفق نمی‌شود) */
export type CaptionsStatus = { node: boolean; local: boolean; ok: boolean; message: string; waiting?: boolean };
export type ExportPreset = { key: string; title: string; group: string; short: number | null; fps: number | null; codec: string; quality: string; audio_kbps: number; max_seconds: number | null; aspect: string | null };
export type Catalogue = {
  color: {
    sliders: { key: string; min: number; max: number; default: number; step: number; title: string; group: string }[];
    wheels: { key: string; title: string }[];
    curves: { key: string; title: string }[];
    hsl: { key: string; title: string; color: string }[];
    look_amount: { min: number; max: number; default: number };
    looks: { key: string; title: string; params: Record<string, unknown> }[];
    samples: number;
  };
  titles: {
    fonts: Choice[]; templates: Choice[]; animations_in: Choice[]; animations_out: Choice[]; hl_modes: Choice[]; aligns: Choice[]; line2_ratio: number;
  };
  transitions: { legacy: Choice[]; groups: Choice[]; kinds: { key: string; title: string; group: string }[] };
  export: { presets: ExportPreset[]; codecs: Choice[]; qualities: Choice[]; resolutions: number[]; fps: number[]; audio_kbps: number[] };
  easings: Choice[];
  blends: Choice[];
  eq: Choice[];
  ramp_presets: { key: string; title: string; ramp: { p: number; v: number }[] }[];
  captions: CaptionsStatus;
  shapes: { key: string; title: string }[];
  stickers: { key: string; title: string; group: string }[];
  render_where: RenderWhere;
  limits: { max_preview_seconds: number; max_tracks: number; max_clips: number; ramp_steps: number };
  /** ناحیه‌های امنِ پلتفرم‌ها (حاشیه‌ها کسری از قاب)؛ نبودنش ⇒ جایگزینِ داخلی SAFE_ZONES_FALLBACK */
  safe_zones?: { key: string; title: string; hint: string; margins: { top: number; bottom: number; left: number; right: number } }[];
};

export type Waveform = { peaks: number[]; per_second: number; duration: number; silent?: boolean };
export type Filmstrip = { url: string; count: number; interval: number; w: number; h: number; duration: number };
export type Beats = { beats: number[]; bpm: number | null; duration: number };

export type RenderJobRow = {
  id: number; state: string; percent: number; label: string; error: string; preset: string; quality: string; created_at: string; active: boolean;
  /** "node" | "server" | "node:<name>" | "" */
  where?: string;
};
export type ExportRow = {
  job_id: number; url: string; rel: string; preset: string; quality: string; seconds: number; bytes: number; size: string; codec: string; note: string;
  rendered_at: string; where?: "node" | "server"; node?: string; encoder?: string; fallback?: string;
  /** نوعِ خروجی: ویدیو (پیش‌فرض)، GIF، عکسِ یک فریم، فقط صدا؛ و آیا فقط بازهٔ ورودی–خروجی بوده */
  format?: "mp4" | "gif" | "frame" | "audio"; range?: "all" | "inout";
};
export type RenderWhere = { online: boolean; message: string; node: string; nvenc: boolean; gpu?: string };
export type LutRow = { key: string; title: string; size: number; bytes: number; created: number };
export type MatteRow = { key: string; ref: string; s0: number; s1: number; fps: number; node: string; engine: string; bytes: number; created: number; url: string };
/** engine: «rvm» = مدلِ ویدیوییِ Robust Video Matting (سریع، بدونِ پرش)، «birefnet» = فریم‌به‌فریم، «rvm-pending» = اجراکننده هست و مدل در اولین کار گرفته می‌شود */
export type MatteStatus = { ok: boolean; node: string; message: string; max_seconds: number; engine?: "rvm" | "birefnet" | "rvm-pending" };
export type TrackResult = { samples: { s: number; x: number; y: number; scale: number; rot: number }[]; lost_at: number | null; engine: string; s0: number; s1: number; fps: number; ref: string };
export type SyncResult = { offsets: { ref: string; offset: number; confidence: number; ok: boolean }[] };

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
  render: (store: string, id: number, quality: "draft" | "final", extra: { export?: Record<string, unknown>; data?: unknown } = {}) =>
    api.post<{ job_id: number }>(`${base(store)}/projects/${id}/render/`, { quality, ...extra }).then((r) => r.data),
  catalogue: (store: string) => api.get<Catalogue>(`${base(store)}/catalogue/`).then((r) => r.data),
  waveform: (store: string, ref: string) => api.get<Waveform>(`${base(store)}/analysis/`, { params: { ref, kind: "waveform" } }).then((r) => r.data),
  filmstrip: (store: string, ref: string) => api.get<Filmstrip>(`${base(store)}/analysis/`, { params: { ref, kind: "filmstrip" } }).then((r) => r.data),
  beats: (store: string, ref: string) => api.get<Beats>(`${base(store)}/analysis/`, { params: { ref, kind: "beats" } }).then((r) => r.data),
  speech: (store: string, ref: string) => api.get<{ spans: [number, number][] }>(`${base(store)}/analysis/`, { params: { ref, kind: "speech" } }).then((r) => r.data.spans),
  /** «پیش‌نمایشِ دقیقِ این بازه» — job؛ نتیجه {url, t0, t1, size, seconds, notes} */
  preview: (store: string, id: number, body: { t0: number; t1: number; height?: number; data?: unknown }) =>
    api.post<{ job_id: number; t0: number; t1: number }>(`${base(store)}/projects/${id}/preview/`, body).then((r) => r.data),
  captionsStatus: (store: string) => api.get<CaptionsStatus>(`${base(store)}/captions/status/`).then((r) => r.data),
  /** زیرنویسِ خودکار — job؛ نتیجه {clips: TextClip[], text, engine, count} */
  captions: (store: string, body: { ref: string; start: number; end: number; at: number; speed?: number }) =>
    api.post<{ job_id: number }>(`${base(store)}/captions/`, body).then((r) => r.data),
  /** ترجمهٔ زیرنویس — job؛ نتیجه {lang, items: [{id, text}]} */
  translateCaptions: (store: string, body: { lang: string; clips: { id: string; text: string }[] }) =>
    api.post<{ job_id: number }>(`${base(store)}/captions/translate/`, body).then((r) => r.data),
  renders: (store: string, id: number) => api.get<{ jobs: RenderJobRow[]; exports: ExportRow[]; replaced?: Record<string, { ref: string; seconds: number; has_audio: boolean; title?: string }> }>(`${base(store)}/projects/${id}/renders/`).then((r) => r.data),
  cancelJob: (jobId: number) => api.post(`/jobs/${jobId}/cancel/`),
  // ───────────── ابزارهای ویژه (pro 2)
  luts: (store: string) => api.get<{ luts: LutRow[] }>(`${base(store)}/luts/`).then((r) => r.data.luts),
  uploadLut: (store: string, file: File, title?: string) => {
    const body = new FormData();
    body.append("file", file);
    if (title) body.append("title", title);
    return api.post<{ lut: LutRow }>(`${base(store)}/luts/`, body).then((r) => r.data.lut);
  },
  deleteLut: (store: string, key: string) => api.delete(`${base(store)}/luts/${key}/`),
  lutText: (store: string, key: string) => api.get<string>(`${base(store)}/luts/${key}/file/`, { responseType: "text", transformResponse: (d) => d }).then((r) => r.data),
  /** ردیابیِ حرکت — job؛ نتیجه TrackResult */
  track: (store: string, body: { ref: string; s0: number; s1: number; region: { x: number; y: number; w: number; h: number }; fps?: number }) =>
    api.post<{ job_id: number }>(`${base(store)}/track/`, body).then((r) => r.data),
  /** هم‌زمان‌سازیِ چند ضبط با صدا — job؛ نتیجه SyncResult */
  syncAngles: (store: string, refs: string[]) => api.post<{ job_id: number }>(`${base(store)}/multicam/sync/`, { refs }).then((r) => r.data),
  matteStatus: (store: string) => api.get<MatteStatus>(`${base(store)}/matte/status/`).then((r) => r.data),
  mattes: (store: string) => api.get<{ mattes: MatteRow[] }>(`${base(store)}/mattes/`).then((r) => r.data.mattes),
  /** حذفِ پس‌زمینهٔ یک بازهٔ ویدیو (سرورِ پردازش) — job؛ نتیجه MatteRow */
  startMatte: (store: string, body: { ref: string; s0: number; s1: number; fps?: number }) => api.post<{ job_id: number }>(`${base(store)}/mattes/`, body).then((r) => r.data),
  deleteMatte: (store: string, key: string) => api.delete(`${base(store)}/mattes/${key}/`),
  renderWhere: (store: string) => api.get<RenderWhere>(`${base(store)}/render-where/`).then((r) => r.data),
};
