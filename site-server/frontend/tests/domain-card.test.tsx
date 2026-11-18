/**
 * «دامنه و SSL» — کمک‌های خالص و رندرِ کارت‌ها به HTML (react-dom/server، بی مرورگر)، و هم‌خوانیِ فهرستِ منو با بک‌اند.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/domain-card.test.tsx --bundle --platform=node --format=cjs --jsx=automatic --outfile=/tmp/domain-card.test.cjs
 *   node /tmp/domain-card.test.cjs
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { renderToStaticMarkup } from "react-dom/server";

import { PAGES } from "../src/features/panel/registry";
import {
  commandFor,
  daysText,
  daysTone,
  dnsLabel,
  dnsTone,
  issuerName,
  modeTone,
  type CheckResult,
  type DomainStatus,
} from "../src/features/tools/domain/model";
import { CheckResultView, StatusCard, StepsCard } from "../src/features/tools/domain/parts";

let checks = 0;
const has = (html: string, text: string, msg?: string) => {
  assert.ok(html.includes(text), `${msg ?? "در HTML نیست"}: «${text}»`);
  checks += 1;
};
const hasNot = (html: string, text: string) => {
  assert.ok(!html.includes(text), `نباید در HTML باشد: «${text}»`);
  checks += 1;
};
const eq = <T,>(a: T, b: T, msg?: string) => {
  assert.deepEqual(a, b, msg);
  checks += 1;
};

// ---- کمک‌های خالص
eq(daysTone(75), "ok");
eq(daysTone(30), "warn", "۳۰ روز یعنی هشدار");
eq(daysTone(14), "bad", "۱۴ روز یعنی قرمز");
eq(daysTone(-1), "bad");
eq(daysText(75), "۷۵ روز مانده");
eq(daysText(0), "امروز منقضی می‌شود");
eq(daysText(-3), "منقضی شده");
eq(issuerName("C = US, O = Let's Encrypt, CN = R11"), "R11 (Let's Encrypt)");
eq(issuerName("C = US, O = Let's Encrypt, CN = (STAGING) Ersatz Emmer YR2"), "(STAGING) Ersatz Emmer YR2 (Let's Encrypt)");
eq(issuerName(""), "—");
eq(commandFor("https://Example.IR/panel", true), "/root/nm-domain.sh example.ir --www");
eq(commandFor("", false), "/root/nm-domain.sh example.ir");
eq(dnsLabel("ok"), "درست");
eq(dnsLabel("aaaa"), "رکوردِ AAAA دارد");
eq(dnsTone("partial"), "warn");
eq(dnsTone("wrong"), "bad");
eq(modeTone("ip_only"), "neutral");
eq(modeTone("attention"), "warn");

// ---- کارتِ وضعیت
const base: DomainStatus = {
  configured: false,
  mode: "ip_only",
  server_ip: "87.107.160.17",
  public_base_url: "http://87.107.160.17:8040",
  ip_url: "http://87.107.160.17:8040",
  script: "/root/nm-domain.sh",
  warnings: [],
  domain: null,
  cert: null,
};
{
  const html = renderToStaticMarkup(<StatusCard status={base} />);
  has(html, "فقط با نشانیِ IP (بدونِ https)");
  has(html, "http://87.107.160.17:8040");
  has(html, "هنوز دامنه‌ای وصل نشده");
  hasNot(html, "گواهیِ https");
  hasNot(html, "--rollback");
}
{
  const domainStatus: DomainStatus = {
    ...base,
    configured: true,
    mode: "domain",
    public_base_url: "https://example.ir",
    domain: {
      domain: "example.ir",
      aliases: ["www.example.ir"],
      canonical: "https://example.ir",
      ca: "letsencrypt",
      staging: false,
      applied_at: "2026-11-18T10:00:00Z",
      vhost: "/www/server/panel/vhost/nginx/zz-nm-example.ir.conf",
    },
    cert: { not_after: "2027-02-01T00:00:00Z", days_left: 75, issuer: "C = US, O = Let's Encrypt, CN = R11", names: ["example.ir"], staging: false, self_signed: false },
    dns: { status: "ok", found: ["87.107.160.17"], message: "" },
    rollback_command: "/root/nm-domain.sh --rollback",
    status_command: "/root/nm-domain.sh --status",
  };
  const html = renderToStaticMarkup(<StatusCard status={domainStatus} />);
  has(html, "روی دامنه، با https");
  has(html, "https://example.ir");
  has(html, "۷۵ روز مانده", "تاریخِ انقضا و روزهای مانده");
  has(html, "R11");
  has(html, "u-badge-ok");
  has(html, "درست", "DNS");
  has(html, "/root/nm-domain.sh --rollback");
  hasNot(html, "هنوز دامنه‌ای وصل نشده");

  const soon = renderToStaticMarkup(
    <StatusCard
      status={{
        ...domainStatus,
        mode: "attention",
        warnings: ["گواهی ۷ روز دیگر منقضی می‌شود"],
        cert: { ...domainStatus.cert!, days_left: 7 },
        dns: { status: "wrong", found: ["1.2.3.4"], message: "" },
      }}
    />,
  );
  has(soon, "نیاز به بررسی دارد");
  has(soon, "گواهی ۷ روز دیگر منقضی می‌شود");
  has(soon, "u-badge-bad");
  has(soon, "به جای دیگری اشاره می‌کند");

  const staging = renderToStaticMarkup(<StatusCard status={{ ...domainStatus, cert: { ...domainStatus.cert!, staging: true } }} />);
  has(staging, "آزمایشی (مرورگرها نمی‌پذیرند)");
}

// ---- نتیجهٔ بررسیِ DNS
const report = (status: string, message: string, found: string[] = []) => ({ name: "example.ir", status, message, found, a: { system: found, "1.1.1.1": found } });
const records = [
  { type: "A", name: "@", value: "87.107.160.17", ttl: "3600" },
  { type: "A", name: "www", value: "87.107.160.17", ttl: "3600" },
];
{
  const bad: CheckResult = {
    domain: "example.ir",
    names: ["example.ir", "www.example.ir"],
    server_ip: "87.107.160.17",
    ok: false,
    reports: [report("missing", "برای «example.ir» هنوز رکوردِ A دیده نمی‌شود.")],
    records,
    command: "/root/nm-domain.sh example.ir --www",
    dry_command: "/root/nm-domain.sh example.ir --www --dry-run",
  };
  const html = renderToStaticMarkup(<CheckResultView result={bad} />);
  has(html, "این رکوردها را در پنلِ DNS بسازید");
  has(html, "رکوردِ A ندارد");
  has(html, "87.107.160.17");
  has(html, "www");
  has(html, "۳۶۰۰");
  hasNot(html, "--dry-run", "تا DNS درست نشده دستورِ نصب نشان داده نمی‌شود");

  const ok: CheckResult = { ...bad, ok: true, reports: [report("ok", "«example.ir» به 87.107.160.17 اشاره می‌کند.", ["87.107.160.17"])] };
  const okHtml = renderToStaticMarkup(<CheckResultView result={ok} />);
  has(okHtml, "DNS آماده است");
  has(okHtml, "/root/nm-domain.sh example.ir --www --dry-run");
  has(okHtml, "/root/nm-domain.sh example.ir --www");
  has(okHtml, "پیش‌نمایش؛ هیچ چیز عوض نمی‌شود");
  hasNot(okHtml, "این رکوردها را در پنلِ DNS بسازید");
}

// ---- راهنمای قدم‌به‌قدم
{
  const html = renderToStaticMarkup(<StepsCard ip="87.107.160.17" />);
  has(html, "چه کنم و چه بدهم؟");
  has(html, "دو رکوردِ A بسازید");
  has(html, "87.107.160.17");
  has(html, "فقط نامِ دامنه را به ما بدهید");
  has(html, "آروان‌کلاود", "CDNِ ایرانیِ اختیاری");
  has(html, "به هیچ سرویسِ خارجی نیاز ندارد");
}

// ---- منو: همان کلید در فرانت و بک‌اند
{
  const page = PAGES.find((p) => p.key === "domain_ssl");
  assert.ok(page, "domain_ssl در registry.ts نیست");
  eq(page!.section, "tools");
  eq(page!.to, "/tools/domain");
  eq(page!.staffOnly, true);
  eq(page!.label, "دامنه و SSL");
  const backend = readFileSync(resolve(process.cwd(), "../backend/apps/panel/registry.py"), "utf-8");
  assert.ok(backend.includes('("domain_ssl", "دامنه و SSL", "/tools/domain"'), "registry.py با registry.ts یکی نیست");
  checks += 1;
  const app = readFileSync(resolve(process.cwd(), "src/App.tsx"), "utf-8");
  assert.ok(app.includes('path="/tools/domain"') && app.includes('k="domain_ssl"'), "مسیرِ /tools/domain در App.tsx نیست");
  checks += 1;
}

console.log(`domain-card: ${checks} بررسی درست بود`);
