import { useRef } from "react";

import type { Waveform as Wave } from "./api";
import Waveform from "./Waveform";

/**
 * خطِ زمانیِ انتخابِ بازه روی نوارِ کوچک‌نمایی‌ها و شکلِ موجِ صدا. همیشه چپ‌به‌راست (مثلِ نوارِ پخشِ خودِ ویدیو،
 * و مثلِ کلیدهای ← → که در این صفحه «عقب/جلو» هستند). دو دسته (شروع/پایان) کشیدنی‌اند و دستهٔ «فعال» پررنگ است
 * (کلیک روی دسته فعالش می‌کند؛ کلیدها را صفحه می‌گیرد)؛ بدنهٔ بازه جابه‌جا می‌شود و کلیک روی نوار جای پخش را عوض
 * می‌کند.
 */
export default function RangePicker({
  frames,
  fps,
  stripUrl,
  start,
  end,
  playhead,
  maxCount,
  active,
  wave,
  onChange,
  onSeek,
  onActivate,
}: {
  frames: number;
  fps: number;
  stripUrl: string | null;
  start: number;
  end: number;
  playhead: number;
  maxCount: number;
  active: "start" | "end";
  /** شکلِ موجِ کلِ ویدیو (null = در حالِ آمدن؛ peaks خالی = صدا ندارد) */
  wave: Wave | null;
  onChange: (start: number, end: number) => void;
  onSeek: (frame: number) => void;
  onActivate: (which: "start" | "end") => void;
}) {
  const bar = useRef<HTMLDivElement>(null);
  const drag = useRef<{ mode: "start" | "end" | "move"; grab: number; s: number; e: number } | null>(null);
  const last = frames - 1;
  const pct = (f: number) => `${(f / frames) * 100}%`;

  function frameAt(clientX: number): number {
    const r = bar.current?.getBoundingClientRect();
    if (!r || r.width <= 0) return 0;
    const x = (clientX - r.left) / r.width;
    return Math.max(0, Math.min(last, Math.round(x * frames - 0.5)));
  }

  function clampRange(s: number, e: number, moving: "start" | "end" | "move"): [number, number] {
    s = Math.max(0, Math.min(last, s));
    e = Math.max(0, Math.min(last, e));
    if (moving === "start" && s > e) s = e;
    if (moving === "end" && e < s) e = s;
    if (e - s + 1 > maxCount) {
      if (moving === "start") s = e - maxCount + 1;
      else e = s + maxCount - 1;
    }
    // کلِ ویدیو نه: دستِ کم یک سر باید بماند
    if (s === 0 && e === last) {
      if (moving === "start") s = 1;
      else e = last - 1;
    }
    return [s, e];
  }

  function down(mode: "start" | "end" | "move", ev: React.PointerEvent) {
    ev.stopPropagation();
    (ev.target as HTMLElement).setPointerCapture(ev.pointerId);
    if (mode !== "move") onActivate(mode);
    drag.current = { mode, grab: frameAt(ev.clientX), s: start, e: end };
  }

  function move(ev: React.PointerEvent) {
    const d = drag.current;
    if (!d) return;
    const f = frameAt(ev.clientX);
    if (d.mode === "start") {
      const [s, e] = clampRange(f, d.e, "start");
      onChange(s, e);
      onSeek(s);
    } else if (d.mode === "end") {
      const [s, e] = clampRange(d.s, f, "end");
      onChange(s, e);
      onSeek(e);
    } else {
      const len = d.e - d.s;
      let s = d.s + (f - d.grab);
      s = Math.max(0, Math.min(last - len, s));
      onChange(...clampRange(s, s + len, "move"));
    }
  }

  function up() {
    drag.current = null;
  }

  const handle = (which: "start" | "end") => {
    const on = active === which;
    return (
      <div
        role="slider"
        tabIndex={0}
        aria-label={which === "start" ? "شروعِ بازه" : "پایانِ بازه"}
        aria-valuemin={0}
        aria-valuemax={last}
        aria-valuenow={which === "start" ? start : end}
        data-testid={`regen-handle-${which}`}
        data-active={on ? "1" : "0"}
        onPointerDown={(ev) => down(which, ev)}
        onPointerMove={move}
        onPointerUp={up}
        onFocus={() => onActivate(which)}
        className="absolute top-0 bottom-0 z-20 flex w-4 cursor-ew-resize items-center justify-center"
        style={{
          left: which === "start" ? `calc(${pct(start)} - 8px)` : `calc(${pct(end + 1)} - 8px)`,
          touchAction: "none",
        }}
      >
        <span
          className="block h-full rounded"
          style={{
            width: on ? 8 : 5,
            background: on ? "#fff" : "var(--brand)",
            boxShadow: on ? "0 0 0 2px var(--brand), 0 0 8px var(--brand)" : "0 0 0 2px rgb(0 0 0 / .35)",
          }}
        />
      </div>
    );
  };

  return (
    <div dir="ltr" className="select-none space-y-1">
      <div
        ref={bar}
        data-testid="regen-timeline"
        className="relative h-16 w-full overflow-hidden rounded-lg"
        style={{
          background: stripUrl ? `url(${stripUrl}) 0 0 / 100% 100% no-repeat, #000` : "var(--surface-2)",
          border: "1px solid var(--line)",
          touchAction: "none",
        }}
        onPointerDown={(ev) => onSeek(frameAt(ev.clientX))}
      >
        <div className="absolute inset-y-0 left-0" style={{ width: pct(start), background: "rgb(0 0 0 / .55)" }} />
        <div
          className="absolute inset-y-0 right-0"
          style={{ width: `calc(100% - ${pct(end + 1)})`, background: "rgb(0 0 0 / .55)" }}
        />
        <div
          className="absolute inset-y-0 z-10 cursor-grab"
          style={{
            left: pct(start),
            width: pct(end - start + 1),
            border: "2px solid var(--brand)",
            background: "rgb(139 123 255 / .18)",
            touchAction: "none",
          }}
          onPointerDown={(ev) => down("move", ev)}
          onPointerMove={move}
          onPointerUp={up}
        />
        {handle("start")}
        {handle("end")}
        <div
          className="pointer-events-none absolute inset-y-0 z-30 w-0.5"
          style={{ left: pct(playhead + 0.5), background: "#fff", boxShadow: "0 0 4px #000" }}
        />
      </div>
      <Waveform
        peaks={wave ? wave.peaks : null}
        from={wave?.from ?? 0}
        to={wave && wave.to > wave.from ? wave.to : frames / fps}
        selStart={start / fps}
        selEnd={(end + 1) / fps}
        playhead={(playhead + 0.5) / fps}
        height={36}
        testid="regen-wave"
        onSeek={(t) => onSeek(Math.max(0, Math.min(last, Math.floor(t * fps))))}
      />
    </div>
  );
}
