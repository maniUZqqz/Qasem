import { useCallback, useRef, useState } from "react";

import { countRender } from "./perfCount";

export type HistoryEntry<T> = { label: string; state: T };

const hasOwn = Object.prototype.hasOwnProperty;

/** مقداری که JSON.stringify در یک شیء به کل نمی‌نویسد (و در آرایه `null` می‌نویسد) */
const dropped = (v: unknown): boolean => v === undefined || typeof v === "function" || typeof v === "symbol";

/** کلیدهای یک شیءِ ساده به همان ترتیب و همان فیلترِ JSON.stringify */
function jsonKeys(o: Record<string, unknown>): string[] {
  const out: string[] = [];
  for (const k in o) if (hasOwn.call(o, k) && !dropped(o[k])) out.push(k);
  return out;
}

/** فقط شیء/آرایهٔ سادهٔ داده؛ هر چیزِ عجیب (Date، Map، کلاس، toJSON) برای احتیاط با خودِ JSON.stringify مقایسه می‌شود */
function isPlain(v: object): boolean {
  if (Array.isArray(v)) return true;
  const proto = Object.getPrototypeOf(v);
  return (proto === Object.prototype || proto === null) && typeof (v as { toJSON?: unknown }).toJSON !== "function";
}

function stringifyEqual(a: unknown, b: unknown): boolean {
  countRender("historyStringify", 2);
  return JSON.stringify(a) === JSON.stringify(b);
}

/**
 * «آیا JSON.stringify(a) === JSON.stringify(b)؟» بی‌آن‌که هر دو را رشته کند.
 * حالتِ فعلی/پیشنهادیِ تاریخچه معمولاً بیشترِ زیرشاخه‌هایش را با هم شریک است (ویرایش‌ها فقط مسیرِ تغییر را نو می‌کنند)،
 * پس مقایسهٔ ساختاریِ با میان‌برِ `===` به‌جای رشته‌کردنِ دو بارهٔ کلِ پروژه روی هر ثبت، فقط شاخهٔ تغییرکرده را می‌پیماید.
 * معنایش عیناً همان رشته‌هاست: ترتیبِ کلیدها مهم است، کلیدِ undefined/تابع نادیده است، در آرایه undefined = null، NaN/Infinity = null.
 * هر چیزِ غیرِ ساده (Date، Map، کلاس، toJSON) برای احتیاط به خودِ JSON.stringify می‌افتد.
 */
export function jsonEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  const ta = typeof a;
  const tb = typeof b;
  if (ta === "number" && tb === "number") {
    // NaN و ±Infinity در JSON «null» می‌شوند؛ ‎0 و ‎-0 هر دو «0»
    const fa = Number.isFinite(a as number);
    const fb = Number.isFinite(b as number);
    return !fa && !fb ? true : fa && fb && (a as number) === (b as number);
  }
  if (ta !== "object" || tb !== "object" || a === null || b === null) {
    // یکی از دو شیء/null نیست: رشته، بولین، عدد، undefined، تابع … یا شیءِ دارای toJSON در برابرِ ساده ⇒ راهِ امن
    if (ta === "object" || tb === "object") return stringifyEqual(a, b);
    if (ta === "number" || tb === "number") return false;
    return dropped(a) && dropped(b);
  }
  const oa = a as object;
  const ob = b as object;
  if (!isPlain(oa) || !isPlain(ob)) return stringifyEqual(a, b);
  const aa = Array.isArray(oa);
  if (aa !== Array.isArray(ob)) return false;
  if (aa) {
    const xa = oa as unknown[];
    const xb = ob as unknown[];
    if (xa.length !== xb.length) return false;
    for (let i = 0; i < xa.length; i++) {
      if (!jsonEqual(dropped(xa[i]) ? null : xa[i], dropped(xb[i]) ? null : xb[i])) return false;
    }
    return true;
  }
  const ka = jsonKeys(oa as Record<string, unknown>);
  const kb = jsonKeys(ob as Record<string, unknown>);
  if (ka.length !== kb.length) return false;
  for (let i = 0; i < ka.length; i++) if (ka[i] !== kb[i]) return false;
  for (const k of ka) if (!jsonEqual((oa as Record<string, unknown>)[k], (ob as Record<string, unknown>)[k])) return false;
  return true;
}

/**
 * تاریخچهٔ برگشت/جلو (Undo/Redo) با «پیش‌نمایشِ زنده»:
 *   live(fn)       — هنگامِ کشیدنِ لغزنده؛ فقط پیش‌نمایش، در تاریخچه نمی‌رود
 *   end(label)     — رها شد ⇐ همان حالتِ زنده یک گام در تاریخچه می‌شود
 *   apply(label,fn)— کارِ یک‌باره (کلیک روی دکمه) ⇐ مستقیم گام
 * حداکثر ۱۰۰ گام. `jump(i)` به هر گام می‌پرد؛ گامِ بعدی گام‌های جلوتر را دور می‌ریزد (مثلِ فتوشاپ).
 */
export function useHistory<T>(initial: T, limit = 100) {
  const [entries, setEntries] = useState<HistoryEntry<T>[]>([{ label: "اصل", state: initial }]);
  const [index, setIndex] = useState(0);
  const [draft, setDraft] = useState<T | null>(null);
  const ref = useRef({ entries, index, draft });
  ref.current = { entries, index, draft };

  const current = draft ?? entries[index].state;

  const push = useCallback(
    (label: string, next: T) => {
      const { entries: es, index: i } = ref.current;
      countRender("historyPush");
      // ۱۴۰۵/۰۸/۲۳: به‌جای دو JSON.stringify از کلِ پروژه، مقایسهٔ ساختاریِ با میان‌برِ ===؛ نتیجه عیناً همان است
      if (jsonEqual(next, es[i].state)) {
        setDraft(null);
        return;
      }
      const base = es.slice(0, i + 1);
      base.push({ label, state: next });
      const trimmed = base.length > limit ? base.slice(base.length - limit) : base;
      ref.current = { entries: trimmed, index: trimmed.length - 1, draft: null };
      setEntries(trimmed);
      setIndex(trimmed.length - 1);
      setDraft(null);
    },
    [limit],
  );

  const live = useCallback((fn: (s: T) => T) => {
    const base = ref.current.draft ?? ref.current.entries[ref.current.index].state;
    const next = fn(base);
    ref.current.draft = next;
    setDraft(next);
  }, []);

  const end = useCallback(
    (label: string) => {
      if (ref.current.draft !== null) push(label, ref.current.draft);
    },
    [push],
  );

  const apply = useCallback(
    (label: string, fn: (s: T) => T) => {
      const base = ref.current.draft ?? ref.current.entries[ref.current.index].state;
      push(label, fn(base));
    },
    [push],
  );

  const jump = useCallback((i: number) => {
    const { entries: es } = ref.current;
    const at = Math.max(0, Math.min(es.length - 1, i));
    ref.current.index = at;
    ref.current.draft = null;
    setIndex(at);
    setDraft(null);
  }, []);

  // ۱۴۰۵/۰۸/۲۳: undo/redo/reset هویتِ ثابت دارند (فرزندانِ React.memo با هر رندر دوباره ساخته نشوند)؛ رفتارشان عوض نشده
  const undo = useCallback(() => jump(ref.current.index - 1), [jump]);
  const redo = useCallback(() => jump(ref.current.index + 1), [jump]);
  const reset = useCallback((s: T) => {
    ref.current = { entries: [{ label: "اصل", state: s }], index: 0, draft: null };
    setEntries(ref.current.entries);
    setIndex(0);
    setDraft(null);
  }, []);

  return {
    state: current,
    entries,
    index,
    canUndo: index > 0,
    canRedo: index < entries.length - 1,
    live,
    end,
    apply,
    jump,
    undo,
    redo,
    reset,
  };
}
