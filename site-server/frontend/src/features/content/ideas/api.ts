import { api } from "../../../api/client";

/** بانکِ ایده — نوع‌ها و فراخوانی‌ها (همهٔ مسیرها زیرِ stores/<id>/ideas/). */

export type Filled = { title: string; logline: string; hook: string; shoot: string; cta: string };

export type Idea = {
  key: string;
  builtin: boolean;
  origin: string;
  based_on: string;
  category: string;
  format: string;
  channel: string;
  tags: string[];
  /** قالبِ خام (با جای‌گیرهای {محصول} …)؛ برای ویرایش و کپی. */
  title: string;
  logline: string;
  hook: string;
  shoot: string;
  cta: string;
  occasion: { month: number; day: number; name: string } | null;
  /** همان متن‌ها با جای‌گیرهای پرشده از پروفایلِ فروشگاه — این را نشان بده. */
  filled: Filled;
  /** جاهای خالیِ «[...]» که فروشگاه باید با دادهٔ واقعی پر کند. */
  slots: string[];
  needs_data: boolean;
  placeholders: string[];
  favorite: boolean;
  hidden: boolean;
  uses: number;
  occasion_next: { date: string; label: string; days: number; name: string } | null;
};

export type Facet = { key: string; fa: string; count: number };

export type Overview = {
  ideas: Idea[];
  shown: number;
  total: number;
  needs_data: number;
  categories: Facet[];
  formats: Facet[];
  channels: Facet[];
  tags: { tag: string; count: number }[];
  store: {
    id: number;
    name: string;
    business_type: string;
    audience: string;
    tone: string;
    known: Record<string, boolean>;
    values: Record<string, string>;
  };
  products: { id: number; name: string }[];
  campaigns: { id: number; name: string }[];
  ai: { ok: boolean; why: string };
};

export type GenerateResult = {
  via: "ai" | "mixed" | "formula";
  ai: { tried: boolean; ok: boolean; label: string; reason: string };
  message: string;
  ideas: Idea[];
  saved?: number;
  skipped?: number;
};

export type StudioStart = {
  target: "studio";
  tab: string;
  tabs: { key: string; label: string }[];
  product_id: number | null;
  brief: string;
  detail: string;
  needs_data: string[];
  uses: number;
};
export type ThumbStart = { target: "thumbnail"; format: string; title: string; subtitle: string; kicker: string; needs_data: string[]; uses: number };
export type PlanStart = {
  target: "calendar";
  task_id: number;
  campaign_id: number;
  campaign: string;
  due_at: string;
  needs_data: string[];
  uses: number;
};

export type IdeaDraft = Partial<Pick<Idea, "category" | "format" | "channel" | "title" | "logline" | "hook" | "shoot" | "cta">> & { tags?: string };

const base = (id: string | number) => `/stores/${id}/ideas`;

export const ideasApi = {
  overview: async (id: string | number, product?: number | null) =>
    (await api.get<Overview>(`${base(id)}/`, { params: { hidden: 1, ...(product ? { product } : {}) } })).data,
  create: async (id: string | number, draft: IdeaDraft) => (await api.post<Idea>(`${base(id)}/`, draft)).data,
  update: async (id: string | number, key: string, draft: IdeaDraft) => (await api.patch<Idea>(`${base(id)}/${key}/`, draft)).data,
  remove: async (id: string | number, key: string) => api.delete(`${base(id)}/${key}/`),
  duplicate: async (id: string | number, key: string) => (await api.post<Idea>(`${base(id)}/${key}/duplicate/`, {})).data,
  mark: async (id: string | number, key: string, patch: { favorite?: boolean; hidden?: boolean }) =>
    (await api.post<Idea>(`${base(id)}/${key}/mark/`, patch)).data,
  generate: async (
    id: string | number,
    body: { category?: string; count?: number; topic?: string; instruction?: string; facts?: string[]; product?: number | null; ai?: boolean; variation?: number },
  ) => (await api.post<GenerateResult>(`${base(id)}/generate/`, body)).data,
  startStudio: async (id: string | number, key: string, product?: number | null) =>
    (await api.post<StudioStart>(`${base(id)}/${key}/start/`, { target: "studio", product: product || undefined })).data,
  startThumbnail: async (id: string | number, key: string) => (await api.post<ThumbStart>(`${base(id)}/${key}/start/`, { target: "thumbnail" })).data,
  startCalendar: async (id: string | number, key: string, body: { campaign?: number; product?: number; due?: string }) =>
    (await api.post<PlanStart>(`${base(id)}/${key}/start/`, { target: "calendar", ...body })).data,
  fromTrendIdea: async (id: string | number, trendIdea: number) =>
    (await api.post<{ idea: Idea; created: boolean; message: string }>(`${base(id)}/from-trend/`, { trend_idea: trendIdea })).data,
  fromCluster: async (id: string | number, cluster: number) =>
    (await api.post<{ idea: Idea; created: boolean; message: string }>(`${base(id)}/from-trend/`, { cluster })).data,
};

// جست‌وجو و ارقام: منطقِ خالص (بدونِ axios) در logic.ts تا بی‌مرورگر آزموده شود
export { faDigits, fold, jalaliText, matches } from "./logic";
