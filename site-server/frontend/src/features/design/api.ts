import { api } from "../../api/client";

/** «استودیوی طراحی» — همان شکلِ backend/apps/design_studio (views.py، services.py). */

export type Kind = "catalog" | "deck" | "ui";
export type Check = { key: string; level: "ok" | "warn" | "info"; title: string; detail: string };
export type FontRow = { key: string; title: string; family: string; role: string; license: string; copyright: string; source: string; note: string; weights: number[]; css: string };
export type Look = { key: string; name_fa: string; palette: string[]; mood: string };
export type UiStyle = { key: string; label: string; en: string; mood: string; desc: string; colors: Record<string, string>; radius?: number };
export type ProductRow = { id: number; name: string; price: number | null; currency: string; available: boolean; category: string; image_ref: string; image_url: string; has_description: boolean };
export type DocSummary = { id: number; kind: Kind; kind_fa: string; title: string; rev: number; source: string; count: number; updated_at: string; created_at: string; site?: SiteInfo | null; ai?: AiInfo | null };
export type AiInfo = { used: boolean; via: string; message: string; model?: string };
export type SiteInfo = { project_id: number; slug: string; pages: { frame: string; title: string; slug: string; blocks: number }[]; url: string; style: string; published: boolean };
export type Recipient = { key: string; title: string; doc_kinds: Kind[]; pack: string; what: string; note: string };
export type ExportKindInfo = { label: string; ext: string; kinds: Kind[] };

export type Overview = {
  store: { id: number; name: string; has_logo: boolean };
  docs: DocSummary[];
  products: ProductRow[];
  fonts: FontRow[];
  looks: Look[];
  ui: { styles: UiStyle[]; devices: { key: string; label: string; w: number }[] };
  catalog: { page_types: { key: string; label: string }[]; page_sizes: { key: string; w: number; h: number }[]; defaults: Record<string, unknown>; layouts: Record<string, string> };
  deck: { slide_types: { key: string; label: string }[]; templates: { key: string; label: string }[]; defaults: Record<string, unknown> };
  exports: Record<string, ExportKindInfo>;
  recipients: Recipient[];
  ai: { ok: boolean; message: string };
  node: { state: string; message: string };
};

export type Doc = DocSummary & { data: any; meta: Record<string, any> };

export type El = {
  id: string; type: "rect" | "ellipse" | "line" | "text" | "image"; x: number; y: number; w: number; h: number; rot?: number; role?: string; name?: string; node?: string;
  text?: string; font?: string; weight?: number; size?: number; color?: string; align?: string; fill?: any; radius?: any; opacity?: number; src?: string; ph?: boolean; link?: { page?: string; url?: string };
  lay?: { size: number; n: number; h: number; overflow: boolean; truncated: boolean; shrunk: boolean };
};
export type ScenePage = {
  id: string; name: string; type?: string; w: number; h: number; bleed: number; bg: any; elements: El[]; notes: string; unit: string; device?: string; mode?: string;
  meta?: { nodes: { id: string; x: number; y: number; w: number; h: number; top: boolean }[]; hotspots: { el: string; x: number; y: number; w: number; h: number; to: string }[] };
};
export type Tokens = { style: string; style_label: string; light: Record<string, string>; dark: Record<string, string>; radius: number; space: number[]; type: Record<string, number> };
export type Scene = {
  kind: Kind; unit: "mm" | "px"; rev: number; pages: ScenePage[]; checks: Check[]; settings: Record<string, any>; palette?: Record<string, string>; fonts?: Record<string, string>;
  toc?: { id: string; title: string; index: number }[]; tokens?: Tokens; links?: { from: string; node: string; to: string }[]; styleguide?: { w: number; h: number } | null;
};
export type ExportRow = {
  id: number; kind: string; label: string; state: "QUEUED" | "RUNNING" | "READY" | "FAILED"; progress: number; message: string; error: string; filename: string; size_bytes: number;
  info: Record<string, any>; doc_rev: number; created_at: string; params: Record<string, any>; download: string;
};
export type Comment = { id: number; frame: string; node: string; x: number; y: number; text: string; resolved: boolean; author: string; parent: number | null; created_at: string };
export type BlockDef = { type: string; label: string; group: string; hint: string; fields: FieldSpec[]; defaults: Record<string, any>; category?: string; scope?: string[] };
export type FieldSpec = { key: string; label: string; kind: string; options?: { value: string | number; label: string }[]; fields?: FieldSpec[]; min?: number; max?: number; unit?: string; add_label?: string; item_label?: string; help?: string };
export type BlockCatalog = { groups: { value: string; label: string }[]; blocks: BlockDef[] };

export type Op = Record<string, unknown> & { op: string };

const P = (id: string | number) => `/stores/${id}/design`;

export const designApi = {
  overview: async (id: string) => (await api.get<Overview>(`${P(id)}/`)).data,
  docs: async (id: string, kind?: Kind) => (await api.get<{ docs: DocSummary[] }>(`${P(id)}/docs/`, { params: kind ? { kind } : {} })).data.docs,
  create: async (id: string, kind: Kind, title: string, options: Record<string, unknown>) => (await api.post<{ doc: Doc }>(`${P(id)}/docs/`, { kind, title, options })).data.doc,
  doc: async (id: string, docId: number | string) => (await api.get<{ doc: Doc }>(`${P(id)}/docs/${docId}/`)).data.doc,
  rename: async (id: string, docId: number, title: string) => (await api.patch<{ doc: Doc }>(`${P(id)}/docs/${docId}/`, { title })).data.doc,
  remove: async (id: string, docId: number) => api.delete(`${P(id)}/docs/${docId}/`),
  ops: async (id: string, docId: number, ops: Op[], rev: number) => (await api.post<{ doc: Doc }>(`${P(id)}/docs/${docId}/ops/`, { ops, rev })).data.doc,
  scene: async (id: string, docId: number, mode?: string) => (await api.get<Scene>(`${P(id)}/docs/${docId}/scene/`, { params: mode ? { mode } : {} })).data,
  previewUrl: (id: string, docId: number, page: string, w: number, rev: number, mode?: string) => `${P(id)}/docs/${docId}/preview/${encodeURIComponent(page)}.png?w=${w}&rev=${rev}${mode ? `&mode=${mode}` : ""}`,
  exports: async (id: string, docId: number) => (await api.get<{ exports: ExportRow[] }>(`${P(id)}/docs/${docId}/exports/`)).data.exports,
  startExport: async (id: string, docId: number, kind: string, params: Record<string, unknown> = {}) => (await api.post<{ export: ExportRow }>(`${P(id)}/docs/${docId}/exports/`, { kind, params })).data.export,
  deleteExport: async (id: string, eid: number) => api.delete(`${P(id)}/exports/${eid}/`),
  exportRow: async (id: string, eid: number) => (await api.get<{ export: ExportRow }>(`${P(id)}/exports/${eid}/`)).data.export,
  designer: async (id: string, docId: number, page: string) => (await api.post<{ project: number; asset: number; layers: number; url: string }>(`${P(id)}/docs/${docId}/designer/`, { page })).data,
  video: async (id: string, docId: number, body: { seconds: number; transition: string }) => (await api.post<{ export: ExportRow; node: { state: string; message: string } }>(`${P(id)}/docs/${docId}/video/`, body)).data,
  site: async (id: string, docId: number, body: { name?: string }) => (await api.post<{ site: SiteInfo }>(`${P(id)}/docs/${docId}/site/`, body)).data.site,
  ai: async (id: string, docId: number, body: { brief: string; use_ai: boolean }) => (await api.post<{ doc: Doc; ai: AiInfo }>(`${P(id)}/docs/${docId}/ai/`, body)).data,
  sample: async (id: string, site: boolean) => (await api.post<Record<string, any>>(`${P(id)}/sample/`, { site })).data,
  comments: async (id: string, docId: number) => (await api.get<{ comments: Comment[] }>(`${P(id)}/docs/${docId}/comments/`)).data.comments,
  addComment: async (id: string, docId: number, body: Record<string, unknown>) => (await api.post<{ comment: Comment }>(`${P(id)}/docs/${docId}/comments/`, body)).data.comment,
  patchComment: async (id: string, cid: number, body: Record<string, unknown>) => (await api.patch<{ comment: Comment }>(`${P(id)}/comments/${cid}/`, body)).data.comment,
  deleteComment: async (id: string, cid: number) => api.delete(`${P(id)}/comments/${cid}/`),
  uiCatalog: async (id: string) => (await api.get<BlockCatalog>(`${P(id)}/ui/catalog/`)).data,
  photoAssets: async (id: string) => (await api.get<{ assets: { id: number; title: string; thumb: string | null; url: string | null }[] }>(`/stores/${id}/photo-editor/assets/`)).data.assets,
};

export async function downloadBlob(path: string, filename: string) {
  const res = await api.get(path, { responseType: "blob" });
  const url = URL.createObjectURL(res.data as Blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 4000);
}

// ───────────────────────────── پیش‌نمایش با توکنِ ورود (تگِ img سرآیندِ Authorization ندارد)
const blobCache = new Map<string, Promise<string>>();

export function previewBlob(path: string): Promise<string> {
  let hit = blobCache.get(path);
  if (!hit) {
    hit = api.get(path, { responseType: "blob" }).then((r) => URL.createObjectURL(r.data as Blob));
    blobCache.set(path, hit);
    hit.catch(() => blobCache.delete(path));
    if (blobCache.size > 90) {
      const first = blobCache.keys().next().value as string | undefined;
      if (first) {
        const old = blobCache.get(first);
        blobCache.delete(first);
        old?.then((u) => URL.revokeObjectURL(u)).catch(() => undefined);
      }
    }
  }
  return hit;
}

export const KIND_FA: Record<Kind, string> = { catalog: "کاتالوگ", deck: "ارائه", ui: "طراحی UI/UX" };
export const KIND_PATH: Record<Kind, string> = { catalog: "catalog", deck: "deck", ui: "ui" };
export const fa = (v: number | string) => String(v).replace(/[0-9]/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[Number(d)]);
export const sizeText = (b: number) => (b > 1048576 ? `${fa((b / 1048576).toFixed(1))} مگابایت` : `${fa(Math.max(1, Math.round(b / 1024)))} کیلوبایت`);

export function apiError(e: unknown): string {
  const d = (e as { response?: { data?: { error?: { message?: string; code?: string } } } })?.response?.data?.error;
  if (d?.message) return d.message;
  const m = (e as { message?: string })?.message;
  return m ? `خطا: ${m}` : "خطای ناشناخته";
}
export function isConflict(e: unknown): boolean {
  return (e as { response?: { status?: number } })?.response?.status === 409;
}
