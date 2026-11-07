import type { Layer, ProState } from "./types";
import { nid } from "./types";

/**
 * اکشن‌های ضبط‌شدنی (نوبت ۶): هر گامِ تاریخچه به چند «عملِ» ساده تبدیل می‌شود و بعد می‌شود روی هر عکسِ دیگر اجرا کرد.
 *
 *   set    — کلیدِ بالاسطحیِ حالت (adjust، curve، crop، turn، out، tools …)؛ مقدارِ تازه جایگزین می‌شود
 *   add    — لایهٔ تازه‌ی بی‌پیکسل (متن، شکل، تنظیم، لوگو) به بالای لایه‌ها
 *   patch  — تغییرِ فیلدهای یک لایه؛ ref = "base" (عکس) یا "@k" (k-امین لایه‌ای که همین اکشن افزوده)
 *   remove — برداشتنِ لایه‌ای که همین اکشن افزوده بود
 *
 * آنچه به پیکسلِ همین عکس بسته است (نقاشی، مایع‌سازی، عکس‌های دیگر، ماسکِ نقاشی‌شده، گروه‌ها) ضبط نمی‌شود و شمرده می‌شود
 * (`skipped`) تا کاربر بداند. فرمتِ ذخیره‌شده در سرور (PhotoPreset با kind="action") با backend `normalize_action_data` یکی است.
 */
export type ActionOp =
  | { op: "set"; key: string; value: unknown }
  | { op: "add"; layer: Record<string, unknown> }
  | { op: "patch"; ref: string; set: Record<string, unknown> }
  | { op: "remove"; ref: string };

export type ActionStep = { label: string; ops: ActionOp[] };
export type ActionData = { steps: ActionStep[] };

export const ACTION_MAX_STEPS = 80;

/** لایه‌هایی که بی‌پیکسلِ این عکس‌اند و روی هر عکسی می‌نشینند */
const PORTABLE = new Set(["text", "shape", "adjust"]);
const RESERVED_KEYS = new Set(["layers", "fv", "liquify"]);
const NO_PATCH = new Set(["id", "type", "src", "parent", "path"]);

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/** لایه‌ای که می‌شود در اکشن گذاشت؟ (ماسکِ نقاشی‌شده و لایهٔ فرزندِ گروه نه) */
export function portableLayer(l: Layer): boolean {
  if (l.parent) return false;
  if (l.type === "image") return l.src.kind === "logo";
  return PORTABLE.has(l.type);
}

function stripLayer(l: Layer): Record<string, unknown> {
  const c = clone(l) as unknown as Record<string, unknown>;
  const m = c.mask as { type?: string } | null | undefined;
  if (m && m.type === "paint") c.mask = null; // پیکسلِ ماسک همراهش نمی‌آید
  return c;
}

export type DiffResult = { ops: ActionOp[]; skipped: number };

/**
 * تفاوتِ دو حالت ⇒ عمل‌ها. ctx.added نگاشتِ شناسهٔ لایه ⇒ «@k» است و میانِ گام‌های پیاپیِ یک ضبط نگه داشته می‌شود.
 */
export function diffStates(before: ProState, after: ProState, ctx: { added: Map<string, string> }): DiffResult {
  const ops: ActionOp[] = [];
  let skipped = 0;
  const a = before as unknown as Record<string, unknown>;
  const b = after as unknown as Record<string, unknown>;
  for (const key of Object.keys(b)) {
    if (RESERVED_KEYS.has(key)) continue;
    if (!same(a[key], b[key])) ops.push({ op: "set", key, value: clone(b[key]) });
  }
  if (!same(before.liquify ?? null, after.liquify ?? null)) skipped++;
  const was = new Map(before.layers.map((l) => [l.id, l]));
  const now = new Map(after.layers.map((l) => [l.id, l]));
  for (const l of after.layers) {
    if (was.has(l.id)) continue;
    if (!portableLayer(l)) {
      skipped++;
      continue;
    }
    ctx.added.set(l.id, `@${ctx.added.size}`);
    ops.push({ op: "add", layer: stripLayer(l) });
  }
  for (const l of before.layers) {
    if (now.has(l.id)) continue;
    const ref = ctx.added.get(l.id);
    if (ref) {
      ops.push({ op: "remove", ref });
      ctx.added.delete(l.id);
    } else skipped++;
  }
  for (const l of after.layers) {
    const o = was.get(l.id);
    if (!o || same(o, l)) continue;
    const ref = l.id === "base" ? "base" : ctx.added.get(l.id);
    if (!ref) {
      // لایهٔ از پیش موجود (مثلاً عکسِ دیگر / نقاشی): فقط اگر پیکسلی نباشد ارزشِ ضبط ندارد؛ اینجا نادیده گرفته می‌شود
      skipped++;
      continue;
    }
    const set: Record<string, unknown> = {};
    const lo = o as unknown as Record<string, unknown>;
    const ln = l as unknown as Record<string, unknown>;
    for (const k of Object.keys(ln)) {
      if (NO_PATCH.has(k)) continue;
      if (!same(lo[k], ln[k])) set[k] = k === "mask" && (ln[k] as { type?: string } | null)?.type === "paint" ? null : clone(ln[k]);
    }
    if (Object.keys(set).length) ops.push({ op: "patch", ref, set });
  }
  return { ops, skipped };
}

/** عمل‌ها را روی یک حالت اجرا می‌کند ⇒ حالتِ تازه (ورودی دست‌نخورده)؛ added = نگاشتِ «@k» ⇒ شناسهٔ تازه */
export function applyOps(state: ProState, ops: ActionOp[], added: Map<string, string> = new Map()): ProState {
  const s = clone(state) as ProState;
  const rec = s as unknown as Record<string, unknown>;
  for (const o of ops) {
    if (o.op === "set") {
      if (!RESERVED_KEYS.has(o.key)) rec[o.key] = clone(o.value);
    } else if (o.op === "add") {
      const l = clone(o.layer) as unknown as Layer & Record<string, unknown>;
      const isLogo = l?.type === "image" && (l as { src?: { kind?: string } }).src?.kind === "logo";
      if (!l || typeof l !== "object" || (!PORTABLE.has(l.type) && !isLogo)) continue;
      l.id = nid();
      delete l.parent;
      added.set(`@${added.size}`, l.id);
      s.layers.push(l as Layer);
    } else if (o.op === "patch") {
      const id = o.ref === "base" ? "base" : added.get(o.ref);
      const t = id ? s.layers.find((x) => x.id === id) : null;
      if (!t) continue;
      const tr = t as unknown as Record<string, unknown>;
      for (const [k, v] of Object.entries(o.set)) if (!NO_PATCH.has(k)) tr[k] = clone(v);
    } else if (o.op === "remove") {
      const id = added.get(o.ref);
      if (id) s.layers = s.layers.filter((x) => x.id !== id);
    }
  }
  return s;
}

/** همهٔ گام‌ها پشتِ هم ⇒ یک حالت (برای اجرای اکشن روی عکسِ باز) */
export function playAction(state: ProState, data: ActionData): ProState {
  const added = new Map<string, string>();
  let s = state;
  for (const st of data.steps) s = applyOps(s, st.ops, added);
  return s;
}

const KEY_FA: Record<string, string> = {
  adjust: "تنظیمِ نور و رنگ", curve: "منحنی", crop: "برش", turn: "چرخش", straighten: "صاف‌کردن", flipH: "قرینهٔ افقی", flipV: "قرینهٔ عمودی",
  persp: "پرسپکتیو", out: "تنظیمِ خروجی", tools: "ابزارِ فیلتر و متن", kitAuto: "بهبودِ خودکار", spots: "ترمیمِ لکه",
};

/** شرحِ کوتاهِ فارسیِ یک گام برای فهرست */
export function describeStep(st: ActionStep): string {
  const parts: string[] = [];
  for (const o of st.ops) {
    if (o.op === "set") parts.push(KEY_FA[o.key] ?? o.key);
    else if (o.op === "add") parts.push(`لایهٔ ${(o.layer.name as string) || "تازه"}`);
    else if (o.op === "patch") parts.push(o.ref === "base" ? "تنظیمِ لایهٔ عکس" : "ویرایشِ لایهٔ افزوده");
    else parts.push("برداشتنِ لایه");
  }
  return [...new Set(parts)].join("، ") || st.label;
}

/** اعتبارسنجیِ سبکِ دادهٔ ذخیره‌شده (از سرور) پیش از اجرا */
export function parseAction(raw: unknown): ActionData | null {
  const steps = (raw as { steps?: unknown })?.steps;
  if (!Array.isArray(steps)) return null;
  const out: ActionStep[] = [];
  for (const s of steps.slice(0, ACTION_MAX_STEPS)) {
    const ops = (s as { ops?: unknown })?.ops;
    if (!Array.isArray(ops)) continue;
    out.push({ label: String((s as { label?: unknown }).label ?? "گام").slice(0, 80), ops: ops.filter((o) => o && typeof o === "object" && ["set", "add", "patch", "remove"].includes((o as ActionOp).op)) as ActionOp[] });
  }
  return { steps: out };
}
