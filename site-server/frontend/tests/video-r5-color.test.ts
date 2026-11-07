/**
 * آزمونِ ابزارهای رنگِ خودکار: رنگِ خودکار، تطبیقِ رنگ، قطره‌چکانِ تعادلِ سفید، و منحنیِ Hue-vs. داور = خودِ `applyColor` (همان کدی که پیش‌نمایش را می‌سازد).
 *
 *   cd frontend && node_modules/.bin/esbuild tests/video-r5-color.test.ts --bundle --platform=node --format=esm --outfile=/tmp/video-r5-color.test.mjs
 *   node /tmp/video-r5-color.test.mjs
 */
import assert from "node:assert/strict";

import { applyColor } from "../src/features/content/video/manual/color";
import {
  HUE_BANDS, HUE_MODES, Px, autoColor, eyedropper, frameStats, hueCurve, matchColor, patchToParams, samplePixel, solveWb, wbGains,
} from "../src/features/content/video/manual/colorTools";

const results: { name: string; ok: boolean; err?: string }[] = [];
function check(name: string, fn: () => void) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, err: e instanceof Error ? `${e.message}\n${e.stack?.split("\n").slice(1, 3).join("\n")}` : String(e) });
  }
}

/** یک «عکسِ» ساختگی: گرادیانِ خاکستری (نمایندهٔ صحنه) × ضریبِ رنگ و روشنایی */
function scene(w: number, h: number, gain: [number, number, number], base = 0.5, spread = 0.7): Px {
  const data = new Uint8ClampedArray(w * h * 4);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = (y * w + x) * 4;
    const v = base - spread / 2 + (spread * (x / (w - 1)));          // از تیره تا روشن
    data[i] = Math.round(Math.min(1, v * gain[0]) * 255);
    data[i + 1] = Math.round(Math.min(1, v * gain[1]) * 255);
    data[i + 2] = Math.round(Math.min(1, v * gain[2]) * 255);
    data[i + 3] = 255;
  }
  return { data, width: w, height: h } as Px;
}
const toImg = (p: Px) => ({ data: new Uint8ClampedArray(p.data as Uint8ClampedArray), width: p.width, height: p.height }) as unknown as ImageData;
const meanRgb = (p: Px) => frameStats(p, 1).mean;
const dist = (a: number[], b: number[]) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

check("frame statistics: mean, percentiles, saturation of a known image", () => {
  const gray = scene(64, 8, [1, 1, 1], 0.5, 0.6);
  const s = frameStats(gray, 1);
  assert.ok(Math.abs(s.mean[0] - 0.5) < 0.02 && Math.abs(s.mean[1] - 0.5) < 0.02);
  assert.ok(s.p2 < 0.25 && s.p98 > 0.75 && Math.abs(s.p50 - 0.5) < 0.04, JSON.stringify([s.p2, s.p50, s.p98]));
  assert.ok(s.sat < 0.01);
  const red = scene(16, 16, [1, 0.2, 0.2], 0.6, 0.0);
  assert.ok(frameStats(red).sat > 0.7);
  assert.equal(frameStats({ data: new Uint8ClampedArray(16), width: 2, height: 2 } as Px).n, 0, "fully transparent = nothing to measure");
});

check("solveWb finds the temperature/tint that cancels a cast", () => {
  const cast: [number, number, number] = [1.25, 1.0, 0.8];                  // a warm cast
  const { t, n } = solveWb([1 / cast[0], 1 / cast[1], 1 / cast[2]]);
  const g = wbGains(t, n);
  const out = [cast[0] * g[0], cast[1] * g[1], cast[2] * g[2]];
  const spread = Math.max(...out) / Math.min(...out);
  assert.ok(spread < 1.07, `residual cast ${spread}`);          // the two knobs cannot cancel EVERY cast exactly (a few % are left)
  assert.ok(t < -0.5, "a warm scene needs a cooler setting");
  const none = solveWb([1, 1, 1]);
  assert.ok(Math.abs(none.t) < 0.03 && Math.abs(none.n) < 0.03);
});

check("white-balance eyedropper: the clicked grey becomes grey after applying the result", () => {
  const warm = scene(48, 8, [1.2, 1.0, 0.78], 0.5, 0.5);
  const sample = samplePixel(warm, 0.5, 0.5);
  const fix = eyedropper(sample);
  const img = toImg(warm);
  applyColor(img, { temperature: fix.temperature, tint: fix.tint }, []);
  const m = frameStats(img as unknown as Px, 1).mean;
  assert.ok(Math.max(...m) - Math.min(...m) < 0.045, `still tinted: ${m}`);
  assert.ok(fix.temperature < -20, String(fix.temperature));
});

check("eyedropper adds its correction on top of the grade the clip already has", () => {
  const warm = scene(48, 8, [1.2, 1.0, 0.78], 0.5, 0.5);
  const img = toImg(warm);
  applyColor(img, { temperature: -30 }, []);                                 // the clip is already half corrected
  const sample = samplePixel(img as unknown as Px, 0.5, 0.5);
  const fix = eyedropper(sample, { temperature: -30 });
  const again = toImg(warm);
  applyColor(again, { temperature: fix.temperature, tint: fix.tint }, []);
  const m = frameStats(again as unknown as Px, 1).mean;
  assert.ok(Math.max(...m) - Math.min(...m) < 0.05, `not neutral: ${m}`);
});

check("auto colour: a dark, flat, tinted frame gets brighter, more contrasty and neutral", () => {
  const dull = scene(64, 8, [1.1, 1.0, 0.82], 0.28, 0.36);
  const before = frameStats(dull, 1);
  const patch = autoColor(before);
  assert.ok(patch.exposure > 0.3, `exposure ${patch.exposure}`);
  assert.ok(patch.contrast > 5, `contrast ${patch.contrast}`);
  assert.ok(patch.temperature < 0, `temp ${patch.temperature}`);
  const img = toImg(dull);
  applyColor(img, patchToParams(undefined, patch), []);
  const after = frameStats(img as unknown as Px, 1);
  assert.ok(Math.abs(after.p50 - 0.46) < Math.abs(before.p50 - 0.46) * 0.6, `median ${before.p50} -> ${after.p50}`);
  assert.ok(after.p98 - after.p2 > before.p98 - before.p2 + 0.1, "wider tonal range");
  assert.ok(Math.max(...after.mean) - Math.min(...after.mean) < Math.max(...before.mean) - Math.min(...before.mean), "less cast");
});

check("auto colour leaves a good frame alone and does not fight a deliberate warm look", () => {
  const good = scene(64, 8, [1, 1, 1], 0.46, 0.86);
  const p = autoColor(frameStats(good, 1));
  assert.ok(Math.abs(p.exposure) <= 0.1 && p.contrast <= 3 && p.temperature === 0 && p.tint === 0 && p.saturation === 100, JSON.stringify(p));
  const warmish = autoColor(frameStats(scene(64, 8, [1.04, 1.0, 0.97], 0.46, 0.86), 1));
  assert.ok(Math.abs(warmish.temperature) < 12, `slight warmth is kept: ${warmish.temperature}`);
});

check("colour match: the dull clip moves clearly towards the reference clip", () => {
  const target = scene(64, 8, [0.85, 1.0, 1.2], 0.3, 0.4);                  // dark and blue
  const ref = scene(64, 8, [1.15, 1.0, 0.85], 0.55, 0.8);                   // bright and warm
  const sTarget = frameStats(target, 1);
  const sRef = frameStats(ref, 1);
  const patch = matchColor(sTarget, sRef, 1);
  const img = toImg(target);
  applyColor(img, patchToParams(undefined, patch), []);
  const after = frameStats(img as unknown as Px, 1);
  const before = dist(sTarget.mean, sRef.mean);
  const now = dist(after.mean, sRef.mean);
  assert.ok(now < before * 0.45, `distance ${before.toFixed(3)} -> ${now.toFixed(3)}`);
  assert.ok(Math.abs(after.p50 - sRef.p50) < Math.abs(sTarget.p50 - sRef.p50) * 0.5);
  assert.ok(patch.exposure > 0.3 && patch.temperature > 0, JSON.stringify(patch));
});

check("colour match: strength 0 changes nothing, 0.5 is in between, identical clips give a neutral patch", () => {
  const a = frameStats(scene(64, 8, [0.9, 1, 1.1], 0.35, 0.5), 1);
  const b = frameStats(scene(64, 8, [1.1, 1, 0.9], 0.55, 0.8), 1);
  const none = matchColor(a, b, 0);
  assert.deepEqual([none.exposure, none.contrast, none.temperature, none.tint], [0, 0, 0, 0]);
  assert.equal(none.saturation, 100);
  const half = matchColor(a, b, 0.5);
  const full = matchColor(a, b, 1);
  assert.ok(Math.abs(half.exposure) < Math.abs(full.exposure) && Math.abs(half.temperature) < Math.abs(full.temperature));
  const same = matchColor(a, a, 1);
  assert.ok(Math.abs(same.exposure) < 0.06 && Math.abs(same.temperature) <= 3 && Math.abs(same.contrast) <= 2 && Math.abs(same.saturation - 100) <= 2, JSON.stringify(same));
});

check("patchToParams keeps other settings and drops neutral values", () => {
  const cur = { highlights: -20, curves: { m: [[0, 0], [1, 1]] as [number, number][] } };
  const out = patchToParams(cur, { exposure: 0.4, contrast: 0, temperature: 12, tint: 0, saturation: 100 });
  assert.equal(out.highlights, -20);
  assert.equal(out.exposure, 0.4);
  assert.equal(out.temperature, 12);
  assert.ok(!("contrast" in out) && !("tint" in out) && !("saturation" in out));
});

check("hue-vs curve: passes through its six control values and wraps around the colour wheel", () => {
  const v = [40, -20, 0, 60, -60, 10];
  HUE_BANDS.forEach((b, i) => assert.ok(Math.abs(hueCurve(v, b.hue) - v[i]) < 1e-9, `${b.key}`));
  assert.ok(Math.abs(hueCurve(v, 360) - hueCurve(v, 0)) < 1e-9);
  assert.ok(Math.abs(hueCurve(v, -60) - v[5]) < 1e-9);
  const mid = hueCurve([0, 100, 0, 0, 0, 0], 30);
  assert.ok(mid > 20 && mid < 100, `smooth between points: ${mid}`);
  assert.deepEqual(HUE_MODES.map((m) => m.field), ["s", "h", "l"]);
});

check("hue-vs-sat values written to the HSL bands really desaturate that colour in the real pipeline", () => {
  const w = 12, h = 1;
  const px: Px = { data: new Uint8ClampedArray(w * h * 4), width: w, height: h };
  // left half pure red, right half pure green
  for (let x = 0; x < w; x++) {
    const i = x * 4;
    const red = x < w / 2;
    px.data[i] = red ? 230 : 40; px.data[i + 1] = red ? 40 : 230; px.data[i + 2] = 40; px.data[i + 3] = 255;
  }
  const img = toImg(px);
  applyColor(img, { hsl: { red: { h: 0, s: -100, l: 0 } } }, []);
  const redAfter = [img.data[0], img.data[1], img.data[2]];
  const greenAfter = [img.data[(w - 1) * 4], img.data[(w - 1) * 4 + 1], img.data[(w - 1) * 4 + 2]];
  assert.ok(Math.max(...redAfter) - Math.min(...redAfter) < 60, `red became greyish: ${redAfter}`);
  assert.ok(greenAfter[1] > 200 && greenAfter[0] < 60, `green untouched: ${greenAfter}`);
});

const failed = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? "ok  " : "FAIL"} ${r.name}${r.err ? `\n     ${r.err.replace(/\n/g, "\n     ")}` : ""}`);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
if (failed.length) process.exit(1);
