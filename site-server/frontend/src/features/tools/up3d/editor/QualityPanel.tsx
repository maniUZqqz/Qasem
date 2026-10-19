import { Dispatch, SetStateAction, useEffect } from "react";
import { Link } from "react-router-dom";

import Icon from "../../../../components/Icon";
import { Alert, Badge, Button, Field, Select } from "../../../../components/ui";
import { P, desc, dur, fa, label, up3d } from "../api";
import { Advanced, Muted } from "../shared";
import type { Catalog, Estimate, QualityOverride, RenderProfile } from "../types";
import { DraftNumber } from "./fields";
import { byId } from "./model";

/**
 * بخشِ ۴ «کیفیت و رندر»: پنج پروفایل با تنظیمِ واقعی‌شان (موتور، وضوح، نمونه، نویزگیر، تاریِ حرکت، گام، دستگاه)،
 * تخمینِ زمان از آمارِ واقعیِ کارگرها، یک دکمهٔ شروع که صریح می‌گوید روی کدام کارگر و چقدر طول می‌کشد،
 * و «تنظیماتِ پیشرفته» برای دست‌کاریِ وضوح/نمونه/نویزگیر/گام روی همان پروفایل (compiler.clean_quality).
 */

const ASPECTS: Record<string, [number, number]> = { "9:16": [9, 16], "16:9": [16, 9], "1:1": [1, 1], "4:5": [4, 5] };

/** همان compiler.resolution_for: ضلعِ بلند از پروفایل (یا تنظیمِ دستی)، ضلعِ دیگر از قاب، هر دو زوج. */
export function resolutionFor(p: RenderProfile | undefined, aspect: string, q?: QualityOverride | null): [number, number] {
  const long = q?.resolution || p?.resolution?.long || 640;
  const [a, b] = ASPECTS[aspect] || [9, 16];
  const even = (v: number) => Math.max(2, Math.round(v / 2) * 2);
  return a >= b ? [even(long), even((long * b) / a)] : [even((long * a) / b), even(long)];
}

export const ENGINE_FA: Record<string, string> = {
  WORKBENCH: "Workbench (بی‌نورِ واقعی)",
  CYCLES: "Cycles (نورِ واقعی)",
  EEVEE: "Eevee (بلادرنگ)",
};

const STEP_HINT: Record<string, string> = {
  animatic: "گامِ ۱ — وارسیِ حرکت و زمان",
  preview: "گامِ ۲ — نورِ واقعی، کیفیتِ کم",
  standard: "نهایی · GPU",
  high: "نهایی · GPU",
  ultra: "نهایی · GPU قوی",
};

/** یک خطِ خوانا از تنظیمِ مؤثرِ پروفایل (با تنظیمِ دستی روی آن). */
export function profileMeta(p: RenderProfile, aspect: string, q?: QualityOverride | null): string {
  const [w, h] = resolutionFor(p, aspect, q);
  const samples = q?.samples ?? p.samples;
  const denoise = q?.denoise ?? p.denoise;
  const blur = q?.motion_blur ?? p.motion_blur;
  const step = q?.frame_step ?? p.frame_step ?? 1;
  const parts = [ENGINE_FA[p.engine] || p.engine, `${fa(w)}×${fa(h)}`];
  if (p.engine !== "WORKBENCH" && samples) parts.push(`${fa(samples)} نمونه`);
  if (p.engine !== "WORKBENCH") parts.push(denoise ? "نویزگیر روشن" : "بی‌نویزگیر");
  if (blur) parts.push("تاریِ حرکت");
  parts.push(step > 1 ? `هر ${fa(step)} فریم یکی (نرم می‌شود)` : "همهٔ فریم‌ها");
  parts.push(p.recommended === "gpu" ? "کارگرِ GPU" : "CPU کافی است");
  return parts.join(" · ");
}

export function qualitySummary(q: QualityOverride | null | undefined): string {
  if (!q) return "";
  const parts: string[] = [];
  if (q.resolution) parts.push(`${fa(q.resolution)}px`);
  if (q.samples) parts.push(`${fa(q.samples)} نمونه`);
  if (q.frame_step) parts.push(`گام ${fa(q.frame_step)}`);
  if (q.denoise != null) parts.push(q.denoise ? "نویزگیر" : "بی‌نویزگیر");
  if (q.motion_blur != null) parts.push(q.motion_blur ? "تاریِ حرکت" : "بی‌تاری");
  return parts.join(" · ");
}

export function hasQuality(q: QualityOverride | null | undefined): boolean {
  return !!q && Object.values(q).some((v) => v != null);
}

/** جملهٔ تخمین برای یک پروفایل (در کارتِ پروفایل و در خلاصه). */
export function estimateText(e: Estimate | undefined): { text: string; tone: "ok" | "warn" | "bad" | "neutral" } {
  if (!e) return { text: "در حالِ تخمین…", tone: "neutral" };
  if (e.available) return { text: `${fa(e.frames)} فریم · ~${dur(e.seconds)} روی ${e.worker}`, tone: "ok" };
  if (e.cpu_seconds) return { text: `${fa(e.frames)} فریم · کارگرِ GPU آنلاین نیست · روی CPU ِ سرور ~${dur(e.cpu_seconds)}`, tone: "warn" };
  return { text: `${fa(e.frames)} فریم · هیچ کارگری آنلاین نیست`, tone: "bad" };
}

export default function QualityPanel({
  cat,
  pid,
  version,
  aspect,
  profile,
  setProfile,
  quality,
  setQuality,
  est,
  setEst,
  onRender,
}: {
  cat: Catalog;
  pid: number;
  version: number | null;
  aspect: string;
  profile: string;
  setProfile: (id: string) => void;
  quality: QualityOverride | null;
  setQuality: (q: QualityOverride | null) => void;
  est: Record<string, Estimate>;
  setEst: Dispatch<SetStateAction<Record<string, Estimate>>>;
  onRender: (profile: string, allowCpu: boolean, quality: QualityOverride | null) => void;
}) {
  const qKey = JSON.stringify(quality || {});

  // تخمین از آمارِ واقعیِ کارگرها؛ با هر نسخهٔ تازه یا تنظیمِ دستی دوباره (با کمی تأخیر تا تایپ تمام شود)
  useEffect(() => {
    let alive = true;
    const q = JSON.parse(qKey) as QualityOverride;
    const timer = window.setTimeout(async () => {
      if (!alive) return;
      setEst({});
      for (const p of cat.render_profile) {
        try {
          const e = await up3d.estimate(p.id, pid, hasQuality(q) ? q : null);
          if (alive) setEst((prev) => ({ ...prev, [p.id]: e }));
        } catch {
          /* بی‌تخمین */
        }
      }
    }, 350);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [cat, pid, version, qKey, setEst]);

  const p = byId(cat, "render_profile", profile);
  const e = est[profile];
  const q = hasQuality(quality) ? quality : null;
  const setQ = (k: keyof QualityOverride, v: number | boolean | null) => {
    const next: QualityOverride = { ...(quality || {}) };
    if (v == null) delete next[k];
    else (next as Record<string, unknown>)[k] = v;
    setQuality(hasQuality(next) ? next : null);
  };

  const start = () => {
    if (!e || !p) return;
    if (e.available) {
      onRender(profile, false, q);
      return;
    }
    if (e.cpu_seconds) {
      if (
        e.cpu_seconds > 1800 &&
        !window.confirm(`روی CPU ِ سرور حدودِ ${dur(e.cpu_seconds)} طول می‌کشد (اولویتِ پایین؛ سایت کند نمی‌شود). شروع شود؟`)
      )
        return;
      onRender(profile, true, q);
    }
  };

  const action = (() => {
    if (!p) return null;
    if (!e)
      return (
        <Button disabled>
          در حالِ تخمینِ زمان…
        </Button>
      );
    if (e.available)
      return (
        <Button onClick={start}>
          <Icon name="play" size={15} />
          شروعِ رندر «{label(p)}» — ~{dur(e.seconds)} روی {e.worker}
        </Button>
      );
    if (e.cpu_seconds)
      return (
        <Button variant="secondary" onClick={start}>
          <Icon name="cpu" size={15} />
          اجرای «{label(p)}» روی CPU ِ سرور — ~{dur(e.cpu_seconds)}
        </Button>
      );
    return (
      <Button disabled>
        <Icon name="ban" size={15} />
        هیچ کارگری آنلاین نیست
      </Button>
    );
  })();

  return (
    <div className="space-y-3">
      <div className="u3d-profiles">
        {cat.render_profile.map((rp) => {
          const ee = est[rp.id];
          const et = estimateText(ee);
          const on = rp.id === profile;
          return (
            <button type="button" key={rp.id} className={`u3d-profile ${on ? "on" : ""}`} onClick={() => setProfile(rp.id)}>
              <span className="u3d-radio" aria-hidden />
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  <b className="text-sm" style={{ color: "var(--text)" }}>
                    {label(rp)}
                  </b>
                  {STEP_HINT[rp.id] && <Badge tone={rp.recommended === "gpu" ? "neutral" : "brand"}>{STEP_HINT[rp.id]}</Badge>}
                </span>
                <span className="meta block">{desc(rp)}</span>
                <span className="meta block">{profileMeta(rp, aspect, on ? q : null)}</span>
                <span className="est block" style={{ color: et.tone === "ok" ? "var(--text-2)" : et.tone === "neutral" ? "var(--text-3)" : `var(--${et.tone})` }}>
                  {et.text}
                </span>
              </span>
            </button>
          );
        })}
      </div>

      {e && !e.available && !e.cpu_seconds && (
        <Alert tone="bad" title="هیچ کارگرِ رندری آنلاین نیست">
          رندر داخلِ پنل اجرا نمی‌شود؛ یک «کارگر» باید کار را بگیرد. کارگرِ CPU ِ سرور (server-cpu) باید روشن باشد، یا کارگرِ GPU را راه بیندازید.{" "}
          <Link to={P.workers()} style={{ color: "var(--brand-strong)" }}>
            صفحهٔ کارگرها
          </Link>
        </Alert>
      )}
      {e && !e.available && e.cpu_seconds && p?.recommended === "gpu" && (
        <Alert tone="warn" title={`کیفیتِ «${label(p)}» برای کارگرِ GPU است و کارگرِ GPU آنلاین نیست`}>
          می‌توانید روی CPU ِ سرور اجرا کنید (خیلی کند: ~{dur(e.cpu_seconds)})، یا اول «انیمیک/پیش‌نمایش» بگیرید و کیفیتِ نهایی را بعد از راه‌اندازیِ کارگرِ GPU.{" "}
          <Link to={P.workers()} style={{ color: "var(--brand-strong)" }}>
            راه‌اندازیِ کارگرِ GPU
          </Link>
        </Alert>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {action}
        {q && <Badge tone="info">تنظیمِ دستی: {qualitySummary(q)}</Badge>}
      </div>
      <Muted className="text-xs">
        پیشنهاد: اول «انیمیک» (چند دقیقه) برای وارسیِ حرکت و زمان، بعد «پیش‌نمایش» با نورِ واقعی؛ کیفیت‌های ۷۲۰p/۱۰۸۰p/4K روی کارگرِ GPU.
        صحنه پیش از رندر خودکار ذخیره و وارسی می‌شود.
      </Muted>

      <Advanced title="تنظیماتِ پیشرفتهٔ کیفیت" hint="وضوح، نمونه، نویزگیر و گام روی همین پروفایل — زمانِ رندر با پیکسل × نمونه بزرگ می‌شود">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="وضوح (ضلعِ بلند)" hint={p ? `پیش‌فرضِ پروفایل: ${fa(p.resolution.long)}px` : undefined}>
            <Select value={quality?.resolution ? String(quality.resolution) : ""} onChange={(ev) => setQ("resolution", ev.target.value ? Number(ev.target.value) : null)}>
              <option value="">پیش‌فرضِ پروفایل</option>
              {[480, 640, 960, 1280, 1920, 2560, 3840].map((r) => (
                <option key={r} value={r}>
                  {fa(r)}px
                </option>
              ))}
            </Select>
          </Field>
          <Field label="نمونه در هر پیکسل" hint={p?.engine === "WORKBENCH" ? "برای انیمیک معنی ندارد" : p?.samples ? `پیش‌فرض: ${fa(p.samples)}` : undefined}>
            <DraftNumber
              value={quality?.samples ?? null}
              min={1}
              max={2048}
              step={1}
              placeholder={p?.samples ? String(p.samples) : ""}
              disabled={p?.engine === "WORKBENCH"}
              onCommit={(v) => setQ("samples", v == null ? null : Math.max(1, Math.min(2048, Math.round(v))))}
            />
          </Field>
          <Field label="نویزگیر (Denoise)">
            <Select
              value={quality?.denoise == null ? "" : quality.denoise ? "1" : "0"}
              onChange={(ev) => setQ("denoise", ev.target.value === "" ? null : ev.target.value === "1")}
              disabled={p?.engine === "WORKBENCH"}
            >
              <option value="">پیش‌فرضِ پروفایل{p && p.engine !== "WORKBENCH" ? ` (${p.denoise ? "روشن" : "خاموش"})` : ""}</option>
              <option value="1">روشن</option>
              <option value="0">خاموش</option>
            </Select>
          </Field>
          <Field label="گامِ فریم" hint="۲ یعنی نصفِ فریم‌ها رندر و بقیه نرم می‌شود (نصفِ زمان)">
            <Select value={quality?.frame_step ? String(quality.frame_step) : ""} onChange={(ev) => setQ("frame_step", ev.target.value ? Number(ev.target.value) : null)}>
              <option value="">پیش‌فرضِ پروفایل{p ? ` (${fa(p.frame_step ?? 1)})` : ""}</option>
              {[1, 2, 3, 4].map((s) => (
                <option key={s} value={s}>
                  {fa(s)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="تاریِ حرکت (Motion blur)">
            <Select
              value={quality?.motion_blur == null ? "" : quality.motion_blur ? "1" : "0"}
              onChange={(ev) => setQ("motion_blur", ev.target.value === "" ? null : ev.target.value === "1")}
              disabled={p?.engine === "WORKBENCH"}
            >
              <option value="">پیش‌فرضِ پروفایل{p && p.engine !== "WORKBENCH" ? ` (${p.motion_blur ? "روشن" : "خاموش"})` : ""}</option>
              <option value="1">روشن</option>
              <option value="0">خاموش</option>
            </Select>
          </Field>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant="ghost" onClick={() => setQuality(null)} disabled={!q}>
            بازگشت به پیش‌فرضِ پروفایل
          </Button>
          {p && (
            <Muted className="text-xs">
              تنظیمِ مؤثر: {profileMeta(p, aspect, q)}
            </Muted>
          )}
        </div>
      </Advanced>
    </div>
  );
}
