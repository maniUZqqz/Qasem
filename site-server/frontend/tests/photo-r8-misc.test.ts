// آزمونِ دورِ ۸: شیبِ چندتوقفی (gradients.ts) و متنِ عمودی (هم‌ارزِ backend textlayer.vertical_lines).
import { DEFAULT_STOPS, MAX_STOPS, addStop, colorAt, cssGradient, normStops, removeStop } from "../src/features/content/photo/pro/gradients";
import { verticalLines } from "../src/features/content/photo/pro/gl/raster";
import { SHAPES, SHAPE_MAX_POINTS, buildShape, fitUnitBox, regularPolygon, starPoly } from "../src/features/content/photo/pro/shapesLib";
import { BUILTIN_STYLES, allowedKeys, captureStyle, styleToPatch } from "../src/features/content/photo/pro/styleLib";
import type { Layer } from "../src/features/content/photo/pro/types";
import { readFileSync } from "node:fs";

let fails = 0;
let total = 0;
const ok = (c: unknown, msg: string) => {
  total++;
  if (!c) {
    fails++;
    console.log("FAIL:", msg);
  }
};
const eq = (a: unknown, b: unknown, msg: string) => ok(JSON.stringify(a) === JSON.stringify(b), `${msg} (${JSON.stringify(a)} ≠ ${JSON.stringify(b)})`);

// ── normStops
eq(normStops(null), DEFAULT_STOPS, "نامعتبر ⇒ پیش‌فرض");
eq(normStops([[0, "#ff0000"]]), DEFAULT_STOPS, "یک توقف کافی نیست");
eq(normStops([[1, "#0000FF"], [0, "#FF0000"]]), [[0, "#ff0000"], [1, "#0000ff"]], "مرتب و حروفِ کوچک");
eq(normStops([[-1, "#111111"], [5, "#222222"]]), [[0, "#111111"], [1, "#222222"]], "جایگاه به ۰..۱ می‌رود");
eq(normStops([[0, "red"], [0.5, "#123"], [1, "#00ff00"]]), DEFAULT_STOPS, "رنگِ نامعتبر کنار می‌رود و کمتر از ۲ ⇒ پیش‌فرض");
ok(normStops(Array.from({ length: 30 }, (_, i) => [i / 30, "#000000"])).length === MAX_STOPS, "سقفِ ۱۲ توقف");
eq(normStops([[0.12345, "#abcdef"], [0.9, "#000000"]])[0][0], 0.123, "گردکردن به سه رقم");

// ── colorAt / cssGradient / add / remove
const s2 = normStops([[0, "#000000"], [1, "#ffffff"]]);
eq(colorAt(s2, 0), "#000000", "سرِ شیب");
eq(colorAt(s2, 1), "#ffffff", "ته شیب");
eq(colorAt(s2, 0.5), "#808080", "وسط (خاکستری)");
eq(colorAt(s2, -3), "#000000", "بیرون از بازه");
const s3 = normStops([[0, "#ff0000"], [0.5, "#00ff00"], [1, "#0000ff"]]);
eq(colorAt(s3, 0.25), "#808000", "میانِ قرمز و سبز");
eq(colorAt(s3, 0.5), "#00ff00", "روی توقف");
ok(cssGradient(s3).startsWith("linear-gradient(90deg, #ff0000 0.0%"), "css");
const a = addStop(s3, 0.25);
eq(a.length, 4, "توقفِ تازه");
eq(a[1], [0.25, "#808000"], "رنگِ توقفِ تازه درون‌یابی است");
eq(addStop(Array.from({ length: MAX_STOPS }, (_, i) => [i / 20, "#000000"] as [number, string]), 0.99).length, MAX_STOPS, "بالای سقف افزوده نمی‌شود");
eq(removeStop(a, 1).length, 3, "حذف");
eq(removeStop(s2, 0), s2, "دو توقفِ آخر حذف نمی‌شود");

// ── متنِ عمودی ≡ backend (tests_r8_text.py)
eq(verticalLines("ABCD"), ["A", "B", "C", "D"], "عمودی: ABCD");
eq(verticalLines("A B"), ["A", "", "B"], "فاصله ⇒ خطِ خالی");
eq(verticalLines("A\nB"), ["A", "", "", "B"], "خطِ تازه ⇒ دو خطِ خالی");
eq(verticalLines("سَلام"), ["سَ", "ل", "ا", "م"], "نشانه‌ها به حرفِ خودشان می‌چسبند");
ok(verticalLines("x".repeat(500)).length === 40, "سقفِ ۴۰ خط");

// ── شکل‌های آماده
for (const s of SHAPES) {
  const b = buildShape(s.id, { sides: 7, inner: 0.4 });
  ok(!!b, `شکل ${s.id} ساخته می‌شود`);
  if (!b) continue;
  const xs = b.path.pts.map((p) => p.x);
  const ys = b.path.pts.map((p) => p.y);
  ok(b.path.closed && b.path.pts.length >= 3 && b.path.pts.length <= SHAPE_MAX_POINTS, `${s.id}: بسته و تعدادِ نقطه در حد (${b.path.pts.length})`);
  ok(Math.min(...xs) === 0 && Math.max(...xs) === 1 && Math.min(...ys) === 0 && Math.max(...ys) === 1, `${s.id}: جعبه دقیقاً [۰..۱]²`);
  ok(b.path.pts.every((p) => p.hi === null && p.ho === null), `${s.id}: بی دستگیره`);
  ok(b.aspect >= 0.15 && b.aspect <= 4, `${s.id}: نسبتِ جعبه ${b.aspect.toFixed(2)}`);
}
eq(buildShape("polygon", { sides: 8 })?.path.pts.length, 8, "چندضلعی ۸ ضلعی");
eq(buildShape("star", { sides: 7 })?.path.pts.length, 14, "ستارهٔ ۷ پر ⇒ ۱۴ نقطه");
eq(buildShape("nope"), null, "شکلِ ناشناخته");
eq(regularPolygon(2).length, 3, "چندضلعی دست‌کم ۳");
ok(starPoly(5, 0.2).length === 10 && starPoly(500).length <= SHAPE_MAX_POINTS, "ستاره سقف دارد");
const fb = fitUnitBox([[2, 4], [6, 4], [6, 12]]);
eq(fb, [[0, 0], [1, 0], [1, 1]], "fitUnitBox");

// ── سبک‌ها
const txt = { id: "t1", type: "text", name: "ت", visible: true, locked: false, opacity: 0.8, blend: "normal", mask: null, text: "سلام", font: "vazirmatn", weight: 700, size: 0.05, color: "#fff", align: "center", dir: "auto", line_height: 1.3, letter_spacing: 0, width: 0, cx: 0.5, cy: 0.5, rot: 0, stroke: null, shadow: null, box: null, tile: null } as unknown as Layer;
const shp = { id: "s1", type: "shape", name: "ش", visible: true, locked: false, opacity: 1, blend: "normal", mask: null, shape: "rect", cx: 0.5, cy: 0.5, w: 0.3, h: 0.2, rot: 0, fill: { type: "solid", color: "#fff", opacity: 1 }, stroke: null, radius: 0 } as unknown as Layer;
const base = { id: "base", type: "base", name: "عکس", visible: true, locked: false, opacity: 1, blend: "normal", mask: null } as unknown as Layer;
const cs = captureStyle(txt);
ok(cs?.target === "text" && cs.props.font === "vazirmatn" && cs.props.opacity === 0.8 && !("text" in (cs?.props ?? {})) && !("cx" in (cs?.props ?? {})), "captureStyle متن: ویژگی‌های سبک نه محتوا و جایگاه");
ok(captureStyle(base) === null && captureStyle(null) === null, "از لایهٔ عکس سبک گرفته نمی‌شود");
ok(!!captureStyle(shp)?.props.fill, "captureStyle شکل");
const toShape = styleToPatch(shp, { target: "text", props: { color: "#000", weight: 800, opacity: 0.5, fx: { shadow: null, glow: null, stroke: null } } });
ok(!!toShape && "opacity" in toShape && "fx" in toShape && !("color" in toShape) && !("weight" in toShape), "سبکِ متن روی شکل فقط کلیدهای مشترک را می‌گذارد");
ok(styleToPatch(base, { target: "any", props: { opacity: 0.5 } }) === null, "به لایهٔ عکس نمی‌خورد");
const toText = styleToPatch(txt, { target: "text", props: { color: "#000" } });
ok(!!toText && "lines" in toText, "سبکِ متن خط‌های شکسته را بی‌اعتبار می‌کند");
for (const b of BUILTIN_STYLES) {
  const keys = Object.keys(b.style.props);
  const okKeys = new Set([...allowedKeys("text"), ...allowedKeys("shape"), ...allowedKeys("image")]);
  ok(keys.length > 0 && keys.every((k) => okKeys.has(k)), `سبکِ آمادهٔ «${b.title}» فقط کلیدِ مجاز دارد`);
}
ok(new Set(BUILTIN_STYLES.map((b) => b.id)).size === BUILTIN_STYLES.length, "شناسهٔ سبک‌های آماده یکتاست");
ok(!/photoshop|adobe|فتوشاپ|lightroom|camera raw/i.test(JSON.stringify(BUILTIN_STYLES)), "واژهٔ ممنوع در سبک‌ها نیست");

// ── سیم‌کشیِ دستورهای «extra»: هر h.extra.X در registry باید در ProWorkspace باشد (آزمونِ spy فقط وجودِ تماس را می‌بیند)
const reg = readFileSync("src/features/content/photo/pro/menu/registry.ts", "utf-8");
const ws = readFileSync("src/features/content/photo/pro/ProWorkspace.tsx", "utf-8");
const used = new Set([...reg.matchAll(/h\.extra\.(\w+)\(/g)].map((m) => m[1]));
const at = ws.indexOf("extra: {");
const block = at >= 0 ? ws.slice(at, ws.indexOf("};", at)) : "";
ok(used.size >= 10, `دستورهای extra پیدا شد (${used.size})`);
for (const n of used) ok(new RegExp(String.raw`\b${n}\s*:`).test(block), `extra.${n} در ProWorkspace سیم‌کشی شده`);

console.log(fails ? `photo-r8-misc: ${fails} FAIL از ${total}` : `photo-r8-misc: همهٔ ${total} بررسی درست`);
if (fails) process.exit(1);
