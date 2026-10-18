import { useLayoutEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { pUrl } from "./api";
import type { ErModel } from "./types";

/**
 * نمودارِ مدل‌ها و رابطه‌ها — هر اپ یک ستون، هر مدل یک جدول، رابطه‌ها با خطِ منحنی.
 * خط‌ها از روی موقعیتِ واقعیِ ردیف‌ها کشیده می‌شوند (نه حدس)، پس بعد از هر
 * تغییرِ اندازه دوباره محاسبه می‌شوند. چند-به-چند خط‌چین است.
 */

const REL: Record<string, string> = { ForeignKey: "FK", OneToOneField: "1:1", ManyToManyField: "M2M" };

type Path = { d: string; dashed: boolean };

function pos(el: Element, host: HTMLElement) {
  const r = el.getBoundingClientRect();
  const h = host.getBoundingClientRect();
  return { l: r.left - h.left + host.scrollLeft, t: r.top - h.top + host.scrollTop, w: r.width, h: r.height };
}

export default function ErDiagram({ models, slug }: { models: ErModel[]; slug: string }) {
  const host = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const [paths, setPaths] = useState<Path[]>([]);
  const [size, setSize] = useState<{ w: number; h: number }>({ w: 0, h: 0 });

  const byApp = new Map<string, ErModel[]>();
  for (const m of models) {
    const list = byApp.get(m.app) ?? [];
    list.push(m);
    byApp.set(m.app, list);
  }

  useLayoutEffect(() => {
    const el = host.current;
    if (!el) return;
    let pending = 0;
    const draw = () => {
      const out: Path[] = [];
      el.querySelectorAll<HTMLElement>("[data-to]").forEach((row) => {
        const target = el.querySelector<HTMLElement>(`[data-model="${row.dataset.to}"] .er-h`);
        const box = row.closest<HTMLElement>("[data-model]");
        if (!target || !box) return;
        const a = pos(row, el);
        const b = pos(target, el);
        const bx = pos(box, el);
        const ay = a.t + a.h / 2;
        const by = b.t + b.h / 2;
        let d: string;
        if (box === target.closest("[data-model]")) {
          const x = bx.l + bx.w;
          d = `M${x} ${ay} C${x + 40} ${ay},${x + 40} ${by},${x} ${by}`;
        } else if (Math.abs(b.l - bx.l) < 4) {
          // همان ستون: از کنارِ جدول‌ها دور بزن، از رویشان رد نشو
          const x0 = bx.l;
          const bend = 34 + Math.min(60, Math.abs(by - ay) / 8);
          d = `M${x0} ${ay} C${x0 - bend} ${ay},${x0 - bend} ${by},${b.l} ${by}`;
        } else {
          const right = b.l > bx.l;
          const ax = right ? bx.l + bx.w : bx.l;
          const tx = right ? b.l : b.l + b.w;
          const dx = Math.max(40, Math.abs(tx - ax) / 2) * (right ? 1 : -1);
          d = `M${ax} ${ay} C${ax + dx} ${ay},${tx - dx} ${by},${tx} ${by}`;
        }
        out.push({ d, dashed: row.dataset.kind === "ManyToManyField" });
      });
      setPaths(out);
      setSize({ w: el.scrollWidth, h: el.scrollHeight });
    };
    const later = () => {
      window.clearTimeout(pending);
      pending = window.setTimeout(draw, 60);
    };
    later();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(later) : null;
    ro?.observe(el);
    window.addEventListener("resize", later);
    if (document.fonts?.ready) document.fonts.ready.then(later).catch(() => undefined);
    return () => {
      window.clearTimeout(pending);
      ro?.disconnect();
      window.removeEventListener("resize", later);
    };
  }, [models]);

  return (
    <div ref={host} className="relative overflow-auto p-2" style={{ minHeight: 160 }}>
      <div className="flex items-start gap-10">
        {[...byApp.entries()].map(([app, list]) => (
          <div key={app} className="flex min-w-[220px] flex-col gap-5">
            <div dir="ltr" className="font-mono text-xs font-bold" style={{ color: "var(--text-3)", textAlign: "left" }}>
              apps/{app}
            </div>
            {list.map((m) => (
              <div
                key={m.id}
                data-model={m.id}
                role="button"
                tabIndex={0}
                onClick={() => navigate(pUrl(slug, `model/${m.id}`))}
                onKeyDown={(e) => e.key === "Enter" && navigate(pUrl(slug, `model/${m.id}`))}
                className="u-card u-card-hover cursor-pointer text-xs"
                style={{ opacity: m.managed ? 1 : 0.75, position: "relative", zIndex: 1 }}
              >
                <div
                  className="er-h flex items-baseline justify-between gap-2 px-3 py-2 font-bold"
                  style={{ background: "var(--brand-soft)", color: "var(--text)" }}
                >
                  <span dir="ltr" className="font-mono">
                    {m.name}
                  </span>
                  <small className="font-normal" style={{ color: "var(--text-3)" }}>
                    {m.fa}
                  </small>
                </div>
                <div className="flex justify-between gap-3 px-3 py-1" style={{ color: "var(--text-3)" }}>
                  <span dir="ltr" className="font-mono">
                    id
                  </span>
                  <span>PK</span>
                </div>
                {m.fields.map((f) => {
                  const rel = REL[f.type];
                  return (
                    <div
                      key={f.name}
                      data-to={f.to ?? undefined}
                      data-kind={f.to ? f.type : undefined}
                      className="flex justify-between gap-3 px-3 py-1"
                      style={{ borderTop: "1px solid var(--line)", color: rel ? "var(--brand-strong)" : "var(--text-2)" }}
                    >
                      <span dir="ltr" className="font-mono">
                        {f.name}
                      </span>
                      <span dir="ltr" className="font-mono" style={{ color: "var(--text-3)" }}>
                        {rel ? `${rel}${f.ref ? ` → ${f.ref.replace("settings.AUTH_USER_MODEL", "User")}` : ""}` : f.type.replace("Field", "")}
                      </span>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        ))}
      </div>
      <svg
        className="pointer-events-none absolute inset-0"
        width={size.w || "100%"}
        height={size.h || "100%"}
        style={{ overflow: "visible", zIndex: 2 }}
      >
        <defs>
          <marker id="studio-er-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0 0L10 5L0 10z" fill="#7c3aed" />
          </marker>
        </defs>
        {paths.map((p, i) => (
          <path
            key={i}
            d={p.d}
            fill="none"
            stroke="#7c3aed"
            strokeWidth={1.8}
            opacity={0.85}
            strokeDasharray={p.dashed ? "6 4" : undefined}
            markerEnd="url(#studio-er-arrow)"
          />
        ))}
      </svg>
    </div>
  );
}
