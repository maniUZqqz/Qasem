/**
 * توانایی‌های یک سرورِ پردازش برای نمایش (بدونِ React، تا بدونِ مرورگر آزمون شود).
 *
 * عاملِ گره در heartbeat ده‌ها کلیدِ فنی می‌فرستد (data_dir، commands، disk_free_gb، gpu_util_pct، preflight …). پیش‌تر هر کلیدِ درست
 * به‌صورتِ برچسبِ انگلیسی در ردیفِ سرور چاپ می‌شد (ردیف ۶۰۰ پیکسل بلند می‌شد و هر فیلدِ تازهٔ عامل یک برچسبِ تازه می‌آورد).
 * حالا فقط یک فهرستِ مجازِ برچسب‌دار («چه کاری از این سرور برمی‌آید») نشان داده می‌شود و بقیه پشتِ «جزئیات فنی» می‌ماند.
 *
 * آزمون: frontend/tests/compute-capabilities.test.tsx
 */

export type CapPill = { key: string; label: string };
export type TechRow = { key: string; value: string };

/** پرچم‌های درست/نادرستِ عامل که برای مالک معنی دارند ⇒ برچسبِ فارسی (سرویس‌های روشن/خاموش جای دیگری‌اند) */
export const FLAG_LABELS: Record<string, string> = {
  ffmpeg: "ffmpeg",
  photo_matting: "حذفِ پس‌زمینهٔ عکس",
  voice_clone: "کلونِ صدا",
  lipsync: "هم‌گام‌سازیِ لب",
};

/** زیرکلیدهای caps.audio */
export const AUDIO_LABELS: Record<string, string> = {
  moss: "گفتارِ فارسیِ MOSS",
  sfx: "افکتِ صدا",
  music: "موسیقیِ زمینه",
};

/** برچسبِ فارسیِ پرچم‌های شمارش‌شدهٔ کارتِ «توانایی‌های آنلاین» (هر کلیدِ دیگر نشان داده نمی‌شود) */
export const SUMMARY_LABELS: Record<string, string> = {
  comfyui: "ComfyUI",
  comfy_bridge: "پلِ ComfyUI",
  photo: "عکس",
  video: "ویدیو",
  voice: "صدا",
  ollama: "Ollama",
  blender: "Blender",
  worker3d: "رندرِ سه‌بعدی",
  ...FLAG_LABELS,
};

/** کلیدهایی که اندازه‌گیریِ لحظه‌ای‌اند، نه توانایی؛ هرگز در «جزئیات فنی» هم نمی‌آیند (در نوارهای حافظه و نمودارها دیده می‌شوند) */
const METRIC_KEYS = new Set([
  "disk_free_gb", "disk_total_gb", "gpu_util_pct", "gpu_temp_c", "ram_total_mb", "ram_free_mb", "vram_used_mb", "vram_total_mb",
  "started_at", "site_errors",
]);

function isObj(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** «چه کاری از این سرور برمی‌آید»: فقط پرچم‌های مجازِ روشن، با برچسبِ فارسی */
export function capabilityPills(caps: Record<string, unknown> | null | undefined): CapPill[] {
  const c = caps ?? {};
  const out: CapPill[] = [];
  for (const [key, label] of Object.entries(FLAG_LABELS)) {
    if (c[key] === true) out.push({ key, label });
  }
  const edit = c.edit;
  if (isObj(edit) && edit.render) {
    out.push({ key: "edit", label: "ویرایشگرِ ویدیو" });
    const nv = edit.nvenc;
    if (isObj(nv) && (nv.h264 || nv.h265)) out.push({ key: "nvenc", label: "رمزگذاریِ ویدیو با کارت (NVENC)" });
  }
  const audio = c.audio;
  if (isObj(audio)) {
    for (const [key, label] of Object.entries(AUDIO_LABELS)) {
      if (audio[key] === true) out.push({ key: `audio.${key}`, label });
    }
  }
  return out;
}

/** برچسبِ کارتِ «توانایی‌های آنلاین» برای یک پرچم؛ null = نشان داده نمی‌شود (مثلاً auto_switch که تنظیم است نه توانایی) */
export function summaryLabel(key: string): string | null {
  return SUMMARY_LABELS[key] ?? null;
}

function short(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "string" || typeof v === "number") return String(v).slice(0, 200);
  if (Array.isArray(v)) {
    const head = v.slice(0, 6).map((x) => (typeof x === "string" || typeof x === "number" ? String(x) : "…")).join(", ");
    return `[${v.length}] ${head}${v.length > 6 ? ", …" : ""}`;
  }
  try {
    const s = JSON.stringify(v);
    return s.length > 160 ? `${s.slice(0, 157)}…` : s;
  } catch {
    return "…";
  }
}

/** «جزئیات فنی»: key = value برای همهٔ کلیدهای عامل، جز اندازه‌گیری‌های لحظه‌ای و کلیدهایی که جای دیگری نشان داده می‌شوند (`hidden`) */
export function technicalRows(caps: Record<string, unknown> | null | undefined, hidden?: ReadonlySet<string>): TechRow[] {
  return Object.entries(caps ?? {})
    .filter(([k, v]) => !METRIC_KEYS.has(k) && !hidden?.has(k) && v !== undefined && v !== null && v !== false && v !== "")
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, value]) => ({ key, value: short(value) }));
}
