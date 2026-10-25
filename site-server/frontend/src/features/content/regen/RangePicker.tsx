import { useRef } from "react";

/**
 * خطِ زمانیِ انتخابِ بازه روی نوارِ کوچک‌نمایی‌ها. همیشه چپ‌به‌راست (مثلِ نوارِ پخشِ خودِ ویدیو).
 * دو دسته (شروع/پایان) کشیدنی‌اند، بدنهٔ بازه جابه‌جا می‌شود، کلیک روی نوار جای پخش را عوض می‌کند،
 * و هر دسته با کلیدهای ← → یک فریم (با Shift یک ثانیه) جلو/عقب می‌رود.
 */
export default function RangePicker({
  frames,
  fps,
  stripUrl,
  start,
  end,
  playhead,
  maxCount,
  onChange,
  onSeek,
}: {
  frames: number;
  fps: number;
  stripUrl: string | null;
  start: number;
  end: number;
  playhead: number;
  maxCount: number;
  onChange: (start: number, end: number) => void;
  onSeek: (frame: number) => void;
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
    drag.current = { mode, grab: frameAt(ev.clientX), s: start, e: end };
  }

  function move(ev: React.PointerEvent) {
    const d = drag.current;
    if (!d) return;
    const f = frameAt(ev.clientX);
    if (d.mode === "start") onChange(...clampRange(f, d.e, "start"));
    else if (d.mode === "end") onChange(...clampRange(d.s, f, "end"));
    else {
      const len = d.e - d.s;
      let s = d.s + (f - d.grab);
      s = Math.max(0, Math.min(last - len, s));
      onChange(...clampRange(s, s + len, "move"));
    }
  }

  function up() {
    drag.current = null;
  }

  function key(which: "start" | "end", ev: React.KeyboardEvent) {
    const step = ev.shiftKey ? Math.max(1, Math.round(fps)) : 1;
    let delta = 0;
    if (ev.key === "ArrowRight") delta = step;
    else if (ev.key === "ArrowLeft") delta = -step;
    else return;
    ev.preventDefault();
    if (which === "start") onChange(...clampRange(start + delta, end, "start"));
    else onChange(...clampRange(start, end + delta, "end"));
  }

  const handle = (which: "start" | "end") => (
    <div
      role="slider"
      tabIndex={0}
      aria-label={which === "start" ? "شروعِ بازه" : "پایانِ بازه"}
      aria-valuemin={0}
      aria-valuemax={last}
      aria-valuenow={which === "start" ? start : end}
      data-testid={`regen-handle-${which}`}
      onPointerDown={(ev) => down(which, ev)}
      onPointerMove={move}
      onPointerUp={up}
      onKeyDown={(ev) => key(which, ev)}
      className="absolute top-0 bottom-0 z-20 flex w-4 cursor-ew-resize items-center justify-center"
      style={{
        left: which === "start" ? `calc(${pct(start)} - 8px)` : `calc(${pct(end + 1)} - 8px)`,
        touchAction: "none",
      }}
    >
      <span
        className="block h-full w-1.5 rounded"
        style={{ background: "var(--brand)", boxShadow: "0 0 0 2px rgb(0 0 0 / .35)" }}
      />
    </div>
  );

  return (
    <div dir="ltr" className="select-none">
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
    </div>
  );
}
