// آزمونِ نوبت ۶: اکشن‌های ضبط‌شدنی — تفاوتِ دو حالت ⇒ عمل‌ها ⇒ اجرا روی عکسِ دیگر.
import { ActionData, applyOps, describeStep, diffStates, parseAction, playAction, portableLayer } from "../src/features/content/photo/pro/actions";
import { makeAdjust, makeBase, makeImage, makePaintLayer, makeText, ProState } from "../src/features/content/photo/pro/types";
import { defaultState } from "../src/features/content/photo/manual/model";

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

const fresh = (): ProState => ({ ...defaultState(), fv: 2, layers: [makeBase()], persp: null });
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

// ── گام ۱: تنظیمِ نور و رنگ (کلیدِ بالاسطحی)
const s0 = fresh();
const s1 = { ...clone(s0), adjust: { exposure: 0.4, contrast: 15 } } as ProState;
const ctx = { added: new Map<string, string>() };
const d1 = diffStates(s0, s1, ctx);
eq(d1.ops.length, 1, "یک عمل set");
eq(d1.ops[0], { op: "set", key: "adjust", value: { exposure: 0.4, contrast: 15 } }, "set adjust");
eq(d1.skipped, 0, "چیزی نادیده گرفته نشد");

// ── گام ۲: افزودنِ متن (واترمارک) + گام ۳: تغییرِ همان لایه
const t = makeText(0.8, 0.92, "فروشگاه من");
const s2 = { ...clone(s1), layers: [...clone(s1.layers), t] } as ProState;
const d2 = diffStates(s1, s2, ctx);
eq(d2.ops.map((o) => o.op), ["add"], "add متن");
eq(ctx.added.get(t.id), "@0", "نگاشتِ شناسه ⇒ @0");
const s3 = clone(s2);
(s3.layers[1] as { opacity: number }).opacity = 0.5;
(s3.layers[0] as { opacity: number }).opacity = 0.9;
const d3 = diffStates(s2, s3, ctx);
eq(d3.ops.map((o) => `${o.op}:${(o as { ref?: string }).ref}`), ["patch:base", "patch:@0"], "patch به base و @0");

// ── پخش روی یک عکسِ دیگر (حالتِ تمیز)
const act: ActionData = { steps: [{ label: "نور", ops: d1.ops }, { label: "واترمارک", ops: d2.ops }, { label: "کم‌رنگ", ops: d3.ops }] };
const target = fresh();
const out = playAction(target, act);
eq(out.adjust, { exposure: 0.4, contrast: 15 }, "پخش: adjust");
eq(out.layers.length, 2, "پخش: یک لایه افزوده شد");
const nt = out.layers[1] as unknown as { type: string; text: string; opacity: number; id: string };
ok(nt.type === "text" && nt.text === "فروشگاه من" && nt.opacity === 0.5, "پخش: متن با کم‌رنگیِ ثبت‌شده");
ok(nt.id !== t.id, "شناسهٔ تازه گرفت");
eq((out.layers[0] as { opacity: number }).opacity, 0.9, "پخش: patch روی base");
eq(target.layers.length, 1, "ورودی دست‌نخورده");
// دو بار پخش ⇒ دو واترمارکِ جدا با شناسهٔ متفاوت
const twice = playAction(out, act);
ok(twice.layers.length === 3 && new Set(twice.layers.map((l) => l.id)).size === 3, "پخشِ دوباره: شناسه‌ها یکتا");

// ── حذفِ لایهٔ افزودهٔ همین اکشن
const ctx2 = { added: new Map<string, string>() };
const a = diffStates(s0, { ...clone(s0), layers: [...clone(s0.layers), t] } as ProState, ctx2);
const b = diffStates({ ...clone(s0), layers: [...clone(s0.layers), t] } as ProState, s0, ctx2);
eq(b.ops, [{ op: "remove", ref: "@0" }], "remove با مرجع");
const gone = playAction(fresh(), { steps: [{ label: "a", ops: a.ops }, { label: "b", ops: b.ops }] });
eq(gone.layers.length, 1, "افزودن و حذف ⇒ بی‌اثر");

// ── آنچه پیکسلِ این عکس است ضبط نمی‌شود و شمرده می‌شود
const paint = makePaintLayer("p1");
const withPaint = { ...clone(s0), layers: [...clone(s0.layers), paint] } as ProState;
const dp = diffStates(s0, withPaint, { added: new Map() });
eq(dp.ops, [], "لایهٔ نقاشی ضبط نمی‌شود");
eq(dp.skipped, 1, "ولی شمرده می‌شود");
const photo = makeImage({ kind: "asset", asset: 7 });
ok(!portableLayer(photo) && !portableLayer(paint), "عکس و نقاشی قابلِ حمل نیستند");
ok(portableLayer(t) && portableLayer(makeAdjust("x", { exposure: 0.1 })) && portableLayer(makeImage({ kind: "logo" })), "متن، تنظیم و لوگو قابلِ حمل‌اند");
// تغییرِ لایهٔ از پیش موجودِ غیر از base (مثلاً عکسِ دیگر) نادیده گرفته می‌شود
const two = { ...clone(s0), layers: [...clone(s0.layers), photo] } as ProState;
const two2 = clone(two);
(two2.layers[1] as { cx: number }).cx = 0.2;
const dq = diffStates(two, two2, { added: new Map() });
eq(dq.ops, [], "patch روی لایهٔ ناشناخته ضبط نمی‌شود");
eq(dq.skipped, 1, "شمرده می‌شود");
// ماسکِ نقاشی‌شده همراهِ لایهٔ افزوده نمی‌آید
const tm = { ...clone(makeText()), mask: { type: "paint", id: "m1", invert: false, rev: 4 } } as unknown as ProState["layers"][number];
const dm = diffStates(s0, { ...clone(s0), layers: [...clone(s0.layers), tm] } as ProState, { added: new Map() });
eq((dm.ops[0] as { layer: { mask: unknown } }).layer.mask, null, "ماسکِ نقاشی‌شده حذف شد");
// کلیدهای ممنوع (layers, fv, liquify) هرگز set نمی‌شوند
const hack = applyOps(fresh(), [{ op: "set", key: "layers", value: [] }, { op: "set", key: "fv", value: 9 }, { op: "set", key: "liquify", value: { rev: 1 } }]);
ok(hack.layers.length === 1 && hack.fv === 2 && !hack.liquify, "کلیدهای ممنوع نادیده گرفته شد");
// patch کلیدهای محافظت‌شده را عوض نمی‌کند
const prot = applyOps(fresh(), [{ op: "patch", ref: "base", set: { id: "x", type: "text", opacity: 0.3 } }]);
ok(prot.layers[0].id === "base" && prot.layers[0].type === "base" && prot.layers[0].opacity === 0.3, "id و type محافظت‌شده");
// add با نوعِ ممنوع (عکسِ کتابخانه) نادیده گرفته می‌شود؛ مرجعِ ناشناخته بی‌اثر است
const bad = applyOps(fresh(), [{ op: "add", layer: clone(photo) as unknown as Record<string, unknown> }, { op: "patch", ref: "@9", set: { opacity: 0 } }, { op: "remove", ref: "@9" }]);
eq(bad.layers.length, 1, "add نوعِ ممنوع نادیده گرفته شد");

// ── شرح، تجزیه
ok(describeStep({ label: "x", ops: d1.ops }).includes("نور و رنگ"), "شرحِ گامِ نور");
ok(describeStep({ label: "x", ops: d2.ops }).includes("لایهٔ"), "شرحِ گامِ افزودن");
ok(parseAction(null) === null && parseAction({ steps: 5 }) === null, "parseAction داده‌ی بد ⇒ null");
const pa = parseAction({ steps: [{ label: "a", ops: [{ op: "set", key: "kitAuto", value: true }, { op: "zzz" }, 5] }, { nolabel: 1 }, { label: "b", ops: "x" }] });
ok(pa !== null && pa.steps.length === 1 && pa.steps[0].ops.length === 1, "parseAction عمل‌های بد و گام‌های بی‌عمل را می‌اندازد");

console.log(fails ? `photo-r6-actions: ${fails} FAIL از ${total}` : `photo-r6-actions: همهٔ ${total} بررسی درست`);
if (fails) process.exit(1);
