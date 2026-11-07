/**
 * آزمونِ ترجمهٔ زیرنویس (منطقِ خالصِ پنل).
 *
 *   cd frontend && node_modules/.bin/esbuild tests/video-r5-translate.test.ts --bundle --platform=node --format=esm --outfile=/tmp/video-r5-translate.test.mjs
 *   node /tmp/video-r5-translate.test.mjs
 */
import assert from "node:assert/strict";

import { AnyClip, Project, TextClip, emptyProject } from "../src/features/content/video/manual/model";
import { MAX_LINES, TRANSLATE_LANGS, applyTranslation, captionLines, langTitle, resultItems } from "../src/features/content/video/manual/r5translate";

const results: { name: string; ok: boolean; err?: string }[] = [];
function check(name: string, fn: () => void) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, err: e instanceof Error ? `${e.message}\n${e.stack?.split("\n").slice(1, 4).join("\n")}` : String(e) });
  }
}

const text = (id: string, at: number, duration: number, t: string, over: Partial<TextClip> = {}): TextClip => ({
  id, type: "text", text: t, at, duration, position: "bottom", size: 6, color: "#fff", box: false, opacity: 1, label: t, ...over,
});
function proj(captionClips: AnyClip[], other: AnyClip[] = []): Project {
  const p = emptyProject();
  let first = false;
  return {
    ...p,
    tracks: p.tracks.map((t) => {
      if (t.kind === "text" && !first) { first = true; return { ...t, caption: true, name: "زیرنویس", clips: captionClips }; }
      return t;
    }).concat(other.length ? [{ id: "tx2", kind: "text" as const, name: "عنوان", muted: false, locked: false, clips: other }] : []),
  };
}

const cap = (p: Project) => p.tracks.find((t) => t.kind === "text" && t.caption)!;

check("خط‌های زیرنویس به ترتیبِ زمان و فقط غیرخالی", () => {
  const p = proj([text("b", 5, 2, "دوم"), text("a", 1, 2, "اول"), text("e", 8, 1, "   ")]);
  assert.deepEqual(captionLines(p), [{ id: "a", text: "اول" }, { id: "b", text: "دوم" }]);
});
check("اگر ترکِ زیرنویس خالی بود همهٔ متن‌ها", () => {
  const p = proj([], [text("t", 0, 2, "عنوان")]);
  assert.deepEqual(captionLines(p), [{ id: "t", text: "عنوان" }]);
});
check("با ترکِ زیرنویس، عنوان‌های دیگر جزءِ ترجمه نیستند", () => {
  const p = proj([text("a", 0, 2, "سلام")], [text("t", 0, 2, "عنوان")]);
  assert.deepEqual(captionLines(p).map((l) => l.id), ["a"]);
});
check("ترکِ تازه: زمان و سبک می‌ماند، متن عوض می‌شود، اصل دست نخورده، کلمه‌ها پاک", () => {
  const p = proj([text("a", 1, 2, "سلام", { size: 8, words: [{ w: "سلام", s: 0, e: 1 }] }), text("b", 4, 2, "دنیا")]);
  const q = applyTranslation(p, [{ id: "a", text: "Hello" }, { id: "b", text: "World" }], "en", "new");
  const before = p.tracks.flatMap((t) => t.clips).map((c) => (c as TextClip).text);
  assert.deepEqual(cap(q).clips.map((c) => (c as TextClip).text), before.slice(0, 2), "اصل");
  const made = q.tracks.find((t) => t.name === "ترجمه (انگلیسی)")!;
  assert.ok(made && made.kind === "text");
  assert.equal(made.caption, false);
  const [x, y] = made.clips as TextClip[];
  assert.equal(x.text, "Hello");
  assert.equal(x.at, 1);
  assert.equal(x.duration, 2);
  assert.equal(x.size, 8);
  assert.equal(x.words, undefined);
  assert.equal(x.align, "center", "زبانِ چپ‌به‌راست وسط‌چین");
  assert.equal(y.text, "World");
  assert.notEqual(x.id, "a");
  assert.equal(new Set(q.tracks.flatMap((t) => t.clips.map((c) => c.id))).size, 4, "شناسه‌ها یکتا");
});
check("جایگزینی: همان قطعه‌ها، متنِ تازه، بدونِ ترکِ جدید", () => {
  const p = proj([text("a", 1, 2, "hello", { words: [{ w: "hello", s: 0, e: 1 }] })]);
  const q = applyTranslation(p, [{ id: "a", text: "سلام" }], "fa", "replace");
  assert.equal(q.tracks.length, p.tracks.length);
  const c = cap(q).clips[0] as TextClip;
  assert.equal(c.text, "سلام");
  assert.equal(c.id, "a");
  assert.equal(c.words, undefined);
  assert.notEqual(c.align, "center", "فارسی تراز را عوض نمی‌کند");
});
check("ترجمهٔ شناسه‌های ناشناخته چیزی را خراب نمی‌کند", () => {
  const p = proj([text("a", 1, 2, "سلام")]);
  assert.equal(applyTranslation(p, [{ id: "zzz", text: "x" }], "en", "new"), p);
  const r = applyTranslation(p, [{ id: "zzz", text: "x" }], "en", "replace");
  assert.equal((cap(r).clips[0] as TextClip).text, "سلام");
});
check("نتیجهٔ job: شکلِ درست پذیرفته، شکلِ غلط null", () => {
  assert.deepEqual(resultItems({ items: [{ id: "a", text: "x" }] }), [{ id: "a", text: "x" }]);
  assert.equal(resultItems({ items: [{ id: "a" }] }), null);
  assert.equal(resultItems({ items: [] }), null);
  assert.equal(resultItems(undefined), null);
  assert.equal(resultItems({ items: "x" }), null);
});
check("زبان‌ها: کلیدهای یکتا، عنوانِ فارسی، و همخوان با سرور", () => {
  assert.equal(new Set(TRANSLATE_LANGS.map((l) => l.key)).size, TRANSLATE_LANGS.length);
  assert.equal(langTitle("tr"), "ترکی استانبولی");
  assert.equal(langTitle("xx"), "xx");
  for (const k of ["fa", "en", "ar", "tr", "ru", "de", "fr", "es", "it", "zh", "hi", "ur"]) assert.ok(TRANSLATE_LANGS.some((l) => l.key === k), k);
  assert.equal(MAX_LINES, 300);
});

const bad = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? "✓" : "✗"} ${r.name}${r.err ? `\n    ${r.err}` : ""}`);
console.log(`\n${results.length - bad.length}/${results.length} passed`);
if (bad.length) process.exit(1);
