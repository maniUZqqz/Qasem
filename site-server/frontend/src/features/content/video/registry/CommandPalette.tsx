import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { Keymap, prettyCombo } from "./keymap";
import { loadRecent, searchFeatures } from "./search";
import { FeatureDef, MENUS, WorkspaceApi } from "./types";
import "./registry.css";

type Props = {
  features: FeatureDef[];
  km: Keymap;
  getApi: () => WorkspaceApi;
  run: (f: FeatureDef) => void;
  onClose: () => void;
};

/** پیشنهادِ شروع، وقتی هنوز چیزی تایپ نشده و «اخیراً»ی نیست */
const SUGGEST = [
  "edit.split", "clip.speed", "clip.reverse", "clip.crop-reframe", "color.curves", "color.scopes", "audio.eq", "audio.remove-silence",
  "gfx.captions", "file.export-presets", "edit.history", "win.shortcuts-edit",
];

const crumb = (f: FeatureDef) => `${MENUS.find((m) => m.id === f.menu)?.title ?? ""} › ${f.group}`;

/** جستجوی ابزار (Ctrl+K): هر ویژگی با نامِ فارسی، انگلیسی یا مترادف پیدا و اجرا می‌شود؛ میان‌برش کنارش نوشته شده است. */
export default function CommandPalette({ features, km, getApi, run, onClose }: Props) {
  const [q, setQ] = useState("");
  const [idx, setIdx] = useState(0);
  const [msg, setMsg] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const api = getApi();

  const rows = useMemo(() => {
    const byId = new Map(features.map((f) => [f.id, f]));
    if (!q.trim()) {
      const rec = loadRecent().map((id) => byId.get(id)).filter((f): f is FeatureDef => !!f);
      const sug = SUGGEST.map((id) => byId.get(id)).filter((f): f is FeatureDef => !!f && !rec.includes(f));
      return [
        ...rec.map((f) => ({ f, tag: "اخیراً" })),
        ...sug.map((f) => ({ f, tag: "پیشنهاد" })),
      ];
    }
    return searchFeatures(q, features, 40).map((h) => ({ f: h.feature, tag: "" }));
  }, [q, features]);

  useEffect(() => {
    input.current?.focus();
  }, []);
  useEffect(() => {
    setIdx(0);
    setMsg(null);
  }, [q]);
  useEffect(() => {
    list.current?.querySelector<HTMLElement>(`[data-i="${idx}"]`)?.scrollIntoView({ block: "nearest" });
  }, [idx]);

  const choose = (f: FeatureDef | undefined) => {
    if (!f) return;
    const reason = f.when ? f.when(api) : null;
    if (reason) {
      setMsg(`«${f.title}» الان ممکن نیست: ${reason}`);
      return;
    }
    onClose();
    window.setTimeout(() => run(f), 0);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    e.stopPropagation();
    if (e.key === "Escape" || ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k")) {
      e.preventDefault();
      onClose();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setIdx((i) => Math.min(rows.length - 1, i + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setIdx((i) => Math.max(0, i - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      choose(rows[idx]?.f);
    }
  };

  return createPortal(
    <div className="rg-back" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="rg-pal" role="dialog" aria-modal="true" aria-label="جستجوی ابزار" dir="rtl" data-testid="palette" onKeyDown={onKeyDown} onKeyUp={(e) => e.stopPropagation()}>
        <input
          ref={input} className="rg-pal-in" value={q} onChange={(e) => setQ(e.target.value)} placeholder="چه کاری می‌خواهید بکنید؟ مثلاً: سرعت، برش، رنگ، زیرنویس، EQ، crop…"
          role="combobox" aria-expanded aria-controls="rg-pal-list" aria-activedescendant={rows[idx] ? `rg-opt-${idx}` : undefined} aria-label="جستجوی ابزار" data-testid="palette-input"
        />
        <ul id="rg-pal-list" ref={list} className="rg-pal-list" role="listbox">
          {rows.length === 0 && (
            <li className="rg-pal-empty" data-testid="palette-empty">
              چیزی پیدا نشد. با کلمهٔ دیگری امتحان کنید (فارسی یا انگلیسی). همهٔ ابزارها در «منوی کامل» هم هستند.
            </li>
          )}
          {rows.map(({ f, tag }, i) => {
            const reason = f.when ? f.when(api) : null;
            const combo = km.effective(f.id);
            const showTag = tag && (i === 0 || rows[i - 1].tag !== tag);
            return (
              <li key={f.id} role="presentation">
                {showTag && <div className="rg-pal-tag">{tag}</div>}
                <div
                  id={`rg-opt-${i}`} data-i={i} data-feature={f.id} role="option" aria-selected={i === idx} aria-disabled={reason ? true : undefined}
                  className={`rg-pal-row ${i === idx ? "is-sel" : ""} ${reason ? "is-off" : ""}`}
                  onMouseMove={() => idx !== i && setIdx(i)} onClick={() => choose(f)}
                >
                  <span className="rg-pal-main">
                    <b>{f.title}</b>
                    <small>{reason ? `الان ممکن نیست — ${reason}` : f.tip}</small>
                  </span>
                  <span className="rg-pal-side">
                    <em>{crumb(f)}</em>
                    {combo && <kbd dir="ltr">{prettyCombo(combo)}</kbd>}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
        {msg && <div className="rg-pal-msg" role="status" data-testid="palette-msg">{msg}</div>}
        <div className="rg-pal-foot"><span>↑↓ حرکت</span><span>Enter اجرا</span><span>Esc بستن</span></div>
      </div>
    </div>,
    document.body,
  );
}
