/**
 * تنظیماتِ خروجیِ «نهایی» که پنل می‌فرستد: همیشه یک شیءِ کامل و درست، حتی وقتی در تبِ «خروجی» هیچ‌چیز تنظیم نشده یا فقط نیمی از آن پر است.
 * سرور هم خودش پیش‌فرض می‌گذارد (services/editing/export.py: default_spec)؛ این‌جا کاری می‌کنیم که پنل هیچ‌وقت حالتِ خراب نفرستد.
 * آزمون: tests/video-r5-exportdefaults.test.ts.
 */
import type { ExportBlock } from "./model";

const FORMATS = ["mp4", "gif", "frame", "audio"] as const;
const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** بلوکِ پروژه + تنظیمِ یک‌باره ⇒ شیءِ پاک‌شده؛ همیشه `format` دارد (پیش‌فرض mp4)؛ مقدارهای نامعتبر کنار گذاشته می‌شوند */
export function finalExport(block?: ExportBlock | null, override?: Record<string, unknown> | null): Record<string, unknown> {
  const m: Record<string, unknown> = { ...(block && typeof block === "object" ? block : {}), ...(override && typeof override === "object" ? override : {}) };
  const out: Record<string, unknown> = {};
  if (typeof m.preset === "string" && m.preset.trim()) out.preset = m.preset.trim();
  if (m.codec === "h264" || m.codec === "h265") out.codec = m.codec;
  if (finite(m.fps) && m.fps > 0) out.fps = Math.max(12, Math.min(60, Math.round(m.fps)));
  if (finite(m.height) && m.height > 0) out.height = Math.max(240, Math.min(2160, Math.round(m.height)));
  if (m.quality === "high" || m.quality === "medium" || m.quality === "small") out.quality = m.quality;
  if (finite(m.audio_kbps) && m.audio_kbps > 0) out.audio_kbps = Math.max(64, Math.min(320, Math.round(m.audio_kbps)));
  if (finite(m.target_mb) && m.target_mb > 0) out.target_mb = m.target_mb;
  if (m.where === "auto" || m.where === "server") out.where = m.where;
  out.format = (FORMATS as readonly unknown[]).includes(m.format) ? m.format : "mp4";
  if (m.range === "inout" || m.range === "all") out.range = m.range;
  if (finite(m.frame_t) && m.frame_t >= 0) out.frame_t = m.frame_t;
  if (m.replace === true) out.replace = true;
  return out;
}
