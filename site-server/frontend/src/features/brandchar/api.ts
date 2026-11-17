import { api } from "../../api/client";

/** «شخصیتِ برند» — همان شکلِ backend/apps/brandchar (views.py، services.py، persona.py). */

// ───────────────────────────── سندِ شخصیت

export type PathPt = { x: number; y: number; hi: [number, number] | null; ho: [number, number] | null };
export type UnitPath = { closed: boolean; pts: PathPt[] };
export type Anchor = "world" | "head" | "body" | "hand";
export type LayerShape = "rect" | "ellipse" | "line" | "path";

export type Layer = {
  id: string;
  name: string;
  shape: LayerShape;
  anchor: Anchor;
  box: { cx: number; cy: number; w: number; h: number; rot: number };
  fill: string | null;
  stroke: string | null;
  sw: number;
  opacity: number;
  above: boolean;
  hidden: boolean;
  locked: boolean;
  radius: number;
  flip_x: boolean;
  link: string;
  shape_id: string;
  path?: UnitPath;
};

export type CharDoc = {
  name: string;
  style: string;
  body: string;
  head_style: string;
  eye_style: string;
  brows: string;
  nose: string;
  hair: string;
  hat: string;
  neck: string;
  extra: string;
  outfit: string;
  bottoms: string;
  shoes_type: string;
  prop: string;
  logo: string;
  blush: boolean;
  freckles: boolean;
  beard: boolean;
  skin: string;
  hair_colour: string;
  top: string;
  top2: string;
  bottom: string;
  shoes: string;
  hat_colour: string;
  neck_colour: string;
  extra_colour: string;
  prop_colour: string;
  outline: string;
  limb_colour: string;
  head_fill: string;
  line_width: number;
  layers: Layer[];
};

export type PaletteRow = { role: string; hex: string; name: string; name_fa?: string };
export type CheckResult = { at?: string; ok?: boolean; passed?: number; total?: number; seconds?: number; version?: number; style?: string; failed?: { pose: string; size: string; notes: string[] }[] };

export type Character = {
  id: number;
  name: string;
  role: string;
  role_fa: string;
  doc: CharDoc;
  palette: PaletteRow[];
  version: number;
  locked: boolean;
  locked_at: string | null;
  is_primary: boolean;
  brand_colours: string[];
  check: CheckResult;
  concept: Record<string, unknown>;
  has_logo: boolean;
  style: string;
  style_fa: string;
  shots: number;
  stickers: number;
  mascot: number | null;
  cover?: string | null;
  /** «bust» = کارتِ پایدار (نیم‌تنهٔ شفافِ نسخهٔ فعلی)؛ «other» = فعلاً چیزِ دیگری؛ «» = هنوز خروجی‌ای نیست */
  cover_kind?: "bust" | "other" | "";
  updated_at: string;
};

export type Role = { key: string; fa: string; hint: string; background: string; expression: string; pose: string; tags: string[] };
export type PoseInfo = { key: string; fa: string; en: string; tags: string[]; original: boolean };
export type Option = { key: string; fa: string };
export type BackgroundInfo = { key: string; fa: string; en: string; group: "marketing" | "scene" };
export type SizeInfo = { key: string; fa: string; w: number; h: number; aspect: string; safe: [number, number] };
export type StyleInfo = { key: string; fa: string; hint: string; vector: boolean };

export type Options = {
  poses: PoseInfo[];
  pose_tags: { key: string; fa: string; poses: string[] }[];
  expressions: Option[];
  backgrounds: BackgroundInfo[];
  sizes: SizeInfo[];
  choices: Record<string, Option[]>;
  bools: Option[];
  skin_presets: { hex: string; fa: string }[];
  colour_keys: Option[];
  styles: StyleInfo[];
  anchors: Option[];
  layer_shapes: Option[];
  bubble_kinds: Option[];
  positions: Option[];
  crops: Option[];
  limits: { max_layers: number; max_points: number };
};

// ───────────────────────────── شخصیتِ گفتار

export type PersonaData = {
  name: string;
  archetype: string;
  secondary: string;
  tagline: string;
  summary: string;
  audience: string;
  tone: Record<string, number>;
  values: string[];
  do_words: string[];
  dont_words: string[];
  catchphrases: string[];
  emoji: string;
  address: string;
  greeting: string;
  signoff: string;
  sample_lines: { situation: string; text: string }[];
  voice: { voice_id: string; speed: number; gender: string };
};

export type PersonaPublic = {
  exists: boolean;
  data: PersonaData;
  version: number;
  locked: boolean;
  locked_at: string | null;
  active: boolean;
  source: string;
  score: { done: number; total: number; missing: string[] };
  archetype_fa: string;
  archetype_about: string;
  tone_words: string[];
  updated_at: string | null;
};

export type PersonaInfo = PersonaPublic & {
  archetypes: { key: string; fa: string; en: string; about: string; tone: Record<string, number>; values: string[] }[];
  sliders: { key: string; label: string; low: string; high: string }[];
  emoji_policies: Option[];
  address: Option[];
  situations: Option[];
  limits: Record<string, number>;
  voices: { id?: string; name?: string; gender?: string; group?: string; available?: boolean; why?: string }[];
};

export type PersonaDraft = { persona: PersonaData; sources: { fact: string; source: string }[]; notes: string[]; origin: string; ai: { used: boolean; reason: string; label: string }; brief?: { given: boolean; applied: string[]; used_by_ai: boolean } | null; score: PersonaPublic["score"] };

// ───────────────────────────── نمای کلی

export type UsageSurface = { key: string; fa: string; about: string; page: string; count: number };
export type Usage = { surfaces: UsageSurface[]; total: number; persona_active: boolean; injection: { key: string; fa: string; kind: string; active: boolean }[] };

export type Overview = {
  store: { id: number; name: string; colors: string[]; has_logo: boolean };
  roles: Role[];
  options: Options;
  lines: { text: string; source: string }[];
  characters: Character[];
  persona: PersonaPublic;
  limits: { max_characters: number; max_text: number; max_renders: number };
  usage: Usage;
  has_facts: boolean;
  notes: string[];
};

// ───────────────────────────── خروجی‌ها و کار

export type Qa = { ok: boolean; score: number | null; colours: { role: string; hex: string; name: string; name_fa?: string; found: boolean; share: number }[]; notes: string[]; scope: string };
export type Claim = { code: string; label_fa: string; term: string };
export type Scene = {
  size: string;
  pose: string;
  expression: string;
  background: string;
  position: string;
  flip: boolean;
  prop: string;
  bubble?: { text: string; kind: string } | null;
  caption?: { text: string; position: string } | null;
  allow_claims?: boolean;
};
export const DEFAULT_SCENE: Scene = { size: "ig_portrait", pose: "stand", expression: "happy", background: "brand", position: "center", flip: false, prop: "auto", bubble: null, caption: null };

export type AssetRow = { id: number; title: string; thumb: string | null; url: string | null; width: number; height: number; has_alpha: boolean };
export type RenderItem = {
  id: number;
  character: number;
  kind: "shot" | "sticker" | "sheet" | "svg" | "pdf" | "ai" | "template";
  kind_fa: string;
  version: number;
  locked: boolean;
  params: Record<string, unknown>;
  qa: Partial<Qa>;
  width: number;
  height: number;
  asset: AssetRow | null;
  created_at: string;
  urls: { png: string | null; thumb: string | null; download: string };
  size_kb: number;
  cached?: boolean;
};
export type Preview = { image: string; width: number; height: number; qa: Qa; claims: Claim[]; claims_message: string; prop: string };
export type SvgOut = { svg: string; embedded: boolean; view: number[]; anchors?: Record<Anchor, number[]>; head?: number[] };

export type ConceptOption = { index: number; title: string; why: string; source: string; doc: CharDoc; preview?: string; prop?: string; prop_fa?: string };
export type Concept = { id: number; description: string; options: ConceptOption[]; source: string; note: string; chosen: number | null; character: number | null; created_at: string };

export type NodeStatus = { known: boolean; online: boolean; ready: boolean; kind_known: boolean; profiles: string[]; identity_tools: string[]; agent: string; note: string };
export type AiJob = {
  id: number;
  character: number;
  mode: string;
  mode_fa: string;
  look: string;
  look_fa: string;
  pose: string;
  state: "queued" | "running" | "done" | "failed";
  state_fa: string;
  message: string;
  error: string;
  check: { ok?: boolean; palette_score?: number | null; silhouette?: number | null; notes?: string[] };
  progress: number;
  asset: AssetRow | null;
  sticker: AssetRow | null;
  created_at: string;
};

export type TemplateRow = { id: string; fa: string; size: string; size_fa: string; aspect: string; w: number; h: number; pose: string; expression: string; bubble: string; caption: string; kind: string };

export type MotionScene = Record<string, unknown>;

const P = (id: string) => `/stores/${id}/brand-character`;

export const bcApi = {
  overview: async (id: string) => (await api.get<Overview>(`${P(id)}/`)).data,
  node: async (id: string) => (await api.get<NodeStatus>(`${P(id)}/node/`)).data,
  // شخصیتِ گفتار
  persona: async (id: string) => (await api.get<PersonaInfo>(`${P(id)}/persona/`)).data,
  savePersona: async (id: string, data: PersonaData, source = "manual") => (await api.put<PersonaPublic>(`${P(id)}/persona/`, { data, source })).data,
  personaDraft: async (id: string, brief: string, useAi: boolean) => (await api.post<PersonaDraft>(`${P(id)}/persona/draft/`, { brief, use_ai: useAi })).data,
  personaLock: async (id: string) => (await api.post<PersonaPublic>(`${P(id)}/persona/lock/`, {})).data,
  personaUnlock: async (id: string) => (await api.post<PersonaPublic>(`${P(id)}/persona/unlock/`, {})).data,
  personaActive: async (id: string, active: boolean) => (await api.post<PersonaPublic>(`${P(id)}/persona/active/`, { active })).data,
  personaVersions: async (id: string) => (await api.get<{ items: { version: number; source: string; note: string; created_at: string; name: string }[] }>(`${P(id)}/persona/versions/`)).data.items,
  personaRestore: async (id: string, version: number) => (await api.post<PersonaPublic>(`${P(id)}/persona/restore/`, { version })).data,
  personaPrompt: async (id: string, kind: string) => (await api.get<{ text: string; chars: number; limit: number; active: boolean }>(`${P(id)}/persona/prompt/`, { params: { kind } })).data,
  // شخصیتِ دیداری
  create: async (id: string, body: Record<string, unknown>) => (await api.post<Character>(`${P(id)}/characters/`, body)).data,
  patch: async (id: string, cid: number, body: Record<string, unknown>) => (await api.patch<Character>(`${P(id)}/characters/${cid}/`, body)).data,
  remove: async (id: string, cid: number) => api.delete(`${P(id)}/characters/${cid}/`),
  lock: async (id: string, cid: number) => (await api.post<Character>(`${P(id)}/characters/${cid}/lock/`, {})).data,
  unlock: async (id: string, cid: number) => (await api.post<Character>(`${P(id)}/characters/${cid}/unlock/`, {})).data,
  primary: async (id: string, cid: number) => (await api.post<Character>(`${P(id)}/characters/${cid}/primary/`, {})).data,
  publishMascot: async (id: string, cid: number) => (await api.post<{ mascot: number }>(`${P(id)}/characters/${cid}/publish-mascot/`, {})).data,
  check: async (id: string, cid: number) => (await api.post<CheckResult>(`${P(id)}/characters/${cid}/check/`, {})).data,
  cover: async (id: string, cid: number) => (await api.post<Character>(`${P(id)}/characters/${cid}/cover/`, {})).data,
  versions: async (id: string, cid: number) => (await api.get<{ items: { version: number; note: string; created_at: string; style: string }[] }>(`${P(id)}/characters/${cid}/versions/`)).data.items,
  restore: async (id: string, cid: number, version: number) => (await api.post<Character>(`${P(id)}/characters/${cid}/restore/`, { version })).data,
  preview: async (id: string, cid: number, body: Record<string, unknown>, signal?: AbortSignal) => (await api.post<Preview>(`${P(id)}/characters/${cid}/preview/`, body, { signal })).data,
  svg: async (id: string, cid: number, body: Record<string, unknown>, signal?: AbortSignal) => (await api.post<SvgOut>(`${P(id)}/characters/${cid}/svg/`, body, { signal })).data,
  render: async (id: string, cid: number, body: Record<string, unknown>) => (await api.post<RenderItem>(`${P(id)}/characters/${cid}/render/`, body)).data,
  sticker: async (id: string, cid: number, body: Record<string, unknown>) => (await api.post<RenderItem>(`${P(id)}/characters/${cid}/sticker/`, body)).data,
  sheet: async (id: string, cid: number) => (await api.post<RenderItem>(`${P(id)}/characters/${cid}/sheet/`, {})).data,
  sheetPdf: async (id: string, cid: number) => (await api.post<RenderItem>(`${P(id)}/characters/${cid}/sheet-pdf/`, {})).data,
  svgFile: async (id: string, cid: number, body: Record<string, unknown>) => (await api.post<RenderItem>(`${P(id)}/characters/${cid}/svg-file/`, body)).data,
  renders: async (id: string, cid: number, kind?: string, limit = 60) => (await api.get<{ items: RenderItem[] }>(`${P(id)}/characters/${cid}/renders/`, { params: { ...(kind ? { kind } : {}), limit } })).data.items,
  removeRender: async (id: string, cid: number, rid: number) => api.delete(`${P(id)}/characters/${cid}/renders/${rid}/`),
  downloadPath: (id: string, cid: number, rid: number) => `${P(id)}/characters/${cid}/renders/${rid}/download/`,
  exportPath: (id: string, cid: number) => `${P(id)}/characters/${cid}/export/`,
  // ایده و هوش مصنوعی
  concepts: async (id: string, description: string, useAi = true) => (await api.post<Concept>(`${P(id)}/concepts/`, { description, use_ai: useAi })).data,
  conceptList: async (id: string) => (await api.get<{ items: Concept[] }>(`${P(id)}/concepts/`)).data.items,
  choose: async (id: string, cid: number, index: number, name?: string) => (await api.post<{ character: Character; sheet?: RenderItem }>(`${P(id)}/concepts/${cid}/choose/`, { index, name })).data,
  aiRender: async (id: string, cid: number, body: Record<string, unknown>) => (await api.post<AiJob>(`${P(id)}/characters/${cid}/ai-render/`, body)).data,
  aiJobs: async (id: string, cid: number) => (await api.get<{ items: AiJob[]; node: NodeStatus }>(`${P(id)}/characters/${cid}/ai-jobs/`)).data,
  // قالب‌ها و کاربردها
  templates: async (id: string) => (await api.get<{ items: TemplateRow[]; character: number | null }>(`${P(id)}/templates/`)).data,
  renderTemplate: async (id: string, tid: string, body: Record<string, unknown>) => (await api.post<RenderItem>(`${P(id)}/templates/${tid}/render/`, body)).data,
  usage: async (id: string) => (await api.get<Usage & { recent: { id: number; surface: string; surface_fa: string; ref: string; created_at: string }[] }>(`${P(id)}/usage/`)).data,
  useMotion: async (id: string, body: Record<string, unknown>) => (await api.post<MotionScene>(`${P(id)}/use/motion/`, body)).data,
  useThumbnail: async (id: string, body: Record<string, unknown>) => (await api.post<{ asset: number; url: string; thumb: string; title: string; open: string }>(`${P(id)}/use/thumbnail/`, body)).data,
  useSiteHero: async (id: string, body: Record<string, unknown>) => (await api.post<{ image: string; image_alt: string; title: string; subtitle: string; bubble: string; name: string; bound: boolean }>(`${P(id)}/use/site-hero/`, body)).data,
  useDirector: async (id: string, body: Record<string, unknown>) => (await api.post<{ items: { key: string; fa: string; pose: string; asset: number; url: string; thumb: string }[]; name: string; greeting: string; signoff: string; catchphrase: string }>(`${P(id)}/use/director/`, body)).data,
  inbox: async (id: string) => (await api.get<{ enabled: boolean; name?: string; greeting?: string; signoff?: string; avatar?: string | null; avatar_full?: string | null }>(`${P(id)}/use/inbox/`)).data,
};

/** نشانیِ API را برای کلاینتِ ما (که خودش پیشوندِ /api/v1 دارد) می‌سازد: سرور نشانیِ کامل (/api/v1/...) می‌دهد و بدونِ این برش پیشوند دو بار می‌آمد و دانلود ۴۰۴ می‌شد. */
export function apiPath(path: string): string {
  return path.replace(/^(?:https?:\/\/[^/]+)?\/api\/v1(?=\/)/, "");
}

/** دانلود با توکنِ ورود (لینکِ ساده سرآیندِ Authorization ندارد). */
export async function downloadBlob(path: string, filename: string, method: "get" | "post" = "get") {
  const url0 = apiPath(path);
  const res = method === "post" ? await api.post(url0, {}, { responseType: "blob" }) : await api.get(url0, { responseType: "blob" });
  const url = URL.createObjectURL(res.data as Blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 4000);
}

/** خطای «ادعا» (۴۲۲) از بک‌اند: فهرستِ ادعاهای پیدا‌شده در متن. */
export function claimsOf(e: unknown): { message: string; found: Claim[] } | null {
  const d = (e as { response?: { data?: { error?: { code?: string; message?: string; found?: Claim[] } } } })?.response?.data?.error;
  return d && d.code === "claims" ? { message: d.message ?? "", found: d.found ?? [] } : null;
}

export function isCancel(e: unknown): boolean {
  return typeof e === "object" && e !== null && (e as { code?: string }).code === "ERR_CANCELED";
}
