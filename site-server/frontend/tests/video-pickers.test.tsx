/**
 * «زبانِ گفتار» و «ظاهرِ زیرنویس» در تدوینِ خودکار (بازبینیِ ۱۱/۱۳): هر سه زبان و هر هفت ظاهر انتخاب‌شدنی‌اند، پیش‌فرض‌ها همان رفتارِ قبلی‌اند.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/video-pickers.test.tsx --bundle --platform=node --format=cjs --jsx=automatic --outfile=/tmp/video-pickers.test.cjs
 *   node /tmp/video-pickers.test.cjs
 */
import assert from "node:assert/strict";

import { renderToStaticMarkup } from "react-dom/server";

import CaptionLookPicker, { CAPTION_LOOKS, captionLook } from "../src/features/content/video/autoedit/CaptionLook";
import SpeechLanguagePicker, { SPEECH_LANGS, speechLang } from "../src/features/content/video/autoedit/SpeechLanguage";

const results: { name: string; ok: boolean; err?: string }[] = [];
function check(name: string, fn: () => void) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, err: e instanceof Error ? e.message : String(e) });
  }
}
const noop = () => undefined;

check("زبانِ گفتار: فارسی، English و تشخیصِ خودکار؛ هر مقدارِ ناشناخته فارسی می‌شود", () => {
  assert.deepEqual(SPEECH_LANGS.map((l) => l.key), ["fa", "en", "auto"]);
  assert.equal(speechLang("en"), "en");
  assert.equal(speechLang("auto"), "auto");
  assert.equal(speechLang("de"), "fa");
  assert.equal(speechLang(""), "fa");
  const html = renderToStaticMarkup(<SpeechLanguagePicker value="en" onChange={noop} testId="x" />);
  assert.ok(html.includes('data-testid="x"'));
  for (const l of SPEECH_LANGS) assert.ok(html.includes(`value="${l.key}"`), l.key);
  assert.ok(html.includes("English (انگلیسی)") && html.includes("تشخیصِ خودکارِ زبان") && html.includes("فارسی"));
  assert.ok(html.includes("زبانِ گفتار"));
});

check("ظاهرِ زیرنویس: خودکار + هر هفت ظاهرِ آماده", () => {
  assert.deepEqual(CAPTION_LOOKS.map((l) => l.key), ["", "pop", "box", "karaoke", "clean", "neon", "typewriter", "lower"]);
  assert.equal(captionLook("neon"), "neon");
  assert.equal(captionLook("bogus"), "");
  const html = renderToStaticMarkup(<CaptionLookPicker value="" onChange={noop} testId="y" />);
  assert.ok(html.includes('data-testid="y"'));
  for (const l of CAPTION_LOOKS.filter((x) => x.key)) assert.ok(html.includes(`value="${l.key}"`), l.key);
  assert.ok(html.includes("خودکار (بر پایهٔ حال‌وهوای ویدیو)"));
});

const bad = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? "✓" : "✗"} ${r.name}${r.err ? ` — ${r.err}` : ""}`);
console.log(bad.length ? `${bad.length} از ${results.length} آزمون رد شد` : `همهٔ ${results.length} بررسی درست`);
if (bad.length) process.exit(1);
