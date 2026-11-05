import { useEffect, useRef, useState } from "react";

import { PanelDef, WorkspaceApi } from "./types";
import "./registry.css";

type Props = {
  panels: PanelDef[];
  active: { id: string; props?: Record<string, unknown> } | null;
  api: WorkspaceApi;
  onClose: () => void;
};

/** پنجرهٔ شناورِ ناقفل (تاریخچه، ویرایشگرِ میان‌برها، …). با موس از نوارِ عنوانش جابه‌جا می‌شود؛ کار با تایم‌لاین را نمی‌بندد. */
export default function PanelHost({ panels, active, api, onClose }: Props) {
  const def = active ? panels.find((p) => p.id === active.id) : null;
  const [off, setOff] = useState({ x: 0, y: 0 });
  const drag = useRef<{ px: number; py: number; x: number; y: number } | null>(null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setOff({ x: 0, y: 0 });
    box.current?.focus();
  }, [active?.id]);

  if (!active || !def) return null;
  const C = def.Component;
  return (
    <div
      ref={box} className={`rg-panel rg-panel-${def.size ?? "md"}`} role="dialog" aria-label={def.title} dir="rtl" tabIndex={-1} data-testid={`panel-${def.id}`}
      style={{ transform: `translate(${off.x}px, ${off.y}px)` }}
      onKeyDown={(e) => {
        e.stopPropagation();
        if (e.key === "Escape") onClose();
      }}
      onKeyUp={(e) => e.stopPropagation()}
    >
      <div
        className="rg-panel-head"
        onPointerDown={(e) => {
          if ((e.target as HTMLElement).closest("button")) return;
          drag.current = { px: e.clientX, py: e.clientY, x: off.x, y: off.y };
          (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
        }}
        onPointerMove={(e) => {
          const d = drag.current;
          if (d) setOff({ x: d.x + e.clientX - d.px, y: d.y + e.clientY - d.py });
        }}
        onPointerUp={() => { drag.current = null; }}
      >
        <b>{def.title}</b>
        <button type="button" className="ws-btn" onClick={onClose} aria-label="بستن" title="بستن (Esc)" data-testid="panel-close">×</button>
      </div>
      <div className="rg-panel-body">
        <C api={api} props={active.props} onClose={onClose} />
      </div>
    </div>
  );
}
