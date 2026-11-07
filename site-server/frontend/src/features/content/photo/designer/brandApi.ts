import { api } from "../../../../api/client";
import type { Edit } from "../api";

/** تنظیماتِ فروشگاه (پیش‌فرضِ هوش مصنوعی + سبکِ برند) و طراحیِ گروهی — backend/apps/photoedit/brand.py و batch.py */

export type Brand = {
  colors: string[];
  heading_font: string;
  body_font: string;
  logo: { mode: "store" | "asset" | "none"; asset: number | null; position: string; size: number };
  tone: string;
};
export type AiCost = { variants: number; fast: number; normal: number; best: number; batch_per_photo: number };
export type SmartOffline = "ask" | "site" | "queue";
export type MattingModelId = "rvm" | "u2netp" | "isnet" | "birefnet-lite";
export type StoreSettings = {
  ai_assist: boolean; brand: Brand; brand_set: boolean; ai_cost: AiCost; positions: string[];
  /** «ویرایش با دستور» وقتی سرورِ پردازش خاموش است: ask = هر بار بپرس */
  smart_offline: SmartOffline;
  matting_model: MattingModelId;
};

export const emptyBrand = (): Brand => ({ colors: [], heading_font: "", body_font: "", logo: { mode: "store", asset: null, position: "", size: 0 }, tone: "" });

export const POSITION_FA: Record<string, string> = {
  tl: "بالا، چپ",
  tr: "بالا، راست",
  bl: "پایین، چپ",
  br: "پایین، راست",
  bottom_center: "پایین، وسط",
  top_center: "بالا، وسط",
};

const base = (store: string) => `/stores/${store}/photo-editor`;

export const settingsApi = {
  get: (store: string) => api.get<StoreSettings>(`${base(store)}/settings/`).then((r) => r.data),
  put: (store: string, body: { ai_assist?: boolean; brand?: Brand; smart_offline?: SmartOffline; matting_model?: MattingModelId }) => api.put<StoreSettings>(`${base(store)}/settings/`, body).then((r) => r.data),
};

export type BatchItem = {
  asset: { id: number; title: string; thumb: string };
  design: null | { id: number; state: "QUEUED" | "RUNNING" | "READY" | "FAILED"; message: string; error: string; preview: string; score: number | null; issues: string[]; needs: boolean };
};
export type Batch = {
  id: number;
  title: string;
  state: "QUEUED" | "RUNNING" | "READY" | "FAILED" | "CANCELLED";
  progress: number;
  done: number;
  total: number;
  message: string;
  error: string;
  recipe: string;
  prompt: string;
  format: string;
  options: { use_ai?: boolean; use_brand?: boolean };
  created: string;
  items: BatchItem[];
};
export type BatchRow = { id: number; title: string; state: Batch["state"]; progress: number; done: number; total: number; message: string; created: string };
export type BatchInput = {
  assets: number[];
  prompt: string;
  recipe: string;
  format: string;
  mood: string;
  copy: Record<string, string>;
  use_ai: boolean;
  use_brand: boolean;
  brand?: Partial<Brand>;
};

export const batchApi = {
  list: (store: string) => api.get<{ batches: BatchRow[] }>(`${base(store)}/designer/batches/`).then((r) => r.data.batches),
  create: (store: string, body: BatchInput) => api.post<{ batch: Batch }>(`${base(store)}/designer/batches/`, body).then((r) => r.data.batch),
  get: (store: string, id: number) => api.get<{ batch: Batch }>(`${base(store)}/designer/batches/${id}/`).then((r) => r.data.batch),
  cancel: (store: string, id: number) => api.post<{ batch: Batch }>(`${base(store)}/designer/batches/${id}/`, { action: "cancel" }).then((r) => r.data.batch),
  remove: (store: string, id: number) => api.delete(`${base(store)}/designer/batches/${id}/`),
  /** zip ِ خروجیِ نهایی را می‌گیرد و دانلود می‌کند؛ assets = فقط همین عکس‌ها */
  async download(store: string, id: number, assets?: number[]): Promise<void> {
    const r = await api.get<Blob>(`${base(store)}/designer/batches/${id}/zip/`, { params: assets ? { assets: assets.join(",") } : undefined, responseType: "blob" });
    const url = URL.createObjectURL(r.data);
    const a = document.createElement("a");
    a.href = url;
    a.download = `batch-${id}.zip`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 4000);
  },
  apply: (store: string, designId: number) =>
    api.post<{ project: number; edit: Edit }>(`${base(store)}/designer/designs/${designId}/apply/`, { variant: 0 }).then((r) => r.data),
};

export type { Edit };
