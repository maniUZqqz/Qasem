import { useState } from "react";

import { Button, fa } from "../../../../components/ui";
import type { ToolInfo } from "../../ToolPicker";
import ToolForm from "../ToolForm";
import { MediaClip, Params, ProgramOp, Project, AnyClip, Track, uid } from "./model";

/** افکت‌هایی که روی «یک قطعه» می‌نشینند (همان فهرستِ timeline.CLIP_EFFECT_TOOLS ِ سرور) */
const CLIP_TOOLS = ["brightness", "contrast", "saturation", "white_balance", "deflicker", "sharpen", "vignette", "blur_region", "rotate"];
/** ابزارهایی که روی «کلِ ویدیو یا یک بازه» اعمال می‌شوند (مرحلهٔ دوم رندر، از راهِ EDL) */
const PROGRAM_TOOLS = ["cut", "trim_silence", "brightness", "contrast", "saturation", "white_balance", "deflicker", "stabilize", "zoom",
  "speed", "crop_format", "denoise_audio", "normalize_audio", "fade", "rotate", "watermark", "blur_region", "sharpen", "vignette", "transition"];
const PREVIEWED = ["brightness", "contrast", "saturation", "white_balance", "sharpen", "vignette", "blur_region", "rotate"];

/** توضیحِ جای هر ابزار — «همه‌چیز در دسترس است» */
const WHERE: Record<string, string> = {
  cut: "برش: در تایم‌لاین با S تقسیم و با Delete حذف کنید؛ یا بازهٔ «از–تا» را از کلِ ویدیو بردارید.",
  trim_silence: "حذفِ سکوت: روی کلِ ویدیو (سکوت‌ها از خودِ صدا پیدا می‌شوند).",
  subtitle: "زیرنویس: از زیرنویسِ ساخته‌شدهٔ ویدیو، ترکِ متن می‌سازد (دکمهٔ پایین).",
  speed: "سرعت: هم ویژگیِ هر قطعه (تب «قطعه») هم روی کلِ ویدیو.",
  fade: "محو شدن: هم ویژگیِ هر قطعه (ابتدا/انتها) هم روی کلِ ویدیو.",
  transition: "گذار: بینِ دو قطعه در تب «قطعه» (محو به سیاه / محوشدنِ تدریجی) یا کلِ ویدیو.",
  crop_format: "تغییرِ قاب: روی کلِ ویدیو؛ قابِ پروژه را هم در تب «خروجی» انتخاب می‌کنید.",
};


export type FxProps = {
  project: Project;
  selected: { track: Track; clip: AnyClip } | null;
  tools: ToolInfo[];
  edit: { live: (fn: (p: Project) => Project) => void; end: (label: string) => void; apply: (label: string, fn: (p: Project) => Project) => void };
  onSubtitles: (ref: string) => void;
  hasSubtitleSource: boolean;
};

// ═══════════════════════════════════════════════════════════════ افکت‌ها

export default function EffectsTab({ project, selected, edit, tools, onSubtitles, hasSubtitleSource }: FxProps) {
  const [key, setKey] = useState("");
  const [values, setValues] = useState<Params>({});
  const info = tools.find((t) => t.key === key);
  const clip = selected && selected.clip.type === "media" && selected.track.kind === "video" ? (selected.clip as MediaClip) : null;
  const choose = (k: string) => {
    setKey(k);
    const t = tools.find((x) => x.key === k);
    setValues(Object.fromEntries((t?.params ?? []).map((p) => [p.name, p.default])) as Params);
  };
  const canClip = !!clip && CLIP_TOOLS.includes(key);
  const canProgram = PROGRAM_TOOLS.includes(key);

  const addClipFx = () => {
    if (!clip || !info) return;
    const params = { ...values };
    delete params.from_s;
    delete params.to_s;
    edit.apply(`افکت: ${info.title}`, (pr) => ({ ...pr, tracks: pr.tracks.map((t) => ({ ...t, clips: t.clips.map((c) => (c.id === clip.id && c.type === "media" ? { ...c, effects: [...c.effects, { tool: key, params }] } : c)) })) }));
  };
  const addProgram = () => {
    if (!info) return;
    const op: ProgramOp = { id: uid("g"), tool: key, params: { ...values } };
    edit.apply(`افکتِ کلِ ویدیو: ${info.title}`, (pr) => ({ ...pr, global_ops: [...pr.global_ops, op] }));
  };

  const fxList = clip?.effects ?? [];
  return (
    <div data-testid="fx-tab">
      <div className="ws-card">
        <div className="ws-card-title">همهٔ ابزارهای ویرایش ({fa(tools.length)})</div>
        <select className="u-input" value={key} onChange={(e) => choose(e.target.value)} data-testid="fx-select" aria-label="ابزار">
          <option value="">یک ابزار انتخاب کنید…</option>
          {tools.map((t) => <option key={t.key} value={t.key}>{t.title}{CLIP_TOOLS.includes(t.key) ? " · قطعه" : ""}{PROGRAM_TOOLS.includes(t.key) ? " · کل" : ""}</option>)}
        </select>
        {info && (
          <>
            <p className="ws-hint mt-2">{info.why}</p>
            {WHERE[key] && <p className="ws-hint" style={{ color: "var(--brand-strong)" }}>{WHERE[key]}</p>}
            <ToolForm tool={info} values={values} onChange={(v) => setValues(v as Params)} />
            <div className="mt-3 flex flex-wrap gap-2">
              {CLIP_TOOLS.includes(key) && (
                <Button size="sm" onClick={addClipFx} disabled={!canClip} title={clip ? "" : "اول یک قطعهٔ تصویر را انتخاب کنید"} data-testid="fx-add-clip">
                  افزودن به قطعهٔ انتخاب‌شده
                </Button>
              )}
              {canProgram && <Button size="sm" variant="secondary" onClick={addProgram} data-testid="fx-add-program">افزودن به کل ویدیو / بازه</Button>}
              {key === "subtitle" && (
                <Button size="sm" onClick={() => selected && selected.clip.type === "media" && onSubtitles(selected.clip.ref)}
                  disabled={!hasSubtitleSource} title={hasSubtitleSource ? "" : "یک قطعهٔ ویدیو را انتخاب کنید"} data-testid="fx-subtitles">
                  ساختِ متن‌ها از زیرنویسِ ویدیو
                </Button>
              )}
            </div>
            {PREVIEWED.includes(key) ? null : canProgram || CLIP_TOOLS.includes(key) ? (
              <p className="ws-hint mt-2">پیش‌نمایشِ مرورگر برای این ابزار نیست؛ در خروجی اعمال می‌شود.</p>
            ) : null}
          </>
        )}
      </div>

      <div className="ws-card" data-testid="clip-fx-list">
        <div className="ws-card-title">افکت‌های قطعهٔ انتخاب‌شده</div>
        {!clip && <p className="ws-hint">قطعهٔ تصویر انتخاب نشده است.</p>}
        {clip && fxList.length === 0 && <p className="ws-hint">افکتی نیست.</p>}
        {fxList.map((fx, i) => (
          <FxRow key={i} tool={tools.find((t) => t.key === fx.tool)} params={fx.params}
            onParams={(pp) => edit.apply("تنظیمِ افکت", (pr) => ({ ...pr, tracks: pr.tracks.map((t) => ({ ...t, clips: t.clips.map((c) => (c.id === clip!.id && c.type === "media" ? { ...c, effects: c.effects.map((e, j) => (j === i ? { ...e, params: pp } : e)) } : c)) })) }))}
            onRemove={() => edit.apply("برداشتنِ افکت", (pr) => ({ ...pr, tracks: pr.tracks.map((t) => ({ ...t, clips: t.clips.map((c) => (c.id === clip!.id && c.type === "media" ? { ...c, effects: c.effects.filter((_e, j) => j !== i) } : c)) })) }))} />
        ))}
      </div>

      <div className="ws-card" data-testid="program-fx-list">
        <div className="ws-card-title">افکت‌های کلِ ویدیو</div>
        {project.global_ops.length === 0 && <p className="ws-hint">افکتی نیست. این‌ها پس از چیدنِ تایم‌لاین، روی کلِ ویدیوی ساخته‌شده اعمال می‌شوند (بازهٔ «از–تا» به ثانیهٔ تایم‌لاین است).</p>}
        {project.global_ops.map((op, i) => (
          <FxRow key={op.id} tool={tools.find((t) => t.key === op.tool)} params={op.params}
            onParams={(pp) => edit.apply("تنظیمِ افکتِ کل", (pr) => ({ ...pr, global_ops: pr.global_ops.map((o, j) => (j === i ? { ...o, params: pp } : o)) }))}
            onRemove={() => edit.apply("برداشتنِ افکتِ کل", (pr) => ({ ...pr, global_ops: pr.global_ops.filter((_o, j) => j !== i) }))} />
        ))}
      </div>
    </div>
  );
}

function FxRow({ tool, params, onParams, onRemove }: { tool?: ToolInfo; params: Params; onParams: (p: Params) => void; onRemove: () => void }) {
  const [open, setOpen] = useState(false);
  if (!tool) return null;
  const summary = tool.params.filter((p) => p.name in params && !["from_s", "to_s"].includes(p.name)).slice(0, 3).map((p) => `${p.title}: ${typeof params[p.name] === "number" ? fa(Math.round(Number(params[p.name]) * 100) / 100) : String(params[p.name])}`).join(" · ");
  return (
    <div className="vw-effect-row" data-fx={tool.key} style={{ flexWrap: "wrap" }}>
      <b>{tool.title}</b>
      <span className="ws-muted" style={{ flex: 1 }}>{summary}</span>
      <button type="button" className="ws-link" onClick={() => setOpen(!open)}>{open ? "بستن" : "تنظیم"}</button>
      <button type="button" className="ws-link" onClick={onRemove} aria-label="برداشتن">×</button>
      {open && <div style={{ width: "100%" }}><ToolForm tool={tool} values={params} onChange={(v) => onParams(v as Params)} /></div>}
    </div>
  );
}

