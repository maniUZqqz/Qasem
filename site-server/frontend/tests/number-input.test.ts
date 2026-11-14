/**
 * قیمت و موجودی با ارقام فارسی: «۳۰۰۰۰۰» دیگر کادر را خالی نمی‌کند، و آنچه عدد نیست
 * بی‌صدا دور ریخته نمی‌شود.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/number-input.test.ts --bundle --platform=node --format=esm --outfile=/tmp/number-input.test.mjs
 *   node /tmp/number-input.test.mjs
 */
import assert from "node:assert/strict";

import {
  cleanNumberInput,
  fieldErrorSentence,
  formatGrouped,
  plainNumber,
  rejectedMessage,
  toFaDigits,
  toLatinDigits,
} from "../src/components/numberInput";

const results: { name: string; ok: boolean; err?: string }[] = [];
function check(name: string, fn: () => void) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, err: e instanceof Error ? e.message : String(e) });
  }
}

check("ارقام فارسی و عربی لاتین می‌شوند", () => {
  assert.equal(toLatinDigits("۰۱۲۳۴۵۶۷۸۹"), "0123456789");
  assert.equal(toLatinDigits("٠١٢٣٤٥٦٧٨٩"), "0123456789");
  assert.equal(toFaDigits(1234), "۱۲۳۴");
});

check("«۳۰۰۰۰۰» همان ۳۰۰۰۰۰ است (باگِ اصلی: کادر خالی می‌ماند)", () => {
  const c = cleanNumberInput("۳۰۰۰۰۰");
  assert.equal(c.value, "300000");
  assert.equal(c.rejected, false);
  assert.equal(c.negative, false);
});

check("جداکننده‌های هزارگان همه برمی‌افتند", () => {
  for (const typed of ["۳۰۰٬۰۰۰", "300,000", "۳۰۰،۰۰۰", " ۳۰۰ ۰۰۰ ", "300 000", "3_00_000", "300.000"]) {
    assert.equal(cleanNumberInput(typed).value, "300000", typed);
  }
});

check("نقطه‌ی اعشار برای تومان معنا ندارد و گفته می‌شود", () => {
  const c = cleanNumberInput("1.5");
  assert.equal(c.value, "15");
  assert.equal(c.rejected, true);
  const d = cleanNumberInput("۱٫۵", { decimals: true });
  assert.equal(d.value, "1.5");
  assert.equal(d.rejected, false);
});

check("حرف حذف می‌شود و rejected می‌گوید", () => {
  const c = cleanNumberInput("۳۰ هزار");
  assert.equal(c.value, "30");
  assert.equal(c.rejected, true);
  assert.equal(rejectedMessage(c), "فقط عدد صحیح بنویسید؛ ارقام فارسی هم اشکال ندارد.");
});

check("منفی حذف می‌شود و پیامِ خودش را دارد", () => {
  for (const typed of ["-5000", "−۵۰۰۰", "–5000"]) {
    const c = cleanNumberInput(typed);
    assert.equal(c.value, "5000", typed);
    assert.equal(c.negative, true, typed);
    assert.equal(rejectedMessage(c), "عدد منفی قبول نیست.");
  }
});

check("صفرِ ابتدایی و طولِ بیش از حد", () => {
  assert.equal(cleanNumberInput("007").value, "7");
  assert.equal(cleanNumberInput("0").value, "0");
  assert.equal(cleanNumberInput("0.5", { decimals: true }).value, "0.5");
  const long = cleanNumberInput("1".repeat(30));
  assert.equal(long.value.length, 15);
  assert.equal(long.rejected, true);
});

check("خالی می‌ماند خالی", () => {
  const c = cleanNumberInput("");
  assert.deepEqual(c, { value: "", rejected: false, negative: false });
});

check("نمایشِ خوانا: «۳۰۰٬۰۰۰»", () => {
  assert.equal(formatGrouped("300000"), "۳۰۰٬۰۰۰");
  assert.equal(formatGrouped("1200"), "۱٬۲۰۰");
  assert.equal(formatGrouped("12"), "۱۲");
  assert.equal(formatGrouped("1500.5"), "۱٬۵۰۰٫۵");
  assert.equal(formatGrouped(""), "");
  assert.equal(formatGrouped("abc"), "");
});

check("عددِ سرور → متنِ کادر، بی‌آنکه نقطه کارِ خراب کند", () => {
  assert.equal(plainNumber("300000.00"), "300000");
  assert.equal(plainNumber("1500.50"), "1500.5");
  assert.equal(plainNumber("100.00"), "100");
  assert.equal(plainNumber("0.00"), "0");
  assert.equal(plainNumber("1000"), "1000");
  assert.equal(plainNumber(12), "12");
  assert.equal(plainNumber(null), "");
  assert.equal(plainNumber(""), "");
  assert.equal(plainNumber("x"), "");
  // و همان مقدار از کادرِ عددی «۳۰۰۰۰۰۰۰» نمی‌شود
  assert.equal(cleanNumberInput(plainNumber("300000.00")).value, "300000");
});

check("خطای سرور درباره‌ی فیلد: جمله‌ی فارسیِ سرور همان است، انگلیسیِ پیش‌فرض برچسب می‌گیرد", () => {
  assert.equal(
    fieldErrorSentence({ price: ["قیمت نمی‌تواند منفی باشد."] }),
    "قیمت نمی‌تواند منفی باشد.",
  );
  assert.equal(
    fieldErrorSentence({ stock_quantity: ["A valid integer is required."] }),
    "موجودی: A valid integer is required.",
  );
  assert.equal(fieldErrorSentence({ detail: "x" }), null);
  assert.equal(fieldErrorSentence(null), null);
});

const failed = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? "  ok  " : " FAIL "} ${r.name}${r.err ? ` — ${r.err}` : ""}`);
if (failed.length) {
  console.log(`\n${failed.length} FAILED`);
  process.exit(1);
}
console.log(`\n${results.length} checks passed`);
