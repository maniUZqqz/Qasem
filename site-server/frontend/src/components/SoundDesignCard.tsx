import { SoundDesign } from "../types";
import { Badge, fa } from "./ui";

/** The narration QC verdicts, in words a shop reads. */
const VERDICT: Record<string, { label: string; tone: "ok" | "info" | "warn" | "bad" }> = {
  EXCELLENT: { label: "عالی", tone: "ok" },
  GOOD: { label: "خوب", tone: "ok" },
  REVIEW: { label: "یک بار گوش بدهید", tone: "warn" },
  RESYNTHESIZE: { label: "ضعیف", tone: "bad" },
};

/**
 * What a voiced video sounds like, besides the words: who spoke, and what
 * plays under each scene.
 *
 * Shown because a shop should never have to guess why today's narrator sounds
 * different from yesterday's (the offline fallback took over) or where the
 * rain in scene two came from. The credit list is there for the same reason a
 * music credit is: a recording in a published ad is a claim that we were
 * allowed to use it, and the shop is the one publishing.
 */
export default function SoundDesignCard({ design }: { design: SoundDesign }) {
  const voice = design.voice;
  const scape = design.soundscape;
  const credits = (scape?.credits ?? []).filter((c) => c.source_url || c.attribution);
  const quality = design.quality;
  const verdict = quality?.verdict ? VERDICT[quality.verdict] : undefined;
  const warnings = design.warnings ?? [];

  return (
    <div
      className="flex flex-col gap-2 rounded-xl p-3 text-sm"
      style={{ border: "1px solid var(--line)", color: "var(--text-2)" }}
    >
      <div className="font-bold" style={{ color: "var(--text)" }}>
        🎧 طراحی صدا
      </div>

      {voice && (
        <div className="flex flex-wrap items-center gap-2">
          <span>گوینده:</span>
          <Badge tone={voice.local ? "ok" : "info"}>
            {voice.processor}
          </Badge>
          <span dir="ltr" className="text-xs" style={{ color: "var(--text-3)" }}>
            {voice.voice}
          </span>
          {(voice.notes ?? []).map((note) => (
            <Badge key={note} tone="warn">
              {note}
            </Badge>
          ))}
        </div>
      )}

      {(design.timing ?? []).some((row) => row.shift > 0) && (
        <div className="flex flex-col gap-1 text-xs">
          {(design.timing ?? [])
            .filter((row) => row.shift > 0)
            .map((row) => (
              <div key={row.scene} className="flex flex-wrap items-center gap-2">
                <span className="font-bold">صحنه {fa(row.scene)}:</span>
                <Badge tone="ok">🎯 {row.note}</Badge>
              </div>
            ))}
        </div>
      )}

      {(design.lipsync ?? []).length > 0 && (
        <div className="flex flex-col gap-1 text-xs">
          {(design.lipsync ?? []).map((row) => (
            <div key={row.scene} className="flex flex-wrap items-center gap-2">
              <span className="font-bold">صحنه {fa(row.scene)}:</span>
              <Badge tone={row.status === "done" ? "ok" : row.status === "skipped" ? "neutral" : "warn"}>
                👄 {row.status === "done" ? "لب‌خوانی شد" : "لب‌خوانی نشد"}
              </Badge>
              {row.status !== "done" && <span style={{ color: "var(--text-3)" }}>{row.note}</span>}
            </div>
          ))}
        </div>
      )}

      {quality && quality.overall !== null && verdict && (
        <div className="flex flex-wrap items-center gap-2">
          <span>کیفیت صدای گوینده:</span>
          <Badge tone={verdict.tone}>
            {verdict.label} — {fa(Math.round(quality.overall))} از ۱۰۰
          </Badge>
          {(quality.retries ?? 0) > 0 && (
            <span className="text-xs" style={{ color: "var(--text-3)" }}>
              {fa(quality.retries ?? 0)} بار دوباره ساخته شد تا بهتر شود
            </span>
          )}
        </div>
      )}

      {warnings.length > 0 && (
        <ul className="list-inside list-disc text-xs" style={{ color: "var(--warn)" }}>
          {warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}

      {scape && scape.plan.length > 0 && (
        <div className="flex flex-col gap-1">
          {scape.plan.map((row) => (
            <div key={row.scene} className="flex flex-wrap items-center gap-2 text-xs">
              <span className="font-bold">صحنه {row.scene}:</span>
              {row.ambience_label ? (
                <Badge tone="neutral">🌧️ {row.ambience_label}</Badge>
              ) : (
                <span style={{ color: "var(--text-3)" }}>بدون صدای محیط</span>
              )}
              {row.effects.map((effect) => (
                <Badge key={`${effect.key}-${effect.at}`} tone={effect.synced ? "ok" : "brand"}>
                  ✨ {effect.label}
                  {effect.synced === "event" && ` — روی حرکت تصویر (ثانیه‌ی ${fa(effect.at)})`}
                  {effect.synced === "rhythm" && ` — روی ${fa(effect.steps ?? 0)} قدمِ تصویر`}
                </Badge>
              ))}
            </div>
          ))}
        </div>
      )}

      {scape && scape.plan.some((row) => row.effects.some((e) => e.synced === null && e.key !== "whoosh")) && (
        <p className="text-xs" style={{ color: "var(--text-3)" }}>
          افکت‌های بدون علامت سبز در زمانی پخش شدند که سناریو گفته بود — در تصویرشان حرکت
          مشخصی دیده نشد که رویش بنشینند.
        </p>
      )}

      {scape && scape.missing.length > 0 && (
        <p className="text-xs" style={{ color: "var(--warn)" }}>
          برای این صداها فایلی در کتابخانه نبود: {Array.from(new Set(scape.missing)).join("، ")}
        </p>
      )}

      {!scape && (
        <p className="text-xs" style={{ color: "var(--text-3)" }}>
          صدای محیط و افکت برای این ویدیو ساخته نشد.
        </p>
      )}

      {credits.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer" style={{ color: "var(--text-3)" }}>
            منبع صداها ({credits.length})
          </summary>
          <ul className="mt-1 list-inside list-disc">
            {credits.map((credit) => (
              <li key={`${credit.title}-${credit.source_url}`}>
                {credit.sound}: {credit.title}
                {credit.creator ? ` — ${credit.creator}` : ""} · {credit.licence || credit.engine}
                {credit.source_url && (
                  <>
                    {" "}
                    <a href={credit.source_url} target="_blank" rel="noreferrer">
                      منبع
                    </a>
                  </>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
