import type { ChangeEvent } from "react";

/**
 * «زیرنویس: داخلِ تصویر / فایلِ جدا». داخلِ تصویر = متن روی خودِ ویدیو می‌نشیند و همیشه دیده می‌شود (ریلز، استوری، تیک‌تاک)؛
 * فایلِ جدا = تصویر تمیز می‌ماند و زیرنویس فقط در فایلِ .srt کنارِ ویدیو می‌آید (یوتیوب، آپارات، پخش‌کنندهٔ تلگرام؛ بیننده خاموشش می‌کند).
 * در هر دو حالت فایلِ .srt ساخته می‌شود.
 */
export type CaptionMode = "burn" | "soft";

export const CAPTION_MODES: { key: CaptionMode; label: string }[] = [
  { key: "burn", label: "داخلِ تصویر (همیشه دیده می‌شود)" },
  { key: "soft", label: "فایلِ جدا (.srt؛ بیننده خاموشش می‌کند)" },
];

export default function CaptionModePicker({ value, onChange, testId = "caption-mode" }: { value: CaptionMode; onChange: (m: CaptionMode) => void; testId?: string }) {
  return (
    <label className="flex flex-wrap items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
      زیرنویس:
      <select
        value={value}
        onChange={(e: ChangeEvent<HTMLSelectElement>) => onChange(e.target.value === "soft" ? "soft" : "burn")}
        data-testid={testId}
        className="rounded-lg px-2 py-1 text-sm"
        style={{ border: "1px solid var(--line)", background: "var(--surface)", color: "var(--text)" }}
        title="در هر دو حالت فایلِ .srt کنارِ ویدیو هم ساخته می‌شود؛ «فایلِ جدا» برای یوتیوب، آپارات و تلگرام است"
      >
        {CAPTION_MODES.map((m) => (
          <option key={m.key} value={m.key}>{m.label}</option>
        ))}
      </select>
    </label>
  );
}
