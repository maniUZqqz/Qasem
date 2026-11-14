/**
 * پنجرهٔ «پیش از انتشار» (render به HTML با react-dom/server، بی مرورگر): گروه‌ها، شمارنده با رقمِ فارسی، «برو به این بلوک»،
 * سه کنش (برو درستش کنم · بله، همین را منتشر کن · ذخیره بدون انتشار) و جای هر مورد در صفحهٔ دیگر.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/site-publish-check.test.tsx --bundle --platform=node --format=cjs --jsx=automatic --outfile=/tmp/site-publish-check.test.cjs
 *   node /tmp/site-publish-check.test.cjs
 */
import assert from "node:assert/strict";

import { renderToStaticMarkup } from "react-dom/server";

import { PublishCheckDialog } from "../src/features/tools/studio/builder/PublishCheck";
import type { Finding } from "../src/features/tools/studio/builder/publishFindings";

const results: { name: string; ok: boolean; err?: string }[] = [];
function check(name: string, fn: () => void) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, err: e instanceof Error ? e.message : String(e) });
  }
}

const F = (over: Partial<Finding> = {}): Finding => ({ id: "b1", type: "hero", kind: "sample", text: "متنِ نمونه: «سلام»", target: "page", page: 3, page_title: "خانه", ...over });
const noop = () => undefined;
const render = (findings: Finding[], here = { target: "page", page: 3 as number | null }, busy = false) =>
  renderToStaticMarkup(
    <PublishCheckDialog findings={findings} labelOf={(t) => ({ hero: "سربرگِ بزرگ", button: "دکمه" }[t] ?? "")} here={here} busy={busy} onGo={noop} onPublish={noop} onSaveOnly={noop} onClose={noop} />,
  );

const FOUR = [
  F({ id: "a" }),
  F({ id: "b", kind: "contact", text: "شمارهٔ تماسِ نمونه (۰۲۱-۱۲۳۴۵۶۷۸)", type: "text" }),
  F({ id: "c", kind: "link", text: "دکمهٔ «تماس با ما» هنوز به جایی وصل نیست", type: "button" }),
  F({ id: "d", kind: "media", text: "این تصویر هنوز انتخاب نشده.", type: "image" }),
];

check("فهرستِ چهار موردی: شمارنده با رقمِ فارسی و هر گروه با برچسبش", () => {
  const html = render(FOUR);
  assert.match(html, /data-testid="publish-check-count">۴</);
  for (const label of ["متنِ نمونه", "شماره یا نشانیِ ساختگی", "پیوندِ خالی", "تصویر یا ویدیوی انتخاب‌نشده"]) assert.ok(html.includes(label), label);
  assert.equal((html.match(/برو به این بلوک/g) ?? []).length, 4, "برای هر مورد یک «برو به این بلوک»");
  assert.ok(html.includes("متنِ نمونه: «سلام»") && html.includes("۰۲۱-۱۲۳۴۵۶۷۸"));
});

check("سه کنش: درست‌کردن، تأییدِ صریح و «ذخیره بدون انتشار» کم‌رنگ", () => {
  const html = render(FOUR);
  assert.match(html, /data-testid="publish-check-fix"[^>]*>برو درستش کنم</);
  assert.match(html, /data-testid="publish-check-confirm"[^>]*>بله، همین را منتشر کن</);
  assert.match(html, /class="nbe-quiet"[^>]*data-testid="publish-check-save"[^>]*>ذخیره بدون انتشار</);
});

check("در حالِ انتشار: دکمه‌های تأیید و ذخیره غیرفعال می‌شوند", () => {
  const html = render(FOUR, { target: "page", page: 3 }, true);
  assert.match(html, /data-testid="publish-check-confirm"[^>]*disabled/);
  assert.ok(html.includes("در حالِ انتشار…"));
});

check("موردِ صفحهٔ دیگر یا سربرگ: جایش نوشته می‌شود؛ همین صفحه نه", () => {
  const html = render([F({ id: "o", page: 9, page_title: "دربارهٔ ما" }), F({ id: "h", target: "header", page: null, page_title: "" }), F({ id: "same" })]);
  assert.ok(html.includes("صفحهٔ «دربارهٔ ما»"), "صفحهٔ دیگر");
  assert.ok(html.includes("سربرگِ سایت"), "سربرگ");
  assert.equal((html.match(/صفحهٔ «خانه»/g) ?? []).length, 0, "همین صفحه جای ندارد");
});

check("متنِ مورد escape می‌شود (متنِ کاربر HTML نیست)", () => {
  const html = render([F({ text: "<img src=x onerror=alert(1)>" })]);
  assert.ok(!html.includes("<img src=x"));
  assert.ok(html.includes("&lt;img"));
});

check("برچسبِ نوعِ بلوک از فهرست می‌آید و اگر نبود «بخش»", () => {
  const html = render([F({ type: "hero" }), F({ id: "q", type: "mystery" })]);
  assert.ok(html.includes("سربرگِ بزرگ"));
  assert.ok(html.includes(">بخش<") || html.includes("بخش"));
});

const failed = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? "ok  " : "FAIL"} ${r.name}${r.err ? `\n     ${r.err.replace(/\n/g, "\n     ")}` : ""}`);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
if (failed.length) process.exit(1);
