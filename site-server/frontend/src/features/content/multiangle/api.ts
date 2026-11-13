import { api } from "../../../api/client";

/** «چندزاویه» — همان شکلِ backend/apps/multiangle/views.py و services.py (run_dict، status، presets) */

export type RunMode = "virtual" | "move25d" | "selftest";
export type RunState = "QUEUED" | "RUNNING" | "INGEST" | "READY" | "FAILED" | "CANCELLED";

export type AnglePreset = { key: string; label: string; hint: string; needs_two: boolean; default: boolean };
export type MovePreset = { key: string; label: string; hint: string };
export type Choice = { key: string; label: string };
export type Presets = {
  angles: AnglePreset[];
  formats: Choice[];
  paces: Choice[];
  rhythms: Choice[];
  moves: MovePreset[];
  limits: { max_seconds: number; max_move_seconds: number };
  defaults: { format: string; pace: string; handheld: number; rhythm: string; amount: number; duration: number };
};

export type VideoSource = { ref: string; title: string; duration: number; width: number; height: number; has_audio: boolean; url: string | null; source: string };
export type ImageSource = { ref: string; title: string; width: number; height: number; url: string | null; source: string };
export type Sources = { videos: VideoSource[]; images: ImageSource[] };

export type ModelRow = {
  key: string;
  label: string;
  state: "installed" | "downloading" | "queued" | "missing" | "failed";
  state_label: string;
  size_mb: number | null;
  progress: number | null;
  error: string;
};
export type SelfTestSummary = {
  id: number;
  state: RunState;
  ok: boolean;
  at: string;
  checks: { name: string; label: string; ok: boolean; detail: string }[];
  error: string;
} | null;
export type NodeRow = {
  name: string;
  online: boolean;
  gpu: string;
  ready: { virtual: boolean; move: boolean; selftest: boolean };
  runtime: { ok: boolean | null; gpu: boolean; providers: string[]; message: string };
  models: ModelRow[];
  installing: boolean;
  message: string;
  version: string;
  selftest: SelfTestSummary;
};
export type NodeStatus = {
  nodes: NodeRow[];
  ready: { virtual: boolean; move: boolean };
  online: boolean;
  message: string;
  needs_update: string[];
  update_text: string;
};

export type Angle = { key: string; label: string; url: string | null; preview: string | null; upload: number | null; upscale: number | null; ref: string | null };
export type Cut = { t: number; end: number; angle: string; label: string; reason: string; reason_label: string };

export type Run = {
  id: number;
  mode: RunMode;
  mode_label: string;
  state: RunState;
  state_label: string;
  active: boolean;
  title: string;
  progress: number;
  message: string;
  error: string;
  created_at: string;
  source: string;
  params: Record<string, unknown>;
  project_id: number | null;
  warnings: string[];
  node: { models?: Record<string, string>; model_fallback?: string[]; encoder?: string };
  thumb?: string | null;
  // فقط در جزئیات
  angles?: Angle[];
  multicam_url?: string | null;
  cuts?: Cut[];
  subject?: string;
  output?: { width: number; height: number; fps: number; duration: number } | null;
  skipped?: { key: string; label: string; why: string }[];
  move?: { url: string | null; preview: string | null; depth: string | null; label: string; safe_zoom: number | null; upload: number | null; ref: string | null } | null;
  checks?: { name: string; label: string; ok: boolean; detail: string }[];
  audio?: { pauses: number; sentences: number; beats: number; bpm: number; beat_confidence: number; cut_points: string[] } | null;
  cut_quality?: { segments: number; cuts_on_points: number; forced: number; share_on_points: number; angles_used: string[] } | null;
};

export type Overview = { runs: Run[]; sources: Sources; presets: Presets; status: NodeStatus };

export type VirtualBody = {
  mode: "virtual";
  source: string;
  angles: string[];
  format: string;
  pace: string;
  handheld: number;
  rhythm: string;
  multicam: boolean;
};
export type MoveBody = {
  mode: "move25d";
  source: string;
  move: string;
  amount: number;
  duration: number;
  format: string;
  ease: string;
  relief: number;
  inpaint: boolean;
};

const base = (store: string) => `/stores/${store}/multiangle`;

export const multiangleApi = {
  overview: (store: string) => api.get<Overview>(`${base(store)}/`).then((r) => r.data),
  status: (store: string) => api.get<NodeStatus>(`${base(store)}/status/`).then((r) => r.data),
  prepare: (store: string) => api.post<{ nodes: Record<string, string>; status: NodeStatus }>(`${base(store)}/prepare/`).then((r) => r.data),
  selftest: (store: string) => api.post<{ runs: number[]; status: NodeStatus }>(`${base(store)}/selftest/`).then((r) => r.data),
  create: (store: string, body: VirtualBody | MoveBody) => api.post<{ run: Run }>(`${base(store)}/runs/`, body).then((r) => r.data.run),
  run: (store: string, id: number) => api.get<{ run: Run }>(`${base(store)}/runs/${id}/`).then((r) => r.data.run),
  remove: (store: string, id: number) => api.delete(`${base(store)}/runs/${id}/`),
  cancel: (store: string, id: number) => api.post<{ run: Run }>(`${base(store)}/runs/${id}/cancel/`).then((r) => r.data.run),
  toEditor: (store: string, id: number) => api.post<{ project_id: number; run: Run }>(`${base(store)}/runs/${id}/editor/`).then((r) => r.data),
  real: (store: string, sources: string[], pace: string) =>
    api.post<{ project_id: number; offsets: number[]; cuts: number; length: number }>(`${base(store)}/real/`, { sources, pace }).then((r) => r.data),
};

/** رنگِ هر زاویه روی نوارِ برش‌ها (از توکن‌های پنل؛ فقط ترتیب مهم است) */
export const ANGLE_COLORS: Record<string, string> = {
  wide: "#4f8cff",
  medium: "#22b07d",
  close: "#e8833a",
  two_shot: "#9b6bff",
  over_shoulder: "#e0508b",
};

export const mmss = (s: number): string => {
  const t = Math.max(0, Math.round(s));
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
};

/** نوارِ برش‌ها: هر تکه با پهنای متناسب با طولش؛ جمعِ درصدها ۱۰۰ است */
export function cutBar(cuts: Cut[]): { angle: string; label: string; left: number; width: number; t: number; end: number; reason: string }[] {
  const total = Math.max(0.001, ...cuts.map((c) => c.end));
  return cuts.map((c) => ({
    angle: c.angle,
    label: c.label,
    left: (c.t / total) * 100,
    width: Math.max(0.5, ((c.end - c.t) / total) * 100),
    t: c.t,
    end: c.end,
    reason: c.reason_label,
  }));
}

/** سنجشِ سادهٔ حالتِ دکمه‌ها برای هر حالت از «سرورِ پردازش» */
export function readiness(st: NodeStatus | null | undefined, mode: "virtual" | "move25d"): { ok: boolean; tone: "ok" | "warn" | "info" | "bad"; text: string } {
  if (!st) return { ok: false, tone: "info", text: "در حالِ بررسیِ سرورِ پردازش…" };
  const ready = mode === "virtual" ? st.ready.virtual : st.ready.move;
  if (ready && st.online) return { ok: true, tone: "ok", text: "سرورِ پردازش آماده است." };
  if (st.needs_update.length) return { ok: false, tone: "warn", text: st.update_text };
  return { ok: false, tone: st.online ? "info" : "warn", text: st.message };
}
