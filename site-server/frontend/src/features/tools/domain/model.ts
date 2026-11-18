/**
 * «دامنه و SSL» — نوع‌ها و کمک‌های خالص (بی React؛ با esbuild + node آزموده می‌شود: tests/domain-card.test.tsx).
 * بک‌اند: backend/apps/panel/domain_status.py ⇒ GET /api/v1/panel/domain/ و POST /api/v1/panel/domain/check/.
 */

export type Tone = "neutral" | "brand" | "ok" | "warn" | "bad" | "info";

export type Cert = {
  not_after: string;
  days_left: number;
  issuer: string;
  names: string[];
  staging: boolean;
  self_signed: boolean;
};

export type DomainInfo = {
  domain: string;
  aliases: string[];
  canonical: string;
  ca: string;
  staging: boolean;
  applied_at: string;
  vhost: string;
  version?: string;
  hsts?: boolean;
  strict_hosts?: boolean;
};

export type DomainStatus = {
  configured: boolean;
  mode: "ip_only" | "domain" | "attention";
  server_ip: string;
  public_base_url: string;
  ip_url: string;
  script: string;
  warnings: string[];
  domain: DomainInfo | null;
  cert: Cert | null;
  cert_served?: boolean;
  dns?: { status: string; found: string[]; message: string } | null;
  node_note?: string;
  rollback_command?: string;
  status_command?: string;
};

export type DnsReport = {
  name: string;
  status: string;
  message: string;
  found: string[];
  a: Record<string, string[]>;
  aaaa?: string[];
};

export type DnsRecord = { type: string; name: string; value: string; ttl: string };

export type CheckResult = {
  domain: string;
  names: string[];
  server_ip: string;
  ok: boolean;
  reports: DnsReport[];
  records: DnsRecord[];
  command: string;
  dry_command: string;
};

const DIGITS = "۰۱۲۳۴۵۶۷۸۹";
export const toFa = (value: number | string): string => String(value).replace(/[0-9]/g, (d) => DIGITS[Number(d)]);

export const MODE_TEXT: Record<DomainStatus["mode"], string> = {
  ip_only: "فقط با نشانیِ IP (بدونِ https)",
  domain: "روی دامنه، با https",
  attention: "روی دامنه است، ولی نیاز به بررسی دارد",
};

export function modeTone(mode: DomainStatus["mode"]): Tone {
  return mode === "domain" ? "ok" : mode === "attention" ? "warn" : "neutral";
}

/** رنگِ «چند روز مانده»: زیرِ ۱۴ روز قرمز (تمدیدِ خودکار باید زودتر انجام می‌شد)، زیرِ ۳۰ زرد. */
export function daysTone(days: number): Tone {
  if (days <= 14) return "bad";
  if (days <= 30) return "warn";
  return "ok";
}

export function daysText(days: number): string {
  if (days < 0) return "منقضی شده";
  if (days === 0) return "امروز منقضی می‌شود";
  return `${toFa(days)} روز مانده`;
}

/** «C = US, O = Let's Encrypt, CN = R11» ⇒ «R11 (Let's Encrypt)». */
export function issuerName(issuer: string): string {
  const cn = /CN\s*=\s*([^,]+)/.exec(issuer)?.[1]?.trim();
  const org = /O\s*=\s*([^,]+)/.exec(issuer)?.[1]?.trim();
  if (cn && org && cn !== org) return `${cn} (${org})`;
  return cn || org || issuer || "—";
}

export function certKind(cert: Cert): string {
  if (cert.staging) return "آزمایشی (مرورگرها نمی‌پذیرند)";
  if (cert.self_signed) return "خودامضا (فقط پشتِ CDN)";
  return "Let's Encrypt";
}

export const DNS_LABEL: Record<string, string> = {
  ok: "درست",
  missing: "رکوردِ A ندارد",
  wrong: "به جای دیگری اشاره می‌کند",
  partial: "هنوز پخش می‌شود",
  aaaa: "رکوردِ AAAA دارد",
  timeout: "جواب نداد",
};

export function dnsTone(status: string): Tone {
  if (status === "ok") return "ok";
  if (status === "partial" || status === "timeout") return "warn";
  return "bad";
}

export function dnsLabel(status: string): string {
  return DNS_LABEL[status] ?? status;
}

export function commandFor(domain: string, www: boolean, script = "/root/nm-domain.sh"): string {
  const name = domain.trim().toLowerCase().replace(/^https?:\/\//, "").replace(/\/.*$/, "");
  return `${script} ${name || "example.ir"}${www ? " --www" : ""}`;
}

export function fmtDate(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("fa-IR", { dateStyle: "long" });
}

export function fmtDateTime(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  // تاریخ و ساعت جدا، تا در متنِ راست‌به‌چپ جابه‌جا نشوند
  const day = d.toLocaleDateString("fa-IR", { dateStyle: "medium" });
  const time = d.toLocaleTimeString("fa-IR", { hour: "2-digit", minute: "2-digit" });
  return `${day} ساعت ${time}`;
}
