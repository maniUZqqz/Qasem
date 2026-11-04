import { fa } from "../../components/ui";
import type { SourceInfo } from "./types";

/** Persian (Jalali) date, e.g. «۱۴۰۵/۰۸/۱۴». */
export function faDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString("fa-IR");
}

/** Persian date and time, e.g. «۱۴۰۵/۰۸/۱۴، ۱۶:۳۰». */
export function faDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("fa-IR", { dateStyle: "short", timeStyle: "short" });
}

/** «۳ دقیقه پیش» ... up to «۲۰ روز پیش», then the date. */
export function faAgo(iso: string | null | undefined): string {
  if (!iso) return "—";
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (Number.isNaN(seconds)) return "—";
  if (seconds < 45) return "همین الان";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${fa(minutes)} دقیقه پیش`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${fa(hours)} ساعت پیش`;
  const days = Math.round(hours / 24);
  return days <= 20 ? `${fa(days)} روز پیش` : faDate(iso);
}

export const num = (n: number | string) => fa(Number(n).toLocaleString("en-US")).replace(/,/g, "٬");

export function bytes(n: number): string {
  if (n < 1024) return `${fa(n)} بایت`;
  if (n < 1024 * 1024) return `${fa(Math.round(n / 1024))} کیلوبایت`;
  return `${fa((n / (1024 * 1024)).toFixed(1))} مگابایت`;
}

export type Tone = "neutral" | "brand" | "ok" | "warn" | "bad" | "info";

/** The badge colour of a lead status. */
export function statusTone(status: string): Tone {
  switch (status) {
    case "won":
    case "interested":
    case "demo_scheduled":
    case "negotiation":
      return "ok";
    case "qualified":
    case "ready_for_outreach":
    case "replied":
      return "brand";
    case "contacted":
    case "researched":
      return "info";
    case "lost":
    case "not_interested":
      return "bad";
    default:
      return "neutral";
  }
}

/** The colour of a background job status. */
export function jobTone(status: string): Tone {
  return status === "completed" ? "ok" : status === "failed" ? "bad" : status === "cancelled" ? "warn" : status === "running" ? "brand" : "neutral";
}

/** «از فایل ‹leads.csv› ردیف ۱۴» / «ثبت دستی» / «استخراج از سایت». */
export function sourceText(source: SourceInfo | null | undefined): string {
  if (!source) return "";
  if (source.kind === "manual") return "ثبت دستی";
  if (source.kind === "csv") return `فایل ${source.file ?? ""}${source.row ? ` · ردیف ${fa(source.row)}` : ""}`;
  if (source.kind === "extract") return `استخراج از سایت${source.run ? ` · اجرای ${fa(source.run)}` : ""}`;
  return source.ref ?? "";
}

/** A short badge colour class for tags. */
export function tagTone(color: string): Tone {
  return (["neutral", "brand", "ok", "warn", "bad", "info"].includes(color) ? color : "neutral") as Tone;
}

/** Strip the scheme and trailing slash for compact display. */
export function shortUrl(url: string): string {
  return url.replace(/^https?:\/\//, "").replace(/\/$/, "");
}
