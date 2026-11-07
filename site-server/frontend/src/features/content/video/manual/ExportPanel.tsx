import { useCallback, useEffect, useMemo, useState } from "react";

import { errorMessage } from "../../../../api/client";
import { Alert, Badge, Spinner, fa } from "../../../../components/ui";
import type { Catalogue, Check, ExportRow, RenderJobRow, RenderWhere } from "../api";
import { videoApi } from "../api";
import { Chips, Section } from "./controls";
import { ExportBlock, Master, Project, SOCIAL_LOUDNESS, projectLength, timecode } from "./model";
import "./sound.css";
import "./text.css";

type Cat = Catalogue["export"];

type Props = {
  storeId: string;
  projectId: number | null;
  project: Project;
  check: Check | null;
  cat: Cat;
  /** بلوکِ کاملِ تازهٔ `project.export` (جایگزینِ قبلی می‌شود) */
  onExport: (block: ExportBlock) => void;
  /** تغییرِ مسترِ پروژه (یکسان‌سازیِ بلندیِ خروجی = `master.loudness`) با یک گامِ برگشت */
  onMaster?: (patch: Partial<Master>) => void;
  onRender: (quality: "draft" | "final", override?: Record<string, unknown>) => Promise<void>;
  /** جای سرِ پخش (برای «عکسِ یک فریم») */
  playhead?: number;
  busy: boolean;
  /** آیا سرورِ پردازش برای رندرِ نهایی آماده است (از کاتالوگ یا تازه) */
  where?: RenderWhere | null;
};

const mb = (bytes: number) => `${fa((bytes / 1048576).toFixed(1))} مگابایت`;

/** همان size_for ِ سرور: ضلعِ کوتاه = `short`؛ طرف‌ها زوج */
function outSize(w: number, h: number, short: number | null): [number, number] {
  if (!short) return [w, h];
  const k = short / Math.min(w, h);
  return [Math.max(2, Math.round((w * k) / 2) * 2), Math.max(2, Math.round((h * k) / 2) * 2)];
}

/** «روی چه ساخته شد» برای فهرستِ خروجی‌ها */
const whereText = (e: { where?: string; node?: string; encoder?: string }) =>
  e.where === "node" ? `سرورِ پردازش${e.node ? ` «${e.node}»` : ""}${e.encoder ? ` · ${e.encoder}` : ""}` : e.where === "server" ? "سرورِ سایت" : "";

export default function ExportPanel({ storeId, projectId, project, check, cat, onExport, onMaster, onRender, busy, where, playhead = 0 }: Props) {
  const block: ExportBlock = project.export ?? {};
  const loudness = project.master?.loudness;
  const loudOn = !!loudness?.on;
  const preset = cat.presets.find((p) => p.key === block.preset);
  const codec = block.codec ?? (preset?.codec as ExportBlock["codec"]) ?? "h264";
  const short = block.height ?? preset?.short ?? null;
  const fps = block.fps ?? preset?.fps ?? null;
  const quality = block.quality ?? (preset?.quality as ExportBlock["quality"]) ?? "high";
  const kbps = block.audio_kbps ?? preset?.audio_kbps ?? 160;
  const [w, h] = outSize(project.format.width, project.format.height, short);
  const length = check?.length ?? projectLength(project);

  const [data, setData] = useState<{ jobs: RenderJobRow[]; exports: ExportRow[] } | null>(null);
  const [dismissed, setDismissed] = useState<Set<number>>(new Set());
  const [pending, setPending] = useState<"draft" | "final" | null>(null);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  const refresh = useCallback(async () => {
    if (!projectId) {
      setData(null);
      return;
    }
    try {
      setData(await videoApi.renders(storeId, projectId));
    } catch {
      /* شبکه رفت؛ دورِ بعد دوباره */
    }
  }, [storeId, projectId]);

  const active = !!data?.jobs.some((j) => j.active);
  useEffect(() => {
    void refresh();
    const t = window.setInterval(() => void refresh(), active ? 2000 : 15000);
    return () => window.clearInterval(t);
  }, [refresh, active]);
  useEffect(() => {
    void refresh();
  }, [busy, refresh]);

  const groups = useMemo(() => {
    const m = new Map<string, Cat["presets"]>();
    for (const p of cat.presets) m.set(p.group, [...(m.get(p.group) ?? []), p]);
    return [...m.entries()];
  }, [cat.presets]);

  const set = (patch: Partial<ExportBlock>) => onExport({ ...block, ...patch });
  const aspectWarn = useMemo(() => {
    if (!preset?.aspect) return "";
    const [a, b] = preset.aspect.split(":").map(Number);
    return Math.abs(project.format.width / project.format.height - a / b) > 0.05
      ? `قابِ پروژه ${preset.aspect} نیست؛ خروجی با همان قابِ پروژه ساخته می‌شود (قاب را در بخشِ «پروژه» عوض کنید).`
      : "";
  }, [preset, project.format]);
  const longWarn = preset?.max_seconds && length > preset.max_seconds + 0.5 ? `این پلتفرم تا ${fa(preset.max_seconds)} ثانیه می‌پذیرد؛ ویدیوی شما ${fa(Math.round(length))} ثانیه است.` : "";
  const heavyWarn = short && short >= 1440 ? "۱۴۴۰ پیکسل برای سرورِ کوچک سنگین است و ممکن است چند دقیقه طول بکشد." : "";
  const blocked = !!check && !check.ok;

  const hasRange = !!project.inout && project.inout.out > project.inout.in + 0.05;
  const go = async (q: "draft" | "final", override?: Record<string, unknown>) => {
    setPending(q);
    try {
      await onRender(q, override);
    } finally {
      setPending(null);
      await refresh();
      window.setTimeout(() => void refresh(), 1200);
    }
  };

  const cancel = async (id: number) => {
    setCancelError(null);
    try {
      await videoApi.cancelJob(id);
    } catch (err) {
      setCancelError(errorMessage(err));
    }
    await refresh();
  };

  const presetTitle = (e: ExportRow) => (e.format === "gif" ? "GIF" : e.format === "frame" ? "عکسِ یک فریم" : e.format === "audio" ? "فقط صدا" : e.range === "inout" ? "فقط بازهٔ ورودی–خروجی" : cat.presets.find((p) => p.key === e.preset)?.title ?? (e.quality === "draft" ? "پیش‌نویسِ سریع" : "خروجیِ نهایی"));
  const jobs = data?.jobs ?? [];
  const failed = jobs.filter((j) => j.state === "FAILED" && !dismissed.has(j.id)).slice(0, 2);
  const exports = data?.exports ?? [];
  const latest = exports[0];

  return (
    <div className="xp-panel" dir="rtl" data-testid="export-panel">
      <div className="ws-card-title">خروجی</div>
      <Section title="پیش‌تنظیمِ پلتفرم" defaultOpen testId="xp-presets">
        {groups.map(([group, list]) => (
          <div key={group} className="xp-group">
            <div className="tx-sub">{group}</div>
            <div className="flex flex-wrap gap-1">
              {list.map((p) => (
                <button key={p.key} type="button" className={`ws-chip ${block.preset === p.key ? "is-on" : ""}`} aria-pressed={block.preset === p.key}
                  title={[p.aspect ?? "", p.short ? `${p.short}p` : "اندازهٔ پروژه", p.fps ? `${p.fps}fps` : "", p.max_seconds ? `تا ${p.max_seconds} ثانیه` : ""].filter(Boolean).join(" · ")}
                  onClick={() => onExport({ preset: p.key, ...(block.target_mb ? { target_mb: block.target_mb } : {}) })} data-preset={p.key}>{p.title}</button>
              ))}
            </div>
          </div>
        ))}
        <div className="mt-2">
          <div className="tx-sub">حجمِ هدفِ فایل</div>
            <select className="u-input" value={block.target_mb ?? ""} aria-label="حجمِ هدف" data-testid="export-target-mb"
            onChange={(e) => set({ target_mb: e.target.value ? Number(e.target.value) : null })}>
              <option value="">بدونِ سقف</option>
              <option value={8}>تا ۸ مگابایت (پیام‌رسان‌ها)</option>
              <option value={16}>تا ۱۶ مگابایت (واتساپ و تلگرام)</option>
              <option value={25}>تا ۲۵ مگابایت (ایمیل)</option>
              <option value={50}>تا ۵۰ مگابایت</option>
              <option value={100}>تا ۱۰۰ مگابایت</option>
            </select>
            <p className="ws-hint">با سقفِ حجم، کیفیتِ تصویر خودکار تنظیم می‌شود تا فایل از آن بزرگ‌تر نشود.</p>
        </div>
        {block.preset && <button type="button" className="ws-link" onClick={() => onExport(block.target_mb ? { target_mb: block.target_mb } : {})}>بدونِ پیش‌تنظیم (همه‌چیز دستی)</button>}
        {aspectWarn && <p className="xp-warn" data-testid="xp-aspect">{aspectWarn}</p>}
        {longWarn && <p className="xp-warn">{longWarn}</p>}
      </Section>

      <Section title="محلِ رندرِ نهایی" defaultOpen testId="xp-where">
        <Chips value={(block.where ?? "auto") as "auto" | "server"} options={[{ key: "auto", title: "خودکار (سرورِ پردازش اگر روشن بود)" }, { key: "server", title: "فقط سرورِ سایت" }]} onPick={(k) => set({ where: k })} />
        {where?.online ? (
          <p className="ws-hint" data-testid="xp-where-online">سرورِ پردازشِ «{where.node}» روشن است{where.gpu ? ` (${where.gpu})` : ""}؛ خروجیِ نهایی {block.where === "server" ? "با انتخابِ شما روی سرورِ سایت" : `آن‌جا${where.nvenc ? " با NVENC (کارتِ گرافیک)" : ""}`} ساخته می‌شود. اگر خاموش شد یا خطا داد، خودکار روی سرورِ سایت ساخته می‌شود.</p>
        ) : (
          <p className="ws-hint" data-testid="xp-where-offline">خروجیِ نهایی روی سرورِ سایت ساخته می‌شود. {where?.message ?? ""}</p>
        )}
        <p className="ws-hint" data-testid="xp-draft-where">
          «پیش‌نویسِ سریع» پیش‌فرض روی سرورِ سایت ساخته می‌شود. فقط وقتی سنگین باشد (سایت حدس می‌زند بیش از حدود ۴۵ ثانیه طول بکشد) و سرورِ پردازش روشن و بی‌کار باشد و
          فایل‌های اصلی را از قبل داشته باشد (یا حجمشان کم باشد)، خودکار آن‌جا ساخته می‌شود؛ تنظیمی لازم نیست. زیرِ هر خروجی نوشته می‌شود «ساخته‌شده روی: …».
        </p>
      </Section>

      <Section title="خروجی‌های دیگر: GIF، عکسِ یک فریم، فقط صدا، فقط یک بازه" testId="xp-formats">
        <p className="ws-hint">هر کدام یک بار ساخته می‌شود و به تنظیم‌های پروژه دست نمی‌زند. از همان رندرِ نهایی (با همهٔ افکت‌ها و عنوان‌ها) بریده می‌شود.</p>
        <div className="xp-actions" style={{ flexWrap: "wrap" }}>
          <button type="button" className="ws-btn" disabled={busy || pending !== null || blocked} onClick={() => void go("final", { range: "inout" })} data-testid="xf-range"
            title={hasRange ? "فقط بخشِ بینِ ورودی و خروجی (I و O) به‌صورتِ ویدیو" : "اول روی تایم‌لاین ورودی و خروجی بگذارید (I و O)؛ وگرنه کلِ ویدیو ساخته می‌شود"}>
            فقط بازهٔ ورودی–خروجی{hasRange ? "" : " (بازه نیست)"}
          </button>
          <button type="button" className="ws-btn" disabled={busy || pending !== null || blocked} onClick={() => void go("final", { format: "gif", ...(hasRange ? { range: "inout" } : {}) })} data-testid="xf-gif"
            title="تصویرِ متحرکِ بی‌صدا؛ تا ۲۰ ثانیه، ارتفاعِ ۴۰۰ پیکسل">GIF{hasRange ? " (از بازه)" : ""}</button>
          <button type="button" className="ws-btn" disabled={busy || pending !== null || blocked} onClick={() => void go("final", { format: "frame", frame_t: Math.round(playhead * 100) / 100 })} data-testid="xf-frame"
            title="فریمِ زیرِ سرِ پخش به‌صورتِ عکسِ JPG">عکسِ فریمِ سرِ پخش</button>
          <button type="button" className="ws-btn" disabled={busy || pending !== null || blocked} onClick={() => void go("final", { format: "audio", ...(hasRange ? { range: "inout" } : {}) })} data-testid="xf-audio"
            title="فقط صدای میکس‌شده (M4A)؛ مثلاً برای پادکست یا آهنگ">فقط صدا (M4A){hasRange ? " (از بازه)" : ""}</button>
        </div>
      </Section>

      <Section title="تنظیمِ دقیق" testId="xp-manual">
        <div className="tx-sub">کدک</div>
        <Chips value={codec} options={cat.codecs.map((c) => ({ key: c.key as "h264" | "h265", title: c.title }))} onPick={(k) => set({ codec: k })} />
        {codec === "h265" && <p className="ws-hint">H.265 فایلِ کوچک‌تر می‌دهد ولی رندرش کندتر است و بعضی پلتفرم‌ها/گوشی‌های قدیمی آن را نمی‌خوانند.</p>}
        <div className="tx-sub">اندازه (ضلعِ کوتاه)</div>
        <select className="u-input" value={block.height ?? ""} aria-label="اندازه" onChange={(e) => set({ height: e.target.value ? Number(e.target.value) : null })}>
          <option value="">{preset?.short ? `طبقِ پیش‌تنظیم (${fa(preset.short)}p)` : "اندازهٔ پروژه"}</option>
          {cat.resolutions.map((r) => <option key={r} value={r}>{fa(r)}p</option>)}
        </select>
        <div className="tx-sub">نرخِ فریم</div>
        <div className="flex flex-wrap gap-1">
          <button type="button" className={`ws-chip ${block.fps == null ? "is-on" : ""}`} onClick={() => set({ fps: null })}>پیش‌فرض</button>
          {cat.fps.map((f) => <button key={f} type="button" className={`ws-chip ${block.fps === f ? "is-on" : ""}`} aria-pressed={block.fps === f} onClick={() => set({ fps: f })}>{fa(f)}</button>)}
        </div>
        <div className="tx-sub">کیفیت</div>
        <Chips value={quality} options={cat.qualities.map((q) => ({ key: q.key as "high" | "medium" | "small", title: q.title }))} onPick={(k) => set({ quality: k })} />
        <div className="tx-sub">صدا (کیلوبیت بر ثانیه)</div>
        <select className="u-input" value={kbps} aria-label="کیفیتِ صدا" onChange={(e) => set({ audio_kbps: Number(e.target.value) })}>
          {cat.audio_kbps.map((k) => <option key={k} value={k}>{fa(k)}</option>)}
        </select>
        {heavyWarn && <p className="xp-warn">{heavyWarn}</p>}
      </Section>

      {onMaster && (
        <div className="ws-card sq-loud" data-testid="export-loudness-card">
          <div className="ws-card-title">بلندیِ صدا</div>
          <label className="ws-check">
            <input
              type="checkbox" checked={loudOn} data-testid="export-loudness"
              onChange={(e) => onMaster({ loudness: { ...SOCIAL_LOUDNESS, ...(loudness ?? {}), on: e.target.checked } })}
            />{" "}
            یکسان‌سازی برای شبکه‌های اجتماعی (حدود −۱۴ LUFS)
          </label>
          <p className="ws-hint">
            اینستاگرام و تیک‌تاک صدای بلند را خودشان پایین می‌آورند؛ این گزینه صدا را از همان اول در حدِ استاندارد می‌سازد تا ویدیو بعد از انتشار ضعیف نشود.
            {loudOn && loudness && loudness.target !== SOCIAL_LOUDNESS.target ? ` (هدفِ فعلی: ${loudness.target < 0 ? "−" : ""}${fa(Math.abs(loudness.target))} LUFS)` : ""}
          </p>
        </div>
      )}

      <p className="ws-hint" data-testid="xp-summary">
        خروجی: <b dir="ltr">{fa(w)}×{fa(h)}</b>{fps ? <> · <span dir="ltr">{fa(fps)}fps</span></> : null} · {codec === "h265" ? "H.265" : "H.264"} · صدا {fa(kbps)}k · {fa(Math.round(length))} ثانیه
      </p>

      {blocked && <Alert tone="bad" title="این پروژه رندر نمی‌شود">{check?.error}</Alert>}
      <div className="xp-actions">
        <button type="button" className="ws-btn" disabled={busy || pending !== null || blocked} onClick={() => void go("draft")} data-testid="render-draft"
          title="کوچک و سریع، فقط برای دیدنِ نتیجه">{pending === "draft" ? "در حالِ شروع…" : "پیش‌نویسِ سریع"}</button>
        <button type="button" className="ws-btn primary" disabled={busy || pending !== null || blocked} onClick={() => void go("final")} data-testid="render-final">
          {pending === "final" ? "در حالِ شروع…" : "خروجیِ نهایی"}
        </button>
      </div>
      <p className="ws-hint">خروجیِ نهایی همیشه از <b>فایل‌های اصلی</b> ساخته می‌شود، نه از نسخهٔ سبکِ پیش‌نمایش. هم‌زمان یک رندر اجرا می‌شود؛ بقیه در صف می‌مانند و ادیت کردنِ پروژه ادامه دارد.</p>

      {(jobs.some((j) => j.active) || failed.length > 0) && (
        <div className="xp-queue" data-testid="render-queue">
          <div className="tx-sub">صفِ رندر</div>
          {jobs.filter((j) => j.active).map((j) => {
            const queued = /صف/.test(j.label) || (j.percent === 0 && j.state === "QUEUED");
            return (
              <div key={j.id} className="xp-job" data-job={j.id}>
                <div className="xp-job-head">
                  <span>{j.preset ? cat.presets.find((p) => p.key === j.preset)?.title ?? j.preset : j.quality === "draft" ? "پیش‌نویس" : "نهایی"}</span>
                  <Badge tone={queued ? "neutral" : "info"}>{queued ? "در صف" : `${fa(j.percent)}٪`}</Badge>
                  <button type="button" className="ws-btn" onClick={() => void cancel(j.id)} aria-label="لغوِ رندر" data-testid="render-cancel">لغو</button>
                </div>
                <div className="xp-bar" role="progressbar" aria-valuenow={j.percent} aria-valuemin={0} aria-valuemax={100}><i style={{ width: `${queued ? 4 : j.percent}%` }} /></div>
                <div className="ws-muted">{j.label || (queued ? "در صفِ رندر…" : "در حالِ رندر…")}</div>
                {j.where && <div className="ws-muted" data-testid="job-where">محل: {j.where.startsWith("node") ? "سرورِ پردازش" : "سرورِ سایت"}</div>}
              </div>
            );
          })}
          {failed.map((j) => (
            <Alert key={j.id} tone="bad" title="رندر ناموفق بود" action={<button type="button" className="ws-btn" onClick={() => setDismissed((s) => new Set([...s, j.id]))} aria-label="بستن">×</button>}>
              {j.error || "خطای نامشخص"}
            </Alert>
          ))}
          {cancelError && <p className="xp-warn">{cancelError}</p>}
        </div>
      )}

      {busy && !jobs.some((j) => j.active) && <p className="ws-muted"><Spinner size={12} /> در حالِ ثبتِ رندر…</p>}

      {latest && (
        <div className="xp-done" data-testid="export-latest">
          <div className="tx-sub">آخرین خروجی</div>
          {latest.format === "frame" ? (
            <img className="xp-video" src={latest.url} alt="عکسِ فریم" data-testid="export-image" />
          ) : latest.format === "gif" ? (
            <img className="xp-video" src={latest.url} alt="GIF" data-testid="export-gif" />
          ) : latest.format === "audio" ? (
            <audio src={latest.url} controls preload="metadata" style={{ width: "100%" }} data-testid="export-audio" />
          ) : (
            <video className="xp-video" src={latest.url} controls preload="metadata" playsInline />
          )}
          <div className="xp-exp-meta">
            <b>{presetTitle(latest)}</b> · <span dir="ltr">{latest.size}</span> · {timecode(latest.seconds).slice(0, 5)} · {mb(latest.bytes)}
            {latest.codec === "h265" ? " · H.265" : ""}
          </div>
          {whereText(latest) && <div className="ws-muted" data-testid="export-where">ساخته‌شده روی: {whereText(latest)}</div>}
          {latest.fallback && <p className="xp-warn" data-testid="export-fallback">{latest.fallback}</p>}
          {latest.note && <p className="xp-warn">{latest.note}</p>}
          <a className="ws-btn" href={latest.url} download target="_blank" rel="noreferrer" data-testid="export-download">دانلود</a>
        </div>
      )}
      {exports.length > 1 && (
        <>
          <button type="button" className="ws-link" onClick={() => setShowAll((v) => !v)}>{showAll ? "پنهان‌کردنِ خروجی‌های قبلی" : `خروجی‌های قبلی (${fa(exports.length - 1)})`}</button>
          {showAll && (
            <ul className="xp-list">
              {exports.slice(1).map((e) => (
                <li key={e.job_id}>
                  <span>{presetTitle(e)} · <span dir="ltr">{e.size}</span> · {mb(e.bytes)}{whereText(e) ? ` · ساخته‌شده روی: ${whereText(e)}` : ""}</span>
                  <a href={e.url} download target="_blank" rel="noreferrer">دانلود</a>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
