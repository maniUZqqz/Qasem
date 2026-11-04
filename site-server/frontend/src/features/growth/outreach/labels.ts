import type { Tone } from "../format";
import type { CampaignMode, CampaignState, ItemStatus, OutreachItem, Template } from "./types";

/** Persian wording and colours for every status / reason the outreach API can return. */

export const ITEM_STATUS: Record<ItemStatus, { label: string; tone: Tone; hint: string }> = {
  pending: { label: "در انتظار آماده‌سازی", tone: "neutral", hint: "هنوز صفحهٔ فرمش بررسی نشده" },
  ready: { label: "آمادهٔ تأیید", tone: "info", hint: "فرمِ مناسب پیدا شد؛ منتظر تأییدِ شماست" },
  needs_manual: { label: "نیاز به ارسالِ دستی", tone: "warn", hint: "خودکار نمی‌شود فرستاد؛ باید خودتان بفرستید" },
  approved: { label: "تأییدشده", tone: "brand", hint: "آمادهٔ ارسال خودکار" },
  sending: { label: "در حال ارسال", tone: "brand", hint: "" },
  sent: { label: "ارسال شد", tone: "ok", hint: "" },
  failed: { label: "ناموفق", tone: "bad", hint: "دوباره تلاش نمی‌شود" },
  skipped: { label: "ردشده", tone: "neutral", hint: "" },
  cancelled: { label: "لغوشده", tone: "neutral", hint: "" },
  manual_sent: { label: "دستی ارسال شد", tone: "ok", hint: "" },
  no_form: { label: "فرم نداشت", tone: "warn", hint: "" },
  needs_login: { label: "نیاز به ورود داشت", tone: "warn", hint: "" },
};

export const itemStatus = (status: string) =>
  ITEM_STATUS[status as ItemStatus] ?? { label: status, tone: "neutral" as Tone, hint: "" };

/** Order of the counters on the campaign page. */
export const COUNTER_ORDER: ItemStatus[] = [
  "pending",
  "ready",
  "needs_manual",
  "approved",
  "sending",
  "sent",
  "failed",
  "manual_sent",
  "no_form",
  "needs_login",
  "skipped",
  "cancelled",
];

/** Statuses of an item that is finished (nothing more will happen to it). */
export const FINISHED: ItemStatus[] = ["sent", "failed", "skipped", "cancelled", "manual_sent", "no_form", "needs_login"];

/** Statuses the hand-work queue is made of. */
export const MANUAL_QUEUE_STATUSES = (mode: CampaignMode): ItemStatus[] =>
  mode === "manual" ? ["needs_manual", "pending", "ready"] : ["needs_manual"];

export const CAMPAIGN_STATE: Record<CampaignState, { label: string; tone: Tone }> = {
  draft: { label: "پیش‌نویس", tone: "neutral" },
  active: { label: "فعال", tone: "ok" },
  paused: { label: "متوقف", tone: "warn" },
  completed: { label: "تمام شد", tone: "info" },
  cancelled: { label: "لغوشده", tone: "bad" },
};

export const campaignState = (state: string) => CAMPAIGN_STATE[state as CampaignState] ?? { label: state, tone: "neutral" as Tone };

export const MODE_LABEL: Record<CampaignMode, string> = { auto: "ارسال خودکار", manual: "صفِ دستی" };

export const JOB_KIND_LABEL: Record<string, string> = { prepare: "آماده‌سازی فرم‌ها", send: "ارسال" };

/** Why a form/lead cannot be sent automatically (codes of DESIGN-EXT section 3), used when the server sends no text. */
export const REASON_TEXT: Record<string, string> = {
  captcha: "فرم کپچا (تأییدِ «من ربات نیستم») دارد",
  honeypot: "فرم فیلدِ مخفیِ ضدربات دارد",
  login_required: "برای ارسال باید وارد حساب شد",
  otp_required: "فرم کدِ تأییدِ پیامکی می‌خواهد",
  js_only: "فرم فقط با جاوااسکریپت کار می‌کند",
  challenge_page: "صفحه پشتِ سدِ ضدربات (مثل Cloudflare) است",
  file_upload_required: "آپلودِ فایل اجباری است",
  required_field_unfillable: "فیلدِ اجباری‌ای دارد که نمی‌شود راست‌وحسابی پُرش کرد",
  required_checkbox: "تیکِ اجباری دارد (مثلاً قبولِ قوانین)",
  no_message_field: "جایی برای نوشتنِ پیام ندارد",
  no_form_found: "در صفحه فرمی پیدا نشد",
  no_target_url: "آدرسِ صفحهٔ تماس ندارد",
  robots_blocked: "robots.txt سایت اجازه نمی‌دهد",
  robots_unavailable: "robots.txt خوانده نشد؛ برای احتیاط رد شد",
  fetch_failed: "صفحه باز نشد",
  suppressed: "در فهرستِ «تماس نگیر» است",
  already_in_campaign: "قبلاً در این کمپین است",
  already_contacted: "قبلاً با همین قالب پیام گرفته",
  duplicate_domain: "از همین سایت قبلاً یک لید در کمپین هست",
  archived: "بایگانی‌شده است",
  limit: "به سقفِ تعدادِ کمپین رسیده",
  identity_incomplete: "مشخصاتِ فرستنده در تنظیمات کامل نیست",
};

export const reasonText = (item: Pick<OutreachItem, "skip_reason" | "skip_reason_text">): string =>
  item.skip_reason_text || (item.skip_reason ? REASON_TEXT[item.skip_reason] ?? item.skip_reason : "");

export const SOURCE_LABEL: Record<string, string> = {
  sender_name: "نامِ فرستنده (تنظیمات)",
  sender_company: "شرکتِ فرستنده (تنظیمات)",
  sender_email: "ایمیلِ فرستنده (تنظیمات)",
  sender_phone: "تلفنِ فرستنده (تنظیمات)",
  sender_website: "وب‌سایتِ فرستنده (تنظیمات)",
  subject: "موضوعِ قالب",
  message: "متنِ پیام",
  hidden: "مقدارِ مخفیِ صفحه",
  default: "پیش‌فرضِ خودِ فرم",
  checkbox_default: "پیش‌فرضِ خودِ فرم",
};

export const GUESS_LABEL: Record<string, { label: string; tone: Tone }> = {
  likely_success: { label: "به نظر موفق", tone: "ok" },
  unclear: { label: "نامشخص", tone: "warn" },
  likely_failure: { label: "به نظر ناموفق", tone: "bad" },
};

export const SUPPRESSION_KIND: Record<string, string> = { phone: "تلفن", email: "ایمیل", website: "وب‌سایت", instagram: "اینستاگرام" };

export const SUPPRESSION_REASONS: { value: string; label: string }[] = [
  { value: "opt_out", label: "خودش درخواستِ لغو داد" },
  { value: "asked_not_to_contact", label: "گفت تماس نگیرید" },
  { value: "complaint", label: "شکایت کرد" },
  { value: "invalid_contact", label: "راهِ تماس نامعتبر است" },
  { value: "other", label: "دلیلِ دیگر" },
];

export const suppressionReason = (value: string) => SUPPRESSION_REASONS.find((r) => r.value === value)?.label ?? value;

export const AUDIT_KIND: Record<string, string> = {
  settings_changed: "تنظیمات عوض شد",
  emergency_stop: "توقفِ اضطراری",
  emergency_resume: "رفعِ توقفِ اضطراری",
  suppress_added: "به «تماس نگیر» اضافه شد",
  suppress_removed: "از «تماس نگیر» برداشته شد",
  campaign_status: "وضعیتِ کمپین",
  approval: "تأییدِ ارسال",
  send_attempt: "تلاش برای ارسال",
};

export const DEFAULT_PLACEHOLDERS = [
  { key: "business_name", label: "نامِ کسب‌وکار" },
  { key: "city", label: "شهر" },
  { key: "country", label: "کشور" },
  { key: "category", label: "دسته" },
  { key: "website", label: "وب‌سایت" },
  { key: "domain", label: "دامنه" },
  { key: "instagram", label: "اینستاگرام" },
];

export const LANGUAGES = [
  { value: "fa", label: "فارسی" },
  { value: "en", label: "English" },
];

export function templateName(campaign: { template?: number | { id: number; name: string } | null; template_name?: string }, templates?: Template[]): string {
  if (campaign.template_name) return campaign.template_name;
  if (campaign.template && typeof campaign.template === "object") return campaign.template.name;
  if (typeof campaign.template === "number") return templates?.find((t) => t.id === campaign.template)?.name ?? `قالب ${campaign.template}`;
  return "—";
}

export function itemLeadName(item: Pick<OutreachItem, "lead" | "lead_id" | "lead_name">): string {
  return item.lead_name || item.lead?.display_name || item.lead?.business_name || (item.lead_id ? `لید ${item.lead_id}` : item.lead?.id ? `لید ${item.lead.id}` : "—");
}

export const itemLeadId = (item: Pick<OutreachItem, "lead" | "lead_id">): number | null => item.lead?.id ?? item.lead_id ?? null;

/** The closing lines every message gets: sender block + opt-out line (DESIGN-EXT section 3, «Message»). */
export function closingBlock(f: { sender_name: string; sender_company: string; sender_phone: string; sender_email: string; opt_out_line: string }): string {
  const who = [f.sender_name.trim(), f.sender_company.trim()].filter(Boolean).join(" | ");
  const how = [f.sender_phone.trim(), f.sender_email.trim()].filter(Boolean).join(" · ");
  return [who, how].filter(Boolean).join("\n") + (f.opt_out_line.trim() ? `\n\n${f.opt_out_line.trim()}` : "");
}
