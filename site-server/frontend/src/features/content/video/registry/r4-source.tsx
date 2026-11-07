import { useEffect, useMemo, useRef, useState } from "react";

import { fa } from "../../../../components/ui";
import type { MediaItem } from "../api";
import { useMediaUrls } from "../manual/Monitor";
import { timecode } from "../manual/model";
import { replaceEdit } from "../manual/r6ops";
import { ThreePointInput, clipFromSource, fitToFill, insertAt, overwriteAt, targetTrack, threePoint } from "../manual/r4ops";
import type { PanelProps } from "./types";

type Where = "playhead" | "in" | "out" | "range";
const WHERE: { key: Where; title: string }[] = [
  { key: "playhead", title: "سرِ پخش" },
  { key: "in", title: "ورودیِ تایم‌لاین (I)" },
  { key: "out", title: "خروجیِ تایم‌لاین (O)" },
  { key: "range", title: "بازهٔ ورودی–خروجیِ تایم‌لاین" },
];

const tc = (s: number | null) => (s === null ? "—" : timecode(s));

/**
 * مانیتورِ منبع: یک رسانه را پیش از گذاشتن روی تایم‌لاین ببینید، ورودی (I) و خروجی (O) بگذارید، بعد «درج» (بعدی‌ها جلو می‌روند)
 * یا «رویه‌گذاری» (روی همان بازه می‌نشیند و چیزی جابه‌جا نمی‌شود). با ورودی/خروجیِ تایم‌لاین ویرایشِ سه‌نقطه‌ای می‌شود.
 */
export default function SourcePanel({ api, props }: PanelProps) {
  const items = useMemo(() => [...(api.bin?.videos ?? []), ...(api.bin?.audio ?? []), ...(api.bin?.images ?? [])], [api.bin]);
  const selRef = api.selected && api.selected.clip.type === "media" && api.selected.clip.ref !== "shape" ? api.selected.clip.ref : "";
  const [ref, setRef] = useState<string>(() => String(props?.ref ?? "") || selRef || items.find((i) => i.kind === "video")?.ref || items[0]?.ref || "");
  const item: MediaItem | undefined = api.media[ref] ?? items.find((i) => i.ref === ref);
  const urls = useMediaUrls(api.media, ref ? [ref] : []);
  const el = useRef<HTMLVideoElement>(null);
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [inP, setIn] = useState<number | null>(null);
  const [outP, setOut] = useState<number | null>(null);
  const [where, setWhere] = useState<Where>("playhead");

  const dur = item ? (item.kind === "image" ? 5 : Math.max(0.1, item.duration || 0.1)) : 0;
  const fps = api.fps || 30;

  useEffect(() => {
    setT(0);
    setIn(null);
    setOut(null);
    setPlaying(false);
  }, [ref]);
  useEffect(() => {
    const v = el.current;
    if (!v) return;
    const tick = () => setT(v.currentTime);
    v.addEventListener("timeupdate", tick);
    v.addEventListener("ended", () => setPlaying(false));
    return () => v.removeEventListener("timeupdate", tick);
  }, [ref, urls[ref]]);

  // پخشِ J / K / L (عقب / ایست / جلو؛ هر بار L یا J سریع‌تر تا ۴ برابر). عقب‌رفتن را مرورگر ندارد ⇒ با قدم‌هایِ کوچک شبیه‌سازی می‌شود.
  const rev = useRef<number | null>(null);
  const [shuttle, setShuttle] = useState(0);
  const stopRev = () => {
    if (rev.current !== null) window.clearInterval(rev.current);
    rev.current = null;
  };
  useEffect(() => stopRev, []);
  useEffect(() => {
    stopRev();
    setShuttle(0);
  }, [ref]);
  const jkl = (key: "j" | "k" | "l") => {
    const v = el.current;
    if (!v) return;
    stopRev();
    if (key === "k") {
      v.pause();
      setPlaying(false);
      setShuttle(0);
      return;
    }
    const speeds = [1, 2, 4];
    const cur = Math.abs(shuttle);
    const dir = key === "l" ? 1 : -1;
    const next = Math.sign(shuttle) === dir ? speeds[Math.min(2, speeds.indexOf(cur) + 1)] : 1;
    setShuttle(dir * next);
    if (dir > 0) {
      v.playbackRate = next;
      if (v.currentTime >= dur - 0.05) v.currentTime = inP ?? 0;
      void v.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
    } else {
      v.pause();
      setPlaying(false);
      rev.current = window.setInterval(() => {
        const nt = Math.max(0, v.currentTime - 0.04 * next);
        v.currentTime = nt;
        setT(nt);
        if (nt <= 0) { stopRev(); setShuttle(0); }
      }, 40);
    }
  };

  const seekTo = (x: number) => {
    const v = el.current;
    const c = Math.max(0, Math.min(dur, x));
    if (v) v.currentTime = c;
    setT(c);
  };
  const toggle = () => {
    const v = el.current;
    if (!v) return;
    if (v.paused) {
      if (v.currentTime >= dur - 0.05) v.currentTime = inP ?? 0;
      void v.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
    } else {
      v.pause();
      setPlaying(false);
    }
  };
  const mark = (which: "in" | "out") => {
    const x = Math.round(t * fps) / fps;
    if (which === "in") {
      setIn(x);
      if (outP !== null && outP <= x) setOut(null);
    } else {
      setOut(x);
      if (inP !== null && inP >= x) setIn(null);
    }
  };

  const io = api.project.inout;
  const plan = useMemo(() => {
    if (!item) return null;
    const i: ThreePointInput = {
      srcIn: inP, srcOut: outP, srcDuration: dur, playhead: api.time,
      tlIn: where === "in" || where === "range" ? (io?.in ?? null) : null,
      tlOut: where === "out" || where === "range" ? (io?.out ?? null) : null,
    };
    return threePoint(i);
  }, [item, inP, outP, dur, api.time, where, io?.in, io?.out]);

  const kind = item?.kind === "audio" ? "audio" : "video";
  const target = targetTrack(api.project, kind);
  const needsRange = (where !== "playhead") && !io;
  const why = !item ? "اول یک رسانه را انتخاب کنید." : !target ? "ترکِ بازی از این نوع نیست (قفل نباشد)." : needsRange ? "برای این گزینه اول در تایم‌لاین ورودی/خروجی بگذارید (I و O)." : null;

  const place = (mode: "insert" | "overwrite") => {
    if (why || !item || !plan || !target) {
      api.notice(why ?? "نشد.");
      return;
    }
    const clip = clipFromSource(item, plan.srcIn, plan.srcOut);
    api.apply(mode === "insert" ? "درج از مانیتورِ منبع" : "رویه‌گذاری از مانیتورِ منبع", (p) => (mode === "insert" ? insertAt(p, target.id, clip, plan.at) : overwriteAt(p, target.id, clip, plan.at)));
    api.notice(mode === "insert"
      ? `درج شد: ${fa(Math.round(plan.length * 10) / 10)} ثانیه در ${tc(plan.at)}؛ قطعه‌های بعدی ${fa(Math.round(plan.length * 10) / 10)} ثانیه جلو رفتند.`
      : `رویه‌گذاری شد: ${fa(Math.round(plan.length * 10) / 10)} ثانیه در ${tc(plan.at)}؛ چیزی جابه‌جا نشد.`);
    api.seek(plan.at);
  };

  const fill = () => {
    if (!item || !target) { api.notice(why ?? "نشد."); return; }
    if (!io) { api.notice("برای «پر کردنِ بازه» اول روی تایم‌لاین ورودی و خروجی بگذارید (I و O)."); return; }
    if (inP === null || outP === null) { api.notice("برای «پر کردنِ بازه» روی منبع هم ورودی و هم خروجی بگذارید."); return; }
    const r = fitToFill(item, inP, outP, io.in, io.out);
    if ("error" in r) { api.notice(r.error); return; }
    api.apply("پر کردنِ بازه از مانیتورِ منبع", (p) => overwriteAt(p, target.id, r.clip, io.in));
    api.notice(`بازه پر شد: منبع با سرعتِ ${fa(Math.round(r.speed * 100) / 100)} برابر دقیقاً جای ${tc(io.in)} تا ${tc(io.out)} را گرفت.`);
    api.seek(io.in);
  };

  const replace = () => {
    if (!item) { api.notice("اول یک رسانه را در مانیتورِ منبع انتخاب کنید."); return; }
    const sel = api.selected;
    if (!sel || sel.clip.type !== "media") { api.notice("اول قطعه‌ای را روی تایم‌لاین انتخاب کنید که باید جایگزین شود."); return; }
    const r = replaceEdit(api.project, sel.clip.id, item, inP ?? 0);
    if ("error" in r) { api.notice(r.error); return; }
    api.apply("جایگزینی از مانیتورِ منبع", () => r.project);
    api.notice(`قطعه با «${item.title}» از ${tc(inP ?? 0)} جایگزین شد؛ جا، طول، رنگ و جلوه‌هایش همان ماند (برگشت: Ctrl+Z).`);
  };

  const onKey = (e: React.KeyboardEvent) => {
    const k = e.key.toLowerCase();
    if (e.target instanceof HTMLSelectElement || (e.target instanceof HTMLInputElement && e.target.type !== "range")) return;
    if (e.code === "KeyJ" || e.code === "KeyK" || e.code === "KeyL") { e.preventDefault(); jkl(e.code === "KeyJ" ? "j" : e.code === "KeyK" ? "k" : "l"); }
    else if (k === " ") { e.preventDefault(); stopRev(); setShuttle(0); toggle(); }
    else if (e.code === "KeyI") { e.preventDefault(); mark("in"); }
    else if (e.code === "KeyO") { e.preventDefault(); mark("out"); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); seekTo(t - (e.shiftKey ? 1 : 1 / fps)); }
    else if (e.key === "ArrowRight") { e.preventDefault(); seekTo(t + (e.shiftKey ? 1 : 1 / fps)); }
    else if (e.altKey && e.code === "KeyX") { e.preventDefault(); setIn(null); setOut(null); }
  };

  const src = urls[ref];
  return (
    <div className="src-panel" data-testid="source-panel" tabIndex={0} onKeyDown={onKey}>
      <label className="ws-field">
        <span>رسانه</span>
        <select className="u-input" value={ref} onChange={(e) => setRef(e.target.value)} aria-label="رسانهٔ مانیتورِ منبع" data-testid="src-pick">
          {items.length === 0 && <option value="">رسانه‌ای نیست</option>}
          {(["videos", "audio", "images"] as const).map((g) => ((api.bin?.[g]?.length ?? 0) > 0 ? (
            <optgroup key={g} label={g === "videos" ? "ویدیوها" : g === "audio" ? "صدا و موسیقی" : "عکس‌ها"}>
              {api.bin![g].map((it) => <option key={it.ref} value={it.ref}>{it.title}</option>)}
            </optgroup>
          ) : null))}
        </select>
      </label>
      {selRef && selRef !== ref && <button type="button" className="ws-btn" onClick={() => setRef(selRef)} data-testid="src-use-selected">رسانهٔ قطعهٔ انتخاب‌شده</button>}

      <div className="src-stage">
        {item?.kind === "image" ? (
          <img src={src} alt={item.title} className="src-media" />
        ) : (
          <video ref={el} src={src} className="src-media" playsInline preload="metadata" data-testid="src-video" onLoadedMetadata={() => seekTo(typeof props?.at === "number" && ref === String(props?.ref ?? "") ? Number(props.at) : 0)} />
        )}
        {!item && <p className="ws-hint">رسانه‌ای انتخاب نشده.</p>}
      </div>

      <div className="src-bar" dir="ltr">
        <button type="button" className="ws-btn" onClick={() => seekTo(t - 1 / fps)} aria-label="یک فریم عقب" title="یک فریم عقب (←)">◀︎</button>
        <button type="button" className="ws-btn" onClick={toggle} aria-label={playing ? "ایست" : "پخش"} title="پخش / ایست (Space)" data-testid="src-play">{playing ? "❚❚" : "▶"}</button>
        <button type="button" className="ws-btn" onClick={() => seekTo(t + 1 / fps)} aria-label="یک فریم جلو" title="یک فریم جلو (→)">▶︎</button>
        <button type="button" className={`ws-btn ${shuttle < 0 ? "is-on" : ""}`} onClick={() => jkl("j")} aria-label="عقب‌رفتن (J)" title="J = عقب‌رفتن؛ دوباره بزنید تا سریع‌تر شود" data-testid="src-j">J</button>
        <button type="button" className="ws-btn" onClick={() => jkl("k")} aria-label="ایست (K)" title="K = ایست" data-testid="src-k">K</button>
        <button type="button" className={`ws-btn ${shuttle > 0 ? "is-on" : ""}`} onClick={() => jkl("l")} aria-label="جلورفتن (L)" title="L = جلورفتن؛ دوباره بزنید تا سریع‌تر شود (تا ۴ برابر)" data-testid="src-l">L</button>
        {shuttle !== 0 && <span className="src-tc" data-testid="src-rate">{shuttle < 0 ? "◀◀" : "▶▶"} {Math.abs(shuttle)}×</span>}
        <input type="range" min={0} max={dur || 1} step={1 / fps} value={Math.min(t, dur || 1)} onChange={(e) => seekTo(Number(e.target.value))} aria-label="جای پخش در منبع" data-testid="src-seek" style={{ flex: 1 }} />
        <span className="src-tc" data-testid="src-time">{tc(t)}</span>
      </div>
      {inP !== null || outP !== null ? (
        <div className="src-range" aria-hidden>
          <div className="src-range-fill" style={{ insetInlineStart: `${((inP ?? 0) / (dur || 1)) * 100}%`, width: `${(((outP ?? dur) - (inP ?? 0)) / (dur || 1)) * 100}%` }} />
        </div>
      ) : null}

      <div className="src-marks">
        <button type="button" className="ws-btn" onClick={() => mark("in")} title="ورودی را روی همین فریم بگذار (I)" data-testid="src-mark-in">ورودی (I)</button>
        <button type="button" className="ws-btn" onClick={() => mark("out")} title="خروجی را روی همین فریم بگذار (O)" data-testid="src-mark-out">خروجی (O)</button>
        <button type="button" className="ws-btn" onClick={() => { setIn(null); setOut(null); }} disabled={inP === null && outP === null} title="پاک‌کردنِ ورودی و خروجی (Alt+X)">پاک</button>
        <span className="src-info" data-testid="src-info">ورودی {tc(inP)} · خروجی {tc(outP)} · طول {fa(Math.round((plan?.length ?? 0) * 10) / 10)} ثانیه</span>
      </div>

      <label className="ws-field">
        <span>کجای تایم‌لاین بگذارم؟</span>
        <select className="u-input" value={where} onChange={(e) => setWhere(e.target.value as Where)} aria-label="محلِ گذاشتن روی تایم‌لاین" data-testid="src-where">
          {WHERE.map((w) => <option key={w.key} value={w.key}>{w.title}</option>)}
        </select>
      </label>
      <p className="ws-hint" data-testid="src-plan">
        {plan ? `از ${tc(plan.at)} تایم‌لاین (${plan.mode}) · روی ترکِ «${target?.name || (kind === "audio" ? "صدا" : "تصویر")}»` : ""}
        {where === "range" || where === "in" || where === "out" ? " — اگر دو نقطه روی تایم‌لاین باشد طولِ تایم‌لاین حکم می‌کند (ویرایشِ سه‌نقطه‌ای)." : ""}
      </p>

      <div className="src-go">
        <button type="button" className="ws-btn primary" onClick={() => place("insert")} disabled={!!why} title="درج: از آن نقطه به بعد همهٔ ترک‌ها به اندازهٔ طول جلو می‌روند" data-testid="src-insert">درج (Insert)</button>
        <button type="button" className="ws-btn primary" onClick={() => place("overwrite")} disabled={!!why} title="رویه‌گذاری: روی همان بازه می‌نشیند و چیزی جابه‌جا نمی‌شود" data-testid="src-overwrite">رویه‌گذاری (Overwrite)</button>
        <button type="button" className="ws-btn" onClick={replace} disabled={!item || !api.selected} title="Replace edit: قطعهٔ انتخاب‌شده در تایم‌لاین در همان جا و با همان طول، محتوایش از نقطهٔ ورودیِ منبع می‌شود" data-testid="src-replace">جایگزینی (Replace)</button>
        <button type="button" className="ws-btn" onClick={fill} disabled={!item || !target || item.kind !== "video"} title="ورودی/خروجی را روی منبع و روی تایم‌لاین بگذارید؛ سرعتِ منبع طوری عوض می‌شود که دقیقاً همان بازه را پر کند (ویرایشِ چهارنقطه‌ای)" data-testid="src-fill">پر کردنِ بازه (Fit to fill)</button>
      </div>
      {why && <p className="ws-hint" data-testid="src-why">{why}</p>}
      <p className="ws-hint">ترکِ هدف را با دکمهٔ ◎ کنارِ نامِ هر ترک عوض کنید (وگرنه اولین ترکِ بازِ آن نوع). هر دو کار با «برگشت» (Ctrl+Z) برمی‌گردد.</p>
    </div>
  );
}
