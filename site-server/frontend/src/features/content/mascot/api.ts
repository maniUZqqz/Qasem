import { api } from "../../../api/client";

/** «ماسکوتِ برند» — همان شکلِ backend/apps/mascot (views.py، services.py). */

export type Spec = {
  name: string;
  limb_colour: string;
  head_fill: string;
  outline: string;
  line_width: number;
  head_style: string;
  eye_style: string;
  hat: string;
  hat_colour: string;
  hair: string;
  hair_colour: string;
  neck: string;
  neck_colour: string;
  extra: string;
  extra_colour: string;
  prop: string;
  prop_colour: string;
  logo: string;
};

export type PaletteRow = { role: string; hex: string; name: string };
export type CheckResult = { at?: string; ok?: boolean; passed?: number; total?: number; seconds?: number; version?: number; poses?: number; sizes?: number; failed?: { pose: string; size: string; notes: string[] }[] };

export type Mascot = {
  id: number;
  name: string;
  role: string;
  role_fa: string;
  spec: Spec;
  palette: PaletteRow[];
  anchor: string;
  version: number;
  locked: boolean;
  locked_at: string | null;
  brand_colours: string[];
  check: CheckResult;
  has_logo: boolean;
  shots: number;
  stickers: number;
  cover?: string | null;
  updated_at: string;
};

export type Role = { key: string; fa: string; hint: string; background: string; expression: string; pose: string; tags: string[] };
export type PoseInfo = { key: string; fa: string; en: string; tags: string[]; original: boolean };
export type Option = { key: string; fa: string };
export type BackgroundInfo = { key: string; fa: string; en: string; group: "marketing" | "scene" };
export type SizeInfo = { key: string; fa: string; w: number; h: number; aspect: string; safe: [number, number] };

export type Options = {
  poses: PoseInfo[];
  pose_tags: { key: string; fa: string; poses: string[] }[];
  expressions: Option[];
  backgrounds: BackgroundInfo[];
  sizes: SizeInfo[];
  choices: Record<string, Option[]>;
  bubble_kinds: Option[];
  positions: Option[];
  crops: Option[];
  colour_keys: string[];
};

export type Overview = {
  store: { id: number; name: string; colors: string[]; has_logo: boolean };
  roles: Role[];
  options: Options;
  lines: { text: string; source: string }[];
  mascots: Mascot[];
  limits: { max_mascots: number; max_text: number; max_renders: number };
  notes: string[];
};

export type Qa = {
  ok: boolean;
  score: number | null;
  colours: { role: string; hex: string; name: string; found: boolean; share: number }[];
  notes: string[];
  scope: string;
};

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

export type AssetRow = { id: number; title: string; thumb: string | null; url: string | null; width: number; height: number; has_alpha: boolean; source_kind: string; product: number | null };

export type RenderItem = {
  id: number;
  mascot: number;
  kind: "shot" | "sticker" | "sheet";
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

export type Claim = { code: string; label_fa: string; term: string };

export type Preview = { image: string; width: number; height: number; qa: Qa; claims: Claim[]; claims_message: string; prop: string };

const P = (id: string) => `/stores/${id}/mascot`;

export const mascotApi = {
  overview: async (id: string) => (await api.get<Overview>(`${P(id)}/`)).data,
  create: async (id: string, body: { role: string; name?: string; use_logo?: boolean; brand_colours?: string[] }) => (await api.post<Mascot>(`${P(id)}/`, body)).data,
  patch: async (id: string, mid: number, body: Record<string, unknown>) => (await api.patch<Mascot>(`${P(id)}/${mid}/`, body)).data,
  remove: async (id: string, mid: number) => api.delete(`${P(id)}/${mid}/`),
  lock: async (id: string, mid: number) => (await api.post<Mascot>(`${P(id)}/${mid}/lock/`)).data,
  unlock: async (id: string, mid: number) => (await api.post<Mascot>(`${P(id)}/${mid}/unlock/`)).data,
  preview: async (id: string, mid: number, body: Record<string, unknown>, signal?: AbortSignal) => (await api.post<Preview>(`${P(id)}/${mid}/preview/`, body, { signal })).data,
  render: async (id: string, mid: number, body: Record<string, unknown>) => (await api.post<RenderItem>(`${P(id)}/${mid}/render/`, body)).data,
  sticker: async (id: string, mid: number, body: Record<string, unknown>) => (await api.post<RenderItem>(`${P(id)}/${mid}/sticker/`, body)).data,
  sheet: async (id: string, mid: number) => (await api.post<RenderItem>(`${P(id)}/${mid}/sheet/`)).data,
  check: async (id: string, mid: number) => (await api.post<CheckResult>(`${P(id)}/${mid}/check/`)).data,
  shots: async (id: string, mid: number, kind?: string) => (await api.get<{ items: RenderItem[] }>(`${P(id)}/${mid}/shots/`, { params: kind ? { kind } : {} })).data.items,
  removeShot: async (id: string, mid: number, rid: number) => api.delete(`${P(id)}/${mid}/shots/${rid}/`),
  downloadPath: (id: string, mid: number, rid: number) => `${P(id)}/${mid}/shots/${rid}/download/`,
};

/** خطای «ادعا» (۴۲۲) از بک‌اند: فهرستِ ادعاهای پیدا‌شده در متن. */
export function claimsOf(e: unknown): { message: string; found: Claim[] } | null {
  const d = (e as { response?: { data?: { error?: { code?: string; message?: string; found?: Claim[] } } } })?.response?.data?.error;
  return d && d.code === "claims" ? { message: d.message ?? "", found: d.found ?? [] } : null;
}

export const DEFAULT_SCENE: Scene = {
  size: "ig_portrait", pose: "stand", expression: "happy", background: "brand", position: "center", flip: false, prop: "auto", bubble: null, caption: null,
};
