import { api } from "../../../../api/client";
import type { Job } from "../../../../types";

/** API ِ «کارگردان» (backend/apps/content/views_director.py) */
const base = (store: string) => `/stores/${store}/editor/director`;

export type ParamSpec = {
  name: string;
  title: string;
  kind: "num" | "int" | "bool" | "choice" | "text" | "ref" | "clip" | "list";
  required?: boolean;
  default?: number | string | boolean;
  min?: number;
  max?: number;
  choices?: string[];
  unit?: string;
};
export type ToolSpec = { tool: string; title: string; group: string; does: string; params: ParamSpec[] };

/** تنظیماتِ ویرایشگر برای هر فروشگاه: تیکِ «کمکِ هوش مصنوعی» از چه حالتی شروع شود و پیش‌نویس‌های بازنشده چند روز بمانند */
export type EditorSettings = { ai_default: boolean; draft_days: number; min_days: number; max_days: number; max_drafts: number; cost_note: string };

/** نتیجهٔ ذخیره‌شدهٔ یک «بساز» که هنوز کسی بازش نکرده (سبک؛ با باز کردن در تدوینِ دستی پروژهٔ واقعی می‌شود) */
export type DraftRow = { id: number; key: string; title: string; score: number; length: number; run: string; created_at: string; expires_at: string; days_left: number | null; project_id: number | null; prompt: string };

export type DirectorCatalogue = {
  tools: ToolSpec[];
  recipes: { key: string; title: string; hint: string }[];
  variants: { key: string; title: string }[];
  platforms: { key: string; title: string; preset: string; target: number; max: number }[];
  safe_zones: { key: string; title: string; hint: string; margins: { top: number; bottom: number; left: number; right: number } }[];
  caption_styles: { key: string; title: string }[];
  captions: { node: boolean; local: boolean; ok: boolean; message: string };
  ai: { node: boolean; node_message: string };
  settings: EditorSettings;
};

export type PlanStep = {
  id: string;
  tool: string;
  title: string;
  text: string;
  group?: string;
  why?: string;
  params: Record<string, unknown>;
  on?: boolean;
  round?: number;
  ok?: boolean;
  skipped?: boolean;
  message?: string;
  notes?: string[];
};

export type CritiqueItem = { key: string; title: string; ok: boolean; severity: "info" | "warn" | "bad"; detail: string };
export type Critique = {
  score: number;
  summary: string;
  items: CritiqueItem[];
  vision?: { scores?: Record<string, number>; issues?: { frame?: number; what?: string; fix?: string }[]; verdict?: string; via?: string } | null;
};

export type DirectorVariant = {
  key: string;
  title: string;
  /** پیش‌نویسی که این نسخه در آن ذخیره شده؛ با باز کردن در تدوینِ دستی پروژه می‌شود */
  draft_id: number | null;
  project_id: number | null;
  score: number;
  rounds: number;
  ai_steps: number;
  plan: PlanStep[];
  critique: Critique;
  problems?: string[];
};

export type DirectorAi = { asked: boolean; ok: boolean; enabled?: boolean; via: string; model: string; error: string; error_code: string; used_for_steps?: boolean; needed_for?: string[] };

export type DirectorResult = {
  run: string;
  kind: "run" | "rerun";
  brief: Record<string, unknown> & { recipe?: string; platform?: string; duration?: number; title?: string; cta?: string; pace?: string };
  platform?: string;
  recipe_title?: string;
  ai: DirectorAi;
  degraded: string[];
  primary: string;
  analysis: { has_speech?: boolean; has_words?: boolean; music?: string };
  drafts: { key: string; id: number; title: string; score: number; length: number }[];
  draft_days: number;
  preview: { url?: string; seconds?: number } | null;
  variants: DirectorVariant[];
};

export type RunBody = {
  prompt: string;
  refs: string[];
  options: { variants?: number; rounds?: number; use_ai?: boolean; preview?: boolean; music_ref?: string; override?: Record<string, unknown> };
};

export const directorApi = {
  catalogue: (store: string) => api.get<DirectorCatalogue>(`${base(store)}/catalogue/`).then((r) => r.data),
  run: (store: string, body: RunBody) => api.post<{ job_id: number }>(`${base(store)}/run/`, body).then((r) => r.data),
  rerun: (store: string, body: { brief: unknown; steps: unknown[]; refs: string[]; variant: string; draft_id: number | null }) =>
    api.post<{ job_id: number }>(`${base(store)}/rerun/`, body).then((r) => r.data),
  drafts: (store: string) => api.get<{ drafts: DraftRow[]; draft_days: number; max_drafts: number }>(`${base(store)}/drafts/`).then((r) => r.data),
  openDraft: (store: string, id: number) => api.post<{ project_id: number; title: string }>(`${base(store)}/drafts/${id}/open/`).then((r) => r.data),
  deleteDraft: (store: string, id: number) => api.delete(`${base(store)}/drafts/${id}/`).then(() => undefined),
  settings: (store: string) => api.get<EditorSettings>(`/stores/${store}/editor/settings/`).then((r) => r.data),
  saveSettings: (store: string, body: Partial<Pick<EditorSettings, "ai_default" | "draft_days">>) => api.put<EditorSettings>(`/stores/${store}/editor/settings/`, body).then((r) => r.data),
  job: (id: number) => api.get<Job>(`/jobs/${id}/`).then((r) => r.data),
};
