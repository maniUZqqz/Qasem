// آزمونِ نوبت ۷: ویرایشِ مسیرِ قلم (افزودن/برداشتنِ نقطه، برعکس، نقطه‌گذاریِ میانی) و کانال‌ها.
import { CHANNELS, channelGray } from "../src/features/content/photo/pro/channels";
import { PenPath, flattenPx } from "../src/features/content/photo/pro/pen";

let fails = 0;
let total = 0;
const ok = (c: unknown, msg: string) => {
  total++;
  if (!c) {
    fails++;
    console.log("FAIL:", msg);
  }
};
const near = (a: number, b: number, eps = 1e-6) => Math.abs(a - b) <= eps;
const sc = (x: number, y: number): [number, number] => [x * 1000, y * 800];

// ── مسیرِ مستقیم: وسطِ پاره
const line = new PenPath();
line.add(0.1, 0.1);
line.add(0.5, 0.1);
line.add(0.5, 0.5);
ok(line.sel === 2, "sel = آخرین نقطه");
ok(line.segCount === 2, "مسیرِ باز با ۳ نقطه ۲ پاره دارد");
const hit = line.nearestSegment(sc, 300, 80)!; // نزدیکِ وسطِ پارهٔ اول (x=0.3, y=0.1 ⇒ 300,80)
ok(hit.seg === 0 && near(hit.t, 0.5, 0.02) && hit.d < 1, `نزدیک‌ترین پاره (${hit.seg}, ${hit.t.toFixed(3)}, ${hit.d.toFixed(2)})`);
const far = line.nearestSegment(sc, 900, 700)!;
ok(far.d > 100, "نقطهٔ دور فاصلهٔ زیادی دارد");
const i1 = line.insertAt(hit.seg, hit.t);
ok(i1 === 1 && line.pts.length === 4 && line.sel === 1, "نقطه روی پارهٔ اول نشست");
ok(near(line.pts[1].x, 0.3, 0.01) && near(line.pts[1].y, 0.1) && line.pts[1].hi === null && line.pts[1].ho === null, "نقطهٔ تازه روی خطِ راست و بی‌دستگیره");

// ── مسیرِ منحنی: درج شکل را عوض نمی‌کند
const c = new PenPath();
c.add(0.1, 0.5);
c.add(0.9, 0.5);
c.pts[0].ho = [0.1, -0.3];
c.pts[1].hi = [-0.1, -0.3];
const before = flattenPx(c.toShapePath(), 1000, 800);
const mid0 = c.segPoint(0, 0.5);
c.insertAt(0, 0.5);
ok(c.pts.length === 3 && near(c.pts[1].x, mid0[0], 1e-5) && near(c.pts[1].y, mid0[1], 1e-5), "نقطهٔ میانیِ منحنی روی خم است");
ok(c.pts[1].hi !== null && c.pts[1].ho !== null, "دستگیره‌های نقطهٔ تازه ساخته شد");
const after = flattenPx(c.toShapePath(), 1000, 800);
// فاصلهٔ هر نقطهٔ پیش از درج تا خمِ بعد از درج ناچیز است
let worst = 0;
for (const p of before) {
  let best = Infinity;
  for (let k = 1; k < after.length; k++) {
    const ax = after[k - 1][0], ay = after[k - 1][1], bx = after[k][0], by = after[k][1];
    const vx = bx - ax, vy = by - ay;
    const l2 = vx * vx + vy * vy || 1;
    const f = Math.max(0, Math.min(1, ((p[0] - ax) * vx + (p[1] - ay) * vy) / l2));
    best = Math.min(best, Math.hypot(ax + vx * f - p[0], ay + vy * f - p[1]));
  }
  worst = Math.max(worst, best);
}
ok(worst < 1.2, `شکلِ منحنی بعد از درج عوض نشد (بیشترین انحراف ${worst.toFixed(3)}px)`);
ok(c.insertAt(5, 0.5) === -1, "پارهٔ ناموجود ⇒ -1");

// ── مسیرِ بسته: پارهٔ آخر ⇒ اول
const sq = new PenPath();
for (const [x, y] of [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]) sq.add(x, y);
sq.close();
ok(sq.closed && sq.segCount === 4, "مسیرِ بسته ۴ پاره دارد");
const k = sq.insertAt(3, 0.5);
ok(k === 4 && near(sq.pts[4].x, 0.2) && near(sq.pts[4].y, 0.5), "درج روی پارهٔ بسته‌کننده");
const added = sq.subdivide();
ok(added === 5 && sq.pts.length === 10, `subdivide ⇒ وسطِ هر پاره (${added})`);
const area = (p: PenPath) => {
  const f = flattenPx(p.toShapePath(), 1000, 800);
  let a = 0;
  for (let i = 0; i < f.length; i++) {
    const [x1, y1] = f[i], [x2, y2] = f[(i + 1) % f.length];
    a += x1 * y2 - x2 * y1;
  }
  return Math.abs(a) / 2;
};
ok(near(area(sq), 600 * 480, 1), "مساحتِ مربع بعد از نقطه‌گذاری همان است");

// ── برداشتن
const d = new PenPath();
for (const [x, y] of [[0.1, 0.1], [0.4, 0.2], [0.7, 0.1], [0.9, 0.5]]) d.add(x, y);
d.sel = 1;
ok(d.removeSelected() && d.pts.length === 3 && d.pts[1].x === 0.7, "نقطهٔ انتخاب‌شده برداشته شد");
ok(d.sel === 1, "sel روی همسایه ماند");
d.sel = d.pts.length - 1;
d.removeSelected();
ok(d.pts.length === 2, "نقطهٔ آخر ⇒ همان removeLast");
ok(d.removeAt(9) === false, "شاخصِ نامعتبر ⇒ false");
const cl = new PenPath();
for (const [x, y] of [[0.1, 0.1], [0.5, 0.1], [0.5, 0.5]]) cl.add(x, y);
cl.close();
cl.removeAt(0);
ok(!cl.closed && cl.pts.length === 2, "مسیرِ بسته با کمتر از ۳ نقطه باز می‌شود");

// ── برعکس
const rv = new PenPath();
rv.add(0.1, 0.1);
rv.add(0.5, 0.5);
rv.pts[0].ho = [0.1, 0];
rv.pts[1].hi = [-0.1, 0];
rv.reverse();
ok(rv.pts[0].x === 0.5 && rv.pts[0].ho !== null && rv.pts[0].hi === null && rv.pts[1].hi !== null, "reverse: نقطه‌ها و دستگیره‌ها جابه‌جا شد");
const m1 = rv.segPoint(0, 0.5);
const orig = new PenPath();
orig.add(0.1, 0.1);
orig.add(0.5, 0.5);
orig.pts[0].ho = [0.1, 0];
orig.pts[1].hi = [-0.1, 0];
const m2 = orig.segPoint(0, 0.5);
ok(near(m1[0], m2[0], 1e-9) && near(m1[1], m2[1], 1e-9), "reverse شکل را عوض نمی‌کند");

// ── بارگذاری مسیرِ ذخیره‌شده (کپیِ مستقل)
const saved = sq.toShapePath();
const L = new PenPath();
L.load(saved);
ok(L.pts.length === sq.pts.length && L.closed && L.finished, "load مسیرِ بسته");
L.pts[0].x = 0.99;
ok(sq.pts[0].x !== 0.99 && saved.pts[0].x !== 0.99, "load کپیِ مستقل می‌سازد");
L.clear();
ok(L.sel === null && !L.active, "clear");

// ── کانال‌ها
const px = new Uint8ClampedArray([200, 100, 50, 255, 0, 0, 0, 0]);
ok(channelGray(px, "r")[0] === 200 && channelGray(px, "g")[0] === 100 && channelGray(px, "b")[0] === 50, "کانال‌های R/G/B");
ok(channelGray(px, "a")[0] === 255 && channelGray(px, "a")[1] === 0, "کانالِ شفافیت");
ok(channelGray(px, "l")[0] === Math.round(0.2126 * 200 + 0.7152 * 100 + 0.0722 * 50), "روشنایی");
ok(channelGray(px, "r", true)[0] === 55, "معکوس");
ok(CHANNELS.length === 5 && new Set(CHANNELS.map((x) => x.id)).size === 5, "پنج کانال");

console.log(fails ? `photo-r7-pen: ${fails} FAIL از ${total}` : `photo-r7-pen: همهٔ ${total} بررسی درست`);
if (fails) process.exit(1);
