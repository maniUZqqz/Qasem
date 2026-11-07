import { useEffect, useRef } from "react";

/** روی مانیتور یک نقطه انتخاب می‌شود (قطره‌چکان). onPick با مختصاتِ کسری از قاب (۰..۱) صدا زده می‌شود؛ Esc = انصراف. */
export default function PointOverlay({ hint, onPick, onCancel }: { hint: string; onPick: (fx: number, fy: number) => void; onCancel: () => void }) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onCancel();
      }
    };
    window.addEventListener("keydown", k, true);
    return () => window.removeEventListener("keydown", k, true);
  }, [onCancel]);
  return (
    <div
      ref={host} className="pk-layer pk-point" data-testid="point-overlay" role="application" aria-label={hint}
      onPointerDown={(e) => {
        const r = host.current!.getBoundingClientRect();
        onPick(Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)), Math.max(0, Math.min(1, (e.clientY - r.top) / r.height)));
      }}
    >
      <div className="pk-hint">{hint}</div>
    </div>
  );
}
