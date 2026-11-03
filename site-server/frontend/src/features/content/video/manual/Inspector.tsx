import { useEffect, useState } from "react";

import { Alert, Badge, Button, Spinner, fa } from "../../../../components/ui";
import type { ToolInfo } from "../../ToolPicker";
import type { Check, MediaItem, ProjectRow } from "../api";
import ToolForm from "../ToolForm";
import {
  AnyClip, FORMATS, MediaClip, Params, Project, ProgramOp, TextClip, Track, clipLength, findClip, timecode, uid,
} from "./model";

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

const num = (v: unknown, d = 0) => (typeof v === "number" && Number.isFinite(v) ? v : d);

function Row({ label, value, min, max, step = 0.01, unit = "", onLive, onEnd }: {
  label: string; value: number; min: number; max: number; step?: number; unit?: string; onLive: (v: number) => void; onEnd: () => void;
}) {
  return (
    <label className="ws-slider" data-field={label}>
      <span className="ws-slider-head"><span>{label}</span><span className="ws-slider-val" dir="ltr">{fa(Math.round(value * 100) / 100)}{unit}</span></span>
      <input type="range" min={min} max={max} step={step} value={value} aria-label={label}
        onChange={(e) => onLive(Number(e.target.value))} onPointerUp={onEnd} onKeyUp={onEnd} onBlur={onEnd} />
    </label>
  );
}

function Num({ label, value, step = 0.1, min = 0, onChange }: { label: string; value: number; step?: number; min?: number; onChange: (v: number) => void }) {
  return (
    <label className="ws-field">
      <span>{label}</span>
      <input className="u-input" type="number" step={step} min={min} value={Math.round(value * 1000) / 1000} aria-label={label}
        onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}

type Edit = {
  live: (fn: (p: Project) => Project) => void;
  end: (label: string) => void;
  apply: (label: string, fn: (p: Project) => Project) => void;
};

type Props = {
  project: Project;
  selected: { track: Track; clip: AnyClip } | null;
  playhead: number;
  tools: ToolInfo[];
  media: Record<string, MediaItem>;
  edit: Edit;
  title: string;
  onTitle: (t: string) => void;
  check: Check | null;
  saving: "idle" | "saving" | "saved" | "error";
  projects: ProjectRow[];
  projectId: number | null;
  onOpenProject: (id: number | null) => void;
  onDeleteProject: () => void;
  render: { busy: boolean; label: string; error: string | null; row: ProjectRow | null };
  onRender: (q: "draft" | "final") => void;
  onSubtitles: (ref: string) => void;
  hasSubtitleSource: boolean;
};

export default function Inspector(p: Props) {
  const [tab, setTab] = useState<"clip" | "fx" | "out">("clip");
  const sel = p.selected;
  useEffect(() => {
    if (sel && tab === "out") return;
  }, [sel, tab]);
  return (
    <div className="vw-inspector" dir="rtl" data-testid="inspector">
      <div className="ws-tabs">
        {([["clip", "قطعه"], ["fx", "افکت‌ها"], ["out", "خروجی"]] as const).map(([k, t]) => (
          <button key={k} type="button" className={tab === k ? "is-on" : ""} onClick={() => setTab(k)} data-itab={k}>{t}</button>
        ))}
      </div>
      <div className="vw-scroll">
        {tab === "clip" && <ClipTab {...p} />}
        {tab === "fx" && <EffectsTab {...p} />}
        {tab === "out" && <ExportTab {...p} />}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════ قطعه

function ClipTab({ project, selected, edit, media, playhead }: Props) {
  if (!selected) {
    return (
      <p className="ws-hint" data-testid="no-selection">
        یک قطعه را روی تایم‌لاین انتخاب کنید تا ویژگی‌هایش (جا، اندازه، شفافیت، صدا، سرعت، محوشدن، گذار) این‌جا بیاید.
        <br />میان‌برها: Space پخش · S تقسیم · Delete حذف · Shift+Delete حذفِ بی‌فاصله · Q/W کوتاه کردن تا سرِ پخش · Ctrl+Z برگشت
      </p>
    );
  }
  const { clip } = selected;
  const id = clip.id;
  const upd = (patch: Partial<MediaClip> | Partial<TextClip>) => (pr: Project) => ({
    ...pr, tracks: pr.tracks.map((t) => ({ ...t, clips: t.clips.map((c) => (c.id === id ? ({ ...c, ...patch } as AnyClip) : c)) })),
  });
  const live = (patch: Partial<MediaClip> | Partial<TextClip>) => edit.live(upd(patch));
  const set = (label: string, patch: Partial<MediaClip> | Partial<TextClip>) => edit.apply(label, upd(patch));

  if (clip.type === "text") {
    return (
      <div data-testid="clip-text">
        <div className="ws-card-title">متن روی تصویر</div>
        <label className="ws-field"><span>متن</span>
          <textarea className="u-input" rows={3} value={clip.text} aria-label="متن" onChange={(e) => live({ text: e.target.value, label: e.target.value.slice(0, 20) })} onBlur={() => edit.end("متن")} />
        </label>
        <label className="ws-field"><span>جا</span>
          <select className="u-input" value={clip.position} onChange={(e) => set("جای متن", { position: e.target.value as TextClip["position"] })}>
            <option value="top">بالا</option><option value="middle">وسط</option><option value="bottom">پایین</option>
          </select>
        </label>
        <Row label="اندازه (٪ ارتفاع)" value={clip.size} min={1} max={20} step={0.5} onLive={(v) => live({ size: v })} onEnd={() => edit.end("اندازهٔ متن")} />
        <Row label="شفافیت" value={clip.opacity} min={0.05} max={1} onLive={(v) => live({ opacity: v })} onEnd={() => edit.end("شفافیتِ متن")} />
        <div className="flex items-center gap-3">
          <label className="ws-field"><span>رنگ</span><input type="color" value={clip.color} onChange={(e) => set("رنگِ متن", { color: e.target.value })} aria-label="رنگ" /></label>
          <label className="ws-check"><input type="checkbox" checked={clip.box} onChange={(e) => set("زمینهٔ متن", { box: e.target.checked })} /> زمینهٔ تیره</label>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <Num label="شروع (ثانیه)" value={clip.at} onChange={(v) => set("زمانِ متن", { at: Math.max(0, v) })} />
          <Num label="مدت (ثانیه)" value={clip.duration} min={0.1} onChange={(v) => set("مدتِ متن", { duration: Math.max(0.1, v) })} />
        </div>
      </div>
    );
  }

  const item = media[clip.ref];
  const audioOnly = selected.track.kind === "audio";
  const len = clipLength(clip);
  return (
    <div data-testid="clip-media">
      <div className="ws-card-title">{clip.label}</div>
      <p className="ws-hint" dir="ltr">{timecode(clip.at)} → {timecode(clip.at + len)} ({fa(Math.round(len * 100) / 100)}s){item?.height ? ` · ${item.width}×${item.height}` : ""}</p>
      <div className="grid grid-cols-3 gap-2">
        <Num label="جا (ثانیه)" value={clip.at} onChange={(v) => set("جابه‌جایی", { at: Math.max(0, v) })} />
        <Num label={clip.kind === "image" ? "—" : "از منبع"} value={clip.start} onChange={(v) => clip.kind !== "image" && set("نقطهٔ شروع", { start: Math.max(0, Math.min(clip.end - 0.1, v)) })} />
        <Num label={clip.kind === "image" ? "مدت" : "تا منبع"} value={clip.end} onChange={(v) => set("نقطهٔ پایان", { end: Math.max(clip.start + 0.1, clip.src ? Math.min(clip.src, v) : v) })} />
      </div>

      {!audioOnly && (
        <>
          <div className="ws-group-title">تصویر</div>
          <Row label="شفافیت" value={clip.opacity} min={0} max={1} onLive={(v) => live({ opacity: v })} onEnd={() => edit.end("شفافیت")} />
          <label className="ws-field"><span>جا دادن در کادر</span>
            <select className="u-input" value={clip.fit} onChange={(e) => set("جا دادن", { fit: e.target.value as MediaClip["fit"] })} data-testid="fit">
              <option value="cover">پر کردنِ کادر (برش)</option><option value="contain">کاملِ تصویر (نوارِ سیاه)</option><option value="stretch">کشیده</option>
            </select>
          </label>
          <div className="grid grid-cols-2 gap-x-3">
            <Row label="چپ ٪" value={clip.x * 100} min={0} max={95} step={1} onLive={(v) => live({ x: v / 100, width: Math.min(clip.width, 1 - v / 100) })} onEnd={() => edit.end("جا")} />
            <Row label="بالا ٪" value={clip.y * 100} min={0} max={95} step={1} onLive={(v) => live({ y: v / 100, height: Math.min(clip.height, 1 - v / 100) })} onEnd={() => edit.end("جا")} />
            <Row label="پهنا ٪" value={clip.width * 100} min={5} max={100} step={1} onLive={(v) => live({ width: Math.min(v / 100, 1 - clip.x) })} onEnd={() => edit.end("اندازه")} />
            <Row label="ارتفاع ٪" value={clip.height * 100} min={5} max={100} step={1} onLive={(v) => live({ height: Math.min(v / 100, 1 - clip.y) })} onEnd={() => edit.end("اندازه")} />
          </div>
          <button type="button" className="ws-link" onClick={() => set("تمام‌قاب", { x: 0, y: 0, width: 1, height: 1 })}>تمام‌قاب</button>
        </>
      )}

      <div className="ws-group-title">زمان</div>
      <Row label="سرعت" value={clip.speed} min={0.25} max={4} step={0.05} unit="×" onLive={(v) => live({ speed: v })} onEnd={() => edit.end("سرعت")} />
      <Row label="محو در ابتدا" value={clip.fade_in} min={0} max={Math.max(0.1, Math.min(5, len / 2))} step={0.05} unit="s" onLive={(v) => live({ fade_in: v })} onEnd={() => edit.end("محوِ ابتدا")} />
      <Row label="محو در انتها" value={clip.fade_out} min={0} max={Math.max(0.1, Math.min(5, len / 2))} step={0.05} unit="s" onLive={(v) => live({ fade_out: v })} onEnd={() => edit.end("محوِ انتها")} />

      {(clip.has_audio || audioOnly) && (
        <>
          <div className="ws-group-title">صدا</div>
          {!audioOnly && (
            <label className="ws-check mb-2"><input type="checkbox" checked={clip.audio_on} onChange={(e) => set("صدای قطعه", { audio_on: e.target.checked })} /> صدای خودِ ویدیو پخش شود</label>
          )}
          <Row label="بلندی صدا" value={clip.volume} min={0} max={3} step={0.05} unit="×" onLive={(v) => live({ volume: v })} onEnd={() => edit.end("بلندیِ صدا")} />
          <p className="ws-hint">بیش از ۱× فقط در خروجی اعمال می‌شود؛ پیش‌نمایشِ مرورگر تا ۱× است.</p>
        </>
      )}

      {!audioOnly && (
        <>
          <div className="ws-group-title">گذار از قطعهٔ قبلی</div>
          <div className="flex flex-wrap gap-1" data-testid="transition">
            {([[null, "بی‌گذار"], ["fade", "محو به سیاه"], ["crossfade", "محوشدنِ تدریجی"]] as const).map(([k, t]) => (
              <button key={String(k)} type="button" className={`ws-chip ${(clip.transition?.kind ?? null) === k ? "is-on" : ""}`}
                onClick={() => set("گذار", { transition: k ? { kind: k, duration: clip.transition?.duration ?? 0.6 } : null })} data-transition={String(k)}>{t}</button>
            ))}
          </div>
          {clip.transition && (
            <Row label="مدتِ گذار" value={clip.transition.duration} min={0.1} max={2} step={0.05} unit="s"
              onLive={(v) => live({ transition: { ...clip.transition!, duration: v } })} onEnd={() => edit.end("مدتِ گذار")} />
          )}
          <p className="ws-hint">گذار وقتی کار می‌کند که این قطعه درست بعد از قطعهٔ قبلیِ همان ترک بیاید.</p>
        </>
      )}
      <p className="ws-hint">سرِ پخش: {timecode(playhead)}</p>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════ افکت‌ها

function EffectsTab({ project, selected, edit, tools, onSubtitles, hasSubtitleSource }: Props) {
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

// ═══════════════════════════════════════════════════════════════ خروجی

function ExportTab({ project, edit, title, onTitle, check, saving, projects, projectId, onOpenProject, onDeleteProject, render, onRender }: Props) {
  const f = project.format;
  const setFormat = (patch: Partial<Project["format"]>) => edit.apply("قابِ خروجی", (pr) => ({ ...pr, format: { ...pr.format, ...patch } }));
  return (
    <div data-testid="export-pane">
      <div className="ws-card">
        <div className="ws-card-title">پروژه</div>
        <label className="ws-field"><span>نام</span><input className="u-input" value={title} onChange={(e) => onTitle(e.target.value)} aria-label="نامِ پروژه" data-testid="project-title" /></label>
        <div className="flex flex-wrap items-center gap-2 text-xs" style={{ color: "var(--text-2)" }}>
          <Badge tone={saving === "saved" ? "ok" : saving === "error" ? "bad" : "neutral"}>
            {saving === "saving" ? "در حالِ ذخیره…" : saving === "saved" ? "ذخیره شد" : saving === "error" ? "ذخیره نشد" : "ذخیرهٔ خودکار"}
          </Badge>
          <select className="u-input !w-auto" value={projectId ?? ""} onChange={(e) => onOpenProject(e.target.value ? Number(e.target.value) : null)} aria-label="پروژه‌ها" data-testid="project-select">
            <option value="">پروژهٔ تازه</option>
            {projects.map((p) => <option key={p.id} value={p.id}>{p.title || `پروژه ${p.id}`}</option>)}
          </select>
          {projectId && <button type="button" className="ws-link" onClick={onDeleteProject}>حذفِ این پروژه</button>}
        </div>
      </div>

      <div className="ws-card">
        <div className="ws-card-title">قاب و کیفیت</div>
        <label className="ws-field"><span>قاب</span>
          <select className="u-input" value={FORMATS.find((x) => x.width === f.width && x.height === f.height)?.key ?? "custom"} data-testid="format-select"
            onChange={(e) => { const x = FORMATS.find((y) => y.key === e.target.value); if (x) setFormat({ width: x.width, height: x.height, preset: x.key }); }}>
            {FORMATS.map((x) => <option key={x.key} value={x.key}>{x.title} — {fa(x.width)}×{fa(x.height)}</option>)}
            <option value="custom">دلخواه</option>
          </select>
        </label>
        <div className="grid grid-cols-3 gap-2">
          <Num label="عرض" step={2} min={240} value={f.width} onChange={(v) => setFormat({ width: Math.max(240, Math.min(3840, Math.round(v / 2) * 2)), preset: "custom" })} />
          <Num label="ارتفاع" step={2} min={240} value={f.height} onChange={(v) => setFormat({ height: Math.max(240, Math.min(3840, Math.round(v / 2) * 2)), preset: "custom" })} />
          <label className="ws-field"><span>فریم/ثانیه</span>
            <select className="u-input" value={f.fps} onChange={(e) => setFormat({ fps: Number(e.target.value) })}>{[24, 25, 30, 60].map((n) => <option key={n} value={n}>{fa(n)}</option>)}</select>
          </label>
        </div>
      </div>

      <div className="ws-card" data-testid="render-card">
        <div className="ws-card-title">رندر</div>
        {check && !check.ok && <Alert tone="bad">{check.error}</Alert>}
        {check?.ok && (
          <p className="ws-hint" data-testid="check-ok">
            آماده‌ی رندر: {fa(Math.round((check.length ?? 0) * 10) / 10)} ثانیه · {check.size}
            {(check.gaps ?? []).length > 0 ? ` · ${fa((check.gaps ?? []).length)} فاصلهٔ خالی (سیاه) در ترکِ اصلی` : ""}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" onClick={() => onRender("draft")} disabled={render.busy || !check?.ok} data-testid="render-draft" title="سریع و کم‌حجم؛ برای دیدنِ نتیجه">پیش‌نویسِ سریع</Button>
          <Button size="sm" onClick={() => onRender("final")} disabled={render.busy || !check?.ok} data-testid="render-final">رندرِ نهایی</Button>
        </div>
        {render.busy && <div className="mt-2 flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }} data-testid="render-progress"><Spinner size={16} /> {render.label || "در حالِ رندر…"}</div>}
        {render.error && <div className="mt-2"><Alert tone="bad">{render.error}</Alert></div>}
        {render.row?.state === "READY" && render.row.output_url && (
          <div className="mt-3" data-testid="render-result">
            <video src={render.row.output_url} controls playsInline style={{ width: "100%", maxHeight: 260, background: "#000", borderRadius: 8 }} />
            <p className="ws-hint">
              {fa(Math.round((render.row.render_info.seconds ?? 0) * 10) / 10)} ثانیه · {render.row.render_info.size} · {fa(Math.round((render.row.render_info.bytes ?? 0) / 1024))} KB
              {render.row.render_info.program_tools?.length ? ` · افکتِ کل: ${render.row.render_info.program_tools.length}` : ""}
            </p>
            {(render.row.render_info.refusals ?? []).length > 0 && <Alert tone="warn" title="این‌ها انجام نشد">{(render.row.render_info.refusals ?? []).join(" · ")}</Alert>}
            <a href={render.row.output_url} download><Button size="sm" variant="secondary">دانلود</Button></a>
          </div>
        )}
        <p className="ws-hint mt-2">خروجی همیشه از فایل‌های اصلی ساخته می‌شود، نه از پیش‌نمایشِ سبک.</p>
      </div>
    </div>
  );
}

export { findClip };
