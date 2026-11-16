import { api } from "../../../api/client";

/** «تلفظ» — همان شکلِ backend/apps/pronunciation (views.py، services.py). */

export type EngineKey = "piper" | "edge" | "moss";
export type Depth = "normalize" | "lexicon" | "full";

export type PronSettings = { enabled: boolean; ezafe: boolean; depth: Partial<Record<EngineKey, Depth>> };

export type EngineInfo = {
  key: EngineKey;
  label: string;
  local: boolean;
  native: string;
  blocked: boolean;
  depth: Depth;
  default_depth: Depth;
};

export type RunSummary = {
  overall: { n: number; before: number | null; after: number | null; delta?: number };
  by_tag: Record<string, { n: number; before: number | null; after: number | null; delta?: number }>;
  worse: { tag: string; ref: string; before: number; after: number }[];
  median_sentence_wer_after: number | null;
};

export type EvalRunRow = { id: number; tag: string; ref: string; before: string | null; after: string | null; after_input?: string };

export type EvalRun = {
  id: number;
  engine: EngineKey;
  voice: string;
  sample: "quick" | "full";
  depth: string;
  state: "waiting" | "running" | "done" | "failed";
  state_label: string;
  message: string;
  asr: string;
  where: string;
  baseline: boolean;
  n: number;
  summary: Partial<RunSummary>;
  created_at: string;
  finished_at: string | null;
  rows?: EvalRunRow[];
};

export type Overview = {
  settings: PronSettings;
  engines: EngineInfo[];
  depths: Record<Depth, string>;
  local_only: boolean;
  node: { known: number; online: number; names: string[] };
  counts: { store: number; global: number; shared: number; problems: number; sentences: number };
  tags: Record<string, string>;
  latest: Partial<Record<EngineKey, EvalRun>>;
  runs: EvalRun[];
  is_staff: boolean;
};

export type WordRow = { text: string; pn: string; source: string; ezafe: boolean; applied: boolean; heard_as: string };

export type Preview = {
  text: string;
  normalized: string;
  words: WordRow[];
  unknown: string[];
  latin_guesses: string[];
  engines: Partial<Record<EngineKey, { depth: Depth; text: string; ipa?: string }>>;
};

export type Convert = { pn: string; respelling: string; ipa: string; syllables: number };

export type Entry = {
  id: number;
  word: string;
  respelling: string;
  pn: string;
  note: string;
  enabled: boolean;
  scope: "store" | "global";
  heard_as: string;
  ipa: string;
  updated_at: string;
};

export type SharedRow = { word: string; pn: string; respelling: string; ipa: string; category: string; tag: string };
export type Shared = { total: number; rows: SharedRow[]; categories: { name: string; count: number }[] };

export type Problem = {
  id: number;
  word: string;
  source: string;
  source_label: string;
  status: "open" | "fixed" | "ignored";
  context: string;
  engine: string;
  detail: string;
  count: number;
  updated_at: string;
};

export type Listen =
  | { state: "ready"; url: string; engine: EngineKey; variant: string }
  | { state: "queued" | "running"; token: string; engine: EngineKey; variant: string; message?: string }
  | { state: "failed"; message: string };

const P = (id: string) => `/stores/${id}/pronunciation`;

export const loadOverview = async (id: string) => (await api.get<Overview>(`${P(id)}/`)).data;
export const saveSettings = async (id: string, body: Partial<PronSettings>) =>
  (await api.patch<PronSettings>(`${P(id)}/settings/`, body)).data;
export const preview = async (id: string, text: string) => (await api.post<Preview>(`${P(id)}/preview/`, { text })).data;
export const convert = async (id: string, respelling: string) =>
  (await api.post<Convert>(`${P(id)}/convert/`, { respelling })).data;
export const listen = async (id: string, text: string, engine: EngineKey, variant: "before" | "after") =>
  (await api.post<Listen>(`${P(id)}/listen/`, { text, engine, variant })).data;
export const listenResult = async (id: string, token: string) => (await api.get<Listen>(`${P(id)}/listen/${token}/`)).data;
export const loadShared = async (id: string, q: string, category: string) =>
  (await api.get<Shared>(`${P(id)}/shared/`, { params: { q, category, limit: 300 } })).data;
export const loadLexicon = async (id: string, scope: "store" | "global", q = "") =>
  (await api.get<{ scope: string; rows: Entry[] }>(`${P(id)}/lexicon/`, { params: { scope, q } })).data.rows;
export const saveEntry = async (id: string, body: { word: string; respelling: string; note?: string; scope?: string }, pk?: number) =>
  (pk
    ? await api.patch<Entry>(`${P(id)}/lexicon/${pk}/`, body)
    : await api.post<Entry>(`${P(id)}/lexicon/`, body)
  ).data;
export const deleteEntry = async (id: string, pk: number) => api.delete(`${P(id)}/lexicon/${pk}/`);
export const loadProblems = async (id: string, status = "open") =>
  (await api.get<{ rows: Problem[] }>(`${P(id)}/problems/`, { params: { status } })).data.rows;
export const addProblem = async (id: string, word: string, context = "", engine = "") =>
  (await api.post<Problem>(`${P(id)}/problems/`, { word, context, engine })).data;
export const patchProblem = async (id: string, pk: number, body: { status?: string; respelling?: string }) =>
  (await api.patch<{ problem: Problem; entry?: Entry }>(`${P(id)}/problems/${pk}/`, body)).data;
export const deleteProblem = async (id: string, pk: number) => api.delete(`${P(id)}/problems/${pk}/`);
export const loadRuns = async (id: string) => (await api.get<{ runs: EvalRun[]; tags: Record<string, string> }>(`${P(id)}/eval/`)).data;
export const loadRun = async (id: string, pk: number) => (await api.get<EvalRun>(`${P(id)}/eval/${pk}/`)).data;
export const startRun = async (id: string, engine: EngineKey, sample: "quick" | "full") =>
  (await api.post<EvalRun>(`${P(id)}/eval/`, { engine, sample })).data;
