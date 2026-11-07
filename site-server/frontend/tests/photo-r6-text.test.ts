// آزمونِ نوبت ۶: فرمولِ متنِ خمیده در مرورگر باید با backend/apps/photoedit/textlayer.py (warp_params / warp_extra) یکی باشد.
import { LINE_W, STRIKE_OFFSET, UL_OFFSET, warpExtra, warpParams } from "../src/features/content/photo/pro/gl/raster";

let fails = 0;
let total = 0;
const ok = (c: unknown, msg: string) => {
  total++;
  if (!c) {
    fails++;
    console.log("FAIL:", msg);
  }
};
const near = (a: number, b: number, eps = 1e-9) => Math.abs(a - b) <= eps;

// همان عددهای آزمونِ پایتون (tests_r6_text.py › test_warp_params_formula_is_the_documented_one)
ok(near(warpParams("arc", 0.5, -1, 100).dy, 0) && near(warpParams("arc", 0.5, 0, 100).dy, -70) && near(warpParams("arc", 0.5, 1, 100).dy, 0), "arc dy");
ok(near(warpParams("bulge", 1, 0, 100).s, 1.7) && near(warpParams("bulge", 1, 1, 100).s, 1) && near(warpParams("bulge", 1, 0, 100).dy, 0), "bulge s");
ok(near(warpParams("rise", 1, -1, 100).dy, 100) && near(warpParams("rise", 1, 0, 100).dy, 0) && near(warpParams("rise", 1, 1, 100).dy, -100), "rise dy");
ok(near(warpParams("wave", 1, -0.5, 100).dy, 70) && near(warpParams("wave", 1, 0.5, 100).dy, -70) && near(warpParams("wave", 1, 0, 100).dy, 0, 1e-9), "wave dy");
ok(near(warpParams("flag", 1, -1 / 3, 100).dy, 0.6 * 100 * Math.sin(1.5 * Math.PI * (2 / 3))), "flag dy");
// امضا: s همیشه ۱ جز در bulge
for (const st of ["arc", "wave", "flag", "rise"] as const) ok(warpParams(st, 0.7, 0.3, 50).s === 1, `${st}: s=1`);
// حاشیهٔ عمودی (صحیح و یکسان با پایتون: ceil(e)+2)
ok(warpExtra("arc", 0.8, 100, 200) === Math.ceil(0.8 * 1.4 * 100) + 2, "warpExtra arc");
ok(warpExtra("arc", -0.8, 100, 200) === warpExtra("arc", 0.8, 100, 200), "extra به علامتِ مقدار بستگی ندارد (جز bulge)");
ok(warpExtra("bulge", 0.9, 100, 200) === Math.ceil((0.7 * 0.9 * 200) / 2) + 2, "warpExtra bulge مثبت");
ok(warpExtra("bulge", -0.9, 100, 200) === 2, "bulge منفی جا نمی‌خواهد");
ok(warpExtra("wave", 0, 100, 200) === 2 && warpExtra("rise", 1, 50, 80) === 52, "warpExtra wave/rise");
// ثابت‌های زیرخط و خط‌خوردگی با پایتون یکی است
ok(UL_OFFSET === 0.12 && STRIKE_OFFSET === -0.28 && LINE_W === 0.065, "ثابت‌های خط");
// جابه‌جاییِ تقارن: arc و rise با u ← −u
for (const u of [0.1, 0.4, 0.9]) {
  ok(near(warpParams("arc", 0.6, u, 80).dy, warpParams("arc", 0.6, -u, 80).dy), "arc متقارن");
  ok(near(warpParams("rise", 0.6, u, 80).dy, -warpParams("rise", 0.6, -u, 80).dy), "rise پادمتقارن");
}

console.log(fails ? `photo-r6-text: ${fails} FAIL از ${total}` : `photo-r6-text: همهٔ ${total} بررسی درست`);
if (fails) process.exit(1);
