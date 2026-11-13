import { api } from "../../../api/client";

/** «تامنیل‌ساز» — همان شکلِ backend/apps/thumbs (views.py، render.py). */

export type FormatInfo = {
  key: string;
  title: string;
  platform: string;
  width: number;
  height: number;
  aspect: string;
  orient: "wide" | "square" | "portrait" | "tall";
  note: string;
  max_kb: number;
  margin: [number, number, number, number];
  avoid: { rect: [number, number, number, number]; note: string }[];
};

export type StyleInfo = {
  key: string;
  title: string;
  short: string;
  pattern: string;
  mood: string;
  mood_fa: string;
  font: string;
  family: string;
  subject: "none" | "optional" | "recommended";
  fields: { key: string; label: string }[];
  formats: string[];
  needs_second: boolean;
  tips: string[];
};

export type Content = {
  title: string;
  subtitle: string;
  kicker: string;
  number: string;
  badge: string;
  tagline: string;
  credits: string;
  cta: string;
  label_a: string;
  label_b: string;
};

export type Spec = {
  format: string;
  style: string;
  content: Content;
  colors: { mood: string; primary: string; secondary: string; accent: string; use_brand: boolean; variation: number };
  font: string;
  background: { kind: "auto" | "gradient" | "texture" | "photo" | "ai"; asset: number | null; texture: string; darken: number; blur: number; job: string };
  subject: { asset: number | null; mode: "auto" | "cutout" | "photo"; side: "auto" | "left" | "right" | "center"; scale: number; outline: boolean };
  subject2: { asset: number | null };
  extra_assets: number[];
  logo: { show: boolean; position: string };
  accents: { arrow: boolean };
  seed: number;
  guides: boolean;
};

export type Layer = { name: string; kind: string; bbox: number[]; blend: string; opacity: number };

export type LibraryAsset = {
  id: number;
  title: string;
  thumb: string | null;
  url: string | null;
  width: number;
  height: number;
  has_alpha: boolean;
  source_kind: string;
  product: number | null;
};

export type ProductRow = { id: number; name: string; image_ref: string; has_price: boolean; price_text: string };

export type AiAvailability = {
  possible: boolean; online: boolean; model: string; message: string;
  selftest?: { state: "none" | "waiting" | "running" | "ok" | "failed"; message: string };
};

export type ThumbItem = {
  id: number;
  title: string;
  format: string;
  format_title: string;
  style: string;
  style_title: string;
  batch: string;
  variant: string;
  variant_note: string;
  state: "READY" | "WAITING_BG" | "FAILED";
  state_fa: string;
  message: string;
  width: number;
  height: number;
  size_kb: number;
  created_at: string;
  asset: number | null;
  urls: { png?: string; jpg?: string; thumb?: string };
  warnings: string[];
  bg_job: string;
  waiting_bg: boolean;
  spec?: Spec;
  layers?: Layer[];
  texts?: { name: string; bbox: number[]; px: number; lines: number; text: string }[];
  palette?: Record<string, string | boolean>;
  ai?: { prompt?: string; engine?: string; note?: string; error?: string };
};

export type Overview = {
  formats: FormatInfo[];
  default_format: string;
  styles: StyleInfo[];
  fonts: { key: string; title: string }[];
  moods: { key: string; title: string }[];
  brand: { colors: string[]; heading_font: string; has_logo: boolean; store_name: string };
  ai_background: AiAvailability;
  bg_presets: { key: string; title: string }[];
  products: ProductRow[];
  limits: { max_variants: number; text: Record<string, number> };
  items: ThumbItem[];
};

export type Idea = {
  id: string;
  title: string;
  subtitle: string;
  kicker: string;
  number: string;
  badge: string;
  tagline: string;
  credits: string;
  cta: string;
  label_a: string;
  label_b: string;
  style: string;
  style_title: string;
  format: string;
  formula: string;
  formula_label: string;
  source: "ai" | "rules";
  concept: string;
  bg_prompt_en: string;
  mood: string;
  needs_second: boolean;
  spec_patch: { format: string; style: string; content: Partial<Content>; colors: { mood: string } };
};

export type IdeasResult = {
  id?: number;
  topic: string;
  format: string;
  via: "ai" | "rules" | "mixed";
  ai: { tried: boolean; ok: boolean; label: string; reason: string };
  message: string;
  ideas: Idea[];
};

export type Archetype = {
  key: string;
  origin: string;
  origin_label: string;
  title: string;
  style: string;
  pattern: string;
  why: string;
  dos: string[];
  donts: string[];
  text_rule: string;
  palette: string;
  formats: string[];
  sample: string;
};

export type Preview = {
  image: string;
  width: number;
  height: number;
  layers: Layer[];
  warnings: string[];
  palette: Record<string, string | boolean>;
  spec: Spec;
};

export type BgJob = {
  job: string;
  state: "QUEUED" | "RUNNING" | "READY" | "FAILED" | "CANCELLED" | "COMPLETED";
  message: string;
  progress?: number;
  error?: string;
  asset?: LibraryAsset;
  engine?: string;
  online?: boolean;
};

export type CutoutNodeModel = { id: string; title: string; hint: string; state: string; state_fa: string; installed_on: string[] };

const P = (id: string) => `/stores/${id}/thumbnails`;

export const thumbsApi = {
  overview: async (id: string) => (await api.get<Overview>(`${P(id)}/`)).data,
  moodboard: async (id: string) => (await api.get<{ archetypes: Archetype[]; note: string }>(`${P(id)}/moodboard/`)).data,
  ideas: async (id: string, body: Record<string, unknown>) => (await api.post<IdeasResult>(`${P(id)}/ideas/`, body)).data,
  preview: async (id: string, spec: Spec, signal?: AbortSignal) => (await api.post<Preview>(`${P(id)}/preview/`, { spec }, { signal })).data,
  render: async (id: string, body: { spec: Spec; variants: number; title?: string; ai?: { preset?: string; text?: string; prompt_en?: string } }) =>
    (await api.post<{ items: ThumbItem[]; batch: string }>(`${P(id)}/render/`, body)).data,
  items: async (id: string, before?: number) =>
    (await api.get<{ items: ThumbItem[]; has_more: boolean }>(`${P(id)}/items/`, { params: before ? { before } : {} })).data,
  item: async (id: string, item: number) => (await api.get<ThumbItem>(`${P(id)}/items/${item}/`)).data,
  patch: async (id: string, item: number, body: { title?: string; spec?: Partial<Spec> }) => (await api.patch<ThumbItem>(`${P(id)}/items/${item}/`, body)).data,
  remove: async (id: string, item: number) => api.delete(`${P(id)}/items/${item}/`),
  openInEditor: async (id: string, item: number) =>
    (await api.post<{ asset: { id: number }; url: string }>(`${P(id)}/items/${item}/editor/`)).data,
  downloadUrl: (id: string, item: number, fmt: "png" | "jpg") => `${P(id)}/items/${item}/download/?fmt=${fmt}`,
  layersUrl: (id: string, item: number) => `${P(id)}/items/${item}/layers/`,
  zipUrl: (id: string, batch: string) => `${P(id)}/batches/${batch}/zip/`,
  bgCreate: async (id: string, body: Record<string, unknown>) =>
    (await api.post<{ jobs: BgJob[]; prompt: string; note: string }>(`${P(id)}/backgrounds/`, body)).data,
  bgStatus: async (id: string, uid: string) => (await api.get<BgJob>(`${P(id)}/backgrounds/${uid}/`)).data,
  bgCancel: async (id: string, uid: string) => api.delete(`${P(id)}/backgrounds/${uid}/`),
  library: async (id: string) => (await api.get<{ assets: LibraryAsset[] }>(`${P(id)}/library/`)).data.assets,
  upload: async (id: string, files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return (await api.post<{ assets: LibraryAsset[]; errors: string[] }>(`${P(id)}/library/upload/`, fd)).data;
  },
  importRef: async (id: string, ref: string) => (await api.post<{ asset: LibraryAsset }>(`${P(id)}/library/import/`, { ref })).data.asset,
  cutout: async (id: string, asset: number, model: string) =>
    (await api.post<{ state: string; asset?: LibraryAsset; message?: string; uid?: string; node_possible?: boolean }>(`${P(id)}/cutout/`, { asset, model })).data,
  cutoutStatus: async (id: string, uid: string) =>
    (await api.get<{ state: string; message: string; asset?: LibraryAsset }>(`${P(id)}/cutout/${uid}/`)).data,
  cutoutModels: async (id: string) =>
    (await api.get<{ models: CutoutNodeModel[]; node_online: boolean; node_known: boolean }>(`${P(id)}/cutout/`)).data,
  sampleUrl: (id: string, style: string, format: string) => `/api/v1${P(id)}/styles/${style}/sample.jpg?fmt=${format}`,
};

export const EMPTY_CONTENT: Content = { title: "", subtitle: "", kicker: "", number: "", badge: "", tagline: "", credits: "", cta: "", label_a: "", label_b: "" };

export function defaultSpec(format: string, style = "face_text"): Spec {
  return {
    format, style, content: { ...EMPTY_CONTENT },
    colors: { mood: "", primary: "", secondary: "", accent: "", use_brand: true, variation: 0 },
    font: "auto",
    background: { kind: "auto", asset: null, texture: "", darken: 0, blur: 0, job: "" },
    subject: { asset: null, mode: "auto", side: "auto", scale: 1, outline: true },
    subject2: { asset: null },
    extra_assets: [],
    logo: { show: true, position: "auto" },
    accents: { arrow: true },
    seed: 1,
    guides: false,
  };
}

/** ایده ⇒ spec (فقط قالب، سبک، متن‌ها و حال‌وهوا عوض می‌شود؛ عکس‌ها و رنگ‌ها می‌مانند). */
export function applyIdea(spec: Spec, idea: Idea, keepFormat = false): Spec {
  return {
    ...spec,
    format: keepFormat ? spec.format : idea.spec_patch.format,
    style: idea.spec_patch.style,
    content: { ...EMPTY_CONTENT, ...idea.spec_patch.content },
    colors: { ...spec.colors, mood: idea.spec_patch.colors.mood || "" },
  };
}

/** آیا نسبتِ طول به عرض (۱۶:۹ ⇄ ۹:۱۶) برای نمایشِ پیش‌نمایش؟ */
export function aspectStyle(f: { width: number; height: number } | undefined): { aspectRatio: string } {
  return { aspectRatio: f ? `${f.width} / ${f.height}` : "16 / 9" };
}
