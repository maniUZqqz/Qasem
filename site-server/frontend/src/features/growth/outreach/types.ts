import type { JobStatus, LeadRow, Paged } from "../types";

/**
 * Types of the compliance + outreach API, exactly as fixed in docs/growth-engine/DESIGN-EXT.md (sections 2 and 3).
 * Where the contract leaves a field open it is typed optional and the screens fall back gracefully.
 */

// ------------------------------------------------------------------ compliance

export type Readiness = { ok: boolean; problems: string[] };

export type GrowthSettings = {
  sending_enabled: boolean;
  emergency_stop: boolean;
  sender_name: string;
  sender_company: string;
  sender_phone: string;
  sender_email: string;
  sender_website: string;
  opt_out_line: string;
  daily_cap: number;
  spacing_min_seconds: number;
  spacing_max_seconds: number;
  ready: Readiness;
  sent_today: number;
  cap_remaining: number;
  updated_at?: string | null;
  updated_by?: string | null;
};

export type SettingsPatch = Partial<
  Pick<
    GrowthSettings,
    | "sending_enabled"
    | "sender_name"
    | "sender_company"
    | "sender_phone"
    | "sender_email"
    | "sender_website"
    | "opt_out_line"
    | "daily_cap"
    | "spacing_min_seconds"
    | "spacing_max_seconds"
  >
>;

export type AuditEntry = {
  id: number;
  kind: string;
  kind_label?: string;
  actor?: number | null;
  actor_name?: string;
  summary: string;
  data?: Record<string, unknown>;
  created_at: string;
};

export type SuppressionReason = "opt_out" | "asked_not_to_contact" | "complaint" | "invalid_contact" | "other";

export type SuppressionEntry = {
  id: number;
  kind: string;
  kind_label?: string;
  value: string;
  normalized?: string;
  reason: SuppressionReason | string;
  reason_label?: string;
  note: string;
  created_by_name?: string;
  created_at: string;
};

// ------------------------------------------------------------------ templates

export type Template = {
  id: number;
  name: string;
  subject: string;
  body: string;
  language: "fa" | "en" | string;
  generator?: string;
  channel?: ChannelKey | "any";
  channel_label?: string;
  is_active: boolean;
  created_by_name?: string;
  created_at?: string;
  updated_at?: string;
  campaigns_count?: number;
};

export type TemplateInput = { name: string; subject: string; body: string; language: string; is_active: boolean; channel: string };

export type Placeholder = { key: string; label: string; example_source?: string };

export type SmsSize = { parts: number; length: number; encoding: "gsm7" | "ucs2"; single_limit: number; part_limit: number; max_parts: number; fits: boolean };

export type PreviewResult = { text: string; subject: string; warnings: string[]; unknown_placeholders: string[]; sms?: SmsSize };

// ------------------------------------------------------------------ campaigns

export type ChannelKey = "contact_form" | "email" | "sms" | "whatsapp" | "telegram" | "eitaa" | "bale" | "rubika" | "phone_call";
export type CampaignChannel = ChannelKey | "auto";

export type ChannelConfigField = {
  name: string;
  label: string;
  type: "text" | "int" | "choice" | "email";
  help?: string;
  min?: number;
  max?: number;
  default?: number;
  choices?: [string, string][];
};

export type ChannelInfo = {
  key: ChannelKey;
  label: string;
  kind: "auto" | "manual";
  description: string;
  hint: string;
  enabled: boolean;
  priority: number;
  daily_cap: number | null;
  spacing_min_seconds: number | null;
  spacing_max_seconds: number | null;
  default_template: { id: number; name: string } | null;
  ready: boolean;
  not_ready_reason: string;
  config_schema: ChannelConfigField[];
  config: { set: Record<string, unknown>; in_force?: Record<string, unknown>; from_server?: string[]; password_from_server?: boolean };
  /** which secrets are SET; their values never come to the browser */
  secrets: Record<string, { label: string; is_set: boolean; server_default?: boolean }>;
  sent_today: number | null;
  cap_remaining: number | null;
  needs_app: boolean;
};

export type CampaignMode = "auto" | "manual";
export type CampaignState = "draft" | "active" | "paused" | "completed" | "cancelled";

export type Campaign = {
  id: number;
  name: string;
  template?: number | { id: number; name: string } | null;
  template_id?: number;
  template_name?: string;
  mode: CampaignMode;
  channel?: CampaignChannel;
  channel_label?: string;
  status: CampaignState;
  status_label?: string;
  created_by_name?: string;
  created_at?: string;
  started_at?: string | null;
  finished_at?: string | null;
  /** status -> number of items, when the list endpoint provides it */
  counts?: Record<string, number>;
  items_total?: number;
};

export type OutreachJobInfo = {
  id: number;
  kind: "prepare" | "send";
  status: JobStatus;
  status_label?: string;
  progress: number;
  total_items: number;
  processed_items: number;
  error: string;
  stalled?: boolean;
  can_resume?: boolean;
  queued_at?: string;
  started_at?: string | null;
  finished_at?: string | null;
};

export type CampaignStatusInfo = {
  campaign: Campaign;
  counts: Record<string, number>;
  job: OutreachJobInfo | null;
  sent_today: number;
  daily_cap: number;
  cap_remaining: number;
  readiness: Readiness;
  emergency_stop: boolean;
  channels?: Record<string, { label: string; enabled: boolean; sent_today: number | null; cap_remaining: number | null; ready: boolean; not_ready_reason: string }>;
};

export type ItemStatus =
  | "pending"
  | "ready"
  | "needs_manual"
  | "approved"
  | "sending"
  | "sent"
  | "failed"
  | "skipped"
  | "cancelled"
  | "manual_sent"
  | "no_form"
  | "needs_login"
  | "handed_off"
  | "unreachable";

export type PlanField = {
  name: string;
  type: string;
  label: string;
  source: string;
  value: string;
  hidden?: boolean;
};

export type ItemPlan = {
  /** e-mail / SMS dry run */
  channel?: string;
  ok?: boolean;
  manual?: boolean;
  problems?: string[];
  recipient?: string;
  from?: string;
  reply_to?: string;
  note?: string;
  sms?: { parts: number; length: number; encoding: string };
  link?: string;
  page_url?: string;
  action_url?: string;
  method?: string;
  enctype?: string;
  verdict?: "eligible" | "skip" | string;
  reasons?: { code: string; text: string }[];
  fields?: PlanField[];
  detected?: Record<string, unknown>;
};

export type ApprovalInfo = { valid: boolean; by?: string | null; at?: string | null };

export type Attempt = {
  attempted_at: string;
  url: string;
  method: string;
  payload: Record<string, string> | { name: string; value: string }[];
  status_code: number;
  response_snippet: string;
  success_guess: "likely_success" | "unclear" | "likely_failure" | string;
  outcome: string;
  error: string;
  elapsed_ms: number;
};

export type ItemLead = Partial<Pick<LeadRow, "display_name" | "business_name" | "website" | "city" | "phone" | "do_not_contact">> & { id: number };

export type OutreachItem = {
  id: number;
  lead?: ItemLead;
  lead_id?: number;
  lead_name?: string;
  domain?: string;
  channel?: ChannelKey;
  channel_label?: string;
  recipient?: string;
  template?: { id: number; name: string } | null;
  manual?: { link: string; link_kind: string; label: string; steps: string; copy_text: boolean; recipient: string; note: string } | null;
  sms?: SmsSize | null;
  target_url: string;
  subject: string;
  rendered_text: string;
  status: ItemStatus;
  status_label?: string;
  skip_reason: string;
  skip_reason_text: string;
  manual_note?: string;
  forced?: boolean;
  plan?: ItemPlan | null;
  plan_checked_at?: string | null;
  approval?: ApprovalInfo | null;
  attempt?: Attempt | null;
  updated_at?: string;
};

export type ApproveResult = { approved: number; refused: { item_id: number; code: string; text: string }[] };

export type AddLeadsResult = {
  added: number;
  skipped: { lead_id: number; lead_name?: string; reason: string; reason_text: string }[];
};

export type ManualOutcome = "sent" | "no_form" | "needs_login" | "unreachable" | "skipped";

// ------------------------------------------------------------------ product knowledge + the AI writer (M5)

export type KnowledgeSection = "feature" | "benefit" | "limitation" | "audience" | "demo" | "offer" | "price" | "note";

export type KnowledgeItem = {
  id: number;
  section: KnowledgeSection;
  section_label: string;
  title: string;
  body: string;
  url: string;
  sort_order: number;
  is_active: boolean;
  note: string;
  is_default: boolean;
  seed_key: string;
  needs_value: boolean;
  needs_value_hint: string;
  updated_at: string;
};

export type KnowledgeList = {
  sections: { key: KnowledgeSection; label: string }[];
  items: KnowledgeItem[];
  summary: { total: number; active: number; prices_missing: number; defaults_missing: number };
};

export type VersionWarning = { code: string; text: string; blocking: boolean };

export type MessageVersion = {
  id: number;
  item_id: number;
  version: number;
  status: "generating" | "proposed" | "approved" | "superseded" | "rejected" | "failed";
  status_label: string;
  instructions: string;
  subject: string;
  body: string;
  text: string;
  personalization_reason: string;
  evidence: { ref: string; label: string; text: string }[];
  warnings: VersionWarning[];
  blocking_warnings: number;
  route: { via?: string; model?: string };
  error: string;
  created_by_name: string;
  created_at: string;
  finished_at: string | null;
  decided_by_name: string;
  decided_at: string | null;
  same_as_current: boolean;
  sms: SmsSize | null;
};

export type VersionList = { versions: MessageVersion[]; current_text: string; current_subject: string };

export type DiffOp = { op: "equal" | "delete" | "insert"; a: string; b: string };
export type VersionCompare = { a: { label: string; text: string }; b: { label: string; text: string }; ops: DiffOp[] };

export type { Paged };
