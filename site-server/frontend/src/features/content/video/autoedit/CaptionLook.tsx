import type { ChangeEvent } from "react";

/**
 * «ظاهرِ زیرنویس»: هفت ظاهرِ آمادهٔ تدوینِ خودکار (services/editing/director/tools.py: CAPTION_STYLES). خالی = «خودکار» (همان رفتارِ قبلی: کارائوکه برای
 * ویدیوهای پرانرژی، وگرنه درشت و پرانرژی). پنج ظاهرِ دیگر قبلاً فقط با ویرایشِ مرحلهٔ «زیرنویس» در پیش‌نویس به دست می‌آمد (بازبینیِ ۱۱/۱۳).
 */
export type CaptionLook = "" | "pop" | "box" | "karaoke" | "clean" | "neon" | "typewriter" | "lower";

export const CAPTION_LOOKS: { key: CaptionLook; label: string }[] = [
  { key: "", label: "خودکار (بر پایهٔ حال‌وهوای ویدیو)" },
  { key: "pop", label: "درشت و پرانرژی" },
  { key: "box", label: "کادرِ تیره" },
  { key: "karaoke", label: "کارائوکه (هایلایت)" },
  { key: "clean", label: "ساده و تمیز" },
  { key: "neon", label: "نئونی (کلمهٔ در حالِ گفتن سبز)" },
  { key: "typewriter", label: "ماشین‌تحریر (حرف‌به‌حرف)" },
  { key: "lower", label: "زیرنویسِ آرام (مصاحبه و سخنرانی)" },
];

export function captionLook(v: string): CaptionLook {
  return CAPTION_LOOKS.some((l) => l.key === v) ? (v as CaptionLook) : "";
}

export default function CaptionLookPicker({ value, onChange, testId = "caption-look" }: { value: CaptionLook; onChange: (l: CaptionLook) => void; testId?: string }) {
  return (
    <label className="flex flex-wrap items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
      ظاهرِ زیرنویس:
      <select
        value={value}
        onChange={(e: ChangeEvent<HTMLSelectElement>) => onChange(captionLook(e.target.value))}
        data-testid={testId}
        className="rounded-lg px-2 py-1 text-sm"
        style={{ border: "1px solid var(--line)", background: "var(--surface)", color: "var(--text)" }}
        title="هفت ظاهرِ آماده؛ «خودکار» خودش بر پایهٔ حال‌وهوای ویدیو انتخاب می‌کند"
      >
        {CAPTION_LOOKS.map((l) => (
          <option key={l.key || "auto"} value={l.key}>{l.label}</option>
        ))}
      </select>
    </label>
  );
}
