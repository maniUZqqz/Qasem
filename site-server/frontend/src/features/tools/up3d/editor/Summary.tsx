import { Link } from "react-router-dom";

import Icon from "../../../../components/Icon";
import { Badge, Button, Card } from "../../../../components/ui";
import { P, dur, fa, label } from "../api";
import { Bar, StateBadge, WaitingAlert } from "../shared";
import type { Catalog, Estimate, Issue, Project, QualityOverride, SceneDoc, Status } from "../types";
import { byId } from "./model";
import { hasQuality, qualitySummary, resolutionFor } from "./QualityPanel";

/**
 * کارتِ چسبانِ «خلاصه و وضعیت» کنارِ ویرایشگر: چه چیزی رندر می‌شود (مدت، قاب، وضوح، صحنه، مجری، محصول، شمارِ قطعه‌ها)،
 * با کدام کیفیت و روی کدام کارگر و چقدر، آماده‌باش (اعتبار، ذخیره، کارگر، AI)، کارِ در جریانِ همین پروژه، آخرین ویدئو.
 * همهٔ دکمه‌ها همان کارهای بخش‌های پایین را می‌زنند.
 */
export default function Summary({
  proj,
  doc,
  cat,
  issues,
  dirty,
  profile,
  quality,
  est,
  status,
  onRender,
  onSave,
  onAllowCpu,
  onCancel,
}: {
  proj: Project;
  doc: SceneDoc;
  cat: Catalog;
  issues: Issue[];
  dirty: boolean;
  profile: string;
  quality: QualityOverride | null;
  est: Record<string, Estimate>;
  status: Status | null;
  onRender: () => void;
  onSave: () => void;
  onAllowCpu: (id: number) => void;
  onCancel: (id: number) => void;
}) {
  const p = byId(cat, "render_profile", profile);
  const e = est[profile];
  const [w, h] = resolutionFor(p, doc.output.aspect, quality);
  const errors = issues.filter((i) => i.level === "error").length;
  const warnings = issues.filter((i) => i.level === "warning").length;
  const active = proj.jobs.find((j) => !j.final && j.kind !== "plan");
  const env = byId(cat, "environment", doc.environment.id);
  const actors = doc.actors.map((a) => label(byId(cat, "character", a.character)));
  const products = doc.products.map((pr) => pr.name || label(byId(cat, "product", pr.asset)));
  const canRender = errors === 0 && !!e && (e.available || !!e.cpu_seconds);

  const check = (tone: "ok" | "warn" | "bad" | "neutral", text: string) => (
    <div className={tone}>
      <i>{tone === "ok" ? "✓" : tone === "bad" ? "✕" : tone === "warn" ? "!" : "…"}</i>
      <span>{text}</span>
    </div>
  );

  return (
    <Card>
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-base font-bold" style={{ color: "var(--text)" }}>
          خلاصه و وضعیت
        </h2>
        <span className="flex flex-wrap gap-1">
          <Badge tone={proj.valid ? "ok" : "bad"}>{proj.version ? `نسخهٔ ${fa(proj.version)}` : "بی‌نسخه"}</Badge>
          {dirty && <Badge tone="warn">ذخیره‌نشده</Badge>}
        </span>
      </div>

      <div className="mt-3 text-xs font-bold" style={{ color: "var(--text-3)" }}>
        چه چیزی رندر می‌شود
      </div>
      <table className="u3d-kv mt-1 w-full">
        <tbody>
          <tr>
            <td>مدت / قاب</td>
            <td>
              {fa(doc.output.duration.toFixed(1))} ثانیه · {doc.output.aspect} · {fa(doc.output.fps)}fps
            </td>
          </tr>
          <tr>
            <td>صحنه</td>
            <td>
              {label(env)}
              {actors.length ? ` · مجری: ${actors.join("، ")}` : " · بی‌مجری (راوی)"}
            </td>
          </tr>
          <tr>
            <td>محصول</td>
            <td>{products.length ? products.join("، ") : "—"}</td>
          </tr>
          <tr>
            <td>قطعه‌ها</td>
            <td>
              {fa(doc.actions.length)} حرکت · {fa(doc.speech.length)} گفتار · {fa(doc.shots.length)} نما · {fa(doc.overlays.length)} نوشته
            </td>
          </tr>
          <tr>
            <td>کیفیت</td>
            <td>
              {p ? label(p) : profile} · {fa(w)}×{fa(h)}
              {hasQuality(quality) ? ` · ${qualitySummary(quality)}` : ""}
            </td>
          </tr>
          <tr>
            <td>زمان / کارگر</td>
            <td>
              {!e
                ? "در حالِ تخمین…"
                : e.available
                  ? `~${dur(e.seconds)} روی ${e.worker}`
                  : e.cpu_seconds
                    ? `کارگرِ GPU آنلاین نیست · CPU ~${dur(e.cpu_seconds)}`
                    : "هیچ کارگری آنلاین نیست"}
            </td>
          </tr>
        </tbody>
      </table>

      <div className="mt-3 text-xs font-bold" style={{ color: "var(--text-3)" }}>
        آماده‌باش
      </div>
      <div className="u3d-check mt-1">
        {errors
          ? check("bad", `${fa(errors)} خطا در صحنه — تا ترمیم نشود رندر نمی‌شود`)
          : warnings
            ? check("warn", `صحنه معتبر است، ${fa(warnings)} هشدار`)
            : check("ok", "صحنه معتبر است")}
        {dirty ? check("warn", "تغییرِ ذخیره‌نشده (با شروعِ رندر خودکار ذخیره می‌شود)") : check("ok", "ذخیره شده")}
        {!e
          ? check("neutral", "تخمینِ کارگر…")
          : e.available
            ? check("ok", `کارگرِ ${e.worker} برای این کیفیت آماده است`)
            : e.cpu_seconds
              ? check("warn", "کارگرِ GPU آنلاین نیست؛ فقط CPU ِ سرور (کند)")
              : check("bad", "هیچ کارگری آنلاین نیست")}
        {status?.ai_ready ? check("ok", "کارگردانِ هوشِ مصنوعی وصل است") : check("warn", "بی‌کلیدِ AI — قالب‌ها و ویرایشِ دستی کار می‌کنند")}
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <Button onClick={onRender} disabled={!canRender} title={errors ? "اول ایرادها را ترمیم کنید" : undefined}>
          <Icon name="play" size={15} />
          رندر با «{p ? label(p) : profile}»
        </Button>
        {dirty && (
          <Button variant="secondary" onClick={onSave}>
            ذخیره
          </Button>
        )}
      </div>

      {active && (
        <div className="mt-3">
          <div className="text-xs font-bold" style={{ color: "var(--text-3)" }}>
            کارِ در جریان
          </div>
          <div className="mt-1 flex items-center justify-between gap-2 text-sm">
            <Link to={P.job(active.id)} className="font-bold" style={{ color: "var(--text)" }}>
              {active.kind_label} #{fa(active.id)} <span className="u3d-mono text-xs">{active.profile}</span>
            </Link>
            <StateBadge job={active} />
          </div>
          <div className="mt-1.5">
            <Bar value={active.progress || 0} />
          </div>
          <div className="mt-1 text-xs" style={{ color: "var(--text-3)" }}>
            {active.worker ? `کارگر: ${active.worker} · ` : ""}
            {active.frames_total ? `فریم ${fa(active.frames_done)}/${fa(active.frames_total)} · ` : ""}
            {active.eta_seconds ? `مانده ~${dur(active.eta_seconds)}` : active.message}
          </div>
          {active.waiting && (
            <div className="mt-2">
              <WaitingAlert job={active} onAllowCpu={onAllowCpu} onCancel={onCancel} />
            </div>
          )}
        </div>
      )}

      {proj.result && (
        <div className="mt-3">
          <div className="text-xs font-bold" style={{ color: "var(--text-3)" }}>
            آخرین ویدئو
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-sm">
            <Link to={P.job(proj.result.job)} style={{ color: "var(--brand-strong)" }}>
              کار #{fa(proj.result.job)} ({proj.result.profile})
            </Link>
            {proj.result.qc && <Badge tone={proj.result.qc === "pass" ? "ok" : proj.result.qc === "warn" ? "warn" : "bad"}>کیفیت: {proj.result.qc}</Badge>}
            <a className="u-btn u-btn-secondary u-btn-sm" href={proj.result.video} download>
              <Icon name="download" size={13} />
              دانلود
            </a>
          </div>
        </div>
      )}
    </Card>
  );
}
