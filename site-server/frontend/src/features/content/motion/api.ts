import { api } from "../../../api/client";
import type { Queued } from "../../../components/QueuedAi";

/** «استودیوی موشن» — همان شکلِ backend/apps/motion/views.py */

export type StyleDef = {
  id: string;
  name_fa: string;
  name_en: string;
  inspired?: string | null;
  group: string;
  group_label: string;
  about: string;
  /** برای چه فروشگاهی مناسب است (فقط سبک‌هایی که دارند) */
  fits?: string;
  tags: string[];
  palette: Record<string, string>;
  font: { latin: string; fa: string };
  /** «سبکِ تازه»: سبکی که کاربر ساخته (فروشگاهی یا همگانی) */
  custom?: boolean;
  pk?: number;
  scope?: "store" | "global";
  thumb_url?: string;
  store_id?: number | null;
  base_style?: string;
  qa?: { state?: string; summary?: string; geometry?: boolean; at?: string };
};

/** یک توکنِ پارامتردار: `{kind: "grid", size: 44, ...}` */
export type Tok = { kind?: string; fx?: string; [k: string]: unknown };

/** سبک به شکلی که ویرایشگر می‌خواند و می‌نویسد (backend/apps/motion/custom.py: sanitize) */
export type StyleDoc = {
  name_fa: string;
  name_en: string;
  about: string;
  tags: string[];
  group: string;
  palette: Record<string, string>;
  font: { latin: string; fa: string; weight: number; body_latin: string | null; body_fa: string | null; case: "none" | "upper"; track: number; lh: number };
  bg: Tok;
  bg2: Tok | null;
  tex: Tok[];
  decor: Tok[];
  text: Tok;
  shape: Record<string, unknown>;
  motion: { enter: string; spring: [number, number, number]; ease: string; stagger: number; stepFps: number | null; wobble: number; cam: { zoom?: number; pan?: [number, number]; rot?: number; sway?: number } | null };
  trans: { kind: string; frames: number };
  fx: Record<string, unknown>;
};

export type ParamSpec = {
  t: "num" | "bool" | "color" | "colors" | "enum" | "enumlist" | "pos" | "rgb" | "palmap" | "fill";
  label: string;
  min?: number;
  max?: number;
  int?: boolean;
  default?: number;
  choices?: string[];
};
export type KindDef = { id: string; label: string; params: Record<string, ParamSpec> };
export type StyleSchema = {
  version: number;
  roles: string[];
  role_labels: Record<string, string>;
  fonts: { key: string; family: string; license: string; fa: boolean; weights: number[] }[];
  bg: KindDef[];
  decor: KindDef[];
  tex: KindDef[];
  text: KindDef[];
  enters: { id: string; label: string }[];
  transitions: { id: string; label: string }[];
  eases: { id: string; label: string }[];
  springs: { id: string; label: string; value: [number, number, number] }[];
  personalities: { id: string; name: string; motion: StyleDoc["motion"]; trans: [string, number] }[];
  shape: Record<string, ParamSpec>;
  fx: Record<string, [number, number]>;
  guard: { fg: string; bg: string; need: number; severity: string; what: string }[];
  groups: Record<string, string>;
  limits: { per_store: number; global: number; tex: number; decor: number };
  blank: StyleDoc;
};
export type ContrastCheck = { fg: string; bg: string; ratio: number; need: number; severity: "ok" | "warn" | "error"; ok: boolean; message: string };
export type ContrastReport = { ok: boolean; checks: ContrastCheck[]; errors: string[]; warnings: string[] };
export type StyleFinding = { code: string; label: string; scene?: number | null; message: string; aspect?: string };
export type StyleCheck = {
  id: number;
  state: "running" | "pass" | "fail" | "error";
  hash: string;
  summary: string;
  progress: number;
  errors: StyleFinding[];
  warnings: StyleFinding[];
  geometry: boolean;
  frames: number;
  contrast?: ContrastReport | null;
  shots: { aspect: string; scene: number; kind: string; image_url?: string }[];
  thumb_url: string;
  at: string;
};

export type SceneType = string;

export type Scene = { type: SceneType; duration: number; [k: string]: unknown };

export type Brand = { name?: string; colors?: string[]; logo?: string; use_brand_colors?: boolean; show_logo?: boolean };

export type AudioCfg = {
  voice?: { on: boolean; voice_id: string; speed?: number };
  music?: { on: boolean; ref: string; level_db?: number };
  sfx?: boolean;
  beat_sync?: boolean;
};

export type Spec = {
  version?: number;
  platform?: string;
  captions?: { on: boolean; position?: string };
  audio?: AudioCfg;
  bare?: boolean;
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

export type FieldSpec = {
  kind: "str" | "num" | "int" | "bool" | "enum" | "ref" | "strs" | "objs";
  max?: number;
  min?: number;
  choices?: string[];
  max_items?: number;
  item_max?: number;
  fields?: Record<string, FieldSpec>;
};

export type Comp = {
  id: string;
  label: string;
  group: "scene" | "data" | "text";
  group_label: string;
  overlay: boolean;
  fields: Record<string, FieldSpec>;
  sample: Scene;
  need: string[];
  duration: { min: number; typical: number; max: number };
  about: string;
};

export type NamedItem = { id: string; name: string };

export type Library = {
  components: Comp[];
  groups: Record<string, string>;
  eases: NamedItem[];
  springs: NamedItem[];
  camera_moves: NamedItem[];
  exits: NamedItem[];
  enters: string[];
  transitions: string[];
  transition_pack: string[];
  platforms: { id: string; name: string; aspect: string; safe: { top: number; right: number; bottom: number; left: number } }[];
  icons: string[];
  icon_labels: Record<string, string>;
  emoji?: string[];
  emoji_labels?: Record<string, string>;
  anchors: string[];
  sfx_kinds: string[];
  templates: { id: string; name: string; scenes: string[] }[];
  schema_version: number;
  rules: { read_s_per_word: number; min_font_frac: number; min_contrast: number; lufs: number; max_words_per_scene: number };
};

export type Finding = {
  code: string;
  label: string;
  severity: "error" | "warn" | "info";
  scene: number | null;
  message: string;
  auto: boolean;
  ops: unknown[];
  why?: string;
  stuck?: string;
  shot?: { kind: string; frame: number };
};
export type QaShot = { scene: number; kind: string; frame: number; image_rel?: string; image_url?: string; W?: number; H?: number };
export type QaRound = { n: number; findings: Finding[]; applied: { code: string; scene: number | null; message: string; ops: unknown[] }[]; unresolved?: Finding[]; shots: QaShot[] };
export type QaProgress = { n?: number; rounds?: number; phase?: "start" | "lock" | "measure" | "frames" | "fix" | "final"; message?: string };
export type QaReport = {
  state?: "running" | "done" | "failed";
  summary?: string;
  progress?: QaProgress;
  started_at?: string;
  beat?: string;
  reverted?: boolean;
  timed_out?: boolean;
  kept?: { state: number; of: number };
  rounds?: QaRound[];
  fixed?: number;
  remaining?: Finding[];
  info?: Finding[];
  geometry?: boolean;
  geometry_error?: string;
  geometry_skipped?: string;
  applied?: boolean;
  at?: string;
};
export type CritiqueShot = { scene: number; frame: number; image_rel?: string; image_url?: string };
export type CritiqueRound = {
  n: number;
  verdict: "ok" | "fix";
  issues: { scene: number; problem: string; severity: "low" | "medium" | "high" }[];
  ops: unknown[];
  applied: unknown[];
  rejected: { op: unknown; why: string }[];
  before: CritiqueShot[];
  after: CritiqueShot[];
};
export type Critique = { state?: "waiting" | "running" | "done" | "failed" | "unavailable"; message?: string; rounds?: CritiqueRound[]; attempts?: number };
export type HistoryRow = { n: number; label: string; source: string; current: boolean; created_at: string };
export type PlanDTO = {
  id: number;
  title: string;
  spec: Spec;
  rev: number;
  can_undo: boolean;
  can_redo: boolean;
  qa: QaReport;
  critique: Critique;
  history?: HistoryRow[];
  warnings?: string[];
  updated_at: string;
};
export type PlanRow = { id: number; title: string; updated_at: string; rev: number; style?: string; aspect?: string; scenes: number; renders: number };
export type SoundInfo = {
  voices: { id: string; name: string; where: string; available: boolean; gender?: string }[];
  music: { ref: string; title: string; duration: number; bpm?: number; license: string }[];
  note: string;
  hint: string;
};

export type RenderRow = {
  id: number;
  mode: "template" | "ai" | "code";
  mode_label: string;
  title: string;
  style: string;
  style_name: string;
  aspect: string;
  state: "QUEUED" | "PREPARING" | "WAITING_NODE" | "RENDERING" | "READY" | "FAILED" | "CANCELLED";
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
  plan_id?: number | null;
  qa?: QaReport;
  audio?: { has_audio?: boolean; error?: string; mux?: string; voice?: { engine?: string; cue_source?: string; note?: string }; music?: { title?: string; bpm?: number }; mix?: { lufs?: number } };
  has_audio?: boolean;
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
  /** بستهٔ موشنِ گره سبک‌های شخصی را می‌کشد؟ (بدونِ گره = رندرِ سایت = همیشه) */
  style_def?: boolean;
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
  sources: (id: string | number, refs?: string[]) => api.get<{ sources: Source[] }>(`${base(id)}/sources/`, refs && refs.length ? { params: { refs: refs.join(",") } } : undefined).then((r) => r.data.sources),
  upload: (id: string | number, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return api.post<{ assets: { id: number; ref: string; title: string; url: string }[]; errors: string[] }>(`${base(id)}/assets/`, fd).then((r) => r.data);
  },
  preview: (id: string | number, spec: Spec) => api.post<{ spec: Spec; total_s: number }>(`${base(id)}/preview/`, { spec }).then((r) => r.data),
  ai: (id: string | number, body: { idea: string; style: string; aspect: string; lang: string; seconds?: number; brand?: Brand; platform?: string }) =>
    api.post<{ spec: Spec; source: "ai" | "rules"; message: string; title: string; components?: string[]; queued?: Queued }>(`${base(id)}/ai/`, body).then((r) => r.data),
  library: () => api.get<Library>("/motion/library/").then((r) => r.data),
  sound: (id: string | number) => api.get<SoundInfo>(`${base(id)}/sound/`).then((r) => r.data),
  createPlan: (id: string | number, spec: Spec, title = "") => api.post<{ plan: PlanDTO }>(`${base(id)}/plans/`, { spec, title }).then((r) => r.data.plan),
  plans: (id: string | number) => api.get<{ plans: PlanRow[] }>(`${base(id)}/plans/`).then((r) => r.data.plans),
  deletePlan: (id: string | number, pid: number) => api.delete(`${base(id)}/plans/${pid}/`).then(() => undefined),
  plan: (id: string | number, pid: number) => api.get<{ plan: PlanDTO }>(`${base(id)}/plans/${pid}/`).then((r) => r.data.plan),
  savePlan: (id: string | number, pid: number, spec: Spec, title = "") =>
    api.put<{ plan: PlanDTO; notes: string[] }>(`${base(id)}/plans/${pid}/`, { spec, title }).then((r) => r.data),
  patchPlan: (id: string | number, pid: number, ops: unknown[], label = "") =>
    api.post<{ plan: PlanDTO; changes: string[] }>(`${base(id)}/plans/${pid}/patch/`, { ops, label }).then((r) => r.data),
  chat: (id: string | number, pid: number, text: string) =>
    api.post<{ plan: PlanDTO; say: string; source: "ai" | "rules"; message: string; applied: boolean; changes?: string[] }>(`${base(id)}/plans/${pid}/chat/`, { text }).then((r) => r.data),
  planStep: (id: string | number, pid: number, action: "undo" | "redo") => api.post<{ plan: PlanDTO }>(`${base(id)}/plans/${pid}/${action}/`, {}).then((r) => r.data.plan),
  restore: (id: string | number, pid: number, n: number) => api.post<{ plan: PlanDTO }>(`${base(id)}/plans/${pid}/restore/`, { n }).then((r) => r.data.plan),
  runQa: (id: string | number, pid: number, apply = true, geometry = true) =>
    api.post<{ plan: PlanDTO }>(`${base(id)}/plans/${pid}/qa/`, { apply, geometry }).then((r) => r.data.plan),
  runCritique: (id: string | number, pid: number) => api.post<{ plan: PlanDTO }>(`${base(id)}/plans/${pid}/critique/`, {}).then((r) => r.data.plan),
  renderPlan: (id: string | number, pid: number, body: Record<string, unknown>) =>
    api.post<{ render: RenderRow; node: NodeInfo }>(`${base(id)}/plans/${pid}/render/`, body).then((r) => r.data),
  aiCode: (id: string | number, body: { idea: string; style?: string; aspect?: string }) =>
    api.post<{ code?: string; warning?: string; queued?: Queued; message?: string }>(`${base(id)}/ai-code/`, body).then((r) => r.data),
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

export const customApi = {
  schema: () => api.get<StyleSchema>("/motion/style-schema/").then((r) => r.data),
  list: (id: string | number) => api.get<{ styles: StyleDef[]; can_global: boolean; limits: { per_store: number; global: number } }>(`${base(id)}/custom-styles/`).then((r) => r.data),
  get: (id: string | number, pk: number) => api.get<{ style: StyleDef & StyleDoc }>(`${base(id)}/custom-styles/${pk}/`).then((r) => r.data.style),
  save: (id: string | number, body: { style: StyleDoc; scope: "store" | "global"; base_style?: string }) =>
    api.post<{ style: StyleDef }>(`${base(id)}/custom-styles/`, body).then((r) => r.data.style),
  update: (id: string | number, pk: number, style: StyleDoc) => api.put<{ style: StyleDef }>(`${base(id)}/custom-styles/${pk}/`, { style }).then((r) => r.data.style),
  remove: (id: string | number, pk: number) => api.delete(`${base(id)}/custom-styles/${pk}/`).then(() => undefined),
  exportJson: (id: string | number, pk: number) => api.get<{ nm_motion_style: number; style: StyleDoc }>(`${base(id)}/custom-styles/${pk}/export/`).then((r) => r.data),
  importJson: (id: string | number, json: unknown) =>
    api.post<{ style: StyleDoc; notes: string[]; contrast: ContrastReport }>(`${base(id)}/custom-styles/import/`, { json }).then((r) => r.data),
  validate: (id: string | number, style: StyleDoc) =>
    api.post<{ style: StyleDoc; notes: string[]; contrast: ContrastReport; hash: string; fixed_palette?: Record<string, string> }>(`${base(id)}/custom-styles/validate/`, { style }).then((r) => r.data),
  describe: (id: string | number, text: string, baseStyle?: string) =>
    api.post<{ style: StyleDoc; source: "ai" | "rules"; message: string; contrast: ContrastReport }>(`${base(id)}/custom-styles/describe/`, { text, base_style: baseStyle }).then((r) => r.data),
  palette: (id: string | number, colors?: string[], dark?: boolean) =>
    api.post<{ palette: Record<string, string>; from: string[] }>(`${base(id)}/custom-styles/palette/`, { colors, dark }).then((r) => r.data),
  preview: (id: string | number, style: StyleDoc, aspect: string, scenes = 2) =>
    api.post<{ spec: Spec }>(`${base(id)}/custom-styles/preview/`, { style, aspect, scenes }).then((r) => r.data.spec),
  check: (id: string | number, style: StyleDoc) =>
    api.post<{ check: StyleCheck; fixed_palette: Record<string, string> | null }>(`${base(id)}/custom-styles/check/`, { style }).then((r) => r.data),
  checkGet: (id: string | number, cid: number) => api.get<{ check: StyleCheck }>(`${base(id)}/custom-styles/check/${cid}/`).then((r) => r.data.check),
};

export const thumbUrl = (styleId: string) => `/api/v1/motion/styles/${styleId}/thumb/`;
export const PLAYER_URL = "/api/v1/motion/player/";

export const SCENE_LABELS: Record<string, string> = {
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

export const COMPONENT_THUMB = (cid: string) => `/api/v1/motion/components/${cid}/thumb/`;

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
