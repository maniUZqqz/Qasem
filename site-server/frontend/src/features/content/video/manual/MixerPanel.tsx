import { useEffect, useRef, useState } from "react";

import { fa } from "../../../../components/ui";
import type { AudioEngine } from "./AudioEngine";
import { Slider, Toggle } from "./controls";
import { DEFAULT_DUCKING, Ducking, Master, Project, Track, TrackRole } from "./model";
import "./audio.css";

const ROLES: TrackRole[] = ["", "speech", "music", "sfx"];
const ROLE_TITLE: Record<TrackRole, string> = { "": "—", speech: "گفتار", music: "موسیقی", sfx: "افکت" };
const ROLE_HINT: Record<TrackRole, string> = {
  "": "نقش: ندارد (کلیک = گفتار)",
  speech: "نقش: گفتار — موسیقی زیرِ آن کم می‌شود (کلیک = موسیقی)",
  music: "نقش: موسیقی — زیرِ گفتار کم می‌شود (کلیک = افکت)",
  sfx: "نقش: افکت (کلیک = بی‌نقش)",
};

const clamp = (x: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, x));
/** دامنهٔ خطی ⇒ ۰..۱ روی مقیاسِ −۶۰..۰ دسی‌بل */
const levelFrac = (x: number) => clamp((20 * Math.log10(Math.max(x, 1e-5)) + 60) / 60, 0, 1);
const fmtDb = (v: number, min: number) => (v <= min + 0.01 ? "−∞" : `${v < 0 ? "−" : v > 0 ? "+" : ""}${fa(Math.abs(Math.round(v * 10) / 10))}`);

/** فیدرِ عمودیِ لمس‌پذیر (دسی‌بل). دوبار کلیک = بازنشانی، ↑/↓ = ۰٫۵ دسی‌بل (Shift = ۳). */
function Fader({
  value, min, max, label, onLive, onEnd, onReset,
}: { value: number; min: number; max: number; label: string; onLive: (v: number) => void; onEnd: () => void; onReset: () => void }) {
  const box = useRef<HTMLDivElement>(null);
  const drag = useRef(false);
  const pick = (e: React.PointerEvent) => {
    const el = box.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const u = clamp(1 - (e.clientY - r.top) / Math.max(1, r.height), 0, 1);
    onLive(Math.round((min + u * (max - min)) * 2) / 2);
  };
  const u = clamp((value - min) / (max - min), 0, 1);
  const zero = clamp((0 - min) / (max - min), 0, 1);
  return (
    <div
      ref={box} className="mx-fader" role="slider" tabIndex={0} aria-label={label} aria-orientation="vertical"
      aria-valuemin={min} aria-valuemax={max} aria-valuenow={Math.round(value * 10) / 10} data-fader={label}
      onPointerDown={(e) => { drag.current = true; e.currentTarget.setPointerCapture(e.pointerId); pick(e); }}
      onPointerMove={(e) => { if (drag.current) pick(e); }}
      onPointerUp={(e) => { if (drag.current) { drag.current = false; e.currentTarget.releasePointerCapture(e.pointerId); onEnd(); } }}
      onPointerCancel={() => { drag.current = false; }}
      onDoubleClick={onReset}
      onKeyDown={(e) => {
        const step = e.shiftKey ? 3 : 0.5;
        if (e.key === "ArrowUp" || e.key === "ArrowRight") { e.preventDefault(); onLive(clamp(value + step, min, max)); onEnd(); }
        else if (e.key === "ArrowDown" || e.key === "ArrowLeft") { e.preventDefault(); onLive(clamp(value - step, min, max)); onEnd(); }
        else if (e.key === "Home" || e.key === "0") { e.preventDefault(); onReset(); }
      }}
    >
      <i className="mx-rail" />
      <i className="mx-zero" style={{ bottom: `${zero * 100}%` }} />
      <i className="mx-thumb" style={{ bottom: `calc(${u * 100}% - 6px)` }} />
    </div>
  );
}

/** میترِ عمودی؛ ارتفاعِ پوشش و اوج را حلقهٔ انیمیشنِ MixerPanel مستقیم روی DOM می‌گذارد (بدونِ رندرِ React) */
function Meter({ id, refs }: { id: string; refs: React.MutableRefObject<Map<string, HTMLElement>> }) {
  return (
    <span className="mx-meter" aria-hidden>
      <i className="cover" ref={(el) => { if (el) refs.current.set(`${id}:cover`, el); else refs.current.delete(`${id}:cover`); }} />
      <b className="peak" ref={(el) => { if (el) refs.current.set(`${id}:peak`, el); else refs.current.delete(`${id}:peak`); }} />
    </span>
  );
}

function Strip({
  track, refs, onLive, onEnd, onApply,
}: {
  track: Track;
  refs: React.MutableRefObject<Map<string, HTMLElement>>;
  onLive: (patch: Partial<Track>) => void;
  onEnd: (label: string) => void;
  onApply: (label: string, patch: Partial<Track>) => void;
}) {
  const role: TrackRole = track.role ?? "";
  const gain = track.gain_db ?? 0;
  const pan = track.pan ?? 0;
  const nextRole = ROLES[(ROLES.indexOf(role) + 1) % ROLES.length];
  return (
    <div className={`mx-strip ${track.muted ? "is-muted" : ""}`} data-strip={track.id} data-kind={track.kind}>
      <span className="mx-name" title={track.name}>{track.kind === "video" ? "🎞 " : "🔊 "}{track.name}</span>
      <button type="button" className={`mx-role r-${role || "none"}`} title={ROLE_HINT[role]} aria-label={`نقشِ ترک ${track.name}`}
        onClick={() => onApply("نقشِ ترک", { role: nextRole })} data-role={track.id}>{ROLE_TITLE[role]}</button>
      <div className="mx-body">
        <Fader value={gain} min={-40} max={12} label={`بلندیِ ${track.name}`} onLive={(v) => onLive({ gain_db: v })} onEnd={() => onEnd("بلندیِ ترک")}
          onReset={() => onApply("بلندیِ ترک", { gain_db: 0 })} />
        <Meter id={track.id} refs={refs} />
      </div>
      <span className="mx-db" dir="ltr">{fmtDb(gain, -40)} dB</span>
      <input type="range" className="mx-pan" min={-1} max={1} step={0.05} value={pan} aria-label={`پنِ ${track.name}`}
        onChange={(e) => onLive({ pan: Number(e.target.value) })} onPointerUp={() => onEnd("پنِ ترک")} onKeyUp={() => onEnd("پنِ ترک")}
        onDoubleClick={() => onApply("پنِ ترک", { pan: 0 })} />
      <span className="mx-pan-val">{Math.abs(pan) < 0.03 ? "وسط" : `${pan < 0 ? "چپ" : "راست"} ${fa(Math.round(Math.abs(pan) * 100))}`}</span>
      <div className="mx-ms">
        <button type="button" className={`mx-btn m ${track.muted ? "is-on" : ""}`} aria-pressed={track.muted} title="بی‌صدا (Mute)"
          onClick={() => onApply("بی‌صدا", { muted: !track.muted })} data-mixmute={track.id}>M</button>
        <button type="button" className={`mx-btn s ${track.solo ? "is-on" : ""}`} aria-pressed={!!track.solo} title="فقط این ترک (Solo)"
          onClick={() => onApply("Solo", { solo: !track.solo })} data-mixsolo={track.id}>S</button>
      </div>
    </div>
  );
}

function DuckingCard({ project, onDucking }: { project: Project; onDucking: (patch: Partial<Ducking>) => void }) {
  const d = project.ducking ?? DEFAULT_DUCKING;
  const [draft, setDraft] = useState<Partial<Ducking>>({});
  const ref = useRef<Partial<Ducking>>({});
  ref.current = draft;
  const v = { ...d, ...draft };
  const live = (k: keyof Ducking) => (x: number) => setDraft((cur) => ({ ...cur, [k]: x }));
  const end = (k: keyof Ducking) => () => {
    const x = ref.current[k];
    if (x === undefined) return;
    onDucking({ [k]: x } as Partial<Ducking>);
    setDraft((cur) => { const { [k]: _gone, ...rest } = cur; void _gone; return rest; });
  };
  const speech = project.tracks.some((t) => t.kind !== "text" && t.role === "speech" && t.clips.length > 0);
  const music = project.tracks.some((t) => t.kind !== "text" && t.role === "music" && t.clips.length > 0);
  return (
    <div className="ws-card mx-duck" data-testid="ducking">
      <div className="ws-card-title">کم‌کردنِ خودکارِ موسیقی زیرِ گفتار</div>
      <Toggle label="روشن" checked={d.on} onChange={(on) => onDucking({ on })} />
      <p className="ws-hint">
        وقتی در ترک‌های «گفتار» حرف زده می‌شود، صدای ترک‌های «موسیقی» نرم کم می‌شود و بعد برمی‌گردد. نقشِ هر ترک را با دکمهٔ نقش بالای نوارش بگذارید.
      </p>
      {d.on && !speech && <p className="mx-warn">هیچ ترکِ «گفتار»ی با صدا نیست؛ نقشِ ترکِ گویندگی یا ویدیوی حرف‌زدن را «گفتار» کنید.</p>}
      {d.on && !music && <p className="mx-warn">هیچ ترکِ «موسیقی»ای با قطعه نیست؛ نقشِ ترکِ موسیقی را «موسیقی» کنید.</p>}
      <Slider label="مقدارِ کم‌شدن (dB)" value={v.amount_db} min={3} max={30} step={1} def={DEFAULT_DUCKING.amount_db} digits={0} onLive={live("amount_db")} onEnd={end("amount_db")} />
      <Slider label="پیش‌خیز (میلی‌ثانیه)" value={v.attack_ms} min={5} max={500} step={5} def={DEFAULT_DUCKING.attack_ms} digits={0} onLive={live("attack_ms")} onEnd={end("attack_ms")} />
      <Slider label="برگشت (میلی‌ثانیه)" value={v.release_ms} min={50} max={3000} step={50} def={DEFAULT_DUCKING.release_ms} digits={0} onLive={live("release_ms")} onEnd={end("release_ms")} />
    </div>
  );
}

/** نوارهای کانال برای ترک‌های صدا و ترک‌های تصویری که صدا دارند، مستر با میترِ استریو، و کارتِ کم‌شدنِ خودکارِ موسیقی */
export default function MixerPanel({
  project, engine, onTrackLive, onTrackEnd, onTrackApply, onMasterLive, onMasterEnd, onDucking,
}: {
  project: Project;
  engine: AudioEngine | null;
  onTrackLive: (id: string, patch: Partial<Track>) => void;
  onTrackEnd: (label: string) => void;
  onTrackApply: (id: string, label: string, patch: Partial<Track>) => void;
  onMasterLive: (patch: Partial<Master>) => void;
  onMasterEnd: () => void;
  onDucking: (patch: Partial<Ducking>) => void;
}) {
  const refs = useRef<Map<string, HTMLElement>>(new Map());
  const clipped = useRef(false);
  const master: Master = project.master ?? { gain_db: 0, limiter: true };
  const strips = [
    ...[...project.tracks].filter((t) => t.kind === "video" && t.clips.some((c) => c.type === "media" && c.kind === "video" && c.has_audio)).reverse(),
    ...project.tracks.filter((t) => t.kind === "audio"),
  ];
  const ids = strips.map((t) => t.id).join(",");

  // یک حلقهٔ انیمیشن برای همهٔ میترها (مستقیم روی DOM)
  useEffect(() => {
    if (!engine) {
      for (const el of refs.current.values()) if (el instanceof HTMLElement && el.classList.contains("cover")) el.style.height = "100%";
      return;
    }
    let raf = 0;
    const set = (key: string, fn: (el: HTMLElement) => void) => { const el = refs.current.get(key); if (el) fn(el); };
    const tick = () => {
      for (const id of ids.split(",").filter(Boolean)) {
        const lv = engine.trackLevel(id);
        set(`${id}:cover`, (el) => { el.style.height = `${(1 - levelFrac(lv)) * 100}%`; });
      }
      const m = engine.levels();
      set("master:l:cover", (el) => { el.style.height = `${(1 - levelFrac(m.l)) * 100}%`; });
      set("master:r:cover", (el) => { el.style.height = `${(1 - levelFrac(m.r)) * 100}%`; });
      set("master:l:peak", (el) => { el.style.bottom = `${levelFrac(m.peakL) * 100}%`; });
      set("master:r:peak", (el) => { el.style.bottom = `${levelFrac(m.peakR) * 100}%`; });
      if (Math.max(m.peakL, m.peakR) >= 0.99) clipped.current = true;
      set("master:clip", (el) => { el.classList.toggle("is-on", clipped.current); });
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [engine, ids]);

  return (
    <div className="mx-root" dir="rtl" data-testid="mixer">
      <div className="mx-strips">
        {/* مستر اول است (در راست‌به‌چپ = سمتِ راست) تا روی گوشی بدونِ اسکرول دیده شود */}
        <div className="mx-strip mx-master" data-strip="master">
          <span className="mx-name">مستر</span>
          <button type="button" className="mx-role" ref={(el) => { if (el) refs.current.set("master:clip", el); }} title="چراغِ برش (clip) — کلیک برای پاک‌کردن"
            onClick={() => { clipped.current = false; }}>CLIP</button>
          <div className="mx-body">
            <Fader value={master.gain_db} min={-24} max={12} label="بلندیِ مستر" onLive={(v) => onMasterLive({ gain_db: v })} onEnd={onMasterEnd}
              onReset={() => { onMasterLive({ gain_db: 0 }); onMasterEnd(); }} />
            <Meter id="master:l" refs={refs} />
            <Meter id="master:r" refs={refs} />
          </div>
          <span className="mx-db" dir="ltr">{fmtDb(master.gain_db, -24)} dB</span>
          <label className="ws-check mx-lim" title="لیمیتر: جلوی برشِ صدا را می‌گیرد (alimiter)">
            <input type="checkbox" checked={master.limiter} onChange={(e) => { onMasterLive({ limiter: e.target.checked }); onMasterEnd(); }} /> لیمیتر
          </label>
        </div>
        {strips.length === 0 && <p className="ws-hint">هنوز ترکِ صدا یا ویدیوی صدادار روی تایم‌لاین نیست.</p>}
        {strips.map((t) => (
          <Strip key={t.id} track={t} refs={refs}
            onLive={(patch) => onTrackLive(t.id, patch)} onEnd={onTrackEnd} onApply={(label, patch) => onTrackApply(t.id, label, patch)} />
        ))}
      </div>
      {!engine && <p className="ws-hint">میترها فقط هنگامِ پخش در پیش‌نمایش کار می‌کنند.</p>}
      <DuckingCard project={project} onDucking={onDucking} />
    </div>
  );
}
