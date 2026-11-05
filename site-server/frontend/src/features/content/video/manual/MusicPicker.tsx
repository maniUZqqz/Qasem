import { useEffect, useMemo, useRef, useState } from "react";

import { Spinner, fa } from "../../../../components/ui";
import { AudioAsset, AudioOverview, loadOverview } from "../../../audio/api";
import type { Bin as BinData, MediaItem } from "../api";
import { Section } from "./controls";
import { timecode } from "./model";
import { useMediaUrls } from "./Monitor";
import SoundDialog from "./SoundDialog";
import { assetAsMedia, makeAsset, soundError, useAudioKinds } from "./soundApi";
import "./sound.css";

/** آنچه کاربر انتخاب کرد: یک صدای ذخیره‌شده (ref) یا یک عبارتِ جست‌وجو در کتابخانهٔ رایگان (query) */
export type MusicChoice = { ref?: string; query?: string; title?: string };
export type ChooseOutcome = { ok: boolean; message: string };

const clamp = (x: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, x));

/**
 * «موسیقیِ پس‌زمینه»: ۱) موسیقی‌های ذخیره‌شدهٔ فروشگاه (با پیش‌شنیدن)، ۲) ساختنِ موسیقی با هوش مصنوعی (روی سرورِ پردازش)،
 * ۳) کتابخانهٔ رایگان. انتخاب = ابزارِ add_music (در SoundQuick اجرا می‌شود): روی ترکِ موسیقی می‌نشیند، به طولِ ویدیو می‌رسد و زیرِ گفتار کم می‌شود.
 */
export default function MusicPicker({
  storeId, bin, media, programSeconds, busy, onChoose, onBinChanged, onClose,
}: {
  storeId: string;
  bin: BinData | null;
  media: Record<string, MediaItem>;
  programSeconds: number;
  /** ابزارِ add_music در حالِ اجراست */
  busy: boolean;
  onChoose: (c: MusicChoice) => Promise<ChooseOutcome>;
  onBinChanged: () => void;
  onClose: () => void;
}) {
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const [overview, setOverview] = useState<AudioOverview | null>(null);
  const [ovError, setOvError] = useState<string | null>(null);
  useEffect(() => {
    let on = true;
    loadOverview(storeId).then(
      (o) => on && setOverview(o),
      (e) => on && setOvError(soundError(e)),
    );
    return () => {
      on = false;
    };
  }, [storeId]);

  // ───────────── فهرستِ موسیقی‌های ذخیره‌شده
  const kinds = useAudioKinds(storeId, true, bin?.audio.length ?? 0);
  const [fresh, setFresh] = useState<AudioAsset[]>([]);
  const freshMedia = useMemo(() => Object.fromEntries(fresh.map((a) => [`audio:${a.id}`, assetAsMedia(storeId, a)])), [fresh, storeId]);
  const allMedia = useMemo(() => ({ ...media, ...freshMedia }), [media, freshMedia]);
  const rows: MediaItem[] = useMemo(() => {
    const saved = (bin?.audio ?? []).filter((it) => (kinds ? kinds[it.ref] === "MUSIC" : true) && !freshMedia[it.ref]);
    return [...fresh.map((a) => freshMedia[`audio:${a.id}`]), ...saved];
  }, [bin, kinds, fresh, freshMedia]);
  const [newest, setNewest] = useState<string | null>(null);

  // پیش‌شنیدن (صداهای کتابخانه با توکن‌اند ⇐ همان قلابِ مانیتور blob می‌سازد؛ فقط برای آنچه کاربر زد)
  const [playing, setPlaying] = useState<string | null>(null);
  const urls = useMediaUrls(allMedia, playing ? [playing] : []);
  const url = playing ? urls[playing] : undefined;
  const player = useRef<HTMLAudioElement>(null);
  useEffect(() => {
    const a = player.current;
    if (!a || !url) return;
    a.currentTime = 0;
    void a.play().catch(() => setPlaying(null));
  }, [url]);

  // ───────────── ساختنِ موسیقی
  const range = overview?.limits.music ?? [15, 60];
  const lo = Math.max(15, range[0]);
  const hi = Math.min(60, range[1]);
  const [min, max] = lo <= hi ? [lo, hi] : [range[0], range[1]];
  const [secs, setSecs] = useState(() => clamp(Math.round(programSeconds) || 30, 15, 60));
  const seconds = clamp(secs, min, max);
  const [style, setStyle] = useState("");
  const styles = overview?.music_styles ?? [];
  const chosenStyle = style || styles[0]?.id || "";
  const engine = overview?.status.engines.music;
  const engineDown = !!engine && !engine.ready;
  const [genBusy, setGenBusy] = useState(false);
  const [genText, setGenText] = useState("");
  const [genError, setGenError] = useState<string | null>(null);
  const [genDone, setGenDone] = useState(false);

  const make = async () => {
    setGenBusy(true);
    setGenError(null);
    setGenDone(false);
    try {
      const a = await makeAsset(storeId, { kind: "music", style: chosenStyle, seconds }, (t) => alive.current && setGenText(t));
      onBinChanged();
      if (alive.current) {
        setFresh((f) => [a, ...f.filter((x) => x.id !== a.id)]);
        setNewest(`audio:${a.id}`);
        setGenDone(true);
      }
    } catch (err) {
      if (alive.current) setGenError(soundError(err));
    } finally {
      if (alive.current) {
        setGenBusy(false);
        setGenText("");
      }
    }
  };

  // ───────────── انتخاب
  const [pickError, setPickError] = useState<string | null>(null);
  const [picking, setPicking] = useState<string | null>(null);
  const pick = async (c: MusicChoice, key: string) => {
    setPickError(null);
    setPicking(key);
    setPlaying(null);
    const r = await onChoose(c);
    if (alive.current) {
      setPicking(null);
      if (!r.ok) setPickError(r.message);
    }
  };
  const working = busy || picking !== null;
  const [q, setQ] = useState("");

  return (
    <SoundDialog title="موسیقیِ پس‌زمینه" testId="music-picker" onClose={onClose}>
      <audio ref={player} src={url || undefined} onEnded={() => setPlaying(null)} hidden />
      <p className="ws-hint">موسیقی را انتخاب کنید؛ خودکار روی ترکِ «موسیقی» می‌نشیند، به اندازهٔ ویدیو می‌شود و زیرِ صدای گفتار کم می‌شود. هر وقت خواستید با «برگشت» (Ctrl+Z) برش می‌گردانید.</p>
      {working && <p className="sq-busy" role="status"><Spinner size={14} /> در حالِ گذاشتنِ موسیقی روی تایم‌لاین…</p>}
      {pickError && <p className="sq-note is-warn" data-testid="mp-error">{pickError}</p>}

      <div className="sq-sub">موسیقی‌های ذخیره‌شدهٔ شما</div>
      {rows.length === 0 ? (
        <p className="ws-hint" data-testid="mp-empty">هنوز موسیقیِ ذخیره‌شده‌ای ندارید؛ پایین یکی بسازید یا از کتابخانهٔ رایگان بیاورید.</p>
      ) : (
        <ul className="sq-music-list">
          {rows.map((it) => (
            <li key={it.ref} className={`sq-music-row ${newest === it.ref ? "is-new" : ""}`} data-ref={it.ref} data-testid="mp-item">
              <button type="button" className="ws-btn sq-play" aria-label={`پیش‌شنیدنِ ${it.title}`} title="پیش‌شنیدن" onClick={() => setPlaying((p) => (p === it.ref ? null : it.ref))}>
                {playing === it.ref ? (url ? "⏸" : "…") : "▶"}
              </button>
              <span className="sq-music-title">
                <b>{it.title}</b>
                <small>{it.duration ? fa(timecode(it.duration).slice(0, 5)) : ""}{newest === it.ref ? " · تازه ساخته شد" : ""}</small>
              </span>
              <button type="button" className="ws-btn primary" disabled={working} onClick={() => void pick({ ref: it.ref, title: it.title }, it.ref)} data-testid="mp-use" title="این موسیقی را زیرِ ویدیو بگذار">
                همین را بگذار
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="ws-card sq-gen" data-testid="mp-generate">
        <div className="ws-card-title">ساختنِ موسیقی با هوش مصنوعی</div>
        {ovError && <p className="sq-note is-warn">{ovError}</p>}
        {engineDown && engine && <p className="sq-note is-warn" data-testid="mp-engine">{engine.message}</p>}
        {!overview && !ovError && <p className="sq-busy"><Spinner size={14} /> در حالِ بارگیری…</p>}
        {overview && (
          <>
            <div className="ws-group-title">حال‌وهوا</div>
            <div className="sq-chips">
              {styles.map((s) => (
                <button key={s.id} type="button" className={`ws-chip ${chosenStyle === s.id ? "is-on" : ""}`} aria-pressed={chosenStyle === s.id} title={s.label} onClick={() => setStyle(s.id)} data-style={s.id}>
                  {s.label}
                </button>
              ))}
            </div>
            <label className="sq-slider sq-slider-sm">
              <span className="sq-slider-head"><span className="sq-slider-label">مدت</span><span className="sq-slider-val" dir="ltr">{fa(seconds)} ثانیه</span></span>
              <input type="range" min={min} max={max} step={5} value={seconds} onChange={(e) => setSecs(Number(e.target.value))} aria-label="مدتِ موسیقی (ثانیه)" data-testid="mp-seconds" />
            </label>
            <button type="button" className="ws-btn primary sq-wide" disabled={genBusy || engineDown || !chosenStyle} onClick={() => void make()} data-testid="mp-make">
              {genBusy ? "در حالِ ساختن…" : "🎵 بساز"}
            </button>
            {genBusy && <p className="sq-busy" role="status" data-testid="mp-progress"><Spinner size={14} /> {genText || "در حالِ ساختن…"}</p>}
            {genBusy && <p className="ws-hint">ساختن چند دقیقه طول می‌کشد. اگر پنجره را ببندید، کار ادامه دارد و موسیقی در بخشِ «صدا»ی رسانه‌ها ذخیره می‌شود.</p>}
            {genDone && <p className="sq-note is-ok" data-testid="mp-done">آماده شد و ذخیره شد؛ بالا در فهرست است. با ▶ بشنوید و «همین را بگذار» را بزنید.</p>}
            {genError && <p className="sq-note is-warn" data-testid="mp-gen-error">{genError}</p>}
          </>
        )}
      </div>

      <Section title="از کتابخانهٔ موسیقیِ رایگان" testId="mp-library">
        <p className="ws-hint">همهٔ آهنگ‌های این کتابخانه برای ویدیوی تبلیغاتی مجازند؛ اگر آهنگی «CC-BY» باشد باید نامِ سازنده را در توضیحاتِ پست بنویسید. برای نتیجهٔ بهتر عبارتِ انگلیسی بنویسید.</p>
        <div className="sq-search">
          <input className="u-input" dir="auto" value={q} onChange={(e) => setQ(e.target.value)} placeholder="مثلاً: calm piano" aria-label="جست‌وجو در موسیقیِ رایگان" maxLength={120}
            onKeyDown={(e) => { if (e.key === "Enter" && q.trim() && !working) void pick({ query: q.trim() }, "query"); }} data-testid="mp-query" />
          <button type="button" className="ws-btn" disabled={working || !q.trim()} onClick={() => void pick({ query: q.trim() }, "query")} data-testid="mp-query-go" title="در کتابخانه می‌گردد و مناسب‌ترین آهنگ را زیرِ ویدیو می‌گذارد">
            پیدا کن و بگذار
          </button>
        </div>
      </Section>
    </SoundDialog>
  );
}
