import { Badge } from "../../../../components/ui";
import { fa } from "../../../../components/ui";
import type { ToolInfo } from "../../ToolPicker";
import type { Catalogue, Check, MediaItem, ProjectRow } from "../api";
import type { AudioEngine } from "./AudioEngine";
import AudioPanel from "./AudioPanel";
import CaptionsPanel from "./CaptionsPanel";
import ClipInspector from "./ClipInspector";
import ColorPanel from "./ColorPanel";
import type { LookDef } from "./color";
import { Num } from "./controls";
import EffectsTab from "./EffectsTab";
import ExportPanel from "./ExportPanel";
import MixerPanel from "./MixerPanel";
import {
  AnyClip, AttrGroup, DEFAULT_DUCKING, DEFAULT_MASTER, ExportBlock, FORMATS, MediaClip, Project, TextClip, Track, clipLength, timecode, updateClips, updateTrack,
} from "./model";
import TextPanel from "./TextPanel";
import "./inspector.css";

export type InspectorTab = "clip" | "color" | "audio" | "text" | "fx" | "mixer" | "captions" | "out";

type Edit = {
  live: (fn: (p: Project) => Project) => void;
  end: (label: string) => void;
  apply: (label: string, fn: (p: Project) => Project) => void;
};

export type InspectorProps = {
  storeId: string;
  project: Project;
  selection: string[];
  selected: { track: Track; clip: AnyClip } | null;
  playhead: number;
  tools: ToolInfo[];
  media: Record<string, MediaItem>;
  edit: Edit;
  cat: Catalogue | null;
  looks: LookDef[];
  tab: InspectorTab;
  onTab: (t: InspectorTab) => void;
  title: string;
  onTitle: (t: string) => void;
  check: Check | null;
  saving: "idle" | "saving" | "saved" | "error";
  projects: ProjectRow[];
  projectId: number | null;
  onOpenProject: (id: number | null) => void;
  onDeleteProject: () => void;
  engine: AudioEngine | null;
  thumbSource: () => HTMLCanvasElement | null;
  onCompare: (on: boolean) => void;
  hasClipboard: boolean;
  onCopyAttrs: (groups: AttrGroup[]) => void;
  onPasteAttrs: () => void;
  onExtractAudio: () => void;
  onUnlink: () => void;
  onFreeze: () => void;
  onJLCut: (kind: "J" | "L") => void;
  linked: boolean;
  onRender: (q: "draft" | "final") => Promise<void>;
  renderBusy: boolean;
  onSubtitles: (ref: string) => void;
  hasSubtitleSource: boolean;
  onInsertCaptions: (clips: Partial<TextClip>[]) => void;
  onNotice: (m: string) => void;
  onBeats: () => void;
  beatsBusy: boolean;
};

const TABS: { key: InspectorTab; title: string }[] = [
  { key: "clip", title: "قطعه" },
  { key: "color", title: "رنگ" },
  { key: "audio", title: "صدا" },
  { key: "text", title: "متن" },
  { key: "fx", title: "افکت‌ها" },
  { key: "mixer", title: "میکسر" },
  { key: "captions", title: "زیرنویس" },
  { key: "out", title: "خروجی" },
];

export default function Inspector(p: InspectorProps) {
  const { tab, onTab, selected } = p;
  const kind = selected ? (selected.clip.type === "text" ? "text" : selected.track.kind === "audio" ? "audio" : "media") : null;
  return (
    <div className="vw-inspector" dir="rtl" data-testid="inspector">
      <div className="ws-tabs ins-tabs">
        {TABS.map((t) => (
          <button key={t.key} type="button" className={tab === t.key ? "is-on" : ""} onClick={() => onTab(t.key)} data-itab={t.key}>
            {t.title}{t.key === "text" && kind === "text" ? " •" : ""}
          </button>
        ))}
      </div>
      <div className="vw-scroll">
        {tab === "clip" && <ClipTab {...p} kind={kind} />}
        {tab === "color" && <ColorTab {...p} kind={kind} />}
        {tab === "audio" && <AudioTab {...p} kind={kind} />}
        {tab === "text" && <TextTab {...p} kind={kind} />}
        {tab === "fx" && <EffectsTab project={p.project} selected={p.selected} edit={p.edit} tools={p.tools} onSubtitles={p.onSubtitles} hasSubtitleSource={p.hasSubtitleSource} />}
        {tab === "mixer" && <MixerTab {...p} />}
        {tab === "captions" && (
          <CaptionsPanel storeId={p.storeId} project={p.project} selectionIds={p.selection} onInsert={p.onInsertCaptions} onNotice={p.onNotice}
            onImportSrt={p.hasSubtitleSource && selected && selected.clip.type === "media" ? () => p.onSubtitles((selected.clip as MediaClip).ref) : undefined}
            hasSrtSource={p.hasSubtitleSource} />
        )}
        {tab === "out" && <OutTab {...p} />}
      </div>
    </div>
  );
}

type KindProps = InspectorProps & { kind: "text" | "audio" | "media" | null };

function Empty({ what }: { what: string }) {
  return <p className="ws-hint" data-testid="no-selection">{what}</p>;
}

const HELP = (
  <>
    یک قطعه را روی تایم‌لاین انتخاب کنید تا ویژگی‌هایش (جا، اندازه، چرخش، شفافیت، سرعت، گذار، رنگ، صدا) این‌جا بیاید.
    <br />ابزارها: V انتخاب · C تیغه · B ریپل · N رول · Y اسلیپ · U اسلاید · R تغییرِ سرعت · A انتخابِ ترک به جلو
    <br />Space پخش · S تقسیم · Delete حذف · Shift+Delete حذفِ بی‌فاصله · Q/W کوتاه کردن تا سرِ پخش · I/O ورودی/خروجی · M نشانگر · Ctrl+Z برگشت
  </>
);

function ClipTab(p: KindProps) {
  const { selected } = p;
  if (!selected) return <p className="ws-hint" data-testid="no-selection">{HELP}</p>;
  if (selected.clip.type === "text") {
    return (
      <div>
        <p className="ws-hint">متن انتخاب شده؛ ویژگی‌هایش در تبِ «متن» است.</p>
        <button type="button" className="ws-btn" onClick={() => p.onTab("text")}>رفتن به تبِ متن</button>
      </div>
    );
  }
  return (
    <ClipInspector
      clip={selected.clip} track={selected.track} ids={p.selection} playhead={p.playhead} item={p.media[selected.clip.ref]} cat={p.cat} edit={p.edit}
      hasClipboard={p.hasClipboard} onCopyAttrs={p.onCopyAttrs} onPasteAttrs={p.onPasteAttrs} onExtractAudio={p.onExtractAudio}
      onUnlink={p.onUnlink} onFreeze={p.onFreeze} onJLCut={p.onJLCut} linked={p.linked}
    />
  );
}

function ColorTab(p: KindProps) {
  const { selected, edit } = p;
  if (!selected || selected.clip.type !== "media" || selected.track.kind !== "video") return <Empty what="برای تنظیمِ رنگ یک قطعهٔ تصویر یا عکس را انتخاب کنید (چند قطعه = همه با هم)." />;
  if (!p.cat) return <Empty what="در حالِ بارگیریِ ابزارهای رنگ…" />;
  const clip = selected.clip;
  const ids = p.selection;
  return (
    <ColorPanel
      clip={clip} cat={p.cat.color} thumbSource={p.thumbSource} onCompare={p.onCompare}
      onLive={(color) => edit.live((pr) => updateClips(pr, ids, { color } as Partial<MediaClip>))}
      onEnd={(label) => edit.end(label)}
      onApply={(label, color) => edit.apply(label, (pr) => updateClips(pr, ids, { color } as Partial<MediaClip>))}
    />
  );
}

function AudioTab(p: KindProps) {
  const { selected, edit } = p;
  if (!selected || selected.clip.type !== "media") return <Empty what="برای تنظیمِ صدا یک قطعهٔ ویدیو یا صدا را انتخاب کنید. تنظیمِ کلِ ترک‌ها در تبِ «میکسر» است." />;
  const clip = selected.clip;
  const ids = p.selection;
  if (clip.kind === "image") return <Empty what="عکس صدا ندارد." />;
  return (
    <AudioPanel
      clip={clip} trackKind={selected.track.kind === "audio" ? "audio" : "video"} playhead={p.playhead}
      onLive={(patch) => edit.live((pr) => updateClips(pr, patch.kf ? [clip.id] : ids, patch))}
      onEnd={(label) => edit.end(label)}
      onApply={(label, patch) => edit.apply(label, (pr) => updateClips(pr, patch.kf ? [clip.id] : ids, patch))}
      onExtractAudio={p.onExtractAudio} onBeats={clip.kind === "audio" || clip.has_audio ? p.onBeats : undefined} beatsBusy={p.beatsBusy}
    />
  );
}

function TextTab(p: KindProps) {
  const { selected, edit } = p;
  if (!selected || selected.clip.type !== "text") {
    return (
      <div>
        <Empty what="یک متن را روی تایم‌لاین انتخاب کنید، یا با «T+ متن» متنِ تازه بسازید." />
      </div>
    );
  }
  if (!p.cat) return <Empty what="در حالِ بارگیریِ قالب‌های متن…" />;
  const clip = selected.clip;
  const ids = p.selection.filter((id) => p.project.tracks.some((t) => t.clips.some((c) => c.id === id && c.type === "text")));
  const caps = p.project.tracks.flatMap((t) => t.clips).filter((c): c is TextClip => c.type === "text" && !!c.caption);
  return (
    <TextPanel
      clip={clip} cat={p.cat.titles} playhead={p.playhead}
      onLive={(patch) => edit.live((pr) => updateClips(pr, ids.length ? ids : [clip.id], patch))}
      onEnd={(label) => edit.end(label)}
      onApply={(label, patch) => edit.apply(label, (pr) => updateClips(pr, ids.length ? ids : [clip.id], patch))}
      captionCount={caps.length}
      onApplyToCaptions={(patch) => edit.apply("سبکِ همهٔ زیرنویس‌ها", (pr) => updateClips(pr, caps.map((c) => c.id), patch))}
    />
  );
}

function MixerTab(p: InspectorProps) {
  const { edit } = p;
  return (
    <MixerPanel
      project={p.project} engine={p.engine}
      onTrackLive={(id, patch) => edit.live((pr) => updateTrack(pr, id, patch))}
      onTrackEnd={(label) => edit.end(label)}
      onTrackApply={(id, label, patch) => edit.apply(label, (pr) => updateTrack(pr, id, patch))}
      onMasterLive={(patch) => edit.live((pr) => ({ ...pr, master: { ...(pr.master ?? DEFAULT_MASTER), ...patch } }))}
      onMasterEnd={() => edit.end("میکسرِ اصلی")}
      onDucking={(patch) => edit.apply("کم‌کردنِ خودکارِ موسیقی", (pr) => ({ ...pr, ducking: { ...(pr.ducking ?? DEFAULT_DUCKING), ...patch } }))}
    />
  );
}

function OutTab(p: InspectorProps) {
  const { project, edit, title, onTitle, saving, projects, projectId, onOpenProject, onDeleteProject } = p;
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
            {projects.map((r) => <option key={r.id} value={r.id}>{r.title || `پروژه ${r.id}`}</option>)}
          </select>
          {projectId && <button type="button" className="ws-link" onClick={onDeleteProject}>حذفِ این پروژه</button>}
        </div>
      </div>

      <div className="ws-card">
        <div className="ws-card-title">قابِ پروژه</div>
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
            <select className="u-input" value={f.fps} onChange={(e) => setFormat({ fps: Number(e.target.value) })}>{[24, 25, 30, 50, 60].map((n) => <option key={n} value={n}>{fa(n)}</option>)}</select>
          </label>
        </div>
      </div>

      {p.cat ? (
        <ExportPanel
          storeId={p.storeId} projectId={projectId} project={project} check={p.check} cat={p.cat.export} busy={p.renderBusy}
          onExport={(block: ExportBlock) => edit.apply("تنظیماتِ خروجی", (pr) => ({ ...pr, export: block }))}
          onRender={p.onRender}
        />
      ) : <p className="ws-hint">در حالِ بارگیریِ تنظیماتِ خروجی…</p>}
    </div>
  );
}

export { clipLength, timecode };
