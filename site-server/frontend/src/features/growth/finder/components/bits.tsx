import type { ReactNode } from "react";

import { Badge, fa } from "../../../../components/ui";
import type { Reason } from "../types";

export const LEVEL_LABEL: Record<string, string> = { high: "مناسب", medium: "متوسط", low: "کم" };
export const levelTone = (level: string) => (level === "high" ? "ok" : level === "medium" ? "info" : "neutral") as "ok" | "info" | "neutral";

/** The fit score with its level; the title shows every reason (the full list is in the lead panel). */
export function ScoreBadge({ score, level, reasons }: { score: number; level: string; reasons?: Reason[] }) {
  const title = reasons?.length ? reasons.map((r) => `${r.points > 0 ? "+" : ""}${fa(r.points)}  ${r.text}`).join("\n") : undefined;
  return (
    <span title={title} data-testid="score-badge">
      <Badge tone={levelTone(level)}>
        {fa(score)} · {LEVEL_LABEL[level] ?? level}
      </Badge>
    </span>
  );
}

export function ReasonList({ reasons }: { reasons: Reason[] }) {
  return (
    <ul className="space-y-1 text-sm" style={{ color: "var(--text-2)" }} data-testid="reason-list">
      {reasons.map((r, i) => (
        <li key={i} className="flex items-start gap-2">
          <span className="u-num shrink-0 rounded-md px-1.5 text-xs font-bold" style={{ background: r.points >= 0 ? "var(--ok-soft)" : "var(--bad-soft)", color: r.points >= 0 ? "var(--ok)" : "var(--bad)" }}>
            {r.points > 0 ? "+" : ""}
            {fa(r.points)}
          </span>
          <span>{r.text}</span>
        </li>
      ))}
    </ul>
  );
}

export function Meterbar({ value, tone = "var(--brand)" }: { value: number; tone?: string }) {
  return (
    <div className="u-meter" role="progressbar" aria-valuenow={Math.round(value)} aria-valuemin={0} aria-valuemax={100}>
      <span style={{ width: `${Math.max(2, Math.min(100, value))}%`, background: tone }} />
    </div>
  );
}

export function Section({ title, hint, action, children }: { title: string; hint?: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-base font-bold" style={{ color: "var(--text)" }}>
            {title}
          </h2>
          {hint && (
            <p className="text-xs" style={{ color: "var(--text-3)" }}>
              {hint}
            </p>
          )}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export const SOURCE_LABEL: Record<string, string> = {
  osm: "نقشه",
  search: "جست‌وجوی وب",
  directory: "فهرست",
  website: "سایت",
  instagram: "اینستاگرام",
  neshan: "نشان",
};

export const TASK_STATUS_LABEL: Record<string, string> = { pending: "در انتظار", running: "در حال اجرا", done: "انجام شد", failed: "ناموفق", skipped: "ردشد", waiting_node: "منتظرِ سرورِ پردازش" };

export function splitList(text: string): string[] {
  return Array.from(new Set(text.split(/[\n,،;؛]+/).map((s) => s.trim()).filter(Boolean)));
}

export function joinList(values: string[] | undefined): string {
  return (values ?? []).join("، ");
}

export function mapsLink(lat: number, lon: number): string {
  return `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=17/${lat}/${lon}`;
}
