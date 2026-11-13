import { memo, useEffect, useState } from "react";

import { fa } from "../../../../components/ui";
import { countRender } from "../../../../hooks/perfCount";
import { Project, clipEnd, clipLength, findClip, framesBetween, nudgeEdge, timecode } from "./model";

/** صفحهٔ لمسی/باریک؟ (انگشت یا عرضِ کمتر از ۷۰۰ پیکسل) */
export function useTouchLayout(): boolean {
  const get = () => {
    if (typeof window === "undefined" || !window.matchMedia) return false;
    return window.matchMedia("(pointer: coarse)").matches || window.matchMedia("(max-width: 699px)").matches;
  };
  const [on, setOn] = useState(get);
  useEffect(() => {
    if (!window.matchMedia) return;
    const qs = [window.matchMedia("(pointer: coarse)"), window.matchMedia("(max-width: 699px)")];
    const h = () => setOn(get());
    qs.forEach((q) => q.addEventListener("change", h));
    return () => qs.forEach((q) => q.removeEventListener("change", h));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return on;
}

const STEPS = [-10, -1, 1, 10];

type Props = {
  project: Project;
  selection: string[];
  fps: number;
  onApply: (label: string, fn: (p: Project) => Project) => void;
  onSeek: (t: number) => void;
  onSplit: () => void;
  onRemove: () => void;
};

/**
 * نوارِ کوتاه‌کردنِ لمسی: فقط وقتی قطعه‌ای انتخاب است و صفحه لمسی/باریک است.
 * دکمه‌های بزرگ برای جابه‌جاییِ لبهٔ شروع، لبهٔ پایان یا جای قطعه به اندازهٔ ۱۰/۱ فریم؛ قطعه‌های پیوندی هم می‌روند.
 */
function TrimBarBase({ project, selection, fps, onApply, onSeek, onSplit, onRemove }: Props) {
  countRender("TrimBar");
  const touch = useTouchLayout();
  const primary = selection[selection.length - 1] ?? null;
  const f = findClip(project, primary);
  if (!touch || !f) return null;
  const c = f.clip;
  const rate = fps > 0 ? fps : 30;
  const len = clipLength(c);

  const run = (side: "pos" | "l" | "r", frames: number) => {
    const label = side === "l" ? "کوتاه‌کردنِ شروع" : side === "r" ? "کوتاه‌کردنِ پایان" : "جابه‌جاییِ فریمی";
    const fn = (p: Project) => nudgeEdge(p, selection, side, frames, rate);
    const after = findClip(fn(project), primary);
    onApply(label, fn);
    if (after) onSeek(side === "r" ? Math.max(after.clip.at, clipEnd(after.clip) - 1 / rate) : after.clip.at);
  };

  const row = (side: "pos" | "l" | "r", title: string, hintMinus: string, hintPlus: string) => (
    <div className="tb-row" role="group" aria-label={title}>
      <span className="tb-title">{title}</span>
      <div className="tb-btns" dir="ltr">
        {STEPS.map((n) => (
          <button
            key={n} type="button" className="ws-btn tb-btn" data-testid={`tb-${side}-${n}`}
            title={`${title}: ${fa(Math.abs(n))} فریم ${n < 0 ? hintMinus : hintPlus}`}
            onClick={() => run(side, n)}
          >
            {n < 0 ? "−" : "+"}{fa(Math.abs(n))}
          </button>
        ))}
      </div>
    </div>
  );

  return (
    <div className="tb-root" dir="rtl" data-testid="trim-bar">
      <div className="tb-info" dir="rtl">
        <b>{c.type === "text" ? c.text.slice(0, 18) : c.label.slice(0, 18)}</b>
        <span>شروع {timecode(c.at, rate)}</span>
        <span>پایان {timecode(clipEnd(c), rate)}</span>
        <span>{fa(framesBetween(0, len, rate))} فریم</span>
      </div>
      {row("l", "لبهٔ شروع", "زودتر (به چپ)", "دیرتر (به راست)")}
      {row("r", "لبهٔ پایان", "زودتر (کوتاه‌تر)", "دیرتر (بلندتر)")}
      {row("pos", "جای قطعه", "به چپ", "به راست")}
      <div className="tb-row tb-actions">
        <button type="button" className="ws-btn tb-btn wide" data-testid="tb-split" title="قطعه در جای سرِ پخش دو تکه شود" onClick={onSplit}>✂ تقسیم در سرِ پخش</button>
        <button type="button" className="ws-btn tb-btn wide" data-testid="tb-ripple-delete" title="قطعهٔ انتخاب‌شده حذف شود و جایش بسته شود" onClick={onRemove}>حذفِ بی‌فاصله</button>
      </div>
    </div>
  );
}

export default memo(TrimBarBase);
