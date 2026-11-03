import { api } from "../../../api/client";

/** «ادیتور عکس» — همان شکلِ backend/apps/photoedit/views.py */

export type Where = "server" | "node";

export type ParamSpec = {
  key: string;
  title: string;
  type: "number" | "select" | "bool" | "text" | "color" | "adjust" | "spots" | "curve" | "layers" | "quad";
  default: unknown;
  help?: string;
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
  options?: { value: string; label: string; help?: string }[];
};

export type Tool = {
  key: string;
  title: string;
  where: Where;
  help: string;
  icon?: string;
  single?: boolean;
  /** ابزارِ داخلی (develop / compose / perspective) که در فهرستِ «افزودنِ ابزار» نمی‌آید */
  hidden?: boolean;
  params: ParamSpec[];
};

export type Params = Record<string, unknown>;

export type Operation = {
  tool: string;
  params: Params;
  on?: boolean;
  optional?: boolean;
  reason?: string;
  title?: string;
  where?: Where;
  /** گروهِ لغزنده‌های کیت (نور، رنگ، …) وقتی این کار از «انتخابِ کیت/هوش مصنوعی» آمده */
  group?: string;
};

export type EditorModeKey = "auto" | "prompt" | "manual";

export type Recipe = {
  key: string;
  title: string;
  help: string;
  operations: Operation[];
  needs_node: boolean;
  /** هر دستور در کدام حالتِ ادیتور زندگی می‌کند */
  mode: EditorModeKey;
};

export type KitParam = {
  key: string;
  group: string;
  title: string;
  help: string;
  min: number;
  max: number;
  default: number;
  step: number;
  unit: string;
};

export type Kit = {
  groups: { key: string; title: string; help: string }[];
  params: KitParam[];
  presets: { key: string; title: string; help: string; kind: string; recipe?: KitRecipe }[];
};

export type KitRecipe = {
  adjust?: Record<string, number>;
  curve?: Record<string, [number, number][]>;
  background?: { remove?: boolean; color?: string; shadow?: number; method?: string };
  output?: { square?: boolean; padding?: number; longEdge?: number; format?: string; quality?: number };
};

export type NodeStatus = { online: boolean; nodes: string[] };

export type Finding = { what: string; note: string; value: number };

export type Facts = Record<string, number | boolean>;

export type Edit = {
  id: number;
  asset: number;
  number: number;
  batch: string;
  recipe: string;
  recipe_title: string;
  operations: { tool: string; params: Params; title: string; where: Where; reason?: string }[];
  /** آنچه کیت/هوشِ مصنوعی واقعاً انتخاب کرد، به‌صورتِ کارهای جدا و قابل‌ویرایش */
  chosen: Operation[];
  needs_node: boolean;
  state: "QUEUED" | "NODE" | "SERVER" | "READY" | "FAILED" | "CANCELLED";
  state_label: string;
  active: boolean;
  progress: number;
  message: string;
  error: string;
  urls: { result: string | null; preview: string | null; thumb: string | null; node: string | null };
  size: [number, number] | null;
  after: Facts | null;
  kit: { recipe?: Params; notes?: string | string[]; usedAi?: boolean; error?: string; auto?: boolean };
  server_notes: string[];
  node: string | null;
  node_seconds: number | null;
  bytes: number | null;
  format: string | null;
  saved: {
    product_images?: { id: number; product: number }[];
    generated_images?: { id: number; product: number }[];
    assets?: number[];
  };
  created_at: string;
};

export type KitAnalysis = {
  state?: string;
  message?: string;
  text?: string;
  notes?: string[];
  error?: string;
};

export type Asset = {
  id: number;
  title: string;
  source_kind: "upload" | "product" | "generated" | "edit";
  source_label: string;
  source_ref: string;
  product: number | null;
  product_name: string | null;
  url: string;
  thumb: string;
  preview: string;
  width: number;
  height: number;
  size_bytes: number;
  has_alpha: boolean;
  facts: Facts;
  findings: Finding[];
  kit_analysis: KitAnalysis;
  created_at: string;
  last_edit?: Edit | null;
  edits_count?: number;
  edits?: Edit[];
};

export type Overview = {
  assets: Asset[];
  active: Edit[];
  tools: Tool[];
  recipes: Recipe[];
  kit: Kit;
  node: NodeStatus;
  store_logo: string | null;
  limits: { max_upload_mb: number; max_batch: number };
};

export type Sources = {
  products: { id: number; name: string; images: { ref: string; id: number; url: string; imported: boolean }[] }[];
  generated: {
    ref: string;
    id: number;
    url: string;
    product_id: number;
    product_name: string;
    kind_label: string;
    imported: boolean;
  }[];
};

export type Plan = { recipe: string; operations: Operation[]; node: NodeStatus; findings: Finding[] };

const base = (store: string) => `/stores/${store}/photo-editor`;

export const photoApi = {
  overview: (store: string) => api.get<Overview>(`${base(store)}/`).then((r) => r.data),
  sources: (store: string) => api.get<Sources>(`${base(store)}/sources/`).then((r) => r.data),
  upload: (store: string, files: File[]) => {
    const body = new FormData();
    files.forEach((f) => body.append("files", f));
    return api
      .post<{ assets: Asset[]; errors: string[] }>(`${base(store)}/assets/`, body)
      .then((r) => r.data);
  },
  importRefs: (store: string, refs: string[]) =>
    api.post<{ assets: Asset[]; errors: string[] }>(`${base(store)}/assets/`, { refs }).then((r) => r.data),
  asset: (store: string, id: number) =>
    api.get<{ asset: Asset }>(`${base(store)}/assets/${id}/`).then((r) => r.data.asset),
  removeAsset: (store: string, id: number) => api.delete(`${base(store)}/assets/${id}/`),
  analyze: (store: string, id: number) =>
    api.post<{ asset: Asset }>(`${base(store)}/assets/${id}/analyze/`).then((r) => r.data.asset),
  plan: (store: string, asset: number, recipe: string) =>
    api.post<Plan>(`${base(store)}/plan/`, { asset, recipe }).then((r) => r.data),
  apply: (store: string, assets: number[], recipe: string, operations: Operation[]) =>
    api
      .post<{ batch: string; edits: Edit[]; node: NodeStatus }>(`${base(store)}/edits/`, {
        assets,
        recipe,
        operations: operations.map((o) => ({ tool: o.tool, params: o.params, on: o.on !== false })),
      })
      .then((r) => r.data),
  /** «پیشنهادی» برای چند عکس: کارها را سرور برای هر عکس از روی اندازه‌گیریِ خودش می‌چیند */
  applyRecipe: (store: string, assets: number[], recipe: string) =>
    api
      .post<{ batch: string; edits: Edit[]; node: NodeStatus }>(`${base(store)}/edits/`, { assets, recipe })
      .then((r) => r.data),
  edits: (store: string, ids: number[]) =>
    api
      .get<{ edits: Edit[]; node: NodeStatus }>(`${base(store)}/edits/`, { params: { ids: ids.join(",") } })
      .then((r) => r.data),
  action: (store: string, id: number, action: string, body: Record<string, unknown> = {}) =>
    api.post<{ edit: Edit; new?: Edit }>(`${base(store)}/edits/${id}/${action}/`, body).then((r) => r.data),
  removeEdit: (store: string, id: number) => api.delete(`${base(store)}/edits/${id}/`),
  /** پیش‌نمایشِ دقیقِ کارهای سرورِ سایت (متن، لوگو، برش، چرخش…) — کارهای کیت در info.skipped می‌آیند */
  preview: async (store: string, asset: number, operations: Operation[]) => {
    let r;
    try {
      r = await api.post<Blob>(
        `${base(store)}/preview/`,
        { asset, operations: operations.map((o) => ({ tool: o.tool, params: o.params, on: o.on !== false })) },
        { responseType: "blob" },
      );
    } catch (err) {
      // خطای ۴۰۰ هم به‌صورتِ blob می‌آید؛ جملهٔ فارسیِ سرور را بیرون بکشیم
      const data = (err as { response?: { data?: unknown } }).response?.data;
      if (data instanceof Blob) {
        try {
          const j = JSON.parse(await data.text());
          if (j?.error?.message) throw new Error(String(j.error.message));
        } catch (inner) {
          if (inner instanceof Error && inner.message && !(inner instanceof SyntaxError)) throw inner;
        }
      }
      throw err;
    }
    let info: PreviewInfo = { size: [0, 0], notes: [], skipped: [] };
    try {
      info = JSON.parse(decodeURIComponent(String(r.headers["x-preview-info"] ?? "{}")));
    } catch {
      /* هدر نبود */
    }
    return { blob: r.data, info };
  },
  zip: (store: string, batch: string) =>
    api.get<Blob>(`${base(store)}/batches/${batch}/zip/`, { responseType: "blob" }).then((r) => r.data),
};

export type PreviewInfo = { size: [number, number]; notes: string[]; skipped: string[] };

// ───────────────────────────── ادیتورِ حرفه‌ای: پروژه، ماسک، پیش‌نمایشِ دقیق، پریست

export type ProjectSummary = { id: number; asset: number; title: string; rev: number; updated_at: string; thumb: string | null };
export type Project = ProjectSummary & { data: Record<string, unknown>; masks: Record<string, string> };
export type ExactStart = {
  online: boolean;
  state: "OFFLINE" | "NOOP" | "QUEUED" | "RUNNING" | "COMPLETED";
  job?: string;
  ignored?: string[];
  nodes?: string[];
  size?: [number, number];
};
export type ExactStatus = {
  job: string;
  state: "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";
  message?: string;
  progress?: number;
  node?: string;
  url?: string | null;
  size?: [number, number];
  online?: boolean;
  error?: string;
};
export type SubjectResult = {
  state: "READY" | "QUEUED" | "RUNNING" | "FAILED";
  method?: string;
  job?: string;
  url?: string;
  w?: number;
  h?: number;
  message?: string;
  error?: string;
};
export type Preset = { id: number; name: string; kind: string; data: Record<string, unknown>; created_at: string; updated_at: string };
export type FontInfo = { key: string; title: string; family: string; weights: number[]; rtl: boolean };

type PresetBody = { preset?: Preset } & Partial<Preset>;

export const proApi = {
  projects: (store: string, asset: number) =>
    api.get<{ projects: ProjectSummary[] }>(`${base(store)}/projects/`, { params: { asset } }).then((r) => r.data.projects),
  createProject: (store: string, asset: number, data?: Record<string, unknown>, title?: string) =>
    api.post<{ project: Project }>(`${base(store)}/projects/`, { asset, data, title }).then((r) => r.data.project),
  project: (store: string, id: number) => api.get<{ project: Project }>(`${base(store)}/projects/${id}/`).then((r) => r.data.project),
  saveProject: (store: string, id: number, data: Record<string, unknown>, rev?: number, title?: string) =>
    api.put<{ project: Project }>(`${base(store)}/projects/${id}/`, { data, rev, title }).then((r) => r.data.project),
  removeProject: (store: string, id: number) => api.delete(`${base(store)}/projects/${id}/`),
  putMask: (store: string, pid: number, mid: string, blob: Blob) =>
    api
      .put<{ id: string; url: string; w: number; h: number }>(`${base(store)}/projects/${pid}/masks/${mid}/`, blob, {
        headers: { "Content-Type": "image/png" },
      })
      .then((r) => r.data),
  exact: (store: string, asset: number, operations: { tool: string; params: Params }[], side = 1280) =>
    api.post<ExactStart>(`${base(store)}/exact/`, { asset, operations, side }).then((r) => r.data),
  exactStatus: (store: string, job: string) => api.get<ExactStatus>(`${base(store)}/exact/${job}/`).then((r) => r.data),
  exactCancel: (store: string, job: string) => api.delete(`${base(store)}/exact/${job}/`).catch(() => undefined),
  subject: (store: string, asset: number, rect?: [number, number, number, number]) =>
    api.post<SubjectResult>(`${base(store)}/subject/`, { asset, rect }).then((r) => r.data),
  subjectStatus: (store: string, job: string) => api.get<SubjectResult>(`${base(store)}/subject/${job}/`).then((r) => r.data),
  fonts: (store: string) => api.get<{ fonts: FontInfo[] }>(`${base(store)}/fonts/`).then((r) => r.data.fonts),
  presets: (store: string) => api.get<{ presets: Preset[] }>(`${base(store)}/presets/`).then((r) => r.data.presets),
  createPreset: (store: string, name: string, data: Record<string, unknown>, kind = "develop") =>
    api.post<PresetBody>(`${base(store)}/presets/`, { name, kind, data }).then((r) => (r.data.preset ?? r.data) as Preset),
  patchPreset: (store: string, id: number, body: { name?: string; data?: Record<string, unknown> }) =>
    api.patch<PresetBody>(`${base(store)}/presets/${id}/`, body).then((r) => (r.data.preset ?? r.data) as Preset),
  removePreset: (store: string, id: number) => api.delete(`${base(store)}/presets/${id}/`),
  applyPreset: (store: string, id: number, assets: number[]) =>
    api
      .post<{ batch: string; edits: Edit[]; node: NodeStatus }>(`${base(store)}/presets/${id}/apply/`, { assets })
      .then((r) => r.data),
};

export const ACTIVE_STATES = ["QUEUED", "NODE", "SERVER"];

export function stateTone(state: Edit["state"]): "ok" | "warn" | "bad" | "info" | "neutral" {
  return (
    { READY: "ok", FAILED: "bad", CANCELLED: "neutral", NODE: "warn", SERVER: "info", QUEUED: "info" } as const
  )[state];
}
