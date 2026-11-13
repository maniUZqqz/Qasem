import { api } from "../../../api/client";

/** «استودیوی موشن» — همان شکلِ backend/apps/motion/views.py */

export type StyleDef = {
  id: string;
  name_fa: string;
  name_en: string;
  inspired?: string | null;
  group: string;
  group_label: string;
  about: string;
  tags: string[];
  palette: Record<string, string>;
  font: { latin: string; fa: string };
};

export type SceneType = "title" | "list" | "quote" | "stat" | "compare" | "product" | "logo" | "app" | "cta";

export type Scene = { type: SceneType; duration: number; [k: string]: unknown };

export type Brand = { name?: string; colors?: string[]; logo?: string; use_brand_colors?: boolean; show_logo?: boolean };

export type Spec = {
  version?: number;
  style: string;
  aspect: string;
  fps?: number;
  lang?: "fa" | "en";
  digits?: "fa" | "en" | "auto";
  brand?: Brand;
  scenes: Scene[];
  intensity?: number;
  transition?: string;
  total_s?: number;
  assets?: Record<string, string>;
};

export type Catalog = {
  styles: StyleDef[];
  groups: Record<string, string>;
  templates: { id: string; name: string; scenes: SceneType[] }[];
  scene_types: { id: SceneType; name: string }[];
  aspects: { id: string; name: string; width: number; height: number }[];
  transitions: string[];
};

export type RenderRow = {
  id: number;
  mode: "template" | "ai" | "code";
  mode_label: string;
  title: string;
  style: string;
  style_name: string;
  aspect: string;
  state: "QUEUED" | "WAITING_NODE" | "RENDERING" | "READY" | "FAILED" | "CANCELLED";
  state_label: string;
  active: boolean;
  progress: number;
  message: string;
  error: string;
  target: "node" | "site";
  target_label: string;
  quality: string | null;
  duration_s: number;
  width: number;
  height: number;
  bytes: number;
  render_s: number;
  video_id: number | null;
  video_ref: string | null;
  video_url: string | null;
  poster_url: string | null;
  created_at: string;
  finished_at: string | null;
  job_uid: string;
};

export type NodeInfo = {
  registered: number;
  capable: number;
  online: number;
  capable_online: number;
  state: "none" | "ready" | "installing" | "failed" | "checking" | "offline" | "outdated";
  message: string;
  detail: { state?: string; progress?: number; message?: string; error?: string; gl?: string; gpu?: boolean };
  names: string[];
};

export type Overview = {
  renders: RenderRow[];
  node: NodeInfo;
  site: { ready: boolean; reasons: string[] };
  brand: { name: string; colors: string[]; logo: string | null; logo_url: string | null };
  limits: {
    max_scenes: number;
    max_total_node: number;
    max_total_site: number;
    site_max_short_side: number;
    qualities: string[];
    default_quality: string;
    fps: number[];
    max_code_kb: number;
  };
  code: { samples: { id: string; title: string; code: string }[]; allowed_imports: string[] };
  sample_spec: Spec;
};

export type Source = { ref: string; title: string; url: string; group: string };

const base = (id: string | number) => `/stores/${id}/motion`;

export const motionApi = {
  catalog: () => api.get<Catalog>("/motion/styles/").then((r) => r.data),
  overview: (id: string | number) => api.get<Overview>(`${base(id)}/`).then((r) => r.data),
  sources: (id: string | number) => api.get<{ sources: Source[] }>(`${base(id)}/sources/`).then((r) => r.data.sources),
  upload: (id: string | number, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return api.post<{ assets: { id: number; ref: string; title: string; url: string }[]; errors: string[] }>(`${base(id)}/assets/`, fd).then((r) => r.data);
  },
  preview: (id: string | number, spec: Spec) => api.post<{ spec: Spec; total_s: number }>(`${base(id)}/preview/`, { spec }).then((r) => r.data),
  ai: (id: string | number, body: { idea: string; style: string; aspect: string; lang: string; seconds?: number; brand?: Brand }) =>
    api.post<{ spec: Spec; source: "ai" | "rules"; message: string; title: string }>(`${base(id)}/ai/`, body).then((r) => r.data),
  aiCode: (id: string | number, body: { idea: string; style?: string; aspect?: string }) =>
    api.post<{ code: string; warning: string }>(`${base(id)}/ai-code/`, body).then((r) => r.data),
  checkCode: (id: string | number, code: string) =>
    api.post<{ ok: boolean; error?: string; line?: number | null; kind?: string }>(`${base(id)}/code/check/`, { code }).then((r) => r.data),
  render: (id: string | number, body: Record<string, unknown>) =>
    api.post<{ render: RenderRow; node: NodeInfo }>(`${base(id)}/renders/`, body).then((r) => r.data),
  renders: (id: string | number) => api.get<{ renders: RenderRow[] }>(`${base(id)}/renders/`).then((r) => r.data.renders),
  one: (id: string | number, rid: number, full = false) =>
    api.get<{ render: RenderRow & { spec?: Spec; code?: string } }>(`${base(id)}/renders/${rid}/${full ? "?full=1" : ""}`).then((r) => r.data.render),
  act: (id: string | number, rid: number, action: "cancel" | "site" | "retry") =>
    api.post<{ render: RenderRow }>(`${base(id)}/renders/${rid}/${action}/`, {}).then((r) => r.data.render),
  remove: (id: string | number, rid: number) => api.delete(`${base(id)}/renders/${rid}/`),
};

export const thumbUrl = (styleId: string) => `/api/v1/motion/styles/${styleId}/thumb/`;
export const PLAYER_URL = "/api/v1/motion/player/";

export const SCENE_LABELS: Record<SceneType, string> = {
  title: "کارتِ عنوان",
  list: "فهرست / مراحل",
  quote: "نقل‌قول",
  stat: "عددِ بزرگ",
  compare: "قبل و بعد",
  product: "معرفیِ محصول",
  logo: "لوگو (استینگ)",
  app: "نمایشِ اپ در قابِ گوشی",
  cta: "دعوت به اقدام",
};

export const QUALITY_LABELS: Record<string, string> = {
  "360": "۳۶۰ (پیش‌نمایشِ سریع)",
  "540": "۵۴۰",
  "720": "۷۲۰ (HD)",
  "1080": "۱۰۸۰ (Full HD)",
};

export function errText(e: unknown): string {
  const any = e as { response?: { data?: { error?: { message?: string }; detail?: string } }; message?: string };
  return any?.response?.data?.error?.message || any?.response?.data?.detail || any?.message || "خطای نامشخص";
}
