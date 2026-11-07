import { useMemo, useState } from "react";

import { replaceSource } from "../manual/r4ops";
import type { PanelProps } from "./types";

/** جایگزینی فیلمِ قطعهٔ انتخاب‌شده با رسانهٔ دیگر (هم‌نوع)؛ رنگ، حرکت، افکت و گذار می‌ماند. */
export default function ReplacePanel({ api, onClose }: PanelProps) {
  const sel = api.selected && api.selected.clip.type === "media" ? api.selected.clip : null;
  const items = useMemo(() => {
    const pool = sel?.kind === "audio" ? api.bin?.audio : sel?.kind === "image" ? api.bin?.images : api.bin?.videos;
    return (pool ?? []).filter((i) => i.ref !== sel?.ref);
  }, [api.bin, sel?.kind, sel?.ref]);
  const [ref, setRef] = useState("");
  if (!sel) return <p className="ws-hint" data-testid="replace-empty">اول یک ویدیو، عکس یا صدا را روی تایم‌لاین انتخاب کنید.</p>;
  const go = () => {
    const item = items.find((i) => i.ref === (ref || items[0]?.ref));
    if (!item) { api.notice("رسانهٔ دیگری از همین نوع نیست."); return; }
    const r = replaceSource(api.project, sel.id, item);
    if ("error" in r) { api.notice(r.error); return; }
    api.apply("جایگزینیِ فیلم", () => r.project);
    api.notice(r.note);
    onClose();
  };
  return (
    <div data-testid="replace-panel">
      <p className="ws-hint">قطعهٔ «{sel.label}» با رسانهٔ دیگری عوض می‌شود. جا، طول، رنگ، افکت، حرکت و گذارش همان می‌ماند.</p>
      <label className="ws-field">
        <span>رسانهٔ تازه</span>
        <select className="u-input" value={ref || items[0]?.ref || ""} onChange={(e) => setRef(e.target.value)} aria-label="رسانهٔ تازه" data-testid="replace-pick">
          {items.length === 0 && <option value="">رسانهٔ دیگری نیست</option>}
          {items.map((i) => <option key={i.ref} value={i.ref}>{i.title}</option>)}
        </select>
      </label>
      <button type="button" className="ws-btn primary" disabled={items.length === 0} onClick={go} data-testid="replace-go">جایگزین کن</button>
    </div>
  );
}
