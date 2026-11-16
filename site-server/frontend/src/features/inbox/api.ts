import { api } from "../../api/client";

/** همهٔ نشانی‌های صندوق زیر /stores/:id/inbox/ هستند. */
export const ib = (storeId: string, path = "") => `/stores/${storeId}/inbox/${path}`;

export async function get<T>(storeId: string, path: string, params?: Record<string, unknown>): Promise<T> {
  const { data } = await api.get<T>(ib(storeId, path), { params });
  return data;
}
export async function post<T>(storeId: string, path: string, body?: unknown): Promise<T> {
  const { data } = await api.post<T>(ib(storeId, path), body ?? {});
  return data;
}
export async function patch<T>(storeId: string, path: string, body?: unknown): Promise<T> {
  const { data } = await api.patch<T>(ib(storeId, path), body ?? {});
  return data;
}
export async function put<T>(storeId: string, path: string, body?: unknown): Promise<T> {
  const { data } = await api.put<T>(ib(storeId, path), body ?? {});
  return data;
}
export async function del<T = unknown>(storeId: string, path: string): Promise<T> {
  const { data } = await api.delete<T>(ib(storeId, path));
  return data;
}

// --------------------------------------------------------------- types

export type ConvState = "AI" | "HUMAN" | "ESCALATED" | "RESOLVED";
export type SlaState = "none" | "ok" | "warning" | "breached";
export type PresenceStatus = "ONLINE" | "BUSY" | "OFFLINE";

export type UserRef = { username: string; name: string };

export type ConvRow = {
  id: number;
  channel: string;
  channel_title: string;
  state: ConvState;
  customer: { id: number; name: string; phone: string };
  contact_id: number | null;
  assigned_to: UserRef | null;
  mine: boolean;
  tags: string[];
  unread: number;
  waiting_minutes: number | null;
  sla: SlaState;
  sla_due_at: string | null;
  is_test: boolean;
  ai_failed: boolean;
  priority: number;
  handoff_reason: string;
  bot_confidence: number | null;
  last_message: { role: string; text: string; at: string } | null;
  last_customer_at: string | null;
  updated_at: string;
};

export type Member = { username: string; name: string; status: PresenceStatus };

export type InboxList = {
  conversations: ConvRow[];
  counts: { waiting: number; unread: number; unassigned: number; mine: number; breached: number; tests: number };
  by_channel: Record<string, number>;
  now: string;
  me: { username: string; can_write: boolean; can_settings: boolean; is_staff: boolean };
  members: Member[];
};

export type ThreadItem = {
  id: number;
  type: "message" | "note";
  role: "CUSTOMER" | "AI" | "HUMAN" | "NOTE";
  text: string;
  at: string;
  kind?: string;
  author: string;
  delivered?: boolean | null;
  delivery_error?: string;
  image?: boolean;
  withheld?: boolean;
  mentions?: string[];
};

export type FollowUp = {
  id: number;
  kind: string;
  kind_title: string;
  target: "CUSTOMER" | "AGENT";
  text: string;
  due_at: string;
  status: string;
  status_title: string;
  conversation_id: number | null;
  order_id: number | null;
  assigned_to: string;
  error: string;
  is_test: boolean;
  sent_at: string | null;
  customer: string;
};

export type Thread = {
  conversation: ConvRow;
  thread: ThreadItem[];
  followups: FollowUp[];
  meta: { first_response_seconds: number | null; reopened_count: number; survey_sent_at: string | null };
};

export type ContactPanel = {
  id: number;
  name: string;
  phone: string;
  email: string;
  notes: string;
  usernames: string[];
  tags: string[];
  orders_count: number;
  total_spent: number;
  last_purchase_at: string | null;
  last_activity_at: string | null;
  first_seen_at: string;
  opt_out: Record<string, boolean>;
  source: string;
  is_test: boolean;
  segments: string[];
  customers: { id: number; channel: string; name: string; matched_by: string }[];
  conversations: { id: number; channel: string; state: string; updated_at: string; is_test: boolean }[];
  orders: { id: number; status: string; status_title: string; total: number; at: string; items: number }[];
  history: { id: number; role: string; text: string; at: string; channel: string; conversation_id: number }[];
  channels?: string[];
};

export type Canned = { id: number; title: string; shortcut: string; text: string; channels: string[]; use_count: number };

export type Settings = {
  assignment_mode: "MANUAL" | "ROUND_ROBIN" | "BY_CHANNEL" | "BY_SKILL";
  assign_when: "HANDOFF" | "ALWAYS";
  assign_only_online: boolean;
  sla_first_response_min: number;
  sla_warn_percent: number;
  sla_pause_off_hours: boolean;
  working_hours: { days?: number[]; start?: string; end?: string };
  bot_enabled: boolean;
  bot_min_confidence: number;
  bot_handoff_keywords: string[];
  bot_handoff_keywords_effective: string[];
  bot_offhours: "BOT" | "MESSAGE" | "QUEUE";
  bot_offhours_default_message: string;
  offhours_message: string;
  greeting_message: string;
  handoff_message: string;
  handoff_default_message: string;
  survey_enabled: boolean;
  survey_text: string;
  survey_delay_min: number;
  payment_reminder_enabled: boolean;
  payment_reminder_hours: number;
  payment_reminder_max: number;
  payment_reminder_text: string;
  rate_limits: Record<string, number>;
  merge_by_username: boolean;
  widget: Record<string, string | boolean>;
  default_working_hours: { days: number[]; start: string; end: string };
  open_now: boolean;
};

export type TeamRow = {
  username: string;
  name: string;
  role: string | null;
  role_title?: string;
  status: PresenceStatus;
  status_note: string;
  open: number;
  max_open: number;
  replies: number;
  avg_response_seconds: number | null;
  avg_first_response_seconds: number | null;
  conversations_answered: number;
  sla_breaches: number;
  accepts_chats: boolean;
  channels: string[];
  skills: string[];
  last_seen_at: string | null;
};

export type Stats = {
  days: number;
  open: number;
  waiting_for_person: number;
  unassigned: number;
  resolved: number;
  sla_breaches: number;
  avg_first_response_seconds: number | null;
  bot_handoffs: number;
  per_channel: Record<string, { open: number; closed: number }>;
  survey: {
    answered: number;
    average: number | null;
    distribution: Record<string, number>;
    by_agent: Record<string, { average: number; count: number }>;
    sent: number;
  };
};

export type ChannelField = {
  key: string;
  label: string;
  secret?: boolean;
  kind?: "list" | "bool";
  placeholder?: string;
  help?: string;
};

export type ChannelInfo = {
  kind: string;
  title: string;
  summary: string;
  fields: ChannelField[];
  steps: string[];
  limits: string;
  docs: string;
  needs_owner_account: boolean;
  mode_hint: string;
  enabled: boolean;
  ready: boolean;
  mode: "AUTO" | "WEBHOOK" | "POLLING";
  masked_token: string;
  config: Record<string, unknown>;
  has_app_secret: boolean;
  hook_url: string;
  health: { ok: boolean | null; detail: string; checked_at: string | null; account: string };
  last_inbound_at: string | null;
  last_outbound_at: string | null;
  last_poll_at: string | null;
  last_error: string;
  last_error_at: string | null;
  inbound_count: number;
  outbound_count: number;
  snippet?: string;
  widget_key?: string;
  sms?: { paused: boolean; forwarding: boolean; online: number; phones: { name: string; online: boolean; sms_ready: boolean | null; battery: number | null }[] };
  can_toggle_forwarding?: boolean;
};

export type SegmentRule = { field: string; op: string; value?: string | number | boolean | null };
export type SegmentRules = { match?: "all" | "any"; rules: SegmentRule[] };
export type Segment = {
  id: number;
  name: string;
  description: string;
  rules: SegmentRules;
  builtin: boolean;
  builtin_key: string;
  count: number | null;
};
export type SegmentField = { key: string; kind: string; label: string };

export type ContactRow = {
  id: number;
  name: string;
  phone: string;
  usernames: string[];
  tags: string[];
  orders_count: number;
  total_spent: number;
  last_purchase_at: string | null;
  last_activity_at: string | null;
  opt_out: Record<string, boolean>;
  is_test: boolean;
  channels?: string[];
};

export type BroadcastRow = {
  id: number;
  name: string;
  text: string;
  channels: string[];
  segment_id: number | null;
  segment_name: string;
  status: string;
  status_title: string;
  dedupe: boolean;
  is_test: boolean;
  created_by: string;
  approved_by: string;
  approved_at: string | null;
  review_note: string;
  scheduled_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  stats: Record<string, number | Record<string, number>>;
  created_at: string;
  can_approve?: boolean;
  cannot_approve_reason?: string;
  recipients_sample?: { channel: string; status: string; status_title?: string; skip_reason: string; skip_reason_title?: string; error: string; contact__name: string; contact__phone: string }[];
};

export type BroadcastPreview = {
  people: number;
  recipients: number;
  per_channel: Record<string, number>;
  skipped: { opted_out: number; no_address: number; channel_off: number };
  channels_off: string[];
  samples: { to: string; channel: string; text: string }[];
  estimated_minutes: number;
  warnings: string[];
};

export type WebhookRow = {
  id: number;
  url: string;
  events: string[];
  active: boolean;
  failure_count: number;
  last_status: string;
  last_delivery_at: string | null;
  secret?: string;
  deliveries?: { id: number; event: string; status: string; attempts: number; response_code: number | null; error: string; created_at: string }[];
};

// ------------------------------------------------------------ constants

export const CHANNEL_COLOR: Record<string, string> = {
  TELEGRAM: "#229ed9",
  BALE: "#39b54a",
  EITAA: "#f58220",
  RUBIKA: "#e0457b",
  WEBCHAT: "#8b7bff",
  SMS: "#8a94a8",
  INSTAGRAM: "#c13584",
  WHATSAPP: "#25d366",
  WEB: "#8b7bff",
  API: "#64748b",
};

export const CHANNEL_TITLE: Record<string, string> = {
  TELEGRAM: "تلگرام",
  BALE: "بله",
  EITAA: "ایتا",
  RUBIKA: "روبیکا",
  WEBCHAT: "چت سایت",
  SMS: "پیامک",
  INSTAGRAM: "اینستاگرام",
  WHATSAPP: "واتساپ",
  WEB: "چت سایت و پنل",
  API: "API",
};

export const STATE_TITLE: Record<string, string> = {
  AI: "ربات جواب می‌دهد",
  HUMAN: "با تیم",
  ESCALATED: "منتظر تیم",
  RESOLVED: "بسته شد",
};

export const ASSIGN_TITLE: Record<string, string> = {
  MANUAL: "دستی (هر کس خودش برمی‌دارد)",
  ROUND_ROBIN: "نوبتی بین آنلاین‌ها",
  BY_CHANNEL: "بر اساس کانال",
  BY_SKILL: "بر اساس مهارت",
};

export const PRESENCE_TITLE: Record<PresenceStatus, string> = {
  ONLINE: "آنلاین",
  BUSY: "مشغول",
  OFFLINE: "آفلاین",
};

export const WEEKDAYS: { n: number; label: string }[] = [
  { n: 5, label: "شنبه" },
  { n: 6, label: "یکشنبه" },
  { n: 0, label: "دوشنبه" },
  { n: 1, label: "سه‌شنبه" },
  { n: 2, label: "چهارشنبه" },
  { n: 3, label: "پنجشنبه" },
  { n: 4, label: "جمعه" },
];

/** نقش‌ها و وضعیت‌های فنی به فارسی؛ پنل هرگز کدِ انگلیسی (OWNER، SENT، opted_out) را چاپ نمی‌کند. */
export const ROLE_TITLE: Record<string, string> = {
  OWNER: "مالک",
  ADMIN: "مدیر",
  MARKETING: "بازاریابی",
  CONTENT: "مدیر محتوا",
  SUPPORT: "پشتیبانی",
  VIEWER: "بازدیدکننده",
};

export const RECIPIENT_STATUS_TITLE: Record<string, string> = {
  QUEUED: "در صف",
  SENT: "فرستاده شد",
  FAILED: "ناموفق",
  SKIPPED: "رد شد",
};

export const SKIP_REASON_TITLE: Record<string, string> = {
  opted_out: "پیام تبلیغاتی را لغو کرده است",
  cancelled: "ارسال لغو شد",
  no_address: "راه ارسال ندارد",
  channel_off: "کانال خاموش است",
};
