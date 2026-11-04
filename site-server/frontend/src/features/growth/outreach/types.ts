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
  is_active: boolean;
  created_by_name?: string;
  created_at?: string;
  updated_at?: string;
  campaigns_count?: number;
};

export type TemplateInput = { name: string; subject: string; body: string; language: string; is_active: boolean };

export type Placeholder = { key: string; label: string; example_source?: string };

export type PreviewResult = { text: string; subject: string; warnings: string[]; unknown_placeholders: string[] };

// ------------------------------------------------------------------ campaigns

export type CampaignMode = "auto" | "manual";
export type CampaignState = "draft" | "active" | "paused" | "completed" | "cancelled";

export type Campaign = {
  id: number;
  name: string;
  template?: number | { id: number; name: string } | null;
  template_id?: number;
  template_name?: string;
  mode: CampaignMode;
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
  | "needs_login";

export type PlanField = {
  name: string;
  type: string;
  label: string;
  source: string;
  value: string;
  hidden?: boolean;
};

export type ItemPlan = {
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

export type ManualOutcome = "sent" | "no_form" | "needs_login" | "skipped";

export type { Paged };
