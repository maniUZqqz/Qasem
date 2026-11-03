import { useCallback, useRef, useState } from "react";

export type HistoryEntry<T> = { label: string; state: T };

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
      if (JSON.stringify(next) === JSON.stringify(es[i].state)) {
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
    undo: () => jump(ref.current.index - 1),
    redo: () => jump(ref.current.index + 1),
    reset: (s: T) => {
      ref.current = { entries: [{ label: "اصل", state: s }], index: 0, draft: null };
      setEntries(ref.current.entries);
      setIndex(0);
      setDraft(null);
    },
  };
}
