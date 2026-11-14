import type { ChangeEvent } from "react";

/**
 * «زبانِ گفتار»: فارسی (پیش‌فرض)، English، یا تشخیصِ خودکار. گفتارخوان (Whisper روی کارتِ گرافیک) برای بریدنِ بی‌صدا و اِم و اوم، برشِ روی مرزِ کلمه
 * و زیرنویس زبانِ گفتار را می‌داند؛ ویدیوی انگلیسی را با مدلِ فارسی خواندن همه‌شان را خراب می‌کرد.
 * سرور: captions.LANGUAGES (فارسی همان رفتارِ قبلی است؛ «تشخیصِ خودکار» از نرم‌افزارِ تازهٔ سرورِ پردازش به بعد کار می‌کند و روی نسخهٔ قدیمی فارسی می‌ماند).
 */
export type SpeechLang = "fa" | "en" | "auto";

export const SPEECH_LANGS: { key: SpeechLang; label: string }[] = [
  { key: "fa", label: "فارسی" },
  { key: "en", label: "English (انگلیسی)" },
  { key: "auto", label: "تشخیصِ خودکارِ زبان" },
];

export function speechLang(v: string): SpeechLang {
  return v === "en" || v === "auto" ? v : "fa";
}

export default function SpeechLanguagePicker({ value, onChange, testId = "speech-language" }: { value: SpeechLang; onChange: (l: SpeechLang) => void; testId?: string }) {
  return (
    <label className="flex flex-wrap items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
      زبانِ گفتار:
      <select
        value={value}
        onChange={(e: ChangeEvent<HTMLSelectElement>) => onChange(speechLang(e.target.value))}
        data-testid={testId}
        className="rounded-lg px-2 py-1 text-sm"
        style={{ border: "1px solid var(--line)", background: "var(--surface)", color: "var(--text)" }}
        title="زبانی که در ویدیو حرف زده می‌شود؛ بریدنِ مکث‌ها و زیرنویس با همین زبان شنیده می‌شود"
      >
        {SPEECH_LANGS.map((l) => (
          <option key={l.key} value={l.key}>{l.label}</option>
        ))}
      </select>
    </label>
  );
}
