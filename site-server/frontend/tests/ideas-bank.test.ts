/**
 * آزمونِ منطقِ خالصِ «بانکِ ایده» (بدونِ مرورگر): جست‌وجوی هم‌شکلِ فارسی (همان قاعدهٔ سرور) و ارقامِ فارسی.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/ideas-bank.test.ts --bundle --platform=node --format=esm --outfile=/tmp/ideas-bank.test.mjs
 *   node /tmp/ideas-bank.test.mjs
 */
import assert from "node:assert/strict";

import type { Idea } from "../src/features/content/ideas/api";
import { faDigits, fold, jalaliText, matches } from "../src/features/content/ideas/logic";

function idea(over: Partial<Idea> = {}): Idea {
  return {
    key: "tips_mistake", builtin: true, origin: "builtin", based_on: "", category: "tips", format: "reel", channel: "instagram", tags: ["آموزش", "اشتباهِ رایج"],
    title: "اشتباهِ رایج دربارهٔ {محصول}", logline: "یک اشتباهِ رایج را نشان بدهید.", hook: "این اشتباه را نکن.", shoot: "نمای نزدیک", cta: "ذخیره کن", occasion: null,
    filled: { title: "اشتباهِ رایج دربارهٔ برنامه‌سازِ هوشمند", logline: "یک اشتباهِ رایج را نشان بدهید.", hook: "این اشتباه را نکن.", shoot: "نمای نزدیک", cta: "ذخیره کن" },
    slots: [], needs_data: false, placeholders: ["محصول"], favorite: false, hidden: false, uses: 0, occasion_next: null,
    ...over,
  };
}

// فولد: ی/ک عربی، نیم‌فاصله، اعراب، ارقام
assert.equal(fold("مربيِ ورزشی ۱۲۳ ك"), fold("مربیِ ورزشی 123 ک"));
assert.equal(fold("مربی‌های   باشگاه"), "مربی های باشگاه");
assert.equal(fold("ABC ١٢٣"), "abc 123");
assert.equal(fold(""), "");

// ارقامِ فارسی
assert.equal(faDigits(12), "۱۲");
assert.equal(faDigits("0 9"), "۰ ۹");

// جست‌وجو: هر واژه در هر فیلد (قالب و پرشده)، برچسب و مناسبت
assert.equal(matches(idea(), ""), true);
assert.equal(matches(idea(), "اشتباه"), true);
assert.equal(matches(idea(), "برنامه‌سازِ هوشمند"), true);          // فقط در متنِ پرشده هست
assert.equal(matches(idea(), "برنامه ساز هوشمند"), true);           // نیم‌فاصله = فاصله
assert.equal(matches(idea(), "آموزش اشتباه"), true);                // چند واژه، فیلدهای مختلف
assert.equal(matches(idea(), "zzzz"), false);
assert.equal(matches(idea(), "اشتباه zzzz"), false);                // همهٔ واژه‌ها باید باشند
assert.equal(matches(idea({ occasion: { month: 9, day: 30, name: "شب یلدا" } }), "یلدا"), true);
assert.equal(matches(idea({ tags: ["چک‌لیست"] }), "چک لیست"), true);

// تاریخِ شمسی برای فیلدِ تاریخ (Intl با ICU کامل؛ نودِ ۲۰ دارد)
assert.equal(jalaliText("2026-12-21"), "۳۰ آذر ۱۴۰۵");
assert.equal(jalaliText("2026-03-21"), "۱ فروردین ۱۴۰۵");
assert.equal(jalaliText("نه"), "");

console.log("ideas-bank: ok");
