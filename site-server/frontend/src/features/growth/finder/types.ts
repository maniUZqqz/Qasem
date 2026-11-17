/** Types of the «مشتری‌یاب» API (`/api/v1/growth/finder/…`). The server is the source of truth: these only describe its answers. */

export type Paged<T> = { count: number; next: string | null; previous: string | null; results: T[] };

export type BusinessTypeInfo = { key: string; label: string; group: string; group_label: string; has_map: boolean; terms: string[]; osm: string[] };
export type PresetInfo = { key: string; name: string; description: string; product: string; store_id: number | null; spec: MissionSpec; has_pitch: boolean; types: string[]; cities: string[]; needs_node: boolean };
export type SourceInfo = { key: string; label: string; needs_node: boolean; needs_key: boolean; default: boolean; help: string; key_set?: boolean };
export type StageInfo = { key: string; label: string; tone: "neutral" | "brand" | "ok" | "warn" | "bad" | "info"; statuses: string[]; primary: string };
export type ChannelInfo = { key: string; label: string; manual: boolean };

export type NodeState = { known: boolean; online: boolean; ready: boolean; message: string };
export type EngineProbe = Record<string, { label: string; ok: boolean; results: number; message: string; resting?: boolean }>;

export type FinderMeta = {
  types: BusinessTypeInfo[];
  groups: Record<string, string>;
  presets: PresetInfo[];
  sources: SourceInfo[];
  stages: StageInfo[];
  channels: ChannelInfo[];
  budget_limits: Record<string, { min: number; max: number }>;
  budget_defaults: Record<string, number>;
  stores: { id: number; name: string }[];
  products: { key: string; label: string; short: string }[];
  node: { crawl: NodeState; instagram: NodeState };
  engines: { at?: string; engines?: EngineProbe; cooldown?: Record<string, { until: string; reason: string }>; brave_api?: boolean };
  outreach: { sending_enabled: boolean; emergency_stop: boolean; daily_cap: number; cap_remaining: number; identity_problems: string[]; sms_room: number };
  individuals: { tag: string; note: string };
  attribution: string;
};

export type Pitch = { brand?: string; what?: string; benefit?: string; cta?: string; voice?: string; sms?: string };

export type MissionSpec = {
  business_types: string[];
  keywords: string[];
  cities: string[];
  language: string;
  sources: Record<string, boolean>;
  budget: Record<string, number>;
  directory_urls?: string[];
  execution?: string;
  size?: string;
  require_contact?: boolean;
  max_results?: number;
  min_score?: number;
  exclude_words?: string[];
  tag?: string;
  pitch?: Pitch;
  ig_hashtags?: string[];
  ig_locations?: string[];
  include_individuals?: boolean;
};

export type CityReport = { cities: Record<string, { leads: number }>; empty: string[]; notes: Record<string, string> };

export type RunSummary = {
  city_report?: CityReport;
  id: number;
  mission_id: number;
  mission_name: string;
  trigger: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  state_label: string;
  paused: boolean;
  pause_requested: boolean;
  cancel_requested: boolean;
  stage: string;
  stage_label: string;
  progress: number;
  message: string;
  error: string;
  tasks: { total: number; done: number; failed: number; waiting_node: number };
  found: number;
  unique: number;
  created: number;
  merged: number;
  skipped: number;
  pages: number;
  bytes: number;
  cache_hits: number;
  out_of_area?: number;
  usage: { requests?: number; bytes?: number; seconds?: number; failures?: number; per_host?: Record<string, number> };
  parked_until: string | null;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  stalled: boolean;
  attempts: number;
};

export type LogRow = { id: number; level: "info" | "warn" | "error"; message: string; created_at: string };

export type RunDetail = RunSummary & {
  by_source: Record<string, Record<string, number>>;
  sample: { name: string; city: string; state: string }[];
  logs: LogRow[];
  spec: MissionSpec;
  mission: { id: number; name: string };
};

export type Mission = {
  id: number;
  name: string;
  preset_key: string;
  store_id: number | null;
  store_name: string;
  product: string;
  spec: MissionSpec;
  types_label: string[];
  cities: string[];
  schedule_days: number;
  enabled: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
  notes: string;
  is_archived: boolean;
  created_at: string;
  findings: number;
  drafts: number;
  last_run: RunSummary | null;
  active_run: number | null;
  outreach: Record<string, number>;
};

export type Reason = { text: string; points: number };
export type PhoneRow = { value: string; display: string; mobile: boolean; primary: boolean };

export type Result = {
  id: number;
  lead_id: number;
  mission_id: number;
  name: string;
  city: string;
  category: string;
  status: string;
  status_label: string;
  stage: string;
  score: number;
  level: "high" | "medium" | "low";
  reasons: Reason[];
  matched: { types?: string[]; words?: string[]; fit_words?: string[]; sources?: string[] };
  phones: PhoneRow[];
  emails: string[];
  website: string;
  instagram: string;
  telegram: string;
  whatsapp: string;
  address: string;
  lat: number | null;
  lon: number | null;
  hours: string;
  rating: number | null;
  tags: string[];
  sources: string[];
  seen_count: number;
  first_seen: string;
  updated_at: string;
  missions: number;
  individual: boolean;
};

export type MapPoint = { id: number; lead_id: number; name: string; score: number; stage: string; lat: number; lon: number; city: string };

export type BoardCard = {
  id: number;
  name: string;
  city: string;
  category: string;
  status: string;
  status_label: string;
  score: number | null;
  phone: string;
  website: string;
  instagram: string;
  tags: string[];
  next_due: string | null;
  overdue: boolean;
};
export type Board = { stages: (StageInfo & { count: number; cards: BoardCard[] })[]; total: number };

export type Reminder = { id: number; lead_id: number; lead_name: string; city: string; status: string; status_label: string; due_at: string; note: string; done_at: string | null; overdue: boolean };
export type Reminders = { counts: { overdue: number; today: number; week: number; open: number }; items: Reminder[] };

export type Draft = {
  id: number;
  mission_id: number;
  lead_id: number;
  lead_name: string;
  city: string;
  channel: string;
  channel_label: string;
  manual: boolean;
  recipient: string;
  subject: string;
  body: string;
  warnings: string[];
  status: "draft" | "approved" | "queued" | "sent_manual" | "rejected" | "blocked";
  status_label: string;
  block_reason: string;
  item_id: number | null;
  campaign_id: number | null;
  approved_at: string | null;
  updated_at: string;
  sms: { parts: number; length: number; encoding: string } | null;
};

export type TaskRow = { id: number; stage: string; source: string; kind: string; label: string; status: string; attempts: number; error: string; result: Record<string, unknown>; not_before: string | null; finished_at: string | null; waiting_job: boolean };
