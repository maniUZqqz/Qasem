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

export type DirectorCatalogue = {
  tools: ToolSpec[];
  recipes: { key: string; title: string; hint: string }[];
  variants: { key: string; title: string }[];
  platforms: { key: string; title: string; preset: string; target: number; max: number }[];
  safe_zones: { key: string; title: string; hint: string; margins: { top: number; bottom: number; left: number; right: number } }[];
  caption_styles: { key: string; title: string }[];
  captions: { node: boolean; local: boolean; ok: boolean; message: string };
  ai: { node: boolean; node_message: string };
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
  projects: { key: string; id: number; title: string; score: number; length: number }[];
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
  rerun: (store: string, body: { brief: unknown; steps: unknown[]; refs: string[]; variant: string; project_id: number | null }) =>
    api.post<{ job_id: number }>(`${base(store)}/rerun/`, body).then((r) => r.data),
  job: (id: number) => api.get<Job>(`/jobs/${id}/`).then((r) => r.data),
};
