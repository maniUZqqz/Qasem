import BeforeAfter from "../../../components/BeforeAfter";
import Icon from "../../../components/Icon";
import { Alert, Badge, Button, Card, fa } from "../../../components/ui";
import { clock, minutes, SeamInfo, Version } from "./api";

const TONE: Record<string, "ok" | "warn" | "bad" | "info" | "neutral"> = {
  QUEUED: "info",
  PREPARING: "info",
  GENERATING: "info",
  STITCHING: "info",
  READY: "ok",
  FAILED: "bad",
  CANCELLED: "neutral",
};

const VERDICT_TONE = { invisible: "ok", slight: "warn", visible: "bad" } as const;

function SeamRow({ name, s }: { name: string; s: SeamInfo }) {
  return (
    <tr style={{ borderTop: "1px solid var(--line)" }}>
      <td className="py-1.5">{name}</td>
      <td className="py-1.5">
        <Badge tone={VERDICT_TONE[s.verdict]}>{s.label}</Badge>
      </td>
      <td className="py-1.5" dir="ltr">
        {fa(s.ratio.toFixed(2))}×
      </td>
      <td className="py-1.5" dir="ltr">
        {fa(s.ssim.toFixed(3))} / {fa(s.typical_ssim.toFixed(3))}
      </td>
      <td className="py-1.5" dir="ltr">
        {fa(Math.round(s.motion_jump * 100))}٪
      </td>
    </tr>
  );
}

/** یک نسخه: پیشرفت تا آماده شدن؛ بعد قبل/بعد کنارِ هم، تکهٔ تنها، نمرهٔ درز و دکمه‌ها. */
export default function VersionCard({
  v,
  fps,
  isCurrent,
  busy,
  onAction,
  onAgain,
  onEdit,
}: {
  v: Version;
  fps: number;
  isCurrent: boolean;
  busy: boolean;
  onAction: (v: Version, action: "accept" | "discard" | "cancel" | "editor") => void;
  onAgain: (v: Version) => void;
  onEdit: (v: Version) => void;
}) {
  const seams = v.seams || {};
  const ready = v.state === "READY";
  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2" data-testid={`regen-version-${v.number}`}>
        <div className="flex flex-wrap items-center gap-2">
          <b style={{ color: "var(--text)" }}>نسخهٔ {fa(v.number)}</b>
          <Badge tone={TONE[v.state] ?? "neutral"}>{v.state_label}</Badge>
          {isCurrent && <Badge tone="brand">قبول‌شده — پایهٔ ویرایش‌های بعدی</Badge>}
          {v.discarded && <Badge tone="neutral">دور انداخته شد</Badge>}
          {ready && seams.label && (
            <Badge tone={VERDICT_TONE[seams.verdict ?? "invisible"]}>
              درز: {seams.label} · نمره {fa(seams.score ?? 0)}
            </Badge>
          )}
        </div>
        <span className="text-xs" style={{ color: "var(--text-3)" }}>
          فریمِ {fa(v.start)} تا {fa(v.end)} · {clock(v.start / fps)} ← {clock((v.end + 1) / fps)} ·{" "}
          {fa(v.seconds.toFixed(2))} ثانیه
        </span>
      </div>

      {v.prompt && (
        <p className="text-sm leading-7" style={{ color: "var(--text-2)" }}>
          «{v.prompt}»
        </p>
      )}

      {v.active && (
        <div className="space-y-1.5">
          <div className="u-meter">
            <span style={{ width: `${Math.round(v.progress * 100)}%`, background: "var(--brand)" }} />
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs" style={{ color: "var(--text-2)" }}>
            <span data-testid="regen-progress-message">
              {fa(Math.round(v.progress * 100))}٪ — {v.message}
            </span>
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => onAction(v, "cancel")}>
              لغو
            </Button>
          </div>
        </div>
      )}

      {v.state === "FAILED" && (
        <Alert tone="bad" title="ساختِ این نسخه ناموفق بود">
          {v.error}
        </Alert>
      )}

      {ready && v.urls.before && v.urls.after && (
        <BeforeAfter
          compact
          beforeUrl={v.urls.before}
          afterUrl={v.urls.after}
          beforeLabel="قبل (اصل)"
          afterLabel={`بعد (نسخهٔ ${fa(v.number)})`}
          note="دو ثانیه قبل و بعد از تکه هم در هر دو پخش می‌شود تا درزها را در جای خودشان ببینید."
        />
      )}

      {ready && (
        <div className="grid gap-3 md:grid-cols-2">
          {v.urls.piece && (
            <div className="space-y-1">
              <div className="text-xs font-bold" style={{ color: "var(--text-2)" }}>
                فقط تکهٔ تازه
              </div>
              <video src={v.urls.piece} controls playsInline preload="metadata" className="w-full rounded-lg" style={{ background: "#000", maxHeight: 240 }} />
            </div>
          )}
          {seams.seams && (
            <div className="space-y-1 text-xs" style={{ color: "var(--text-2)" }}>
              <div className="font-bold">وارسیِ خودکارِ درزها</div>
              <table className="w-full">
                <thead>
                  <tr style={{ color: "var(--text-3)" }}>
                    <th className="py-1 text-start font-normal">درز</th>
                    <th className="py-1 text-start font-normal">نتیجه</th>
                    <th className="py-1 text-start font-normal" title="تفاوتِ دو فریمِ دو طرفِ درز تقسیم بر تفاوتِ عادیِ فریم‌های همین ویدیو">
                      پرش
                    </th>
                    <th className="py-1 text-start font-normal" title="شباهتِ ساختاری در درز / در حالتِ عادی">
                      SSIM
                    </th>
                    <th className="py-1 text-start font-normal" title="تغییرِ ناگهانیِ سرعتِ حرکت در درز">
                      تکانِ حرکت
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {seams.seams.start && <SeamRow name="ابتدا" s={seams.seams.start} />}
                  {seams.seams.end && <SeamRow name="انتها" s={seams.seams.end} />}
                </tbody>
              </table>
              {seams.inner_max && (
                <p>
                  بزرگ‌ترین پرشِ داخلِ تکه: {fa(seams.inner_max.ratio.toFixed(2))}× (فریمِ {fa(seams.inner_max.frame)})
                </p>
              )}
              <p style={{ color: "var(--text-3)" }}>
                {v.assemble.method === "smart"
                  ? `فقط ${fa(v.assemble.reencoded_frames ?? 0)} فریمِ اطرافِ تکه دوباره رمزگذاری شد؛ بقیهٔ ویدیو بیت‌به‌بیت همان اصل است.`
                  : `کلِ ویدیو با تنظیماتِ نزدیک به اصل دوباره رمزگذاری شد${v.assemble.smart_skipped ? ` (${v.assemble.smart_skipped})` : ""}.`}{" "}
                صدای اصلی دست نخورده و طولِ ویدیو تا فریم یکی است.
                {v.gen_seconds ? ` ساخت روی ${v.node || "سرورِ پردازش"}: ${minutes(v.gen_seconds)}.` : ""}
              </p>
            </div>
          )}
        </div>
      )}

      {v.warnings.length > 0 && (
        <Alert tone="warn">
          {v.warnings.map((w) => (
            <div key={w}>{w}</div>
          ))}
        </Alert>
      )}

      {v.model_prompt && (
        <details className="text-xs" style={{ color: "var(--text-3)" }}>
          <summary className="cursor-pointer">پرامپتی که به مدل رفت · seed {fa(v.seed)} · {v.engine === "wan22_flf" ? "Wan 2.2 A14B" : "Fun-InP 1.3B"} {v.quality}</summary>
          <p className="mt-1 leading-6" dir="ltr">
            {v.model_prompt}
          </p>
        </details>
      )}

      {!v.active && (
        <div className="flex flex-wrap gap-2">
          {ready && !v.accepted && v.urls.result && (
            <Button size="sm" disabled={busy} onClick={() => onAction(v, "accept")} data-testid="regen-accept">
              <Icon name="check" size={14} /> قبول
            </Button>
          )}
          {ready && v.accepted && !v.editor_upload && (
            <Button size="sm" variant="secondary" disabled={busy} onClick={() => onAction(v, "editor")}>
              <Icon name="film" size={14} /> بفرست به ادیتور
            </Button>
          )}
          {v.urls.result && (
            <a className="u-btn u-btn-secondary u-btn-sm" href={v.urls.result} download>
              <Icon name="download" size={14} /> دانلودِ ویدیوی کامل
            </a>
          )}
          <Button size="sm" variant="secondary" disabled={busy} onClick={() => onAgain(v)} data-testid="regen-again">
            <Icon name="refresh" size={14} /> دوباره با seed ِ دیگر
          </Button>
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => onEdit(v)}>
            ویرایشِ خواسته و دوباره
          </Button>
          {!v.discarded && (ready || v.state === "FAILED") && (
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => onAction(v, "discard")}>
              <Icon name="trash" size={14} /> دور بینداز
            </Button>
          )}
          {v.result_pruned && (
            <span className="text-xs" style={{ color: "var(--text-3)" }}>
              ویدیوی کاملِ این نسخه برای جای دیسک پاک شد (پیش‌نمایش‌ها هست).
            </span>
          )}
        </div>
      )}
    </Card>
  );
}
