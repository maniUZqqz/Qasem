/**
 * کمکی‌های نمایشِ متنِ سرور به آدم: یک شکلِ تاریخ (شمسی، وقتِ تهران)، «**پررنگ**» و «`کد`» رندر شوند، و سرویسِ دیجیتال
 * «۹۹۹۹ عدد» نشان داده نشود.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/chagher-fmt.test.tsx --bundle --platform=node --format=cjs --jsx=automatic --outfile=/tmp/chagher-fmt.test.cjs
 *   node /tmp/chagher-fmt.test.cjs
 */
import assert from "node:assert/strict";

import { renderToStaticMarkup } from "react-dom/server";

import { RichText, UNLIMITED_STOCK, faDateTime, isUnlimitedStock } from "../src/components/fmt";

let checks = 0;
const eq = (a: unknown, b: unknown, msg?: string) => {
  assert.equal(a, b, msg);
  checks += 1;
};

// تاریخ: ۱۴۰۵/۰۸/۲۳ ۰۶:۰۰ به وقتِ تهران (۰۲:۳۰ UTC)، نه «۲۰۲۶-۱۱-۱۴» و نه «۱۴۰۵/۸/۲۳، ۳:۳۰:۱۰»
eq(faDateTime("2026-11-14T02:30:00Z"), "۱۴۰۵/۰۸/۲۳ ۰۶:۰۰");
eq(faDateTime("2026-11-14T02:30:00Z", false), "۱۴۰۵/۰۸/۲۳");
eq(faDateTime(new Date("2026-11-13T21:00:00Z"), false), "۱۴۰۵/۰۸/۲۳", "نیمه‌شبِ تهران روزِ بعد است");
eq(faDateTime(null), "");
eq(faDateTime("نه تاریخ"), "");

// ۹۹۹۹ = نامحدود
eq(UNLIMITED_STOCK, 9999);
eq(isUnlimitedStock(9999), true);
eq(isUnlimitedStock(12), false);
eq(isUnlimitedStock(undefined), false);

// علامت‌های درون‌خطی
const md = renderToStaticMarkup(<RichText text="برخلاف پوستر، **محصول واقعی شما حفظ می‌شود**. `mode=enhance` فقط عکس را بهتر می‌کند." />);
assert.ok(md.includes("<strong>محصول واقعی شما حفظ می‌شود</strong>"), md);
assert.ok(md.includes("mode=enhance</code>"), md);
assert.ok(!md.includes("**") && !md.includes("`"), md);
checks += 3;

// متنِ بی‌علامت و HTML هرگز تفسیر نمی‌شود
const plain = renderToStaticMarkup(<RichText text="<b>x</b> و ۱ * ۲" />);
assert.ok(plain.includes("&lt;b&gt;x&lt;/b&gt;"), plain);
assert.ok(!plain.includes("<b>"), plain);
checks += 2;

console.log(`chagher-fmt: همهٔ ${checks} بررسی درست`);
