import { useRef, useState } from "react";

import { usePlayhead } from "./playhead";

import { Alert, Badge, Spinner, fa } from "../../../../components/ui";
import type { Bin, LutRow, MatteRow, MatteStatus, MediaItem } from "../api";
import { Chips, Section, Slider } from "./controls";
import { beatTimes, multicamLength, seqIdOf, seqLength } from "./ops";
import { AnyClip, MediaClip, Project, ShapeKind, Track, isMedia, timecode } from "./model";
import { SHAPES } from "./shapes";
import "./propanel.css";

/**
 * تبِ «ابزارها»: شکل و استیکر، توالیِ تودرتو، مولتی‌کم، قطعِ خودکار روی ضرب‌ها، ردیابیِ حرکت، LUT و حذفِ پس‌زمینه.
 * فقط نمایش و دکمه است؛ هر کاری را VideoWorkspace انجام می‌دهد (تا همه‌چیز در یک گامِ برگشت/جلو بنشیند).
 */
type Edit = {
  live: (fn: (p: Project) => Project) => void;
  end: (label: string) => void;
  apply: (label: string, fn: (p: Project) => Project) => void;
};

export type FrameRect = { x: number; y: number; w: number; h: number };
export type SyncRow = { ref: string; label: string; offset: number; confidence: number; ok: boolean };

export type ProProps = {
  project: Project;
  root: Project;
  path: string[];
  selection: string[];
  selected: { track: Track; clip: AnyClip } | null;
  media: Record<string, MediaItem>;
  bin: Bin | null;
  edit: Edit;
  // شکل و استیکر
  onAddShape: (kind: ShapeKind) => void;
  onAddMedia: (item: MediaItem) => void;
  // توالیِ تودرتو
  onNest: () => void;
  onOpenSeq: (id: string) => void;
  onCloseSeq: () => void;
  onUnnest: () => void;
  // مولتی‌کم
  syncBusy: boolean;
  syncRows: SyncRow[] | null;
  syncError: string | null;
  onSync: () => void;
  onCreateMulticam: (useSync: boolean) => void;
  onAngle: (angle: number) => void;
  onRemoveCut: (index: number) => void;
  onMulticamAudio: (angle: number) => void;
  // قطعِ روی ضرب
  onBeats: () => void;
  beatsBusy: boolean;
  onBeatCut: (mode: "split" | "fit" | "snap", every: number) => void;
  // ردیابی
  pickRegion: boolean;
  region: FrameRect | null;
  onPickRegion: (on: boolean) => void;
  trackBusy: string | null;
  trackError: string | null;
  onTrack: (opts: { fps: number; seconds: number }) => void;
  onAttach: (trackerId: string, mask: boolean) => void;
  onDetach: (mask: boolean) => void;
  onDeleteTracker: (id: string) => void;
  // LUT
  luts: LutRow[];
  lutBusy: boolean;
  onImportLut: (file: File) => void;
  onDeleteLut: (key: string) => void;
  // مات
  matteStatus: MatteStatus | null;
  mattes: MatteRow[];
  matteBusy: string | null;
  matteError: string | null;
  onMakeMatte: (fps: number) => void;
  onDeleteMatte: (key: string) => void;
};

const sel = (p: ProProps): MediaClip | null => (p.selected && isMedia(p.selected.clip) ? p.selected.clip : null);

export default function ProPanel(p: ProProps) {
  const clip = sel(p);
  return (
    <div data-testid="pro-panel">
      {p.path.length > 0 && (
        <Alert tone="info" title="داخلِ یک توالیِ تودرتو هستید" action={<button type="button" className="ws-btn" onClick={p.onCloseSeq} data-testid="seq-back">برگشت به توالیِ اصلی</button>}>
          هر ویرایشی که الان می‌کنید روی همان توالی می‌نشیند و در پروژهٔ اصلی هم دیده می‌شود.
        </Alert>
      )}
      <Graphics {...p} />
      <Nest {...p} clip={clip} />
      <Multicam {...p} clip={clip} />
      <Beats {...p} />
      <Tracking {...p} clip={clip} />
      <Luts {...p} clip={clip} />
      <Matte {...p} clip={clip} />
    </div>
  );
}

// ─────────────────────────────────────────────── شکل و استیکر
function Graphics(p: ProProps) {
  const stickers = p.bin?.stickers ?? [];
  return (
    <Section title="شکل و استیکر" defaultOpen testId="sec-graphics">
      <div className="ws-group-title">شکل (در سرِ پخش، روی بالاترین ترکِ تصویر)</div>
      <div className="flex flex-wrap gap-1" data-testid="shape-list">
        {SHAPES.map((s) => <button key={s.key} type="button" className="ws-chip" onClick={() => p.onAddShape(s.key)} data-shape={s.key}>{s.title}</button>)}
      </div>
      <p className="ws-hint">شکل یک تصویرِ کشیده‌شده است: رنگ، لبه و گرادیان را در تبِ «قطعه» عوض کنید؛ مثلِ هر عکسی حرکت، چرخش، ماسک و ردیابی می‌پذیرد.</p>
      <div className="ws-group-title">استیکرها</div>
      {stickers.length === 0 && <p className="ws-hint">استیکری در دسترس نیست.</p>}
      <div className="pp-stickers" data-testid="sticker-grid">
        {stickers.map((s) => (
          <button key={s.ref} type="button" className="pp-sticker" title={s.title} onClick={() => p.onAddMedia(s)} data-sticker={s.ref}>
            <img src={s.url} alt={s.title} loading="lazy" />
          </button>
        ))}
      </div>
    </Section>
  );
}

// ─────────────────────────────────────────────── توالیِ تودرتو
function Nest(p: ProProps & { clip: MediaClip | null }) {
  const sid = seqIdOf(p.clip);
  const seq = sid ? p.root.sequences?.[sid] : undefined;
  return (
    <Section title="توالیِ تودرتو (Nested)" testId="sec-nest" badge={sid ? <span className="ws-dot" /> : undefined}>
      <p className="ws-hint">چند قطعه (روی ترک‌های مختلف) را یک قطعه کنید؛ مثلِ یک ویدیو جابه‌جا، کند، بُرش و افکت می‌خورد، و هر وقت خواستید بازش کنید و تویش ادیت کنید.</p>
      <div className="flex flex-wrap gap-2">
        <button type="button" className="ws-btn" disabled={p.selection.length === 0} onClick={p.onNest} data-testid="nest-selection">ساختِ توالی از قطعه‌های انتخاب‌شده</button>
        {sid && <button type="button" className="ws-btn" onClick={() => p.onOpenSeq(sid)} data-testid="open-seq">باز کردن برای ویرایش</button>}
        {sid && <button type="button" className="ws-btn" onClick={p.onUnnest} data-testid="unnest">بازکردنِ توالی در همین پروژه</button>}
      </div>
      {seq && <p className="ws-hint">«{seq.name}» — {fa(Math.round(seqLength(seq) * 10) / 10)} ثانیه، {fa(seq.tracks.length)} ترک.</p>}
    </Section>
  );
}

// ─────────────────────────────────────────────── مولتی‌کم
type MulticamInfo = NonNullable<NonNullable<Project["sequences"]>[string]["multicam"]>;

/** زاویهٔ فعلی در سرِ پخش: تنها بخشی از تب که زمان را نشان می‌دهد (۱۴۰۵/۰۸/۲۳: مشترکِ انبارِ سرِ پخش؛ بقیهٔ تب با هر تیک ساخته نمی‌شود) */
function AnglesNow({ info, clip, onAngle }: { info: MulticamInfo; clip: MediaClip | null; onAngle: (angle: number) => void }) {
  const playhead = usePlayhead();
  const tn = clip ? Math.max(0, playhead - clip.at + clip.start) : 0;
  return (
    <>
      <div className="ws-group-title">زاویه در سرِ پخش ({timecode(tn)}) — کلیدِ ۱ تا {fa(Math.min(9, info.angles.length))}</div>
      <div className="flex flex-wrap gap-1" data-testid="mc-angles">
        {info.angles.map((a, i) => {
          const cur = [...info.cuts].reverse().find((c) => c.t <= tn + 0.001)?.angle === i;
          return <button key={i} type="button" className={`ws-chip ${cur ? "is-on" : ""}`} onClick={() => onAngle(i)} data-angle={i} title={`برش به «${a.label}» در سرِ پخش`}>{fa(i + 1)}· {a.label}</button>;
        })}
      </div>
    </>
  );
}

function Multicam(p: ProProps & { clip: MediaClip | null }) {
  const sid = seqIdOf(p.clip);
  const seq = sid ? p.root.sequences?.[sid] : undefined;
  const info = seq?.multicam;
  const vids = p.selection.map((id) => p.project.tracks.flatMap((t) => t.clips).find((c) => c.id === id)).filter((c): c is MediaClip => !!c && isMedia(c) && c.kind === "video" && !seqIdOf(c));
  const refs = [...new Set(vids.map((v) => v.ref))];
  return (
    <Section title="مولتی‌کم (چند دوربین)" testId="sec-multicam" badge={info ? <span className="ws-dot" /> : undefined}>
      {!info && (
        <>
          <p className="ws-hint">چند ضبط از یک رویداد (هرکدام یک زاویه) را انتخاب کنید (Ctrl+کلیک)؛ با صدای مشترک هم‌زمان می‌شوند و بعد می‌توانید روی تایم‌لاین بینِ زاویه‌ها سوییچ کنید.</p>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="ws-btn" disabled={refs.length < 2 || p.syncBusy} onClick={p.onSync} data-testid="mc-sync">
              {p.syncBusy ? <><Spinner size={12} /> در حالِ هم‌زمان‌سازی…</> : "هم‌زمان‌سازی با صدا"}
            </button>
            <button type="button" className="ws-btn primary" disabled={refs.length < 2} onClick={() => p.onCreateMulticam(!!p.syncRows)} data-testid="mc-create">
              {p.syncRows ? "ساختِ مولتی‌کم" : "ساختِ مولتی‌کم (بدونِ هم‌زمان‌سازی)"}
            </button>
          </div>
          {refs.length < 2 && <p className="ws-hint">دست‌کم دو ویدیوی متفاوت انتخاب کنید ({fa(refs.length)} انتخاب شده).</p>}
          {p.syncError && <p className="xp-warn">{p.syncError}</p>}
          {p.syncRows && (
            <ul className="pp-list" data-testid="mc-offsets">
              {p.syncRows.map((r, i) => (
                <li key={i}>
                  <span>{r.label}</span>
                  <span dir="ltr">{r.offset >= 0 ? "+" : ""}{r.offset.toFixed(3)}s</span>
                  <Badge tone={r.ok ? "ok" : "warn"}>{r.ok ? `اطمینان ${fa(Math.round(r.confidence * 100))}٪` : "صدای مشترک پیدا نشد"}</Badge>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      {info && (
        <>
          <AnglesNow info={info} clip={p.clip} onAngle={p.onAngle} />
          <div className="ws-group-title">صدا از</div>
          <Chips value={String(info.audio)} options={[{ key: "-1", title: "بی‌صدا" }, ...info.angles.map((a, i) => ({ key: String(i), title: a.label }))]} onPick={(k) => p.onMulticamAudio(Number(k))} />
          <div className="ws-group-title">برش‌ها ({fa(info.cuts.length)}) — طولِ کل {fa(Math.round(multicamLength(info) * 10) / 10)} ثانیه</div>
          <ul className="pp-list" data-testid="mc-cuts">
            {info.cuts.map((c, i) => (
              <li key={i}>
                <span dir="ltr">{timecode(c.t)}</span>
                <span>{info.angles[c.angle]?.label}</span>
                {i > 0 ? <button type="button" className="ws-link" onClick={() => p.onRemoveCut(i)}>حذف</button> : <span />}
              </li>
            ))}
          </ul>
        </>
      )}
    </Section>
  );
}

// ─────────────────────────────────────────────── ضرب‌ها
function Beats(p: ProProps) {
  const beats = beatTimes(p.project);
  const every = useRef(1);
  const mode = useRef<"split" | "fit" | "snap">("split");
  return (
    <Section title="قطعِ خودکار روی ضرب‌ها" testId="sec-beats" badge={beats.length ? <Badge tone="info">{fa(beats.length)}</Badge> : undefined}>
      <p className="ws-hint">اول از یک قطعهٔ موسیقی ضرب‌ها را پیدا کنید (تبِ «صدا» ⇐ «یافتنِ ضرب‌ها»، یا همین‌جا با قطعهٔ صدای انتخاب‌شده)؛ بعد روی نشانگرهای ضرب برش بزنید.</p>
      <div className="flex flex-wrap gap-2">
        <button type="button" className="ws-btn" disabled={p.beatsBusy || !p.selected} onClick={p.onBeats} data-testid="beats-find">{p.beatsBusy ? "در حالِ تحلیل…" : "یافتنِ ضرب‌ها از قطعهٔ انتخاب‌شده"}</button>
      </div>
      <BeatControls beats={beats.length} onApply={p.onBeatCut} every={every} mode={mode} />
    </Section>
  );
}

function BeatControls({ beats, onApply, every, mode }: { beats: number; onApply: (mode: "split" | "fit" | "snap", every: number) => void; every: React.MutableRefObject<number>; mode: React.MutableRefObject<"split" | "fit" | "snap"> }) {
  const [e, setE] = useState(every.current);
  const [m, setM] = useState(mode.current);
  return (
    <>
      <div className="ws-group-title">هر چند ضرب یک برش</div>
      <Chips value={String(e)} options={[{ key: "1", title: "هر ضرب" }, { key: "2", title: "هر ۲ ضرب" }, { key: "4", title: "هر ۴ ضرب" }]} onPick={(k) => { every.current = Number(k); setE(Number(k)); }} />
      <div className="ws-group-title">کار</div>
      <Chips value={m} options={[
        { key: "split", title: "بُریدنِ قطعهٔ انتخابی" }, { key: "fit", title: "چیدنِ قطعه‌ها (مونتاژ)" }, { key: "snap", title: "چسباندنِ برش‌ها به ضرب" },
      ]} onPick={(k) => { mode.current = k; setM(k); }} />
      <p className="ws-hint">
        {m === "split" ? "قطعه(های) انتخاب‌شده روی ضرب‌ها شکافته می‌شوند." : m === "fit" ? "قطعه‌های انتخاب‌شده به ترتیب روی بازه‌های بینِ ضرب‌ها می‌نشینند (کم باشند دور می‌زنند)." : "هر برشِ نزدیکِ یک ضرب (تا ۰٫۲۵ ثانیه) به همان ضرب می‌چسبد."}
      </p>
      <button type="button" className="ws-btn primary" disabled={beats < 2 && m !== "snap" || beats < 1} onClick={() => onApply(m, e)} data-testid="beats-apply">اعمال روی {fa(beats)} ضرب</button>
    </>
  );
}

// ─────────────────────────────────────────────── ردیابی
function Tracking(p: ProProps & { clip: MediaClip | null }) {
  const trackers = p.root.trackers ?? [];
  const c = p.clip;
  const isVideo = !!c && c.kind === "video" && !seqIdOf(c);
  const fps = useRef(15);
  const secs = useRef(8);
  const [target, setTarget] = useState<string>("");
  const follow = c?.follow ?? (p.selected?.clip.type === "text" ? p.selected.clip.follow : undefined);
  const maskFollow = c?.mask?.follow;
  const tid = target || trackers[0]?.id || "";
  return (
    <Section title="ردیابیِ حرکت (Motion tracking)" testId="sec-track" badge={trackers.length ? <Badge tone="info">{fa(trackers.length)}</Badge> : undefined}>
      <p className="ws-hint">یک نقطه یا ناحیه (مثلاً صورت، برچسبِ روی جعبه) را در ویدیو دنبال کنید؛ بعد ماسک، متن، استیکر یا شکل می‌تواند به آن بچسبد و با آن حرکت کند.</p>
      <div className="ws-group-title">ردیابِ تازه</div>
      <p className="ws-hint">{isVideo ? `قطعهٔ ویدیوییِ «${c!.label}» انتخاب است. سرِ پخش را روی فریمی بگذارید که ناحیه در آن دیده می‌شود، ناحیه را بکشید، شروع بزنید.` : "یک قطعهٔ ویدیویی را انتخاب کنید."}</p>
      <div className="flex flex-wrap gap-2 items-center">
        <button type="button" className={`ws-btn ${p.pickRegion ? "is-on" : ""}`} disabled={!isVideo} onClick={() => p.onPickRegion(!p.pickRegion)} data-testid="track-pick">
          {p.pickRegion ? "پایانِ انتخابِ ناحیه" : "ناحیه را روی تصویر بکشید"}
        </button>
        <label className="ws-field"><span>ثانیه</span>
          <select className="u-input" defaultValue={8} onChange={(e) => { secs.current = Number(e.target.value); }} aria-label="طولِ ردیابی">{[3, 5, 8, 12, 20, 30].map((n) => <option key={n} value={n}>{fa(n)}</option>)}</select>
        </label>
        <button type="button" className="ws-btn primary" disabled={!isVideo || !p.region || !!p.trackBusy} onClick={() => p.onTrack({ fps: fps.current, seconds: secs.current })} data-testid="track-start">
          {p.trackBusy ? <><Spinner size={12} /> {p.trackBusy}</> : "شروعِ ردیابی"}
        </button>
      </div>
      {p.trackError && <p className="xp-warn" data-testid="track-error">{p.trackError}</p>}
      {trackers.length > 0 && (
        <>
          <div className="ws-group-title">ردیاب‌ها</div>
          <ul className="pp-list" data-testid="tracker-list">
            {trackers.map((t) => (
              <li key={t.id}>
                <span>{t.name}</span>
                <span className="ws-muted">{fa(t.samples.length)} نمونه · {t.engine.startsWith("node") ? "سرورِ پردازش" : "سرورِ سایت"}{t.lost_at !== null ? " · از دست رفت" : ""}</span>
                <button type="button" className="ws-link" onClick={() => p.onDeleteTracker(t.id)}>حذف</button>
              </li>
            ))}
          </ul>
          <div className="ws-group-title">اتصالِ انتخاب‌شده به ردیاب</div>
          <div className="flex flex-wrap gap-2 items-center">
            <select className="u-input !w-auto" value={tid} onChange={(e) => setTarget(e.target.value)} aria-label="ردیاب" data-testid="track-select">
              {trackers.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
            <button type="button" className="ws-btn" disabled={!p.selected} onClick={() => p.onAttach(tid, false)} data-testid="track-attach">اتصالِ قطعه/متنِ انتخاب‌شده</button>
            <button type="button" className="ws-btn" disabled={!c?.mask || c.mask.shape === "none"} onClick={() => p.onAttach(tid, true)} data-testid="track-attach-mask">اتصالِ ماسکِ قطعه</button>
            {follow && <button type="button" className="ws-btn" onClick={() => p.onDetach(false)}>جدا کردن</button>}
            {maskFollow && <button type="button" className="ws-btn" onClick={() => p.onDetach(true)}>جدا کردنِ ماسک</button>}
          </div>
          {follow && <p className="ws-hint">این قطعه به «{trackers.find((t) => t.id === follow.tracker)?.name ?? "؟"}» وصل است؛ روی تصویر که بکشیدش فاصله‌اش از نقطه عوض می‌شود.</p>}
        </>
      )}
    </Section>
  );
}

// ─────────────────────────────────────────────── LUT
function Luts(p: ProProps & { clip: MediaClip | null }) {
  const file = useRef<HTMLInputElement>(null);
  const c = p.clip;
  const cur = c?.lut;
  const setLut = (key: string | null, amount = 1) => {
    if (!c) return;
    p.edit.apply(key ? "LUT" : "برداشتنِ LUT", (pr) => ({ ...pr, tracks: pr.tracks.map((t) => ({ ...t, clips: t.clips.map((x) => (p.selection.includes(x.id) && isMedia(x) && x.kind !== "audio" ? { ...x, lut: key ? { key, amount } : undefined } : x)) })) }));
  };
  return (
    <Section title="LUT (فایلِ .cube)" testId="sec-lut" badge={cur ? <span className="ws-dot" /> : undefined}>
      <input ref={file} type="file" accept=".cube,text/plain" hidden data-testid="lut-upload" onChange={(e) => { const f = e.target.files?.[0]; if (f) p.onImportLut(f); if (file.current) file.current.value = ""; }} />
      <button type="button" className="ws-btn" disabled={p.lutBusy} onClick={() => file.current?.click()}>{p.lutBusy ? "در حالِ بارگذاری…" : "+ واردکردنِ LUT"}</button>
      {p.luts.length === 0 && <p className="ws-hint">هنوز LUT ای نیست. فایل‌های .cube (سه‌بعدی، تا ۶۵) را از رنگ‌پرداز یا اینترنت بگیرید و این‌جا وارد کنید.</p>}
      <div className="flex flex-wrap gap-1 mt-1" data-testid="lut-list">
        {p.luts.map((l) => (
          <span key={l.key} className="pp-chip-wrap">
            <button type="button" className={`ws-chip ${cur?.key === l.key ? "is-on" : ""}`} disabled={!c || c.kind === "audio"} onClick={() => setLut(l.key, cur?.amount ?? 1)} data-lut={l.key} title={`${l.title} — ${fa(l.size)}³`}>{l.title}</button>
            <button type="button" className="pp-x" aria-label={`حذفِ ${l.title}`} onClick={() => p.onDeleteLut(l.key)}>×</button>
          </span>
        ))}
      </div>
      {cur && (
        <>
          <Slider label="شدتِ LUT" value={cur.amount * 100} min={0} max={100} step={1} unit="٪" digits={0} def={100}
            onLive={(v) => p.edit.live((pr) => ({ ...pr, tracks: pr.tracks.map((t) => ({ ...t, clips: t.clips.map((x) => (p.selection.includes(x.id) && isMedia(x) && x.lut ? { ...x, lut: { ...x.lut, amount: v / 100 } } : x)) })) }))}
            onEnd={() => p.edit.end("شدتِ LUT")} />
          <button type="button" className="ws-link" onClick={() => setLut(null)}>برداشتنِ LUT از این قطعه</button>
        </>
      )}
      <p className="ws-hint">پیش‌نمایشِ فوری تقریبی است؛ خروجی با `lut3d`ِ ffmpeg ساخته می‌شود.</p>
    </Section>
  );
}

// ─────────────────────────────────────────────── مات
function Matte(p: ProProps & { clip: MediaClip | null }) {
  const c = p.clip;
  const fps = useRef(6);
  const mine = c ? p.mattes.filter((m) => m.ref === c.ref) : [];
  const can = !!c && c.kind === "video" && !seqIdOf(c);
  const st = p.matteStatus;
  const fast = st?.engine === "rvm";            // مدلِ ویدیویی: همهٔ فریم‌ها پشتِ هم و با حافظهٔ زمانی؛ نرخِ نمونه را خودِ سرور می‌گذارد
  return (
    <Section title="حذفِ پس‌زمینهٔ ویدیو" testId="sec-matte" badge={c?.matte ? <span className="ws-dot" /> : undefined}>
      {st && !st.ok && <p className="xp-warn" data-testid="matte-status">{st.message}</p>}
      {st?.ok && (
        <p className="ws-hint" data-testid="matte-engine" data-engine={st.engine ?? "birefnet"}>
          سرورِ پردازشِ «{st.node}» آماده است.{" "}
          {fast
            ? "با مدلِ ویدیوییِ RVM همهٔ فریم‌ها پشتِ هم و با حافظهٔ فریمِ قبل بریده می‌شود؛ سریع است و لبه‌ها نمی‌پرند."
            : st.engine === "rvm-pending"
              ? "مدلِ ویدیوییِ RVM (۱۴ مگابایت) در اولین کار خودکار از سایت گرفته می‌شود؛ هر فریم جدا بریده می‌شود."
              : "هر فریم جدا بریده می‌شود (حدود چند ثانیه برای هر فریم)."}{" "}
          تا {fa(st.max_seconds)} ثانیه در هر بار.
        </p>
      )}
      <div className="flex flex-wrap gap-2 items-center">
        {!fast && (
          <label className="ws-field"><span>نمونه در ثانیه</span>
            <select className="u-input" defaultValue={6} onChange={(e) => { fps.current = Number(e.target.value); }} aria-label="نمونه در ثانیه">{[4, 6, 8, 12].map((n) => <option key={n} value={n}>{fa(n)}</option>)}</select>
          </label>
        )}
        <button type="button" className="ws-btn primary" disabled={!can || !st?.ok || !!p.matteBusy} onClick={() => p.onMakeMatte(fps.current)} data-testid="matte-start">
          {p.matteBusy ? <><Spinner size={12} /> {p.matteBusy}</> : "ساختِ مات از بازهٔ این قطعه"}
        </button>
      </div>
      {p.matteError && <p className="xp-warn" data-testid="matte-error">{p.matteError}</p>}
      {can && mine.length > 0 && (
        <ul className="pp-list" data-testid="matte-list">
          {mine.map((m) => (
            <li key={m.key}>
              <span dir="ltr">{timecode(m.s0).slice(0, 5)}–{timecode(m.s1).slice(0, 5)}</span>
              <span className="ws-muted">{fa(m.fps)}/s</span>
              <button type="button" className={`ws-chip ${c?.matte?.key === m.key ? "is-on" : ""}`} onClick={() => p.edit.apply("ماتِ حذفِ پس‌زمینه", (pr) => ({ ...pr, tracks: pr.tracks.map((t) => ({ ...t, clips: t.clips.map((x) => (x.id === c!.id && isMedia(x) ? { ...x, matte: c!.matte?.key === m.key ? undefined : { key: m.key } } : x)) })) }))} data-matte={m.key}>
                {c?.matte?.key === m.key ? "برداشتن" : "اعمال"}
              </button>
              <button type="button" className="ws-link" onClick={() => p.onDeleteMatte(m.key)}>حذف</button>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}
