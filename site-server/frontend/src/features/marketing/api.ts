import { api } from "../../api/client";

export type PlanStatus = "PLANNED" | "DRAFTED" | "WAITING_NODE" | "RUNNING" | "READY" | "NEEDS_YOU" | "FAILED";
export type Decision = "" | "approved" | "done" | "skipped";

export type PlanRef = {
  type: string;
  id: number | string;
  label: string;
  url: string;
  state: string;
  note: string;
};

export type PlanItem = {
  id: number;
  key: string;
  day: number;
  week: number;
  date: string;
  date_fa: string;
  weekday: string;
  when_fa: string;
  kind: string;
  kind_label: string;
  group: string;
  section: string;
  url: string;
  title: string;
  brief: string;
  draft: string;
  status: PlanStatus;
  status_label: string;
  decision: Decision;
  decision_label: string;
  needs_node: boolean;
  ai_wait: boolean;
  needs_you: string;
  message: string;
  error: string;
  checks: string[];
  adopted: boolean;
  polished: boolean;
  companion: string;
  refs: PlanRef[];
};

export type NodeState = { online: boolean; known: number; name: string; last_seen: string | null; agent: string };
export type AiState = { ok: boolean; why: string };

export type PlanCounts = {
  total: number;
  by_status: Record<string, number>;
  decided: number;
  waiting_node: number;
  needs_you: number;
  failed: number;
  ready: number;
};

export type Facts = {
  name: string;
  business: string;
  about: string;
  audience: string;
  tone: string;
  tagline: string;
  products: string[];
  site: string;
  dont_words: string[];
  gaps: string[];
};

export type Plan = {
  id: number;
  key: string;
  name: string;
  goal: string;
  start_date: string;
  start_fa: string;
  days: number;
  autorun: boolean;
  summary: { facts?: Facts; built_at?: string };
  last_run: { at?: string; by?: string; log?: string[]; ran?: number; ok?: number; failed?: number } | Record<string, never>;
  last_run_at: string | null;
  running: boolean;
  counts: PlanCounts;
  items: PlanItem[];
  node: NodeState;
  ai: AiState;
  groups: Record<string, string>;
  status_labels: Record<string, string>;
};

export type PlanResponse =
  | { plan: Plan }
  | { plan: null; facts: Facts; node: NodeState; default_start: string; default_start_fa: string; groups: Record<string, string> };

export async function loadPlan(storeId: string): Promise<PlanResponse> {
  const { data } = await api.get<PlanResponse>(`/stores/${storeId}/marketing-plan/`);
  return data;
}

export async function planAction(storeId: string, action: "create" | "run" | "create_run" | "restart" | "refresh"): Promise<{ plan: Plan; started: string }> {
  const { data } = await api.post<{ plan: Plan; started: string }>(`/stores/${storeId}/marketing-plan/`, { action });
  return data;
}

export async function patchItem(storeId: string, itemId: number, body: { decision?: Decision; draft?: string }): Promise<PlanItem> {
  const { data } = await api.patch<{ item: PlanItem }>(`/stores/${storeId}/marketing-plan/items/${itemId}/`, body);
  return data.item;
}

export async function runItem(storeId: string, itemId: number): Promise<PlanItem> {
  const { data } = await api.post<{ item: PlanItem }>(`/stores/${storeId}/marketing-plan/items/${itemId}/`, {});
  return data.item;
}

// ----------------------------------------------------------------------------- راهنمای آزمون

export type GuideSection = {
  key: string;
  phase: number;
  phase_title: string;
  title: string;
  covers: string[];
  pages: { key: string; title: string }[];
  steps: string[];
  expect: string[];
  node: string;
  kinds: string[];
  minutes: number;
  staff: boolean;
  url: string;
  plan: { total: number; waiting_node: number; ready: number; needs_you: number };
  open_bugs: number;
};

export type GuideResponse = {
  sections: GuideSection[];
  phases: Record<string, string>;
  node: NodeState;
  has_plan: boolean;
  is_staff: boolean;
  open_bugs: number;
};

export async function loadGuide(storeId: string): Promise<GuideResponse> {
  const { data } = await api.get<GuideResponse>(`/stores/${storeId}/test-guide/`);
  return data;
}

export type BugReport = {
  id: number;
  store: number | null;
  user: string;
  section: string;
  section_title: string;
  page_url: string;
  note: string;
  screenshot: string;
  context: Record<string, unknown>;
  state: "new" | "seen" | "fixed" | "wontfix";
  state_label: string;
  response: string;
  created_at: string;
};

export async function loadBugs(storeId: string): Promise<BugReport[]> {
  const { data } = await api.get<{ results: BugReport[] }>(`/stores/${storeId}/bug-reports/`);
  return data.results;
}

export async function setBugState(id: number, state: BugReport["state"]): Promise<BugReport> {
  const { data } = await api.patch<{ report: BugReport }>(`/bug-reports/${id}/`, { state });
  return data.report;
}

export type BugSection = { key: string; title: string; phase_title: string; covers: string[] };

export async function loadBugSections(): Promise<BugSection[]> {
  const { data } = await api.get<{ sections: BugSection[] }>("/bug-reports/sections/");
  return data.sections;
}

/** رویدادی که هر جای پنل می‌تواند بفرستد تا پنجرهٔ «گزارشِ ایراد» با بخشِ پیش‌پر باز شود. */
export const BUG_EVENT = "nm-bug-open";
export function openBugReport(detail: { section?: string; note?: string }) {
  window.dispatchEvent(new CustomEvent(BUG_EVENT, { detail }));
}
