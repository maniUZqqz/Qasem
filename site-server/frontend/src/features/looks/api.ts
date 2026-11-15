import { api } from "../../api/client";

/** «سبک تصویر» — همان شکلِ backend/apps/looks (views.py، library.py). */

export type LookKind = "POSTER" | "PRODUCT_SHOT" | "ENHANCED" | "NEW_IMAGE" | "THUMB_BG" | "SAMPLE";

/** روی این دو نوع «عکسِ واقعیِ محصول» ویرایش می‌شود و محصول نباید عوض شود؛ فقط سبک‌های نور و صحنه مجازند */
export const PRODUCT_KINDS: LookKind[] = ["PRODUCT_SHOT", "ENHANCED"];

export type LookEntry = {
  key: string;
  name_fa: string;
  name_en: string;
  description_fa: string;
  realism: string;
  realism_fa: string;
  group: string;
  group_fa: string;
  family: string;
  family_fa: string;
  animation: string;
  animation_fa: string;
  palette: string[];
  lighting: string;
  mood: string;
  tags: string[];
  suitability: string[];
  ad_fit: string[];
  ad_fit_fa: string[];
  product_safe: boolean;
  theme_key: string;
  preview_url: string;
  sample_url: string | null;
  search_terms: string[];
  known_as: string;
  gen: { model: string; steps: number; guidance: number; cfg: number; aspect: string; workflow_fa: string };
  /** فقط وقتی فهرست با ?kind= گرفته شده: برای آن نوعِ تبلیغ مجاز است؟ */
  usable?: boolean;
};

export type ThemeEntry = {
  key: string;
  name_fa: string;
  name_en: string;
  description_fa: string;
  palette: string[];
  lighting: string;
  mood: string;
  tags: string[];
  mood_key: string;
};

export type LooksIndex = {
  count: number;
  total: number;
  styles: LookEntry[];
  themes: ThemeEntry[];
  groups: { key: string; fa: string; count: number }[];
  realism: { key: string; fa: string; count: number }[];
  ad_fits: { key: string; fa: string; count: number }[];
  kinds: { key: LookKind; fa: string; product_preserving: boolean }[];
  samples: { total: number; done: number; pending: number };
};

export type LookSuggestion = {
  business_fa: string[];
  looks: { look: string; reason_fa: string; business: string; business_fa: string }[];
  themes: { theme: string; reason_fa: string }[];
  matched: boolean;
  basis_fa: string;
};

export type LookCheck = { ok: boolean; code?: string; message_fa?: string };

export type SamplesStatus = {
  total: number; done: number; pending: number; active: number; chunk: number; online: boolean; possible: boolean; model: string; message: string;
  selftest?: { state: "none" | "waiting" | "running" | "ok" | "failed"; message: string };
};

let cache: { at: number; data: LooksIndex } | null = null;
const TTL_MS = 5 * 60 * 1000;

export const looksApi = {
  /** همهٔ سبک‌ها و تم‌ها؛ پنج دقیقه در حافظه می‌ماند (۱۱۶ ردیف، یک بار برای هر دو منتخب‌گر). */
  index: async (force = false): Promise<LooksIndex> => {
    if (!force && cache && Date.now() - cache.at < TTL_MS) return cache.data;
    const data = (await api.get<LooksIndex>("/looks/")).data;
    cache = { at: Date.now(), data };
    return data;
  },
  check: async (look: string, kind: LookKind) => (await api.get<LookCheck>("/looks/check/", { params: { look, kind } })).data,
  suggest: async (store: string | number) => (await api.get<LookSuggestion>("/looks/suggest/", { params: { store } })).data,
  samples: async () => (await api.get<SamplesStatus>("/looks/samples/")).data,
};

/** پیامِ فارسیِ «این سبک روی این نوعِ تبلیغ مجاز نیست» (همان متنِ سرور)؛ برای نمایش وقتی هنوز به سرور نرفته‌ایم */
export function refusalFa(look: LookEntry, kind: LookKind | undefined): string {
  if (!kind || !PRODUCT_KINDS.includes(kind) || look.product_safe) return "";
  return `سبکِ «${look.name_fa}» شکلِ خودِ محصول را عوض می‌کند، برای همین روی «عکسِ محصول» و «بهبودِ عکس» مجاز نیست؛ آن را برای «پوستر تبلیغاتی» به کار ببرید.`;
}
