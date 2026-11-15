// بازبینیِ کیفیتِ ۱۴ آبان — ادیتورِ عکس و تامنیل‌ساز: منطقِ خالصِ سمتِ مرورگر (بی DOM).
//   cd frontend && node_modules/.bin/esbuild tests/photo-audit.test.ts --bundle --platform=node --format=cjs --outfile=/tmp/photo-audit.test.cjs && node /tmp/photo-audit.test.cjs
import { BackoffPoller, POLL_STEPS_MS, edgeKey, isWaitingOnNode, nextStep } from "../src/features/content/photo/polling";
import type { PollEnv, TickResult } from "../src/features/content/photo/polling";
import { LIB_PAGE, filterAssets, findingLabel, normFa, pageAssets, primaryFinding } from "../src/features/content/photo/libraryUtil";
import { COPY_FIELDS, EXAMPLES, QUICK_EXAMPLES, designExamples } from "../src/features/content/photo/designer/labels";
import { HISTORY_PHONE_LIMIT, splitWarnings, visibleHistory } from "../src/features/content/thumbs/historyUtil";
import { EXPORT_CAP_TIP, TOOL_META, buildCommands, withCap } from "../src/features/content/photo/pro/menu/registry";

let fails = 0;
let total = 0;
const ok = (c: unknown, msg: string) => {
  total++;
  if (!c) {
    fails++;
    console.log("FAIL:", msg);
  }
};
const eq = (a: unknown, b: unknown, msg: string) => ok(JSON.stringify(a) === JSON.stringify(b), `${msg}: ${JSON.stringify(a)} !== ${JSON.stringify(b)}`);

// ───────────────────────────── پیگیری با back-off
/** محیطِ جعلی: ساعتِ دستی، تبِ قابلِ پنهان‌شدن */
function fakeEnv() {
  let now = 0;
  let hidden = false;
  let seq = 0;
  const timers = new Map<number, { at: number; fn: () => void }>();
  const listeners = new Set<() => void>();
  const delays: number[] = [];
  const env: PollEnv = {
    setTimeout: (fn, ms) => {
      const id = ++seq;
      delays.push(ms);
      timers.set(id, { at: now + ms, fn });
      return id;
    },
    clearTimeout: (h) => void timers.delete(h as number),
    hidden: () => hidden,
    onVisible: (cb) => {
      listeners.add(cb);
      return () => void listeners.delete(cb);
    },
  };
  /** ساعت را جلو ببر و تایمرهای رسیده را اجرا کن؛ هر تایمر یک دور async را کامل می‌کند */
  async function advance(ms: number) {
    const end = now + ms;
    for (;;) {
      const due = [...timers.entries()].filter(([, t]) => t.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
      if (!due) break;
      timers.delete(due[0]);
      now = due[1].at;
      due[1].fn();
      for (let i = 0; i < 6; i++) await Promise.resolve();
    }
    now = end;
  }
  return {
    env,
    delays,
    advance,
    setHidden(v: boolean) {
      hidden = v;
      if (!v) listeners.forEach((f) => f());
    },
    pending: () => timers.size,
  };
}

async function pollTests() {
  eq([...POLL_STEPS_MS], [3000, 15000, 60000], "پله‌های فاصله");
  const waitUnchanged: TickResult = { changed: false, waitingOnly: true };
  eq(nextStep(0, waitUnchanged), 1, "بی‌تغییر و منتظرِ سرورِ پردازش ⇒ ۱۵ ثانیه");
  eq(nextStep(1, waitUnchanged), 2, "⇒ ۶۰ ثانیه");
  eq(nextStep(2, waitUnchanged), 2, "سقفِ ۶۰ ثانیه");
  eq(nextStep(2, { changed: true, waitingOnly: true }), 0, "هر تغییر ⇒ برگشت به ۳ ثانیه");
  eq(nextStep(1, { changed: false, waitingOnly: false }), 0, "کارِ در حالِ اجرا روی سرورِ سایت ⇒ همان ۳ ثانیه");

  ok(isWaitingOnNode({ state: "NODE" }), "NODE = منتظرِ سرورِ پردازش");
  ok(isWaitingOnNode({ state: "QUEUED", needs_node: true }), "QUEUED با needs_node = منتظر");
  ok(!isWaitingOnNode({ state: "QUEUED", needs_node: false }), "QUEUED سرورِ سایت = منتظرِ گره نیست");
  ok(!isWaitingOnNode({ state: "SERVER" }), "SERVER = در حالِ کار");
  ok(edgeKey({ state: "NODE", progress: 0.1, message: "a" }) !== edgeKey({ state: "NODE", progress: 0.2, message: "a" }), "پیشرفت = تغییر");
  ok(edgeKey({ state: "NODE", progress: 0.1, message: "a" }) === edgeKey({ state: "NODE", progress: 0.1, message: "a" }), "همان وضع = بی‌تغییر");

  // ۱) منتظرِ گره، بی‌تغییر: ۳ ← ۱۵ ← ۶۰ ← ۶۰
  {
    const f = fakeEnv();
    let calls = 0;
    const p = new BackoffPoller(async () => (calls++, { changed: false, waitingOnly: true }), f.env);
    p.start();
    await f.advance(3000);
    eq(calls, 1, "اولین دور بعد از ۳ ثانیه");
    await f.advance(14999);
    eq(calls, 1, "قبل از ۱۵ ثانیه دورِ دوم نیست");
    await f.advance(1);
    eq(calls, 2, "دورِ دوم بعد از ۱۵ ثانیه");
    await f.advance(60000);
    eq(calls, 3, "دورِ سوم بعد از ۶۰ ثانیه");
    await f.advance(60000);
    eq(calls, 4, "و همین‌طور ۶۰ ثانیه");
    eq(f.delays.slice(0, 5), [3000, 15000, 60000, 60000, 60000], "فاصله‌ها به ترتیب");
    p.stop();
    eq(f.pending(), 0, "stop تایمر را برمی‌دارد");
    await f.advance(120000);
    eq(calls, 4, "بعد از stop دورِ تازه‌ای نیست");
  }
  // ۲) تغییر ⇒ برگشت به ۳ ثانیه
  {
    const f = fakeEnv();
    const seqRes: TickResult[] = [
      { changed: false, waitingOnly: true },
      { changed: false, waitingOnly: true },
      { changed: true, waitingOnly: true },
      { changed: false, waitingOnly: true },
    ];
    let i = 0;
    const p = new BackoffPoller(async () => seqRes[Math.min(i++, seqRes.length - 1)], f.env);
    p.start();
    await f.advance(3000 + 15000 + 60000 + 3000);
    eq(f.delays.slice(0, 5), [3000, 15000, 60000, 3000, 15000], "بعد از تغییر دوباره ۳ ثانیه");
    p.stop();
  }
  // ۳) تبِ پنهان: هیچ درخواستی؛ برگشتن ⇒ فوراً یک دور
  {
    const f = fakeEnv();
    let calls = 0;
    const p = new BackoffPoller(async () => (calls++, { changed: false, waitingOnly: false }), f.env);
    p.start();
    f.setHidden(true);
    await f.advance(3000);
    const before = calls;
    await f.advance(10 * 60000);
    eq(calls, before, "تبِ پنهان ⇒ هیچ دورِ تازه‌ای");
    ok(f.pending() === 0, "تبِ پنهان ⇒ تایمری ثبت نیست");
    f.setHidden(false);
    await f.advance(0);
    eq(calls, before + 1, "برگشتنِ تب ⇒ فوراً یک دور");
    p.stop();
  }
  // ۴) stop از خودِ دور؛ خطای شبکه پله را بالا نمی‌برد و ادامه می‌دهد
  {
    const f = fakeEnv();
    let calls = 0;
    const p = new BackoffPoller(async () => (calls++, { changed: false, waitingOnly: false, stop: true }), f.env);
    p.start();
    await f.advance(3000);
    await f.advance(60000);
    eq(calls, 1, "stop:true ⇒ دیگر نمی‌پرسد");
    const g = fakeEnv();
    let n = 0;
    const q = new BackoffPoller(async () => {
      n++;
      if (n === 1) throw new Error("network");
      return { changed: false, waitingOnly: false };
    }, g.env);
    q.start();
    await g.advance(3000);
    await g.advance(3000);
    eq(n, 2, "بعد از خطای شبکه دورِ بعد می‌آید");
    q.stop();
  }
}

// ───────────────────────────── کتابخانه
type A = Parameters<typeof primaryFinding>[0] & { title: string; source_label: string; product_name: string | null };
const mk = (title: string, findings: { what: string; note: string; value: number }[], facts: Record<string, number | boolean> = {}): A => ({
  title, source_label: "آپلود", product_name: null, findings, facts,
});
function libraryTests() {
  const dark = { what: "dark", note: "عکس تیره است (روشناییِ میانه ۴۸ از ۲۵۵)", value: 48 };
  const flat = { what: "flat", note: "عکس کم‌کنتراست و تخت است", value: 20 };
  const plain = { what: "plain_bg", note: "زمینهٔ ساده و روشن دارد", value: 5 };
  const small = { what: "small", note: "عکس کوچک است", value: 600 };
  eq(primaryFinding(mk("a", [flat, dark]))?.what, "dark", "مهم‌ترین هشدار می‌ماند، نه اولی");
  eq(primaryFinding(mk("a", [small, flat]))?.what, "flat", "کم‌کنتراست مهم‌تر از کوچک");
  eq(primaryFinding(mk("a", [plain]))?.what, "plain_bg", "فقط خبرِ خوب ⇒ همان");
  eq(primaryFinding(mk("a", [plain, dark]))?.what, "dark", "هشدار بر خبرِ خوب می‌چربد");
  eq(primaryFinding(mk("a", [])), null, "بی‌هشدار ⇒ بی‌برچسب");
  eq(primaryFinding(mk("slide", [dark, flat], { graphic: true })), null, "طرحِ گرافیکی هیچ برچسبی ندارد");
  eq(findingLabel(dark), "عکس تیره است", "متنِ برچسب بی توضیحِ پرانتزی");

  eq(normFa("  كتاب‌خانه  ‌ي  "), "کتاب خانه ی", "یکسان‌سازیِ ی/ک و فاصلهٔ مجازی");
  const list = [mk("کاروسل: چغر چیست؟ — اسلاید 1", []), mk("استوری: وقتِ مربی", []), mk("زمینهٔ برند — فیروزه‌ای", [])];
  eq(filterAssets(list, "").length, 3, "جستجوی خالی همه را نشان می‌دهد");
  eq(filterAssets(list, "استوری").map((a) => a.title), ["استوری: وقتِ مربی"], "جستجو در عنوان");
  eq(filterAssets(list, "ببرند").length, 0, "بی نتیجه");
  eq(filterAssets(list, "آپلود").length, 3, "جستجو در برچسبِ منبع");
  const many = Array.from({ length: 49 }, (_, i) => i);
  const p1 = pageAssets(many, LIB_PAGE);
  eq([p1.shown.length, p1.rest], [12, 37], "آخرین ۱۲ و ۳۷ تای دیگر");
  eq(pageAssets(many, LIB_PAGE * 5).rest, 0, "همه نمایش داده شد");
  eq(pageAssets(many, Number.MAX_SAFE_INTEGER).shown.length, 49, "نمایشِ همه");
  eq(LIB_PAGE, 12, "صفحه‌بندیِ ۱۲تایی");
}

// ───────────────────────────── مثال‌ها
const PRICEY = /[0-9۰-۹٠-٩%٪]|تومان|ریال|قیمت|تخفیف|درصد/;
function exampleTests() {
  for (const x of [...EXAMPLES, ...QUICK_EXAMPLES]) ok(!PRICEY.test(x), `مثالِ بی قیمت و بی عدد: ${x}`);
  ok(!QUICK_EXAMPLES.join(" ").includes("کافه"), "مثالِ کافه برداشته شد");
  ok(!EXAMPLES.join(" ").includes("کفش"), "مثالِ کفش برداشته شد");
  for (const f of COPY_FIELDS) ok(!/[۰-۹0-9]/.test(f.ph) && !f.ph.includes("تومان"), `جای‌نمای ${f.key} قیمتِ ساختگی ندارد`);
  eq(designExamples(["پستِ معرفیِ «چغر»، شیک و خوانا", "استوریِ «برنامهٔ تکی»"]).length, 2, "مثالِ فروشگاه می‌آید");
  eq(designExamples(["تبلیغِ کفش با تخفیف ۳۰ درصد", "قیمت ۴۵۰ تومان", ""]), EXAMPLES, "مثالِ قیمت‌دار کنار می‌رود و عمومی می‌آید");
  eq(designExamples(null), EXAMPLES, "بی سرور ⇒ عمومی");
  eq(designExamples(["الف", "ب", "ج", "د", "ه", "و", "ز"]).length, 5, "حداکثر ۵");
}

// ───────────────────────────── تاریخچهٔ تامنیل‌ساز
function historyTests() {
  const W1 = "عکسِ سوژه کم‌رزولوشن است";
  const W2 = "متن به لبه نزدیک است";
  const mkItem = (id: number, warnings: string[]) => ({ id, warnings });
  const twelve = Array.from({ length: 12 }, (_, i) => mkItem(i + 1, [W1, W2]));
  const s = splitWarnings(twelve);
  eq(s.shared.map((w) => w.text), [W1, W2], "دو هشدارِ یکسان فقط یک بار");
  eq(s.shared.map((w) => w.count), [12, 12], "شمارش");
  ok([...s.own.values()].every((l) => l.length === 0), "روی کارت‌ها دیگر تکرار نمی‌شود");
  const mixed = [mkItem(1, [W1, "فقط من"]), mkItem(2, [W1]), mkItem(3, [])];
  const m = splitWarnings(mixed);
  eq(m.shared, [{ text: W1, count: 2 }], "مشترکِ دو نسخه");
  eq(m.own.get(1), ["فقط من"], "هشدارِ ویژه می‌ماند");
  const single = splitWarnings([mkItem(9, [W1, W2])]);
  eq(single.shared, [], "فهرستِ تک‌نسخه‌ای دست‌نخورده");
  eq(single.own.get(9), [W1, W2], "هشدارها روی همان کارت");
  eq(splitWarnings([mkItem(1, [W1, W1]), mkItem(2, [])]).own.get(1), [W1], "تکرار داخلِ یک کارت هم یکی می‌شود");

  const items = Array.from({ length: 12 }, (_, i) => i);
  eq(visibleHistory(items, { phone: true, expanded: false }), { shown: [0, 1, 2, 3], hidden: 8 }, "گوشی: آخرین ۴");
  eq(visibleHistory(items, { phone: true, expanded: true }).shown.length, 12, "نمایشِ بیشتر");
  eq(visibleHistory(items, { phone: false, expanded: false }).shown.length, 12, "میز: همه");
  eq(visibleHistory(items.slice(0, 3), { phone: true, expanded: false }), { shown: [0, 1, 2], hidden: 0 }, "سه کارت: چیزی پنهان نیست");
  eq(HISTORY_PHONE_LIMIT, 4, "حدِ گوشی ۴");
}

// ───────────────────────────── منوی خروجی‌های ادیتورِ حرفه‌ای
function exportMenuTests() {
  ok(EXPORT_CAP_TIP.includes("۱۲۸۰") && EXPORT_CAP_TIP.includes("ساخت و ذخیره"), "جملهٔ سقف");
  ok(withCap("x").endsWith(EXPORT_CAP_TIP), "withCap");
  const tools = Object.keys(TOOL_META).map((id) => ({ id, key: "A", title: id, hint: id }));
  const cmds = buildCommands(tools, []);
  const exports = cmds.filter((c) => c.id.startsWith("file.export.") && !["file.exportInstagram", "file.exportStory", "file.exportBanner", "file.exportMarket", "file.exportChat"].includes(c.id));
  const ids = exports.map((c) => c.id.replace("file.export.", ""));
  for (const k of ["psd", "tiff", "pdf", "gif", "bmp", "svg", "gray", "cmyk", "indexed", "rgb16", "lab"]) ok(ids.includes(k), `ورودیِ خروجی ${k} هست`);
  for (const c of exports) ok(c.tip.includes(EXPORT_CAP_TIP), `«${c.id}» سقفِ ۱۲۸۰ را می‌گوید`);
  const tiff = exports.find((c) => c.id === "file.export.tiff");
  ok(!!tiff && !tiff.tip.includes("برای چاپ و بایگانی"), "TIFF دیگر «برای چاپ» تبلیغ نمی‌شود");
  ok(!/adobe|photoshop|پریمیر|فتوشاپ/i.test(exports.map((c) => c.tip + c.title).join(" ")), "نامِ برندِ دیگران نیست");
}

void (async () => {
  await pollTests();
  libraryTests();
  exampleTests();
  historyTests();
  exportMenuTests();
  console.log(`${total - fails}/${total} passed`);
  if (fails) process.exit(1);
})();
