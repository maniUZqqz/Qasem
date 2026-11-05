import { memo, useState } from "react";

import { fa } from "../../../../components/ui";
import { MediaClip, clipLength, snapFade, updateClip } from "./model";
import type { ClipActs } from "./VolumeLine";

type Props = {
  clip: MediaClip;
  w: number;
  h: number;
  px: number;
  /** دستگیره‌ها نشان داده شوند (قطعه انتخاب است، ابزارِ «انتخاب»، ترک قفل نیست) */
  handles: boolean;
  acts: ClipActs;
};

/**
 * محوِ ابتدا/انتهای قطعه (fade_in / fade_out، ثانیه): سایهٔ مایل داخلِ قطعه + دو دستگیرهٔ مثلثی در گوشه‌های بالا.
 * کشیدنِ افقی محو را در گام‌های ۰٫۰۵ ثانیه و تا min(۱۰، نصفِ طول) عوض می‌کند. برای قطعه‌های تصویر هم تصویر و صدا را با هم محو می‌کند.
 */
const FadeHandles = memo(function FadeHandles({ clip, w, h, px, handles, acts }: Props) {
  const [read, setRead] = useState<string | null>(null);
  const len = clipLength(clip);
  const fi = Math.max(0, Math.min(clip.fade_in || 0, len));
  const fo = Math.max(0, Math.min(clip.fade_out || 0, len));
  const wi = fi * px;
  const wo = fo * px;

  const down = (side: "in" | "out") => (e: React.PointerEvent) => {
    e.stopPropagation();
    if (e.button !== 0) return;
    acts.pick(clip.id);
    const orig = acts.base();
    const v0 = side === "in" ? fi : fo;
    const sx = e.clientX;
    let moved = false;
    const move = (ev: PointerEvent) => {
      if (!moved && Math.abs(ev.clientX - sx) < 2) return;
      moved = true;
      const v = snapFade(v0 + ((ev.clientX - sx) / px) * (side === "in" ? 1 : -1), len);
      acts.live(updateClip(orig, clip.id, side === "in" ? { fade_in: v } : { fade_out: v }));
      setRead(`${side === "in" ? "محوِ ابتدا" : "محوِ انتها"} ${v === 0 ? "ندارد" : `${fa(v.toFixed(2)).replace(".", "٫")} ثانیه`}`);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
      setRead(null);
      if (moved) acts.commit(side === "in" ? "محوِ ابتدا" : "محوِ انتها");
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
  };

  return (
    <>
      {(wi > 1 || wo > 1) && (
        <svg className="tl-fades" width={w} height={h} aria-hidden="true">
          {wi > 1 && (
            <>
              <polygon className="fd-shade" points={`0,0 ${wi},0 0,${h}`} />
              <line className="fd-line" x1={0} y1={h} x2={wi} y2={0} />
            </>
          )}
          {wo > 1 && (
            <>
              <polygon className="fd-shade" points={`${w},0 ${w - wo},0 ${w},${h}`} />
              <line className="fd-line" x1={w - wo} y1={0} x2={w} y2={h} />
            </>
          )}
        </svg>
      )}
      {handles && (
        <>
          <i className="fade-h in" data-testid="fade-in-handle" style={{ left: Math.min(wi, Math.max(0, w - 34)) }} title="محوِ ابتدا: به راست بکشید" onPointerDown={down("in")} />
          <i className="fade-h out" data-testid="fade-out-handle" style={{ right: Math.min(wo, Math.max(0, w - 34)) }} title="محوِ انتها: به چپ بکشید" onPointerDown={down("out")} />
        </>
      )}
      {read && <span className="vl-read fd-read" style={{ left: 28, top: 2 }} data-testid="fade-readout">{read}</span>}
    </>
  );
});

export default FadeHandles;
