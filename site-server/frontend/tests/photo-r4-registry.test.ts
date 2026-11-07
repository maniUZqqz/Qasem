// آزمونِ فهرستِ یگانهٔ دستورها (نوبت ۴): هیچ دستورِ مرده‌ای نباشد، نام‌ها یکتا و بدونِ نامِ برندِ دیگران، جستجو درست.
import { MENUS, buildCommands, norm, pageCommands, searchCommands, TOOL_META } from "../src/features/content/photo/pro/menu/registry";
import { EFFECT_ROWS, effectCommands } from "../src/features/content/photo/pro/menu/effects";
import type { Host, HostState } from "../src/features/content/photo/pro/menu/registry";

let fails = 0;
let total = 0;
const ok = (c: unknown, msg: string) => {
  total++;
  if (!c) {
    fails++;
    console.log("FAIL:", msg);
  }
};

const TOOLS = Object.keys(TOOL_META).map((id, i) => ({ id, key: String.fromCharCode(65 + (i % 26)), title: `ابزار ${id}`, hint: `راهنمای ${id}` }));
const ALL_ON: HostState = { hasActive: true, activeType: "group", activeIsBase: false, activeLocked: false, activeHasMask: true, hasSelection: true, canUndo: true, canRedo: true, layerCount: 3, activeIsPaint: true, storeFrameOn: false, nodeOn: true };
const NONE: HostState = { ...ALL_ON, hasActive: false, activeType: null, activeIsPaint: false, activeHasMask: false, hasSelection: false, canUndo: false, canRedo: false, nodeOn: false };

/** Host ِ جعلی: هر تابع صدا زده شود شمرده می‌شود */
function spyHost(s: HostState) {
  const calls: string[] = [];
  const extra = new Proxy({}, { get: (_t, k) => () => calls.push(`extra.${String(k)}`) });
  const h = new Proxy({ s, extra } as unknown as Record<string, unknown>, {
    get: (t, k) => (k in t ? t[k as string] : (..._a: unknown[]) => calls.push(String(k))),
  });
  return { h: h as unknown as Host, calls };
}

const cmds = buildCommands(TOOLS, [...effectCommands(), ...pageCommands()]);
ok(EFFECT_ROWS.length >= 40, `دست‌کم ۴۰ فیلتر در فهرست (${EFFECT_ROWS.length})`);
ok(searchCommands(cmds, "blur")[0]?.cmd.id.startsWith("fx."), "جستجوی blur ⇒ یک فیلتر");
ok(searchCommands(cmds, "بوکه").some((x) => x.cmd.id === "fx.lens_blur"), "بوکه ⇒ محوِ لنز");
ok(searchCommands(cmds, "ریسایز").some((x) => x.cmd.id === "fx.image_size"), "ریسایز ⇒ اندازهٔ تصویر");
ok(searchCommands(cmds, "pixelate")[0]?.cmd.id === "fx.mosaic", "pixelate ⇒ موزاییک");
ok(searchCommands(cmds, "سطل رنگ")[0]?.cmd.id === "tool.bucket", "سطل رنگ ⇒ ابزارِ سطل");
ok(searchCommands(cmds, "paint bucket")[0]?.cmd.id === "tool.bucket", "paint bucket");
ok(searchCommands(cmds, "eraser")[0]?.cmd.id === "tool.eraser", "eraser ⇒ پاک‌کن");
ok(searchCommands(cmds, "اسنپ شات")[0]?.cmd.id === "edit.snapshot", "اسنپ‌شات ⇒ عکسِ لحظه‌ای");
ok(searchCommands(cmds, "لایه خالی").some((x) => x.cmd.id === "layer.newPaint"), "لایه خالی ⇒ لایهٔ نقاشی");
ok(searchCommands(cmds, "قطره چکان").some((x) => x.cmd.id === "tool.picker"), "قطره‌چکان ⇒ ابزارِ رنگ");
ok(searchCommands(cmds, "color picker")[0]?.cmd.id === "tool.picker", "color picker");
ok(cmds.length > 80, `دست‌کم ۸۰ دستور (الان ${cmds.length})`);
const ids = new Set<string>();
for (const c of cmds) {
  ok(!ids.has(c.id), `شناسهٔ تکراری ${c.id}`);
  ids.add(c.id);
  ok(MENUS.some((m) => m.id === c.menu), `منوی ناشناخته ${c.id}`);
  ok(c.title.trim().length > 1 && c.tip.trim().length > 3 && c.en.trim().length > 1, `عنوان/راهنما/نام انگلیسی خالی ${c.id}`);
  const txt = [c.title, c.tip, c.group].join(" ");
  ok(!/photoshop|adobe|فتوشاپ|lightroom|camera raw|premiere|پریمیر/i.test(txt), `نامِ برندِ دیگران در متنِ نمایشیِ ${c.id}`);
  // هر دستور با حالتِ «همه فعال» باید یک کارِ Host را صدا بزند
  const { h, calls } = spyHost(ALL_ON);
  const h0 = spyHost({ ...ALL_ON, activeHasMask: false }).h;
  const h1 = spyHost({ ...ALL_ON, activeType: "image" }).h;
  ok(!c.enabled || c.enabled(h) === null || c.enabled(h0) === null || c.enabled(h1) === null, `در حالتِ فعال باید فعال باشد ${c.id}: ${c.enabled?.(h)}`);
  c.run(h);
  ok(calls.length >= 1, `دستورِ مرده (هیچ کاری نمی‌کند): ${c.id}`);
  // بدونِ لایه/انتخاب: یا فعال است یا دلیلِ فارسی دارد
  const n = spyHost(NONE).h;
  const why = c.enabled?.(n) ?? null;
  ok(why === null || /[\u0600-\u06FF]/.test(why), `دلیلِ غیرفعال بودن فارسی نیست ${c.id}`);
}
for (const m of MENUS) ok(cmds.some((c) => c.menu === m.id), `منوی خالی: ${m.title}`);
ok(searchCommands(cmds, "خاموش کردن هوش مصنوعی")[0]?.cmd.id === "file.settingsAi", "جستجوی «خاموش کردن هوش مصنوعی»");
ok(searchCommands(cmds, "brand")[0]?.cmd.id === "file.settingsBrand", "brand");
ok(searchCommands(cmds, "batch")[0]?.cmd.id === "file.batch", "batch");
// منوی بدون دستورِ غیرفعالِ بی‌دلیل
for (const c of cmds.filter((x) => x.key)) ok(/^(Ctrl\+|Shift\+|Alt\+)*([A-Za-z0-9\\?+-]|Delete|Backspace)$/.test(c.key!), `قالبِ کلید ${c.id}: ${c.key}`);

// جستجو
const first = (q: string) => searchCommands(cmds, q)[0]?.cmd.id;
ok(first("کراپ") === "image.crop" || first("کراپ") === "tool.crop", `کراپ ⇒ ${first("کراپ")}`);
ok(searchCommands(cmds, "crop").some((x) => x.cmd.id === "image.crop"), "crop");
ok(searchCommands(cmds, "ماسک").length >= 4, "ماسک");
ok(searchCommands(cmds, "undo")[0]?.cmd.id === "edit.undo", "undo");
ok(searchCommands(cmds, "ctrl+j")[0]?.cmd.id === "edit.duplicate", "کلیدِ ctrl+j");
ok(searchCommands(cmds, "برگردانــدن".replace("ـ", ""))[0]?.cmd.id === "edit.undo", "برگرداندن");
ok(searchCommands(cmds, "رونوشت لايه")[0]?.cmd.id === "edit.duplicate", "ي عربی");
ok(searchCommands(cmds, "بک گراند").some((x) => x.cmd.id === "image.removeBg"), "بک‌گراند");
ok(searchCommands(cmds, "zzzzqq").length === 0, "چیزِ بی‌ربط");
ok(norm("كيك") === "کیک" && norm("۱۲٣") === "123" && norm("می‌خواهم") === "می خواهم", "norm");
// مرتب‌سازی: فعال‌ها پیش از غیرفعال‌ها
const h2 = spyHost(NONE).h;
const hits = searchCommands(cmds, "ماسک", h2);
const firstDis = hits.findIndex((x) => x.reason);
ok(firstDis < 0 || hits.slice(firstDis).every((x) => x.reason), "فعال‌ها اول");

console.log(fails ? `photo-r4-registry: ${fails} FAIL از ${total}` : `photo-r4-registry: همهٔ ${total} بررسی درست`);
if (fails) process.exit(1);
