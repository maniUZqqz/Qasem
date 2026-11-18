/** شکل پاسخ‌های /api/v1/egress/ (فقط کارکنان) و چند تابعِ کوچکِ نمایش. هیچ‌جای این پاسخ‌ها رمزِ پراکسی نیست؛ فقط «has_password». */

export type HealthState = "ok" | "partial" | "down" | "unknown";

export type Target = {
  label: string;
  ok: boolean;
  status: number | null;
  ms: number | null;
  error: string;
  service?: string;
  proxy_failure?: boolean;
};

export type Health = {
  state: HealthState;
  detail: string;
  checked_at: string | null;
  stale: boolean;
  targets: Target[];
  via?: string;
  proxy?: string;
  latency_ms?: number | null;
};

export type ServiceRow = {
  key: string;
  title: string;
  group: string;
  summary: string;
  used_by: string[];
  hosts: string[];
  probes: { label: string; url: string }[];
  node: boolean;
  proxy_id: number | null;
  proxy_name: string;
  mode: "proxy" | "direct";
  effective: "proxy" | "direct";
  note: string;
  health: Health;
};

export type TestResult = {
  ok: boolean;
  via: "proxy" | "direct";
  proxy: string;
  checked_at: string;
  ip: string;
  country: string;
  country_code: string;
  city: string;
  org: string;
  latency_ms: number | null;
  targets: Target[];
  summary: string;
  proxy_error?: string;
};

export type ProxyRow = {
  id: number;
  name: string;
  scheme: "http" | "https" | "socks5" | "socks5h";
  host: string;
  port: number;
  username: string;
  has_password: boolean;
  enabled: boolean;
  note: string;
  address: string;
  is_local: boolean;
  last_test: Partial<TestResult>;
  last_test_at: string | null;
  services: string[];
};

export type NodeRow = {
  name: string;
  online: boolean;
  proxy: string;
  has_proxy: boolean;
  proxy_source: string;
  signed_in: boolean;
};

export type Overview = {
  /** کلیدِ کلیِ پراکسی: خاموش = همهٔ سرویس‌ها مستقیم (جدولِ مسیرها نگه داشته می‌شود). */
  enabled: boolean;
  generated_at: string;
  groups: { key: string; title: string }[];
  services: ServiceRow[];
  proxies: ProxyRow[];
  nodes: NodeRow[];
  any_proxy: boolean;
  all_direct: boolean;
  settings_path: string;
};

export const SCHEME_FA: Record<string, string> = {
  http: "http",
  https: "https",
  socks5: "socks5 (نامِ سایت را خودِ برنامه پیدا می‌کند)",
  socks5h: "socks5h (نامِ سایت را خودِ پراکسی پیدا می‌کند؛ برای ایران بهتر است)",
};

export const SOURCE_FA: Record<string, string> = {
  env: "متغیرِ NM_ABAGRAM_PROXY",
  file: "فایلِ proxy.txt",
  system: "پراکسیِ سیستمِ ویندوز",
  abagram: "تنظیماتِ خودِ آباگرام",
  site: "همین صفحه (پراکسیِ اینستاگرام)",
};

export function stateTone(s: HealthState): "ok" | "warn" | "bad" | "neutral" {
  return s === "ok" ? "ok" : s === "partial" ? "warn" : s === "down" ? "bad" : "neutral";
}

export function stateText(s: HealthState): string {
  return s === "ok" ? "سالم" : s === "partial" ? "بخشی در دسترس" : s === "down" ? "در دسترس نیست" : "آزمایش نشده";
}

export function whenText(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  try {
    return d.toLocaleString("fa-IR", { dateStyle: "short", timeStyle: "short" });
  } catch {
    return d.toISOString();
  }
}

export function msText(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  return `${ms.toLocaleString("fa-IR")} میلی‌ثانیه`;
}

/** «مستقیم» یا «از راهِ پراکسیِ X» برای یک سرویس. */
export function routeText(s: ServiceRow): string {
  return s.effective === "proxy" ? `از راهِ پراکسیِ «${s.proxy_name}»` : "مستقیم";
}
