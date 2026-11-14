/**
 * قابِ پنل: «صفحه پیدا نشد» (مسیرِ `*` و آدرس‌های قدیمی)، عنوانِ تب از روی فهرستِ منو، و تمِ روشن پیش از اولین رنگ‌آمیزی.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/shell-notfound-title.test.tsx --bundle --platform=node --format=cjs --jsx=automatic --outfile=/tmp/shell-notfound-title.test.cjs
 *   node /tmp/shell-notfound-title.test.cjs
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import vm from "node:vm";

import { renderToStaticMarkup } from "react-dom/server";
import { matchPath } from "react-router-dom";
import { StaticRouter } from "react-router-dom/server";

import { NotFoundCard } from "../src/features/panel/NotFoundCard";
import { editDistance, suggestPages } from "../src/features/panel/notFound";
import {
  BRAND,
  NOT_FOUND_TITLE,
  PUBLIC_LABELS,
  normalizePath,
  pageLabelFor,
  registryPageFor,
  titleFor,
} from "../src/features/panel/tabTitle";
import { PAGES, pageHref } from "../src/features/panel/registry";

let checks = 0;
const eq = (a: unknown, b: unknown, msg?: string) => {
  assert.equal(a, b, msg);
  checks += 1;
};
const ok = (v: unknown, msg?: string) => {
  assert.ok(v, msg);
  checks += 1;
};

// فایل‌ها نسبت به همین پوشه خوانده می‌شوند؛ esbuild --format=cjs پس از باندل __dirname را درست نگه نمی‌دارد، پس از cwd (frontend/) می‌رویم
const ROOT = process.cwd().endsWith("frontend") ? process.cwd() : join(dirname(process.argv[1] ?? "."), "..");
const read = (rel: string) => readFileSync(join(ROOT, rel), "utf-8");

// ----------------------------------------------------------------------------------------------------------- عنوانِ تب
eq(titleFor("/"), "داشبورد | NMarketing");
eq(titleFor("/stores/34/analytics", "فروشگاه نمونه"), "آمار | فروشگاه نمونه | NMarketing");
eq(titleFor("/stores/34/analytics/", "فروشگاه نمونه"), "آمار | فروشگاه نمونه | NMarketing", "اسلشِ آخر نادیده");
eq(titleFor("/stores/34/analytics"), "آمار | NMarketing", "نامِ فروشگاه هنوز نیامده");
eq(titleFor("/stores/34", "ف"), "محصولات | ف | NMarketing", "فهرستِ فروشگاه فقط با تطبیقِ کامل");
eq(titleFor("/stores/34/voice/clone", "ف"), "کلونِ صدا | ف | NMarketing");
eq(titleFor("/stores/34/sales/orders", "ف"), "سفارش‌ها | ف | NMarketing");
eq(titleFor("/growth/leads"), "دیتابیس لیدها | NMarketing");
eq(titleFor("/growth/leads/12"), "جزئیات لید | NMarketing", "پیشوند: صفحهٔ جزئیاتِ لید");
eq(titleFor("/tools/3d/projects/9"), "ویدیوی سه‌بعدی | NMarketing", "زیرصفحه‌های ابزار با پیشوند");
eq(titleFor("/tools/compute"), "سرورهای پردازش | NMarketing");
eq(titleFor("/tools/compute/queue"), "صفِ پردازش | NMarketing");
eq(titleFor("/products/5/market"), "محصول — تحلیل بازار | NMarketing", "زبانه‌های محصول پیشوند «محصول —» می‌گیرند");
eq(titleFor("/products/5"), "محصول — مشخصات | NMarketing");
eq(titleFor("/login"), "ورود | NMarketing");
eq(titleFor("/register"), "ثبت‌نام | NMarketing");
eq(titleFor("/forgot-password"), "فراموشیِ رمز | NMarketing");
eq(titleFor("/reset-password"), "تغییرِ رمز | NMarketing");
eq(titleFor("/changelog"), "چه چیزی تازه است | NMarketing", "با عنوانِ خودِ صفحهٔ changelog یکی است");
eq(titleFor("/stores/34/xyz", "ف"), BRAND, "آدرسِ ناشناخته «محصولات» نمی‌شود");
eq(pageLabelFor("/nonexistent-page"), null);
eq(normalizePath("/stores/34/?a=1#x"), "/stores/34");
eq(normalizePath("/"), "/");
eq(NOT_FOUND_TITLE, "صفحه پیدا نشد | NMarketing");
for (const k of Object.keys(PUBLIC_LABELS)) ok(PUBLIC_LABELS[k].length > 0);

// هر صفحهٔ منو (به‌جز صفحهٔ جنگو) برچسبِ خودش را در عنوان دارد، و فقط صفحه‌های فروشگاهی نامِ فروشگاه
for (const page of PAGES) {
  if (page.external) continue;
  const href = pageHref(page, "34");
  const title = titleFor(href, "فروشگاهِ آزمون");
  ok(title.endsWith(" | NMarketing"), `${page.key}: ${title}`);
  const hit = registryPageFor(href);
  ok(hit, `${page.key}: صفحه‌ای برای ${href} پیدا نشد`);
  // دو ورودیِ هم‌آدرس (growth_leads/growth_lead) یکی را برمی‌دارند؛ برچسب باید از همان صفحه باشد
  ok(title.includes(hit!.label), `${page.key}: برچسب ${hit!.label} در «${title}» نیست`);
  eq(title.includes("فروشگاهِ آزمون"), /^\/stores\/\d+/.test(href), `${page.key}: نامِ فروشگاه فقط در صفحه‌های فروشگاهی`);
}

// ------------------------------------------------------- جدولِ مسیرها: هر صفحهٔ منو مسیر دارد، و مسیرِ `*` و آدرس‌های قدیمی هستند
type R = { full: string; depth: number };
function extractRoutes(src: string): R[] {
  const out: R[] = [];
  const stack: string[] = [];
  const re = /<Route\b|<\/Route>/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(src))) {
    if (m[0] === "</Route>") {
      stack.pop();
      continue;
    }
    let i = m.index + m[0].length;
    let depth = 0;
    let quote = "";
    for (; i < src.length; i++) {
      const ch = src[i];
      if (quote) {
        if (ch === quote) quote = "";
        continue;
      }
      if (ch === '"' || ch === "'" || ch === "`") quote = ch;
      else if (ch === "{") depth++;
      else if (ch === "}") depth--;
      else if (depth === 0 && ch === ">") break;
    }
    const tag = src.slice(m.index, i + 1);
    const self = tag.endsWith("/>");
    // فقط صفتِ `path` در سطحِ بالای تگ (بیرونِ آکولادها)
    let top = "";
    let d = 0;
    for (const ch of tag) {
      if (ch === "{") d++;
      if (d === 0) top += ch;
      if (ch === "}") d--;
    }
    const pm = /\bpath="([^"]*)"/.exec(top);
    const own = pm ? pm[1] : "";
    const parent = stack.length ? stack[stack.length - 1] : "";
    const full = own.startsWith("/") ? own : own === "" ? parent : `${parent.replace(/\/$/, "")}/${own}`;
    if (pm || /\bindex\b/.test(top)) out.push({ full: full || "/", depth: stack.length });
    if (!self) stack.push(full);
  }
  return out;
}

const appSrc = read("src/App.tsx");
const routes = extractRoutes(appSrc);
ok(routes.length > 60, `مسیرهای App.tsx خیلی کم‌اند: ${routes.length}`);
const resolvable = routes.filter((r) => r.full !== "*" && r.full !== "/*");
const resolves = (concrete: string) =>
  resolvable.some((r) => matchPath({ path: r.full, end: !r.full.endsWith("/*") }, concrete));

for (const page of PAGES) {
  if (page.external) continue;
  const href = pageHref(page, "34");
  ok(resolves(href), `صفحهٔ «${page.label}» (${page.key}) در App.tsx مسیری برای ${href} ندارد`);
}
// صفحه‌های بیرون از فهرست
for (const p of ["/login", "/register", "/forgot-password", "/reset-password", "/changelog"]) ok(resolves(p), p);

const catchAll = routes.filter((r) => r.full === "*" || r.full === "/*");
eq(catchAll.length, 1, "دقیقاً یک مسیرِ `*`");
eq(catchAll[0].depth, 0, "مسیرِ `*` بیرون از Layout است، تا وارد نشده‌ها هم کارتِ «پیدا نشد» ببینند");
ok(/path="\*"\s+element=\{<NotFoundRoute/.test(appSrc), "مسیرِ `*` باید NotFoundRoute را بکشد");
// آدرس‌های قدیمی
ok(/path="\/stores\/:id\/settings"\s+element=\{<LegacyRedirect to="\/stores\/:id\/data"/.test(appSrc), "settings ⇐ data");
ok(/path="\/tools\/compute\/models"\s+element=\{<LegacyRedirect to="\/tools\/models"/.test(appSrc), "compute/models ⇐ models");
// مقصدِ هر دو هدایت یک مسیرِ واقعی است
ok(resolves("/stores/34/data"));
ok(resolves("/tools/models"));

// آدرس‌های ناشناخته: هیچ مسیرِ واقعی‌ای جز `*` نمی‌گیرد (پس به «پیدا نشد» می‌رسند)
for (const p of ["/nonexistent-page", "/stores/34/xyz", "/stores/34/campaigns/xyz", "/products/5/nothing", "/admin/nothing"]) {
  eq(resolves(p), false, `${p} نباید مسیر داشته باشد`);
}

// ------------------------------------------------------------------------------------------------- کارتِ «پیدا نشد»
const wrap = (el: JSX.Element) => renderToStaticMarkup(<StaticRouter location="/">{el}</StaticRouter>);
{
  const html = wrap(
    <NotFoundCard
      signedIn
      path="/panel/stores/34/xyz"
      storeId="34"
      suggestions={[{ key: "analytics", label: "آمار", href: "/stores/34/analytics" }]}
      canGoBack
    />,
  );
  ok(html.includes("صفحه‌ای که دنبالش بودید پیدا نشد"), "عنوانِ کارت");
  ok(html.includes("/panel/stores/34/xyz"), "آدرسِ درخواستی نشان داده می‌شود");
  ok(html.includes('dir="ltr"'), "آدرس چپ‌به‌راست");
  ok(html.includes('href="/"') && html.includes("رفتن به داشبورد"), "پیوند به داشبورد");
  ok(html.includes('href="/stores/34"') && html.includes("صفحهٔ اصلیِ فروشگاه"), "پیوند به صفحهٔ فروشگاه");
  ok(html.includes("بازگشت"), "دکمهٔ بازگشت");
  ok(html.includes("شاید این صفحه‌ها را می‌خواستید") && html.includes('href="/stores/34/analytics"'), "پیشنهادها");
  ok(!html.includes("ورود به پنل"), "واردشده پیوندِ ورود نمی‌بیند");
}
{
  const html = wrap(<NotFoundCard signedIn={false} path="/panel/nonexistent-page" />);
  ok(html.includes("صفحه‌ای که دنبالش بودید پیدا نشد"));
  ok(html.includes("/panel/nonexistent-page"));
  ok(html.includes('href="/login"') && html.includes("ورود به پنل"), "وارد نشده پیوندِ ورود می‌بیند");
  ok(!html.includes("رفتن به داشبورد"), "وارد نشده پیوندِ داشبورد نمی‌بیند");
  ok(!html.includes("بازگشت"));
}
{
  // بدون فروشگاهِ فعال، پیوندِ فروشگاه نیست؛ بدون تاریخچه، «بازگشت» نیست
  const html = wrap(<NotFoundCard signedIn path="/panel/x" />);
  ok(!html.includes("صفحهٔ اصلیِ فروشگاه"));
  ok(!html.includes("بازگشت"));
  ok(!html.includes("شاید این صفحه‌ها"));
}
// متنِ آدرس HTML نمی‌شود
{
  const html = wrap(<NotFoundCard signedIn path={'/panel/<script>alert(1)</script>'} />);
  ok(!html.includes("<script>alert"), "آدرسِ خطرناک escape می‌شود");
}

// ----------------------------------------------------------------------------------------------------- پیشنهادِ صفحه‌ها
eq(editDistance("analytic", "analytics"), 1);
eq(editDistance("abc", "abc"), 0);
eq(editDistance("", "abc"), 3);
const names = (p: string, o: Partial<Parameters<typeof suggestPages>[1]> = {}) =>
  suggestPages(p, { storeId: "34", isStaff: false, ...o }).map((s) => s.key);
ok(names("/stores/34/analytic").includes("analytics"), "غلطِ تایپی ⇐ آمار");
ok(names("/stores/34/orders-old").includes("orders"), "orders-old ⇐ سفارش‌ها");
ok(names("/stores/34/plan").includes("plan"));
eq(names("/stores/34/zzzzzz").length, 0, "بی‌ربط ⇐ پیشنهادی نیست");
eq(names("/stores/34").length, 0, "فقط شناسه ⇐ پیشنهادی نیست");
ok(!names("/growth/leadz").includes("growth_leads"), "کارمندی برای غیرکارمند نمی‌آید");
ok(names("/growth/leadz", { isStaff: true }).includes("growth_leads"), "کارمند می‌بیند");
ok(!names("/stores/34/analytic", { storeId: null }).includes("analytics"), "بی فروشگاهِ فعال، صفحهٔ فروشگاهی پیشنهاد نمی‌شود");
ok(!names("/stores/34/analytic", { enabled: (p) => p.key !== "analytics" }).includes("analytics"), "صفحهٔ خاموش پیشنهاد نمی‌شود");
ok(suggestPages("/stores/34/analytic", { storeId: "34", isStaff: false, limit: 1 }).length <= 1);
ok(suggestPages("/stores/34/analytic", { storeId: "34", isStaff: false })[0].href === "/stores/34/analytics");

// ------------------------------------------------------------------------------------ تمِ روشن پیش از اولین رنگ‌آمیزی
const html = read("index.html");
const head = html.slice(html.indexOf("<head>"), html.indexOf("</head>"));
const inline = /<script>([\s\S]*?)<\/script>/.exec(head);
ok(inline, "یک اسکریپتِ درون‌خطی در <head> هست");
ok(html.indexOf("<script>") < html.indexOf('type="module"'), "اسکریپتِ تم پیش از بسته‌ی برنامه اجرا می‌شود");
ok(inline![1].split("\n").length <= 14, "اسکریپت کوتاه می‌ماند");
ok(!/src=|fetch\(|http/.test(inline![1]), "اسکریپتِ تم هیچ‌چیز بار نمی‌کند");

function runThemeScript(storage: "light" | "dark" | "garbage" | null | "throws") {
  const attrs: Record<string, string> = {};
  const sandbox = {
    document: { documentElement: { setAttribute: (k: string, v: string) => (attrs[k] = v) } },
    localStorage: {
      getItem: (k: string) => {
        if (storage === "throws") throw new Error("blocked");
        return k === "upmarket-theme" ? storage : null;
      },
    },
  };
  vm.runInNewContext(inline![1], sandbox);
  return attrs["data-theme"];
}
eq(runThemeScript("light"), "light", "ذخیره‌شده روشن ⇐ روشن");
eq(runThemeScript("dark"), "dark");
eq(runThemeScript(null), "dark", "پیش‌فرض تیره است، مثل پیش");
eq(runThemeScript("garbage"), "dark", "مقدارِ نامعتبر ⇐ تیره");
eq(runThemeScript("throws"), "dark", "دسترسی به localStorage خطا بدهد ⇐ تیره، بی خطا");

// ThemeToggle با همان کلید کار می‌کند و دسترسی به localStorage را نگه می‌دارد
const toggle = read("src/components/ThemeToggle.tsx");
ok(toggle.includes('"upmarket-theme"'), "کلیدِ یکسان");
ok(/try\s*\{[\s\S]*getItem/.test(toggle), "خواندنِ localStorage در ThemeToggle هم try/catch دارد");

console.log(`shell-notfound-title: ${checks} checks passed`);
