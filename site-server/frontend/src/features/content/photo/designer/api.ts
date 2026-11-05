import { api } from "../../../../api/client";
import type { Edit, FontInfo, Params } from "../api";

/** «طراحِ خودکار» — همان شکلِ backend/apps/photoedit/views_designer.py و designer/engine.py */

export type DStep = { id: string; tool: string; on: boolean; title: string; why: string; ai?: boolean; params: Params };
export type DPlan = { version: number; recipe: string; format: string; mood: string; variation: number; title: string; steps: DStep[] };
export type DQa = {
  score: number;
  issues: string[];
  fixes: string[];
  metrics: { min_contrast: number | null; texts: number; min_font: number | null; balance: number };
};
export type DRound = { scores: Record<string, number>; mean: number; summary: string; issues: string[]; applied: string[]; accepted: boolean };
export type DReport = Record<string, { ok: boolean; note: string; resolved?: Record<string, unknown>; deferred?: boolean }>;
export type DVariant = {
  id: string;
  index: number;
  title: string;
  recipe: string;
  canvas: [number, number];
  palette: Record<string, string | boolean>;
  qa: DQa;
  notes: string[];
  needs: { ai: string[]; node: string[]; manual: string[] };
  rounds: DRound[];
  score: number;
  ai_mean: number | null;
  best?: boolean;
  edited?: boolean;
  cutout?: { ok: boolean; reason?: string; method?: string } | null;
  preview: string | null;
  plan?: DPlan;
  report?: DReport;
};
export type DAnalysis = {
  description?: string;
  palette: { hex: string; share: number; name: string }[];
  dominant: string;
  accent: string;
  background: { plain: boolean; color: string };
  subject: { box: number[]; method: string };
  orientation: string;
  suggested_recipe?: string;
};
export type DAiInfo = {
  enabled: boolean;
  planner: { used: boolean; label?: string; model?: string; reason?: string; notes?: string; fell_back?: boolean };
  critic: { used: boolean; rounds: number; label?: string; reason?: string };
};
export type Design = {
  id: number;
  asset: number;
  state: "QUEUED" | "RUNNING" | "READY" | "FAILED";
  state_label: string;
  active: boolean;
  progress: number;
  message: string;
  error: string;
  prompt: string;
  recipe: string;
  format: string;
  mood: string;
  quality: string;
  copy: Record<string, string>;
  analysis: Partial<DAnalysis>;
  ai: Partial<DAiInfo>;
  log: { t: string; text: string }[];
  chosen: number | null;
  project: number | null;
  edit: number | null;
  variants: DVariant[];
  created_at: string;
};
export type DParamSpec = { key: string; type: string; title: string; default: unknown; min?: number | null; max?: number | null; options?: string[] | null; max_len?: number | null };
export type DTool = { key: string; title: string; doc: string; deferred: boolean; params: DParamSpec[] };
export type DesignerInfo = {
  recipes: { key: string; title: string; help: string; format: string; fields: string[] }[];
  formats: { key: string; title: string }[];
  moods: { key: string; title: string }[];
  quality: { key: string; title: string; help: string }[];
  tools: DTool[];
  slots: { key: string; title: string }[];
  fonts: FontInfo[];
  ai: { path: "node" | "site"; first: "local" | "metis"; node_online: boolean; reason: string };
  has_logo: boolean;
  limits: { variants: number; prompt: number };
};
export type DesignInput = {
  asset: number;
  prompt: string;
  recipe: string;
  format: string;
  mood: string;
  quality: string;
  copy: Record<string, string>;
  variants: number;
  use_ai: boolean;
};

const base = (store: string) => `/stores/${store}/photo-editor/designer`;

export const designerApi = {
  info: (store: string) => api.get<DesignerInfo>(`${base(store)}/`).then((r) => r.data),
  analyze: (store: string, asset: number, prompt = "") =>
    api.post<{ analysis: DAnalysis }>(`${base(store)}/analyze/`, { asset, prompt }).then((r) => r.data.analysis),
  create: (store: string, body: DesignInput) => api.post<{ design: Design }>(`${base(store)}/designs/`, body).then((r) => r.data.design),
  get: (store: string, id: number) => api.get<{ design: Design }>(`${base(store)}/designs/${id}/`).then((r) => r.data.design),
  list: (store: string, asset: number) =>
    api.get<{ designs: Design[] }>(`${base(store)}/designs/`, { params: { asset } }).then((r) => r.data.designs),
  remove: (store: string, id: number) => api.delete(`${base(store)}/designs/${id}/`),
  rerender: (store: string, id: number, variant: number, plan: DPlan) =>
    api.post<{ variant: DVariant }>(`${base(store)}/designs/${id}/rerender/`, { variant, plan }).then((r) => r.data.variant),
  apply: (store: string, id: number, variant: number) =>
    api.post<{ project: number; edit: Edit; design: Design }>(`${base(store)}/designs/${id}/apply/`, { variant }).then((r) => r.data),
};
