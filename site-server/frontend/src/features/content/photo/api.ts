import { api } from "../../../api/client";

/** «ادیتور عکس» — همان شکلِ backend/apps/photoedit/views.py */

export type Where = "server" | "node";

export type ParamSpec = {
  key: string;
  title: string;
  type: "number" | "select" | "bool" | "text" | "color" | "adjust" | "spots";
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
};

export type Recipe = {
  key: string;
  title: string;
  help: string;
  operations: Operation[];
  needs_node: boolean;
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
  presets: { key: string; title: string; help: string; kind: string }[];
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
  operations: { tool: string; params: Params; title: string; where: Where }[];
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
  zip: (store: string, batch: string) =>
    api.get<Blob>(`${base(store)}/batches/${batch}/zip/`, { responseType: "blob" }).then((r) => r.data),
};

export const ACTIVE_STATES = ["QUEUED", "NODE", "SERVER"];

export function stateTone(state: Edit["state"]): "ok" | "warn" | "bad" | "info" | "neutral" {
  return (
    { READY: "ok", FAILED: "bad", CANCELLED: "neutral", NODE: "warn", SERVER: "info", QUEUED: "info" } as const
  )[state];
}
