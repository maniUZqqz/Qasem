/**
 * بازبینیِ کیفیت ۱۱/۱۴ — سه خرابیِ کوچکِ ادیتورِ ویدیو: اعلانِ «در صف» در تبِ زیرنویس، جدولِ قبل/بعد، و انتخابِ پروژه در تبِ خروجی؛
 * به‌علاوهٔ رنگِ حرفِ هایلایتِ «کادر» (مثلِ سرور).
 *
 *   cd frontend && node_modules/.bin/esbuild tests/video-ui-trio.test.tsx --bundle --platform=node --format=cjs --jsx=automatic --loader:.css=empty --outfile=/tmp/video-ui-trio.test.cjs
 *   node /tmp/video-ui-trio.test.cjs
 */
import assert from "node:assert/strict";

import { renderToStaticMarkup } from "react-dom/server";

import BeforeAfter, { faText } from "../src/components/BeforeAfter";
import { WaitingNotice, waitingText } from "../src/features/content/video/manual/CaptionsPanel";
import ProjectPicker from "../src/features/content/video/manual/ProjectPicker";
import { projectOptionLabel } from "../src/features/content/video/manual/projectLabel";
import { inkOnBox } from "../src/features/content/video/manual/textRender";

const results: { name: string; ok: boolean; err?: string }[] = [];
function check(name: string, fn: () => void) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, err: e instanceof Error ? e.message : String(e) });
  }
}

check("اعلانِ «در صف»: برچسبِ کوتاه + جملهٔ شکسته‌شونده، نه یک قرصِ تک‌خط", () => {
  assert.equal(waitingText("در صف — منتظر سرور"), "منتظر سرور");
  assert.equal(waitingText("در صف - سرور خاموش است"), "سرور خاموش است");
  assert.equal(waitingText("سرور روشن می‌شود"), "سرور روشن می‌شود");
  const html = renderToStaticMarkup(<WaitingNotice message="در صف — سرورِ پردازش خاموش است؛ بعد از روشن‌شدن خودکار انجام می‌شود" />);
  assert.ok(html.includes('data-testid="captions-waiting-box"'));
  assert.ok(html.includes('<span class="u-badge u-badge-warn">در صف</span>'), "short badge only");
  assert.ok(/<p class="ws-hint cap-wait-text"[^>]*>سرورِ پردازش خاموش است/.test(html), "the sentence is a wrapping paragraph");
  assert.ok(!/u-badge[^>]*>[^<]*سرورِ پردازش/.test(html), "the sentence is not inside the badge");
  const empty = renderToStaticMarkup(<WaitingNotice message="" />);
  assert.ok(empty.includes("در صف می‌ماند"), "a default sentence when the server gave none");
});

check("متنِ سرور با رقمِ فارسی", () => {
  assert.equal(faText("3 cuts, 12.5 s removed"), "۳ cuts, ۱۲٫۵ s removed");
  assert.equal(faText("v1.2 ok."), "v۱٫۲ ok.");
  assert.equal(faText(""), "");
});

check("جدولِ قبل/بعد: سرستون‌ها و عددها هم‌تراز (وسط)، عددِ فارسیِ هم‌عرض، خلاصهٔ سرور فارسی", () => {
  const html = renderToStaticMarkup(
    <BeforeAfter beforeUrl="/a.mp4" afterUrl="/b.mp4" before={{ duration: 21.4, snr_db: 9.2, p50: 80 }} after={{ duration: 18.2, snr_db: 15.6, p50: 120 }}
      summary="3 cuts, 3.2 s removed" improved />,
  );
  assert.ok(html.includes('data-testid="ba-table"'));
  const ths = [...html.matchAll(/<th class="([^"]*)">([^<]*)<\/th>/g)].map((m) => [m[2], m[1]]);
  assert.deepEqual(ths.map((t) => t[0]), ["سنجه", "قبل", "بعد"]);
  assert.ok(ths[1][1].includes("text-center") && ths[2][1].includes("text-center"), "numeric headers centred");
  assert.ok(ths[0][1].includes("text-start"));
  for (const key of ["duration", "snr_db", "p50"]) {
    assert.match(html, new RegExp(`data-testid="ba-before-${key}"[^>]*>[^<]*[۰-۹]`), key);
    assert.ok(new RegExp(`class="py-1 text-center[^"]*"[^>]*data-testid="ba-(before|after)-${key}"`).test(html), `${key}: centred cells`);
  }
  assert.ok(!/dir="ltr"/.test(html.split("ba-table")[1] ?? ""), "no per-cell ltr that left-aligned the numbers");
  assert.ok(html.includes("tabular-nums"));
  assert.ok(html.includes("۲۱٫۴") && html.includes("۱۸٫۲"), "table decimals use the Persian separator like the summary");
  assert.ok(html.includes("۳ cuts, ۳٫۲ s removed"), "the server summary uses Persian digits");
});

check("انتخابِ پروژه: برچسب‌دار، فقط پروژه‌های دیگر با تاریخ و مدت", () => {
  const rows = [
    { id: 7, title: "ریلزِ چغر", state: "READY" as const, error: "", render_info: { seconds: 65 }, output_url: null, updated_at: "2026-11-13T09:00:00Z" },
    { id: 8, title: "", state: "DRAFT" as const, error: "", render_info: {}, output_url: null, updated_at: "2026-11-12T09:00:00Z" },
    { id: 9, title: "پروژهٔ جاری", state: "DRAFT" as const, error: "", render_info: {}, output_url: null, updated_at: "2026-11-14T09:00:00Z" },
  ];
  const html = renderToStaticMarkup(<ProjectPicker projects={rows} projectId={9} onOpen={() => undefined} />);
  assert.ok(html.includes("<span>پروژه‌های دیگر</span>"), "labelled");
  assert.ok(html.includes('aria-label="پروژه‌های دیگر"') && html.includes('data-testid="project-select"'));
  assert.ok(!html.includes("پروژهٔ جاری"), "the open project's name is not repeated");
  assert.ok(html.includes("ریلزِ چغر ·") && html.includes("۱:۰۵"), "date and length in the option");
  assert.ok(html.includes("پروژه ۸"), "an untitled project gets a numbered name");
  assert.ok(html.includes("پروژهٔ تازهٔ خالی"));
  assert.ok(html.includes("out-proj-select"));
  assert.equal(renderToStaticMarkup(<ProjectPicker projects={[]} projectId={null} onOpen={() => undefined} />), "", "nothing to choose, nothing shown");
  const fresh = renderToStaticMarkup(<ProjectPicker projects={rows.slice(0, 1)} projectId={null} onOpen={() => undefined} />);
  assert.ok(!fresh.includes("پروژهٔ تازهٔ خالی"), "no «new» entry while already in a new project");
  assert.equal(projectOptionLabel({ id: 3, title: "الف", updated_at: "bad", render_info: {} }), "الف");
});

check("رنگِ حرفِ هایلایتِ کادر: تیره روی کادرِ روشن، سفید روی کادرِ تیره", () => {
  assert.equal(inkOnBox("#ffd400"), "#111111");
  assert.equal(inkOnBox("#ffffff"), "#111111");
  assert.equal(inkOnBox("#111111"), "#ffffff");
  assert.equal(inkOnBox("#000000"), "#ffffff");
  assert.equal(inkOnBox("#1d3fa6"), "#ffffff");
  assert.equal(inkOnBox("نه"), "#111111", "an unreadable colour falls back to the yellow marker");
});

const bad = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? "✓" : "✗"} ${r.name}${r.err ? ` — ${r.err}` : ""}`);
console.log(bad.length ? `${bad.length} از ${results.length} آزمون رد شد` : `همهٔ ${results.length} بررسی درست`);
if (bad.length) process.exit(1);
