import { api } from "../../../api/client";

/** «بازسازیِ یک تکه» — همان شکلِ backend/apps/regen/views.py */

export type Engine = {
  key: string;
  label: string;
  short: string;
  license: string;
  qualities: string[];
  /** null = هیچ سرورِ پردازشی آنلاین نیست تا بپرسیم */
  ready: boolean | null;
  nodes: string[];
  missing: string[];
  sec_per_frame: Record<string, number>;
};

export type Source = {
  ref: string;
  kind: string;
  kind_label: string;
  title: string;
  url: string;
  created_at: string | null;
};

export type SeamInfo = {
  frame: number;
  diff: number;
  ratio: number;
  ssim: number;
  typical_ssim: number;
  motion: number;
  motion_around: number;
  motion_jump: number;
  verdict: "invisible" | "slight" | "visible";
  label: string;
};

export type Seams = {
  normal_diff?: number;
  typical_ssim?: number;
  seams?: { start?: SeamInfo; end?: SeamInfo };
  inner_max?: { frame: number; diff: number; ratio: number; verdict: string };
  score?: number;
  verdict?: "invisible" | "slight" | "visible";
  label?: string;
};

export type Plan = {
  start: number;
  end: number;
  count: number;
  before: number;
  after: number;
  has_start: boolean;
  has_end: boolean;
  span: number;
  fps: number;
  model_fps: number;
  effective_fps: number;
  speed: number;
  G: number;
  context: number;
  gen_size: [number, number];
  blend: number;
  frames_total: number;
  engine: string;
  quality: string;
  chunks: { length: number }[];
};

export type Version = {
  id: number;
  number: number;
  state: "QUEUED" | "PREPARING" | "GENERATING" | "STITCHING" | "READY" | "FAILED" | "CANCELLED";
  state_label: string;
  active: boolean;
  progress: number;
  message: string;
  error: string;
  start: number;
  end: number;
  seconds: number;
  prompt: string;
  model_prompt: string;
  engine: string;
  quality: string;
  seed: number;
  context: number;
  blend: number | null;
  base: number | null;
  plan: Partial<Plan>;
  seams: Seams;
  urls: {
    result: string | null;
    after: string | null;
    before: string | null;
    piece: string | null;
    frame_before: string | null;
    frame_after: string | null;
  };
  accepted: boolean;
  discarded: boolean;
  assemble: {
    method?: "smart" | "full";
    reencoded_frames?: number;
    seconds?: number;
    smart_skipped?: string;
    checks?: Record<string, { ok: boolean }>;
  };
  stitch: {
    frames?: number;
    exact?: number;
    interpolated?: number;
    sharpen?: number[];
    grain?: number[];
    blend?: number;
  };
  warnings: string[];
  gen_seconds: number | null;
  node: string | null;
  prompt_source: string | null;
  result_pruned: boolean;
  editor_upload: number | null;
  created_at: string;
};

export type Session = {
  id: number;
  title: string;
  state: "PREPARING" | "READY" | "FAILED";
  error: string;
  source_kind: string;
  source_label: string;
  source_ref: string;
  original_url: string | null;
  base_url: string | null;
  current: number | null;
  current_number: number | null;
  info: {
    width: number;
    height: number;
    fps: number;
    fps_num: number;
    fps_den: number;
    n_frames: number;
    duration: number;
    codec: string;
    pix_fmt: string;
    vfr: boolean;
    hdr: boolean;
    rotation: number;
    audio: { codec: string }[];
    bit_rate: number;
  };
  smart_splice: boolean;
  filmstrip: { url: string | null; frames: number[] };
  max_seconds: number;
  created_at: string;
  versions?: Version[];
  versions_count?: number;
  ready_count?: number;
};

export type Estimate = {
  plan: Plan;
  estimate: {
    generate_seconds: number;
    stitch_seconds: number;
    total_seconds: number;
    smart_splice: boolean;
    smart_reason: string;
  };
};

const base = (storeId: string) => `/stores/${storeId}/regen`;

export const regenApi = {
  overview: (storeId: string) =>
    api
      .get<{ sessions: Session[]; sources: Source[]; engines: Engine[]; max_seconds: number }>(`${base(storeId)}/`)
      .then((r) => r.data),
  open: (storeId: string, source: string) =>
    api.post<{ session: Session }>(`${base(storeId)}/sessions/`, { source }).then((r) => r.data.session),
  upload: (storeId: string, file: File, onProgress?: (fraction: number) => void) => {
    const body = new FormData();
    body.append("file", file);
    body.append("title", file.name);
    return api
      .post<{ session: Session }>(`${base(storeId)}/sessions/`, body, {
        onUploadProgress: (e) => onProgress?.(e.total ? e.loaded / e.total : 0),
      })
      .then((r) => r.data.session);
  },
  session: (storeId: string, id: number | string) =>
    api.get<{ session: Session; engines: Engine[] }>(`${base(storeId)}/sessions/${id}/`).then((r) => r.data),
  remove: (storeId: string, id: number) => api.delete(`${base(storeId)}/sessions/${id}/`),
  frame: (storeId: string, id: number, n: number, width = 480) =>
    api
      .get<Blob>(`${base(storeId)}/sessions/${id}/frame/`, { params: { n, w: width }, responseType: "blob" })
      .then((r) => r.data),
  estimate: (storeId: string, id: number, params: Record<string, string | number>) =>
    api.get<Estimate>(`${base(storeId)}/sessions/${id}/estimate/`, { params }).then((r) => r.data),
  create: (storeId: string, id: number, body: Record<string, unknown>) =>
    api.post<{ version: Version }>(`${base(storeId)}/sessions/${id}/versions/`, body).then((r) => r.data.version),
  action: (storeId: string, versionId: number, action: "accept" | "discard" | "cancel" | "editor") =>
    api
      .post<{ version: Version; upload_id?: number }>(`${base(storeId)}/versions/${versionId}/${action}/`)
      .then((r) => r.data),
};

/** ۱۲۳٫۴ ثانیه ⇐ «۲:۰۳٫۴» */
export function clock(seconds: number): string {
  const s = Math.max(0, seconds);
  const m = Math.floor(s / 60);
  const rest = s - m * 60;
  const txt = `${m}:${rest < 10 ? "0" : ""}${rest.toFixed(2)}`;
  return txt.replace(/[0-9]/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[Number(d)]).replace(".", "٫");
}

export function minutes(seconds: number): string {
  if (seconds < 90) return `${Math.max(1, Math.round(seconds))} ثانیه`.replace(/[0-9]/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[Number(d)]);
  return `${Math.round(seconds / 60)} دقیقه`.replace(/[0-9]/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[Number(d)]);
}
