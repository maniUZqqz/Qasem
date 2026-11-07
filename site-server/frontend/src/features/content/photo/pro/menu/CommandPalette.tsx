import { useEffect, useMemo, useRef, useState } from "react";
import { MENUS, searchCommands, type Command, type Host } from "./registry";
import "./menu.css";

const RECENT_KEY = "nm.photo.recent";
const readRecent = (): string[] => {
  try {
    const v = JSON.parse(window.localStorage.getItem(RECENT_KEY) || "[]");
    return Array.isArray(v) ? v.filter((x) => typeof x === "string").slice(0, 8) : [];
  } catch {
    return [];
  }
};
export const pushRecent = (id: string) => {
  try {
    const r = [id, ...readRecent().filter((x) => x !== id)].slice(0, 8);
    window.localStorage.setItem(RECENT_KEY, JSON.stringify(r));
  } catch {
    /* حافظهٔ مرورگر در دسترس نیست؛ فقط «اخیراً» ذخیره نمی‌شود */
  }
};

/** «جستجوی ابزار» (Ctrl+K): هر قابلیت را با نامِ فارسی، انگلیسی یا هم‌معنی پیدا کن و کلیدش را ببین. */
export default function CommandPalette({ cmds, host, run, onClose }: { cmds: Command[]; host: Host; run: (c: Command) => void; onClose: () => void }) {
  const [q, setQ] = useState("");
  const [cur, setCur] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    input.current?.focus();
  }, []);

  const hits = useMemo(() => {
    if (!q.trim()) {
      const rec = readRecent()
        .map((id) => cmds.find((c) => c.id === id))
        .filter(Boolean) as Command[];
      const base = rec.length ? rec : cmds.filter((c) => ["image.autoAll", "layer.text", "image.crop", "select.subject", "file.build", "filter.presets"].includes(c.id));
      return base.map((cmd) => ({ cmd, score: 0, reason: cmd.enabled?.(host) ?? null }));
    }
    return searchCommands(cmds, q, host).slice(0, 40);
  }, [q, cmds, host]);

  useEffect(() => setCur(0), [q]);
  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>(`[data-i="${cur}"]`)?.scrollIntoView({ block: "nearest" });
  }, [cur]);

  const go = (c: Command, reason: string | null) => {
    if (reason) return;
    onClose();
    run(c);
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      onClose();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setCur((i) => Math.min(hits.length - 1, i + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setCur((i) => Math.max(0, i - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const h = hits[cur];
      if (h) go(h.cmd, h.reason);
    }
  };

  return (
    <div className="mn-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()} data-testid="palette">
      <div className="mn-palette" role="dialog" aria-modal="true" aria-label="جستجوی ابزار" dir="rtl" onKeyDown={onKey}>
        <input
          ref={input}
          className="mn-q"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="هر کاری را بنویسید… مثلاً «محو»، «کراپ»، «blur»، «حذف پس‌زمینه»"
          aria-label="جستجوی ابزار"
          aria-controls="mn-results"
          role="combobox"
          aria-expanded="true"
          aria-activedescendant={hits[cur] ? `mn-r-${hits[cur].cmd.id}` : undefined}
          data-testid="palette-input"
          autoComplete="off"
          spellCheck={false}
        />
        <div className="mn-results" id="mn-results" role="listbox" ref={listRef}>
          {!q.trim() && <div className="mn-sub">{readRecent().length ? "اخیراً استفاده‌شده" : "شروعِ سریع"}</div>}
          {hits.map((h, i) => (
            <button
              key={h.cmd.id}
              id={`mn-r-${h.cmd.id}`}
              type="button"
              role="option"
              aria-selected={i === cur}
              aria-disabled={!!h.reason}
              data-i={i}
              data-cmd={h.cmd.id}
              className={`mn-res ${i === cur ? "is-cur" : ""}`}
              onMouseMove={() => setCur(i)}
              onClick={() => go(h.cmd, h.reason)}
              title={h.reason ?? h.cmd.tip}
            >
              <span className="mn-rt">
                <b>{h.cmd.title}</b>
                <small>{h.reason ?? h.cmd.tip}</small>
              </span>
              <span className="mn-rm">
                <i>{MENUS.find((m) => m.id === h.cmd.menu)?.title} ‹ {h.cmd.group}</i>
                {h.cmd.key && <kbd className="mn-k" dir="ltr">{h.cmd.key}</kbd>}
              </span>
            </button>
          ))}
          {q.trim() && hits.length === 0 && <div className="mn-empty" data-testid="palette-empty">چیزی پیدا نشد. با واژهٔ دیگری امتحان کنید؛ مثلاً «رنگ»، «لایه»، «برش».</div>}
        </div>
        <div className="mn-foot">
          <span>↑↓ حرکت</span>
          <span>Enter اجرا</span>
          <span>Esc بستن</span>
        </div>
      </div>
    </div>
  );
}
