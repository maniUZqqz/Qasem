/**
 * آزمونِ منطقِ ویرایشگرِ «سبکِ تازه» (ratio / toDoc) و اینکه گالری سبک‌های شخصی را می‌شناسد.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/motion-style-editor.test.ts --bundle --platform=node --format=cjs --jsx=automatic --outfile=/tmp/motion-style-editor.test.cjs
 *   node /tmp/motion-style-editor.test.cjs
 */
import assert from "node:assert/strict";

import type { StyleDef, StyleDoc } from "../src/features/content/motion/api";
import { ratio, toDoc } from "../src/features/content/motion/StyleEditor";
import { styleMatches } from "../src/features/content/motion/ownerNames";

const results: { name: string; ok: boolean; err?: string }[] = [];
function check(name: string, fn: () => void) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, err: e instanceof Error ? e.message : String(e) });
  }
}

const BLANK: StyleDoc = {
  name_fa: "سبکِ تازه", name_en: "My style", about: "", tags: [], group: "custom",
  palette: { bg: "#f7faff", bg2: "#dbe6ff", ink: "#1b2b45", paper: "#ffffff", accent: "#126f85", accent2: "#163f75", accent3: "#e08a1e", muted: "#5a6b85" },
  font: { latin: "vazirmatn", fa: "vazirmatn", weight: 700, body_latin: null, body_fa: null, case: "none", track: 0, lh: 1.3 },
  bg: { kind: "linear", from: "bg", to: "bg2", angle: 170 }, bg2: null, tex: [{ kind: "grain", opacity: 0.05 }], text: { fx: "plain" },
  shape: { radius: 20, border: 0, shadow: "soft", fill: "paper" }, decor: [],
  motion: { enter: "rise", spring: [24, 120, 1.0], ease: "out-expo", stagger: 7, stepFps: null, wobble: 0, cam: null },
  trans: { kind: "fade", frames: 16 }, fx: {},
};

check("WCAG ratios match the backend guard", () => {
  assert.equal(Math.round(ratio("#000000", "#ffffff") * 10) / 10, 21);
  assert.ok(Math.abs(ratio("#767676", "#ffffff") - 4.54) < 0.02);
  assert.ok(ratio("#808080", "#ffffff") < 4.5);
  assert.equal(ratio("nope", "#ffffff"), 0);
});

check("toDoc fills every missing part from the blank style", () => {
  const d = toDoc({ name_fa: "نمونه", palette: { bg: "#000000" } }, BLANK);
  assert.equal(d.name_fa, "نمونه");
  assert.equal(d.palette.bg, "#000000");
  assert.equal(d.palette.ink, BLANK.palette.ink);
  assert.deepEqual(d.motion.spring, [24, 120, 1.0]);
  assert.equal(d.motion.ease, "out-expo");
  assert.equal(d.bg2, null);
  assert.equal(d.group, "custom");
});

check("toDoc keeps a catalogue style whole and never shares references with it", () => {
  const src = { name_fa: "پیکسل", name_en: "Pixel", palette: { ...BLANK.palette, accent: "#ffcd75" }, bg: { kind: "bands", from: "bg2", to: "bg", n: 12 }, decor: [{ kind: "pixels", n: 26 }],
                tex: [{ kind: "scanlines", gap: 6 }], motion: { enter: "pop", spring: [14, 260, 0.7], stagger: 5, stepFps: 8, wobble: 0, cam: { zoom: 0.05 } }, shape: { radius: 0, border: 6 } };
  const d = toDoc(src, BLANK);
  assert.deepEqual(d.bg, src.bg);
  assert.deepEqual(d.decor, src.decor);
  assert.equal(d.motion.stepFps, 8);
  assert.deepEqual(d.motion.cam, { zoom: 0.05 });
  assert.equal(d.shape.border, 6);
  assert.equal(d.shape.shadow, "soft");                       // a catalogue style without it gets the blank's value
  d.decor.push({ kind: "dust" });
  d.palette.accent = "#000000";
  assert.equal(src.decor.length, 1);
  assert.equal(src.palette.accent, "#ffcd75");
});

check("toDoc survives junk", () => {
  for (const junk of [null, undefined, 3, "x", [], { motion: { spring: [1] } }, { tags: "no" }, { palette: null }]) {
    const d = toDoc(junk, BLANK);
    assert.equal(d.motion.spring.length, 3);
    assert.ok(Array.isArray(d.tags));
    assert.ok(d.palette.bg);
  }
});

check("a custom style is found by the gallery search like any other", () => {
  const s = { id: "u1-neon-gym", name_fa: "نئونِ باشگاه", name_en: "Neon Gym", group: "custom", group_label: "سبک‌های من", about: "تیره با نئونِ صورتی", tags: ["ورزش"], palette: {}, font: { latin: "", fa: "" }, custom: true } as StyleDef;
  assert.ok(styleMatches(s, "نئون"));
  assert.ok(styleMatches(s, "neon gym"));
  assert.ok(styleMatches(s, "ورزش"));
  assert.ok(!styleMatches(s, "ویپورویو"));
});

const bad = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? "ok  " : "FAIL"} ${r.name}${r.err ? " :: " + r.err : ""}`);
console.log(`${results.length - bad.length}/${results.length} passed`);
process.exit(bad.length ? 1 : 0);
