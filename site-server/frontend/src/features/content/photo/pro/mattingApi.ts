import { api } from "../../../../api/client";
import type { Asset } from "../api";

/** حذفِ پس‌زمینه با چند مدل — backend/apps/photoedit/views_matting.py (دورِ ۸) */

export type MattingRow = {
  id: "rvm" | "u2netp" | "isnet" | "birefnet-lite";
  where: "site" | "node";
  title: string;
  hint: string;
  size_mb: number;
  state: "installed" | "downloading" | "queued" | "missing" | "failed";
  state_fa: string;
  installed_on: string[];
  progress: number | null;
  error: string;
};
export type MattingStatus = {
  models: MattingRow[]; node_known: boolean; node_online: boolean; runtime: { ok?: boolean; message?: string } | null; default: string;
  /** سرورِ پردازشی که نرم‌افزارش قدیمی است (باید ۲٫۷ شود) و متنِ راهنمای به‌روزرسانی */
  needs_update?: string[]; update_text?: string; message?: string;
};
export type MattingJob = {
  uid: string;
  model: string;
  state: "queued" | "running" | "ready" | "failed" | "cancelled";
  message: string;
  progress?: number;
  seconds?: number | null;
  device?: string;
  node?: string;
  url?: string;
};

const base = (store: string) => `/stores/${store}/photo-editor/matting`;

export const mattingApi = {
  status: (store: string) => api.get<MattingStatus>(`${base(store)}/`).then((r) => r.data),
  run: (store: string, asset: number, models: string[]) =>
    api.post<{ jobs: MattingJob[]; skipped: { model: string; message: string }[] }>(`${base(store)}/run/`, { asset, models }).then((r) => r.data),
  jobs: (store: string, uids: string[]) =>
    api.get<{ jobs: MattingJob[]; node_online: boolean }>(`${base(store)}/jobs/`, { params: { uids: uids.join(",") } }).then((r) => r.data),
  apply: (store: string, asset: number, model: string, uid?: string) =>
    api.post<{ asset: Asset }>(`${base(store)}/apply/`, { asset, model, uid: uid ?? "" }).then((r) => r.data.asset),
  /** تصویرِ نتیجه (نیازمندِ ورود است؛ <img> هدرِ ورود نمی‌فرستد ⇒ blob می‌گیریم). url نسبت به baseURL ِ api است. */
  blobUrl: (url: string) => api.get<Blob>(url, { responseType: "blob" }).then((r) => URL.createObjectURL(r.data)),
};
