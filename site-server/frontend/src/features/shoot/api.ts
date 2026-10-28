import axios from "axios";

import { api } from "../../api/client";

/** «فیلم‌برداریِ هدایت‌شده» — همان شکلِ backend/apps/shoot/views.py */

export type Overlay = { arrow: string; yaw: number; pitch: number; distance: "close" | "medium" | "far" };
export type Cue = { at: number; text: string };

export type PhotoShot = {
  key: string;
  kind: "photo";
  angle: string;
  title: string;
  instruction: string;
  tip?: string;
  overlay: Overlay;
  check: Record<string, unknown>;
};

export type VideoShot = {
  key: string;
  kind: "video";
  move: string;
  title: string;
  instruction: string;
  pre?: string;
  duration: number;
  speed: string;
  distance_cm: number;
  degrees?: number;
  direction?: string;
  action?: string;
  caption?: string;
  tip?: string;
  overlay: Overlay;
  cues: Cue[];
  check: { min_seconds?: number };
};

export type Shot = PhotoShot | VideoShot;

export type Plan = {
  version: number;
  product_type: string;
  category: string;
  category_label: string;
  features: string[];
  setup: { background: string; lighting: string; tips: string[] };
  photos: PhotoShot[];
  video: VideoShot[];
  ad: { headline: string; cta: string; voiceover: string; music_mood: string; price: string };
  notes?: string[];
};

export type Problem = { code: string; message: string };

export type Take = {
  id: number;
  shot: string;
  kind: "photo" | "video";
  url: string;
  thumb: string | null;
  preview: string | null;
  ok: boolean;
  accepted: boolean;
  score: number;
  duration: number;
  width: number;
  height: number;
  mode: string;
  size: number;
  problems: Problem[];
  summary: string;
  vision: { product_visible: boolean; angle_ok: boolean; problems: string[] } | null;
  where: string;
  saved_image_id: number | null;
  created_at: string;
};

export type Output = {
  id: number;
  kind: "video" | "poster";
  aspect: string;
  version: number;
  template: string;
  options: Record<string, unknown>;
  state: "QUEUED" | "RUNNING" | "READY" | "FAILED";
  progress: number;
  message: string;
  error: string;
  url: string | null;
  thumb: string | null;
  stats: {
    steps?: { step: string; where: string }[];
    notes?: string[];
    seconds?: number;
    render_seconds?: number;
    size?: number;
  };
  saved: Record<string, number[]>;
  created_at: string;
};

export type Session = {
  id: number;
  purpose: "photos" | "ad";
  state: "READY" | "ANALYZING";
  plan_source: string;
  message: string;
  error: string;
  product: { id: number; name: string; price: string; thumb: string | null };
  plan: Plan;
  voice: { state?: "RUNNING" | "READY" | "FAILED"; clips?: Record<string, string>; engine?: string; error?: string };
  takes: Take[];
  outputs: Output[];
  counts?: { takes: number; accepted_shots: number; shots: number; outputs: number };
  created_at: string;
};

export type Overview = {
  sessions: Session[];
  products: { id: number; name: string; price: string; thumb: string | null; images: number }[];
  music: { id: number; title: string; seconds: number; saved: boolean }[];
  capabilities: { stabilize: boolean; xfade: boolean; ducking: boolean; node_online: boolean };
  templates: { key: string; title: string }[];
  aspects: { video: string[]; poster: string[] };
  transitions: { key: string; title: string }[];
  angles: { key: string; title: string }[];
  moves: { key: string; title: string }[];
  categories: { key: string; title: string }[];
  disk: string;
};

const base = (storeId: number | string) => `/stores/${storeId}/shoot/`;
const ses = (storeId: number | string, id: number) => `${base(storeId)}sessions/${id}/`;

export const shootApi = {
  overview: (storeId: number | string) => api.get<Overview>(base(storeId)).then((r) => r.data),
  create: (
    storeId: number | string,
    body: { product: number; purpose: "photos" | "ad"; analyze?: boolean; reuse?: boolean },
  ) => api.post<Session>(`${base(storeId)}sessions/`, body).then((r) => r.data),
  get: (storeId: number | string, id: number) => api.get<Session>(ses(storeId, id)).then((r) => r.data),
  savePlan: (storeId: number | string, id: number, plan: Plan) =>
    api.patch<Session & { problems: string[] }>(ses(storeId, id), { plan }).then((r) => r.data),
  remove: (storeId: number | string, id: number) => api.delete(ses(storeId, id)),
  action: (storeId: number | string, id: number, action: "analyze" | "voice") =>
    api.post<Session>(`${ses(storeId, id)}${action}/`, {}).then((r) => r.data),
  savePhotos: (storeId: number | string, id: number) =>
    api.post<{ created: number[]; session: Session }>(`${ses(storeId, id)}save-photos/`, {}).then((r) => r.data),
  setTake: (storeId: number | string, id: number, take: number, accepted: boolean) =>
    api.patch<Take>(`${ses(storeId, id)}takes/${take}/`, { accepted }).then((r) => r.data),
  deleteTake: (storeId: number | string, id: number, take: number) =>
    api.delete(`${ses(storeId, id)}takes/${take}/`),
  makeOutputs: (
    storeId: number | string,
    id: number,
    body: { kind: "video" | "poster"; aspects: string[]; template: string; options: Record<string, unknown> },
  ) => api.post<Session>(`${ses(storeId, id)}outputs/`, body).then((r) => r.data),
  outputAction: (storeId: number | string, id: number, out: number, action: "product" | "content" | "editor") =>
    api
      .post<{ result: Record<string, unknown>; output: Output }>(`${ses(storeId, id)}outputs/${out}/${action}/`, {})
      .then((r) => r.data),
  deleteOutput: (storeId: number | string, id: number, out: number) =>
    api.delete(`${ses(storeId, id)}outputs/${out}/`),
};

// ───────────────────────────── آپلودِ تکه‌تکه و قابلِ ادامه

const CHUNK = 1024 * 1024;
const MAX_FAILURES = 6;

/** crypto.randomUUID روی http (غیرِ امن) نیست؛ این کافی است. */
export function newUploadId(): string {
  return (
    Date.now().toString(36) +
    Math.random().toString(36).slice(2, 10) +
    Math.random().toString(36).slice(2, 8)
  );
}

const sleep = (ms: number) => new Promise((r) => window.setTimeout(r, ms));

export class UploadStopped extends Error {
  uploadId: string;
  constructor(message: string, uploadId: string) {
    super(message);
    this.uploadId = uploadId;
  }
}

/**
 * فایل را تکه‌های ۱ مگابایتی می‌فرستد. قطعِ اینترنت ⇐ صبر و تلاشِ دوباره از همان جایی که سرور دارد
 * (۴۰۹ یا GET ِ «چقدر رسیده»). اگر شش بار پشتِ سرِ هم نشد، `UploadStopped` با شناسه‌اش برمی‌گردد تا دکمهٔ
 * «ارسالِ دوباره» از همان‌جا ادامه دهد. پاسخِ تکهٔ آخر = برداشتِ وارسی‌شده.
 */
export async function uploadTake(opts: {
  storeId: number | string;
  sessionId: number;
  shot: string;
  kind: "photo" | "video";
  blob: Blob;
  name: string;
  mode: string;
  uploadId?: string;
  onProgress?: (fraction: number) => void;
}): Promise<Take> {
  const { storeId, sessionId, shot, kind, blob, name, mode, onProgress } = opts;
  const id = opts.uploadId || newUploadId();
  const url = `${ses(storeId, sessionId)}upload/`;
  const total = blob.size;
  let offset = 0;
  if (opts.uploadId) {
    try {
      offset = (await api.get<{ received: number }>(url, { params: { upload_id: id } })).data.received;
    } catch {
      offset = 0;
    }
  }
  let failures = 0;
  for (;;) {
    const end = Math.min(total, offset + CHUNK);
    const form = new FormData();
    form.append("upload_id", id);
    form.append("offset", String(offset));
    form.append("total", String(total));
    form.append("kind", kind);
    form.append("shot", shot);
    form.append("name", name);
    form.append("mode", mode);
    form.append("chunk", blob.slice(offset, end), "chunk");
    const start = offset;
    try {
      const { data } = await api.post<{ received: number; take?: Take }>(url, form, {
        onUploadProgress: (e) => onProgress?.(Math.min(1, (start + (e.loaded || 0)) / Math.max(1, total))),
      });
      failures = 0;
      if (data.take) {
        onProgress?.(1);
        return data.take;
      }
      offset = data.received;
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 409) {
        const got = (err.response.data as { received?: number })?.received;
        offset = typeof got === "number" ? got : offset;
        continue;
      }
      const status = axios.isAxiosError(err) ? err.response?.status : undefined;
      if (status && status < 500 && status !== 408 && status !== 429) throw err; // خطای واقعی (عکسِ خراب، …)
      failures += 1;
      if (failures > MAX_FAILURES) {
        throw new UploadStopped("اینترنت قطع شد. «ارسالِ دوباره» را بزن؛ از همان‌جا ادامه می‌دهد.", id);
      }
      await sleep(Math.min(8000, 700 * 2 ** failures));
      try {
        offset = (await api.get<{ received: number }>(url, { params: { upload_id: id } })).data.received;
      } catch {
        /* هنوز قطع است؛ دورِ بعد */
      }
    }
  }
}

/** عکسِ ۱۲ مگاپیکسلیِ گوشی ⇐ JPEG با بلندترین ضلعِ ۲۵۶۰ (آپلود چند برابر سریع‌تر؛ برای فروشگاه کافی). */
export async function shrinkPhoto(file: Blob, maxSide = 2560): Promise<Blob> {
  let url = "";
  try {
    url = URL.createObjectURL(file);
    const img = new Image();
    img.src = url;
    await img.decode();
    const w = img.naturalWidth;
    const h = img.naturalHeight;
    if (!w || !h) return file;
    const scale = Math.min(1, maxSide / Math.max(w, h));
    if (scale === 1 && file.type === "image/jpeg" && file.size < 6_000_000) return file;
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(w * scale);
    canvas.height = Math.round(h * scale);
    const ctx = canvas.getContext("2d");
    if (!ctx) return file;
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((res) => canvas.toBlob(res, "image/jpeg", 0.9));
    return blob ?? file;
  } catch {
    return file;
  } finally {
    if (url) URL.revokeObjectURL(url);
  }
}

/** دوربینِ زنده فقط در «محیطِ امن» (https یا localhost). */
export function liveSupport(): { ok: boolean; video: boolean; reason: string } {
  if (typeof window === "undefined" || !window.isSecureContext) {
    return {
      ok: false,
      video: false,
      reason:
        "پنل الان با http باز شده (نه https). مرورگرها دوربینِ زنده و حسگرِ چرخشِ گوشی را فقط روی https یا localhost به صفحه می‌دهند. " +
        "برای همین از دوربینِ خودِ گوشی استفاده می‌کنیم: هر زاویه را اول با نقشه و تمرین نشانت می‌دهیم، بعد دوربینِ گوشی باز می‌شود، می‌گیری و همین‌جا بررسی می‌شود.",
    };
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    return { ok: false, video: false, reason: "این مرورگر دوربینِ زنده به صفحه نمی‌دهد؛ از دوربینِ خودِ گوشی استفاده می‌کنیم." };
  }
  return { ok: true, video: typeof MediaRecorder !== "undefined", reason: "" };
}

export const fa = (n: number | string) => String(n).replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[Number(d)]);

export function shotsOf(plan: Plan, kinds: ("photo" | "video")[]): Shot[] {
  return [...(kinds.includes("photo") ? plan.photos : []), ...(kinds.includes("video") ? plan.video : [])];
}
