// آزمونِ نوبت ۵: ریاضیِ سطلِ رنگ + PaintStore (نسخه‌ها/برگشت/بودجهٔ حافظه) با یک <canvas> ِ ساختگی. رسمِ قلم‌مو را آزمونِ مرورگر (Playwright) می‌سنجد.
import { PaintStore, floodMask, growMask, hexRgb, normColor, rgbHex, sampleHex } from "../src/features/content/photo/pro/paint";

let fails = 0;
let total = 0;
const ok = (c: unknown, msg: string) => {
  total++;
  if (!c) {
    fails++;
    console.log("FAIL:", msg);
  }
};

// ── canvas ِ ساختگی (فقط آنچه PaintStore لازم دارد)
class FakeCtx {
  fillStyle = "#000000";
  constructor(private c: FakeCanvas) {}
  clearRect(x: number, y: number, w: number, h: number) {
    for (let j = y; j < y + h; j++) for (let i = x; i < x + w; i++) if (i >= 0 && j >= 0 && i < this.c.width && j < this.c.height) this.c.buf.fill(0, (j * this.c.width + i) * 4, (j * this.c.width + i) * 4 + 4);
  }
  fillRect(x: number, y: number, w: number, h: number) {
    const [r, g, b] = [1, 3, 5].map((k) => parseInt(this.fillStyle.slice(k, k + 2), 16));
    for (let j = y; j < y + h; j++) for (let i = x; i < x + w; i++) if (i >= 0 && j >= 0 && i < this.c.width && j < this.c.height) this.c.buf.set([r, g, b, 255], (j * this.c.width + i) * 4);
  }
  getImageData(x: number, y: number, w: number, h: number) {
    const out = new Uint8ClampedArray(w * h * 4);
    for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) out.set(this.c.buf.subarray(((y + j) * this.c.width + x + i) * 4, ((y + j) * this.c.width + x + i) * 4 + 4), (j * w + i) * 4);
    return { data: out, width: w, height: h };
  }
  putImageData(img: { data: Uint8ClampedArray; width: number; height: number }, x: number, y: number) {
    for (let j = 0; j < img.height; j++) for (let i = 0; i < img.width; i++) this.c.buf.set(img.data.subarray((j * img.width + i) * 4, (j * img.width + i) * 4 + 4), ((y + j) * this.c.width + x + i) * 4);
  }
  drawImage(src: FakeCanvas, dx = 0, dy = 0) {
    for (let j = 0; j < src.height; j++) for (let i = 0; i < src.width; i++) {
      const p = (j * src.width + i) * 4;
      if (src.buf[p + 3]) this.c.buf.set(src.buf.subarray(p, p + 4), ((dy + j) * this.c.width + dx + i) * 4);
    }
  }
}
class FakeCanvas {
  buf: Uint8ClampedArray;
  constructor(public width = 1, public height = 1) {
    this.buf = new Uint8ClampedArray(width * height * 4);
  }
  getContext() {
    if (this.buf.length !== this.width * this.height * 4) this.buf = new Uint8ClampedArray(this.width * this.height * 4);
    return new FakeCtx(this);
  }
}
const g = globalThis as unknown as Record<string, unknown>;
g.document = {
  createElement: () => {
    const c = new FakeCanvas();
    return new Proxy(c, {
      set(t, k, v) {
        (t as unknown as Record<string, unknown>)[k as string] = v;
        if (k === "width" || k === "height") t.buf = new Uint8ClampedArray(t.width * t.height * 4);
        return true;
      },
    });
  },
};
g.ImageData = class {
  constructor(public data: Uint8ClampedArray, public width: number, public height: number) {}
};

// ── رنگ
ok(hexRgb("#ff8000").join() === "255,128,0", "hexRgb");
ok(rgbHex(255, 128, 0) === "#ff8000" && rgbHex(-5, 300, 12.4) === "#00ff0c", "rgbHex و برش");
ok(normColor("#ABCDEF") === "#abcdef" && normColor("red") === "#e11d48" && normColor("x", "#111111") === "#111111", "normColor");

// ── flood fill: تصویرِ ۱۰×۶ با دیوارِ عمودیِ سیاه در ستون ۵ که دو سمتِ سفید را جدا می‌کند
const W = 10;
const H = 6;
const img = new Uint8ClampedArray(W * H * 4).fill(255);
for (let y = 0; y < H; y++) img.set([0, 0, 0, 255], (y * W + 5) * 4);
const ref = { data: img, width: W, height: H };
const left = floodMask(ref, 1, 1, 10, true);
ok(left.count === 5 * H, `پیوسته: فقط سمتِ چپ (${left.count})`);
ok(left.mask[0 * W + 5] === 0 && left.mask[0 * W + 6] === 0, "دیوار و سمتِ راست پر نشد");
const both = floodMask(ref, 1, 1, 10, false);
ok(both.count === 9 * H, `ناپیوسته: هر دو سمت (${both.count})`);
const wall = floodMask(ref, 5, 2, 0, true);
ok(wall.count === H, `کلیک روی دیوار ⇒ فقط دیوار (${wall.count})`);
const all = floodMask(ref, 1, 1, 100, true);
ok(all.count === W * H, "شباهتِ ۱۰۰٪ ⇒ همه");
const edge = floodMask(ref, 999, -5, 10, true);
ok(edge.count > 0, "مختصاتِ بیرون از تصویر به لبه گیر می‌کند");
// نیمه‌شفاف: آلفا هم مقایسه می‌شود
const al = new Uint8ClampedArray(4 * 4 * 4);
for (let i = 0; i < 16; i++) al.set(i < 8 ? [10, 10, 10, 0] : [10, 10, 10, 255], i * 4);
ok(floodMask({ data: al, width: 4, height: 4 }, 0, 0, 5, true).count === 8, "ناحیهٔ شفاف از نیمهٔ پر جدا می‌شود");

// ── growMask
const m = new Uint8Array(5 * 5);
m[12] = 1;
const g1 = growMask(m, 5, 5, 1);
ok([...g1].reduce((a, b) => a + b, 0) === 5, "رشد ۱ پیکسل = علامتِ بعلاوه");
const g2 = growMask(m, 5, 5, 2);
ok([...g2].reduce((a, b) => a + b, 0) === 13, "رشد ۲ پیکسل = الماس (۱۳)");
ok(growMask(m, 5, 5, 0) === m, "رشدِ صفر همان آرایه");

// ── sampleHex
const px = new Uint8ClampedArray(3 * 3 * 4);
for (let i = 0; i < 9; i++) px.set([100, 150, 200, 255], i * 4);
ok(sampleHex(px, 3, 3, 0.5, 0.5, 1) === "#6496c8", "sampleHex میانگین");
ok(sampleHex(px, 3, 3, 5, 5, 1) === "#6496c8", "sampleHex بیرون از بازه به لبه");

// ── PaintStore
const s = new PaintStore();
s.setSize(8, 6);
const c = s.create("a");
ok(c.width === 8 && c.height === 6, "اندازهٔ بوم از setSize");
ok(s.has("a") && s.isEmpty("a") && s.dirty.has("a") && s.revs.get("a") === 0, "ساخت: شفاف، کثیف، rev=0");
const ctx = c.getContext("2d") as unknown as FakeCtx;
ctx.fillStyle = "#ff0000";
ctx.fillRect(0, 0, 4, 6);
s.touch("a");
ok(!s.isEmpty("a"), "پس از نقاشی خالی نیست");
s.snapshot("a", 1);
ctx.fillStyle = "#00ff00";
ctx.fillRect(4, 0, 4, 6);
s.snapshot("a", 2);
ok(s.revs.get("a") === 2, "snapshot نسخه را می‌گذارد");
ok(s.restore("a", 1), "restore ۱");
let d = ctx.getImageData(0, 0, 8, 6).data;
ok(d[0] === 255 && d[3] === 255 && d[(4) * 4 + 3] === 0, "نیمهٔ سبز برگشت");
ok(s.restore("a", 0), "restore ۰ (شفافِ کامل)");
ok(s.isEmpty("a"), "نسخهٔ صفر شفاف است");
ok(s.restore("a", 2), "جلو رفتن به ۲");
d = ctx.getImageData(0, 0, 8, 6).data;
ok(d[(5) * 4 + 1] === 255, "نیمهٔ سبز دوباره آمد");
ok(!s.restore("a", 99) && !s.restore("zzz", 0), "نسخهٔ ناموجود ⇒ false");
// نسخه‌ها فقط ۱۴ تا می‌مانند
for (let r = 3; r <= 25; r++) s.snapshot("a", r);
ok(!s.restore("a", 3) && s.restore("a", 25), "نسخه‌های قدیمی دور ریخته می‌شود");
// copy و remove
ok(s.copy("a", "b") && s.has("b") && s.dirty.has("b"), "copy");
const cd = (s.get("b")!.canvas.getContext("2d") as unknown as FakeCtx).getImageData(0, 0, 8, 6).data;
ok(cd[3] === 255, "کپی پیکسل‌ها را دارد");
s.remove("b");
ok(!s.has("b") && !s.dirty.has("b") && !s.restore("b", 0), "remove");
ok(!s.copy("nope", "x"), "copyِ ناموجود");

console.log(fails ? `photo-r5-paint: ${fails} FAIL از ${total}` : `photo-r5-paint: همهٔ ${total} بررسی درست`);
if (fails) process.exit(1);
