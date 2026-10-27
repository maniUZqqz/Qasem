import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import { errorMessage } from "../../../api/client";
import Icon from "../../../components/Icon";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBox,
  Field,
  Input,
  PageHeader,
  SectionTitle,
  Select,
  Spinner,
  TextArea,
  fa,
} from "../../../components/ui";
import { clock, Engine, Estimate, minutes, mmss, regenApi, Session, Source, Version, Waveform as Wave } from "./api";
import AudioPanel, { AudioForm, DEFAULT_AUDIO, specOf } from "./AudioPanel";
import RangePicker from "./RangePicker";
import TimeInput from "./TimeInput";
import VersionCard from "./VersionCard";
import Waveform from "./Waveform";

/**
 * «بازسازیِ یک تکه» — یک بازه از وسطِ هر ویدیو (ساختهٔ AI، خروجیِ ادیتور، رندرِ سه‌بعدی، آپلود) دوباره ساخته
 * و بی‌درز جایگزین می‌شود: مدل از آخرین فریمِ قبل از تکه شروع می‌کند و دقیقاً به اولین فریمِ بعد از آن می‌رسد،
 * کد رنگ/نور/تیزی/زمان را با دو طرف جفت می‌کند و صدای اصلی دست نمی‌خورد. هر بار ساختن یک نسخهٔ تازه است.
 */
export default function PieceRegenPage() {
  const { id: storeId = "" } = useParams<{ id: string }>();
  const [params, setParams] = useSearchParams();
  const sessionId = params.get("session");
  const src = params.get("src");
  const [error, setError] = useState<string | null>(null);

  // ?src=script:12 از صفحه‌های دیگر ⇐ جلسه ساخته/پیدا می‌شود و نشانی به ?session=… عوض می‌شود
  useEffect(() => {
    if (!src || sessionId) return;
    let off = false;
    regenApi
      .open(storeId, src)
      .then((s) => !off && setParams({ session: String(s.id) }, { replace: true }))
      .catch((e) => !off && setError(errorMessage(e)));
    return () => {
      off = true;
    };
  }, [src, sessionId, storeId, setParams]);

  return (
    <div className="space-y-5">
      <PageHeader
        title="بازسازیِ یک تکه"
        subtitle="یک بازه از وسطِ ویدیو را انتخاب کنید و بگویید در آن چه اتفاقی بیفتد؛ همان تکه دوباره ساخته و بی‌درز جایگزین می‌شود."
        actions={
          sessionId ? (
            <Button variant="secondary" onClick={() => setParams({})}>
              <Icon name="back" size={15} /> ویدیوی دیگر
            </Button>
          ) : undefined
        }
      />
      <ErrorBox message={error} />
      {sessionId ? (
        <SessionView storeId={storeId} sessionId={sessionId} />
      ) : src ? (
        <Card>
          <div className="flex items-center gap-3">
            <Spinner /> آماده‌کردنِ ویدیو…
          </div>
        </Card>
      ) : (
        <Picker storeId={storeId} onOpen={(s) => setParams({ session: String(s.id) })} />
      )}
    </div>
  );
}

// ───────────────────────────── انتخابِ ویدیو

function Picker({ storeId, onOpen }: { storeId: string; onOpen: (s: Session) => void }) {
  const [data, setData] = useState<{ sessions: Session[]; sources: Source[]; engines: Engine[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [upload, setUpload] = useState<number | null>(null);

  const load = useCallback(() => {
    regenApi
      .overview(storeId)
      .then(setData)
      .catch((e) => setError(errorMessage(e)));
  }, [storeId]);
  useEffect(load, [load]);

  async function open(ref: string) {
    setBusy(ref);
    setError(null);
    try {
      onOpen(await regenApi.open(storeId, ref));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  async function onFile(file: File | undefined) {
    if (!file) return;
    setError(null);
    setUpload(0);
    try {
      onOpen(await regenApi.upload(storeId, file, setUpload));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setUpload(null);
    }
  }

  async function remove(s: Session) {
    if (!window.confirm(`«${s.title}» و همهٔ نسخه‌هایش پاک شود؟ (ویدیوی اصل در جای خودش می‌ماند)`)) return;
    await regenApi.remove(storeId, s.id).catch((e) => setError(errorMessage(e)));
    load();
  }

  if (!data && !error) {
    return (
      <Card>
        <Spinner />
      </Card>
    );
  }
  return (
    <div className="space-y-5">
      <ErrorBox message={error} />
      {data && <EngineLine engines={data.engines} />}
      <Card>
        <SectionTitle
          action={
            <label className="u-btn u-btn-primary u-btn-sm cursor-pointer">
              <Icon name="upload" size={14} />
              {upload !== null ? `آپلود… ${fa(Math.round(upload * 100))}٪` : "آپلودِ ویدیوی تازه"}
              <input
                type="file"
                accept="video/*,.mkv,.mov"
                className="hidden"
                data-testid="regen-upload"
                disabled={upload !== null}
                onChange={(e) => onFile(e.target.files?.[0])}
              />
            </label>
          }
        >
          کدام ویدیو؟
        </SectionTitle>
        {data && data.sources.length === 0 ? (
          <EmptyState
            icon="film"
            title="هنوز ویدیویی نیست"
            description="ویدیوهای ساخته‌شده با AI، خروجی‌های ادیتور، رندرهای سه‌بعدی و آپلودها این‌جا می‌آیند — یا همین‌جا یک ویدیو آپلود کنید."
          />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {data?.sources.map((s) => (
              <button
                key={s.ref}
                type="button"
                data-testid="regen-source"
                onClick={() => open(s.ref)}
                disabled={busy !== null}
                className="u-card u-card-hover flex flex-col gap-2 p-3 text-start"
              >
                {/* preload="none": ده‌ها ویدیو با metadata هر شش اتصالِ مرورگر به سایت را می‌گرفتند و درخواست‌های پنل
                    (پاک کردن، وضعیت) پشتشان می‌ماندند */}
                <video src={s.url} preload="none" muted playsInline className="aspect-video w-full rounded-lg object-cover" style={{ background: "#000" }} />
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-bold" style={{ color: "var(--text)" }}>
                    {s.title}
                  </span>
                  {busy === s.ref ? <Spinner size={16} /> : <Badge tone="info">{s.kind_label}</Badge>}
                </div>
              </button>
            ))}
          </div>
        )}
      </Card>
      {data && data.sessions.length > 0 && (
        <Card>
          <SectionTitle>کارهای قبلی</SectionTitle>
          <div className="divide-y" style={{ borderColor: "var(--line)" }}>
            {data.sessions.map((s) => (
              <div key={s.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <button type="button" className="text-start text-sm" style={{ color: "var(--text)" }} onClick={() => onOpen(s)}>
                  <b>{s.title}</b>{" "}
                  <span style={{ color: "var(--text-3)" }}>
                    · {s.source_label} · {fa(s.versions_count ?? 0)} نسخه
                    {s.current_number ? ` · نسخهٔ ${fa(s.current_number)} قبول شده` : ""}
                  </span>
                </button>
                <Button size="sm" variant="ghost" onClick={() => remove(s)}>
                  <Icon name="trash" size={14} />
                </Button>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

function EngineLine({ engines }: { engines: Engine[] }) {
  const anyReady = engines.some((e) => e.ready);
  const offline = engines.every((e) => e.ready === null);
  return (
    <Alert
      tone={anyReady ? "ok" : offline ? "warn" : "warn"}
      title={anyReady ? "سرورِ پردازش آماده است" : offline ? "سرورِ پردازش الان آنلاین نیست" : "مدل‌ها روی سرورِ پردازش کامل نیستند"}
    >
      {offline
        ? "ساختن را می‌شود شروع کرد؛ کار در صف می‌ماند تا سرورِ پردازش (START.bat روی کامپیوترِ گرافیکی) روشن شود."
        : engines.map((e) => (
            <div key={e.key}>
              {e.label}: {e.ready ? `آماده روی ${e.nodes.join("، ")}` : `ناقص — ${e.missing.join("، ") || "نامعلوم"}`}
            </div>
          ))}
    </Alert>
  );
}

// ───────────────────────────── یک ویدیو

function useFrameUrl(storeId: string, sessionId: number | null, n: number | null, width = 360) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (sessionId === null || n === null || n < 0) {
      setUrl(null);
      return;
    }
    let off = false;
    let made: string | null = null;
    const t = window.setTimeout(() => {
      regenApi
        .frame(storeId, sessionId, n, width)
        .then((blob) => {
          if (off) return;
          made = URL.createObjectURL(blob);
          setUrl(made);
        })
        .catch(() => !off && setUrl(null));
    }, 250);
    return () => {
      off = true;
      window.clearTimeout(t);
      if (made) URL.revokeObjectURL(made);
    };
  }, [storeId, sessionId, n, width]);
  return url;
}

type Form = { prompt: string; engine: string; quality: string; seed: string; context: number; blend: string };

function SessionView({ storeId, sessionId }: { storeId: string; sessionId: string }) {
  const [session, setSession] = useState<Session | null>(null);
  const [engines, setEngines] = useState<Engine[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [range, setRange] = useState<[number, number] | null>(null);
  const [playhead, setPlayhead] = useState(0);
  const [form, setForm] = useState<Form>({ prompt: "", engine: "wan22_flf", quality: "480p", seed: "", context: 1, blend: "auto" });
  const [est, setEst] = useState<Estimate | null>(null);
  const [estError, setEstError] = useState<string | null>(null);
  const [active, setActive] = useState<"start" | "end">("start");
  const [picture, setPicture] = useState(true);
  const [audioForm, setAudioForm] = useState<AudioForm>(DEFAULT_AUDIO);
  const [wave, setWave] = useState<Wave | null>(null);
  const [zoom, setZoom] = useState<Wave | null>(null);
  const video = useRef<HTMLVideoElement>(null);
  const formRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try {
      const d = await regenApi.session(storeId, sessionId);
      setSession(d.session);
      setEngines(d.engines);
      setError(null);
      return d.session;
    } catch (e) {
      setError(errorMessage(e));
      return null;
    }
  }, [storeId, sessionId]);

  useEffect(() => {
    load();
  }, [load]);

  const polling = session?.state === "PREPARING" || (session?.versions ?? []).some((v) => v.active);
  useEffect(() => {
    if (!polling) return;
    const t = window.setInterval(load, 3000);
    return () => window.clearInterval(t);
  }, [polling, load]);

  // تا بررسیِ ویدیو تمام نشده، info خالی است (همهٔ کلیدها null)
  const info = session?.state === "READY" && session.info?.n_frames ? session.info : undefined;
  const fps = info?.fps || 30;
  const n = info?.n_frames || 0;
  // سقفِ طول فقط برای ساختِ تصویر با مدل است؛ صدا و برش هر طولی را می‌پذیرند
  const maxCount = picture ? Math.max(1, Math.floor((session?.max_seconds ?? 20) * fps)) : Math.max(1, n);

  // بازهٔ پیش‌فرض: یک ثانیه از وسطِ ویدیو
  useEffect(() => {
    if (!info || range) return;
    const mid = Math.floor(n / 2);
    const half = Math.max(1, Math.floor(fps / 2));
    setRange([Math.max(1, mid - half), Math.min(n - 2, mid + half)]);
  }, [info, n, fps, range]);

  // جای پخش ⇐ شمارهٔ فریم (requestVideoFrameCallback دقیق‌تر از timeupdate است)
  useEffect(() => {
    const el = video.current as (HTMLVideoElement & { requestVideoFrameCallback?: (cb: (now: number, meta: { mediaTime: number }) => void) => number }) | null;
    if (!el) return;
    let handle = 0;
    const onTime = () => setPlayhead(Math.max(0, Math.min(n - 1, Math.floor(el.currentTime * fps + 1e-3))));
    if (el.requestVideoFrameCallback) {
      const tick = (_now: number, meta: { mediaTime: number }) => {
        setPlayhead(Math.max(0, Math.min(n - 1, Math.floor(meta.mediaTime * fps + 1e-3))));
        handle = el.requestVideoFrameCallback!(tick);
      };
      handle = el.requestVideoFrameCallback(tick);
    }
    el.addEventListener("seeked", onTime);
    el.addEventListener("timeupdate", onTime);
    return () => {
      el.removeEventListener("seeked", onTime);
      el.removeEventListener("timeupdate", onTime);
      if (handle && "cancelVideoFrameCallback" in el) (el as unknown as { cancelVideoFrameCallback: (h: number) => void }).cancelVideoFrameCallback(handle);
    };
  }, [session?.base_url, fps, n]);

  const seek = useCallback(
    (frame: number) => {
      const el = video.current;
      const f = Math.max(0, Math.min(n - 1, frame));
      setPlayhead(f);
      if (el) {
        el.pause();
        el.currentTime = (f + 0.5) / fps;
      }
    },
    [fps, n],
  );

  const [start, end] = range ?? [0, 0];

  // شکلِ موجِ کلِ ویدیو (یک بار برای هر پایه) و نزدیک‌نمای بازه (یک ثانیه قبل و بعد، با تأخیر)
  useEffect(() => {
    if (!session || session.state !== "READY") return;
    let off = false;
    setWave(null);
    regenApi
      .waveform(storeId, session.id, { n: 800 })
      .then((w) => !off && setWave(w))
      .catch(() => !off && setWave({ from: 0, to: 0, has_audio: false, peaks: [] }));
    return () => {
      off = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storeId, session?.id, session?.state, session?.base_url]);

  const zoomFrom = Math.max(0, start / fps - 1);
  const zoomTo = Math.min(n / fps, (end + 1) / fps + 1);
  useEffect(() => {
    if (!session || session.state !== "READY" || !range || !info?.audio?.length) return;
    let off = false;
    const t = window.setTimeout(() => {
      regenApi
        .waveform(storeId, session.id, { from: zoomFrom, to: zoomTo, n: 400 })
        .then((w) => !off && setZoom(w))
        .catch(() => undefined);
    }, 300);
    return () => {
      off = true;
      window.clearTimeout(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storeId, session?.id, session?.state, session?.base_url, zoomFrom, zoomTo]);

  // کلیدها: ← → دستهٔ فعال یک فریم عقب/جلو (Shift: یک ثانیه، Ctrl/Alt: ده فریم)، Home/End: اول/آخرِ ویدیو،
  // [ و ]: دستهٔ شروع/پایان، فاصله: پخش/توقف. وقتی در کادری تایپ می‌شود کاری نمی‌کند.
  // ← همیشه «عقب» است: خطِ زمانی و دکمه‌های فریم هم در این صفحه چپ‌به‌راست‌اند.
  useEffect(() => {
    if (!range || !n) return;
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (e.metaKey || (t && (t.isContentEditable || t.closest("input, textarea, select")))) return;
      const moveTo = (frame: number) => {
        if (active === "start") {
          const s = Math.max(0, Math.min(end, frame));
          setRange([s, end]);
          seek(s);
        } else {
          const en = Math.min(n - 1, Math.max(start, frame));
          setRange([start, en]);
          seek(en);
        }
      };
      const cur = active === "start" ? start : end;
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        const step = e.shiftKey ? Math.max(1, Math.round(fps)) : e.ctrlKey || e.altKey ? 10 : 1;
        moveTo(cur + (e.key === "ArrowRight" ? step : -step));
      } else if (e.key === "Home") {
        e.preventDefault();
        moveTo(0);
      } else if (e.key === "End") {
        e.preventDefault();
        moveTo(n - 1);
      } else if (e.code === "BracketLeft") {
        e.preventDefault();
        setActive("start");
        seek(start);
      } else if (e.code === "BracketRight") {
        e.preventDefault();
        setActive("end");
        seek(end);
      } else if (e.code === "Space") {
        if (t && (t.tagName === "VIDEO" || t.tagName === "BUTTON" || t.tagName === "A" || t.tagName === "AUDIO")) return;
        e.preventDefault();
        const el = video.current;
        if (el) {
          if (el.paused) el.play().catch(() => undefined);
          else el.pause();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [range, n, fps, active, start, end, seek]);
  const before = useFrameUrl(storeId, session?.state === "READY" ? session.id : null, range ? start - 1 : null);
  const after = useFrameUrl(storeId, session?.state === "READY" ? session.id : null, range && end + 1 < n ? end + 1 : null);

  // تخمینِ زمان و نقشه (با تأخیر، تا کشیدنِ دسته‌ها درخواست‌باران نشود)
  useEffect(() => {
    if (!session || session.state !== "READY" || !range) return;
    let off = false;
    const t = window.setTimeout(() => {
      regenApi
        .estimate(storeId, session.id, { start, end, engine: form.engine, quality: form.quality, context: form.context })
        .then((d) => {
          if (!off) {
            setEst(d);
            setEstError(null);
          }
        })
        .catch((e) => !off && setEstError(errorMessage(e)));
    }, 350);
    return () => {
      off = true;
      window.clearTimeout(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storeId, session?.id, session?.state, start, end, form.engine, form.quality, form.context, range === null]);

  const engine = engines.find((e) => e.key === form.engine);
  const versions = session?.versions ?? [];
  const running = versions.some((v) => v.active);

  async function build(override?: Partial<Form> & { start?: number; end?: number; picture?: boolean; audio?: AudioForm }) {
    if (!session || !range) return;
    setBusy(true);
    setError(null);
    const f = { ...form, ...override };
    const pic = override?.picture ?? picture;
    try {
      await regenApi.create(storeId, session.id, {
        mode: pic ? "picture" : "audio",
        audio: specOf(override?.audio ?? audioForm),
        start: override?.start ?? start,
        end: override?.end ?? end,
        prompt: f.prompt,
        engine: f.engine,
        quality: f.quality,
        seed: f.seed === "" ? undefined : Number(f.seed),
        context: f.context,
        blend: f.blend === "auto" ? undefined : Number(f.blend),
      });
      await load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function cutRange() {
    if (!session || !range) return;
    if (!window.confirm(`فریمِ ${start} تا ${end} (${(count / fps).toFixed(2)} ثانیه) از تصویر و صدا حذف شود؟ اصلِ ویدیو می‌ماند؛ نتیجه یک نسخهٔ تازه است.`)) return;
    setBusy(true);
    setError(null);
    try {
      await regenApi.create(storeId, session.id, { mode: "cut", start, end });
      await load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function act(v: Version, action: "accept" | "discard" | "cancel" | "editor") {
    setBusy(true);
    setError(null);
    try {
      const d = await regenApi.action(storeId, v.id, action);
      if (action === "editor" && d.upload_id) window.alert("در فهرستِ «ادیتور ویدیو» اضافه شد.");
      await load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const audioOf = (v: Version): AudioForm => ({ ...DEFAULT_AUDIO, ...(v.audio as Partial<AudioForm>),
    sourceLabel: (v.audio as { source?: string }).source ? "همان صدای نسخهٔ " + v.number : "", sourceSeconds: 0 });

  function again(v: Version) {
    setRange([v.start, v.end]);
    if (v.mode === "cut") return;
    build({ prompt: v.prompt, engine: v.engine || "wan22_flf", quality: v.quality || "480p", seed: "", context: v.context || 1,
            blend: v.blend === null ? "auto" : String(v.blend), start: v.start, end: v.end,
            picture: v.mode === "picture", audio: audioOf(v) });
  }

  function edit(v: Version) {
    setRange([v.start, v.end]);
    setPicture(v.mode === "picture");
    setAudioForm(audioOf(v));
    if (v.mode === "picture") {
      setForm({ prompt: v.prompt, engine: v.engine, quality: v.quality, seed: "", context: v.context, blend: v.blend === null ? "auto" : String(v.blend) });
    }
    formRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function playRange() {
    const el = video.current;
    if (!el || !range) return;
    const from = Math.max(0, start - Math.round(fps));
    el.currentTime = (from + 0.5) / fps;
    el.play().catch(() => undefined);
    const stopAt = (end + 1 + Math.round(fps)) / fps;
    const stop = () => {
      if (el.currentTime >= stopAt) {
        el.pause();
        el.removeEventListener("timeupdate", stop);
      }
    };
    el.addEventListener("timeupdate", stop);
  }

  const setStart = (s: number) => range && setRange([Math.max(0, Math.min(end, s)), end]);
  const setEnd = (e: number) => range && setRange([start, Math.min(n - 1, Math.max(start, e))]);
  const count = end - start + 1;
  const tooLong = count > maxCount;
  const whole = start === 0 && end === n - 1;
  const hasAudio = !!info?.audio?.length;
  const audioOnlyEmpty = !picture && audioForm.op === "keep";
  const replaceMissing = audioForm.op === "replace" && !audioForm.source;

  const chips = useMemo(() => {
    if (!info) return [];
    return [
      `${fa(info.width)}×${fa(info.height)}`,
      `${fa(Math.round(fps * 100) / 100)} فریم/ثانیه`,
      `${fa(n)} فریم`,
      clock(info.duration || 0),
      (info.codec || "").toUpperCase(),
      info.audio?.length ? "با صدا" : "بی‌صدا",
    ];
  }, [info, fps, n]);

  if (!session) {
    return error ? <ErrorBox message={error} /> : <Card><Spinner /></Card>;
  }
  if (session.state === "PREPARING") {
    return (
      <Card>
        <div className="flex items-center gap-3" style={{ color: "var(--text-2)" }}>
          <Spinner /> بررسیِ ویدیو: شمارشِ فریم‌ها، کلیدفریم‌ها و نوارِ کوچک‌نمایی…
        </div>
      </Card>
    );
  }
  if (session.state === "FAILED") {
    return <Alert tone="bad" title="این ویدیو قابلِ استفاده نیست">{session.error}</Alert>;
  }

  return (
    <div className="space-y-5">
      <ErrorBox message={error} />
      <Card className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <b style={{ color: "var(--text)" }}>{session.title}</b>
            <Badge tone="info">{session.source_label}</Badge>
            {session.current_number && <Badge tone="brand">پایه: نسخهٔ {fa(session.current_number)}</Badge>}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {chips.map((c) => (
              <span key={c} className="u-badge u-badge-neutral">
                {c}
              </span>
            ))}
          </div>
        </div>

        <video
          ref={video}
          key={session.base_url ?? ""}
          src={session.base_url ?? undefined}
          controls
          playsInline
          preload="metadata"
          data-testid="regen-player"
          className="mx-auto w-full rounded-lg"
          style={{ background: "#000", maxHeight: 420 }}
        />

        <div className="flex flex-wrap items-center justify-between gap-2 text-sm" style={{ color: "var(--text-2)" }}>
          <span data-testid="regen-playhead">
            جای پخش: فریمِ <b style={{ color: "var(--text)" }}>{fa(playhead)}</b> · {clock(playhead / fps)}
          </span>
          <div className="flex flex-wrap gap-1.5">
            <span dir="ltr" className="inline-flex gap-1.5">
              <Button size="sm" variant="ghost" onClick={() => seek(playhead - 1)} title="یک فریم عقب (←)" data-testid="regen-step-back">
                ⏴ فریم
              </Button>
              <Button size="sm" variant="ghost" onClick={() => seek(playhead + 1)} title="یک فریم جلو (→)" data-testid="regen-step-fwd">
                فریم ⏵
              </Button>
            </span>
            <Button size="sm" variant="secondary" onClick={() => { setStart(playhead); setActive("start"); }} data-testid="regen-set-start">
              شروع = همین فریم
            </Button>
            <Button size="sm" variant="secondary" onClick={() => { setEnd(playhead); setActive("end"); }} data-testid="regen-set-end">
              پایان = همین فریم
            </Button>
          </div>
        </div>

        {range && (
          <RangePicker
            frames={n}
            fps={fps}
            stripUrl={session.filmstrip.url}
            start={start}
            end={end}
            playhead={playhead}
            maxCount={maxCount}
            active={active}
            wave={wave}
            onChange={(s, e) => setRange([s, e])}
            onSeek={seek}
            onActivate={setActive}
          />
        )}

        {range && hasAudio && (
          <div className="space-y-1">
            <div className="text-xs" style={{ color: "var(--text-3)" }}>
              صدای بازه از نزدیک (یک ثانیه قبل و بعد) — جای گفتار را ببینید؛ کلیک = جای پخش
            </div>
            <Waveform
              peaks={zoom ? zoom.peaks : null}
              from={zoom?.from ?? zoomFrom}
              to={zoom && zoom.to > zoom.from ? zoom.to : zoomTo}
              selStart={start / fps}
              selEnd={(end + 1) / fps}
              playhead={(playhead + 0.5) / fps}
              height={56}
              testid="regen-zoom-wave"
              onSeek={(t) => seek(Math.floor(t * fps))}
            />
          </div>
        )}

        {range && (
          <div className="grid gap-4 md:grid-cols-2">
            {(["start", "end"] as const).map((which) => {
              const value = which === "start" ? start : end;
              const set = which === "start" ? setStart : setEnd;
              const img = which === "start" ? before : after;
              const boundary = which === "start" ? start - 1 : end + 1;
              return (
                <div
                  key={which}
                  className="space-y-2 rounded-xl p-2"
                  data-testid={`regen-box-${which}`}
                  onClick={() => setActive(which)}
                  style={{ border: `1px solid ${active === which ? "var(--brand)" : "transparent"}`, background: active === which ? "var(--brand-soft)" : undefined }}
                >
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-sm font-bold" style={{ color: "var(--text)" }}>
                      {which === "start" ? "اولین فریمِ تکه" : "آخرین فریمِ تکه"}
                    </span>
                    {active === which && <Badge tone="brand">فعال برای ← →</Badge>}
                    <span dir="ltr" className="inline-flex items-center gap-1.5">
                      <Button size="sm" variant="ghost" onClick={() => { set(value - 1); seek(value - 1); }}>−۱</Button>
                      <Input
                        type="number"
                        value={value}
                        min={0}
                        max={n - 1}
                        data-testid={`regen-${which}`}
                        onChange={(e) => set(Number(e.target.value))}
                        className="text-center"
                        style={{ width: 96 }}
                        dir="ltr"
                      />
                      <Button size="sm" variant="ghost" onClick={() => { set(value + 1); seek(value + 1); }}>+۱</Button>
                    </span>
                    <span className="text-xs" style={{ color: "var(--text-3)" }}>{clock(value / fps)}</span>
                  </div>
                  <div className="text-xs" style={{ color: "var(--text-3)" }}>
                    {boundary < 0 || boundary >= n
                      ? which === "start"
                        ? "تکه از اولِ ویدیو است؛ مدل فقط به فریمِ بعد از آن می‌رسد."
                        : "تکه تا آخرِ ویدیو است؛ مدل فقط از فریمِ قبل از آن ادامه می‌دهد."
                      : which === "start"
                        ? `مدل از این فریم شروع می‌کند (فریمِ ${fa(boundary)}، آخرین فریمِ قبل از تکه):`
                        : `و دقیقاً به این فریم می‌رسد (فریمِ ${fa(boundary)}، اولین فریمِ بعد از تکه):`}
                  </div>
                  {boundary >= 0 && boundary < n && (
                    <button type="button" onClick={() => seek(boundary)} className="block w-full">
                      {img ? (
                        <img src={img} alt={`فریمِ ${boundary}`} className="w-full rounded-lg" style={{ border: "1px solid var(--line)" }} data-testid={`regen-thumb-${which}`} />
                      ) : (
                        <div className="u-skeleton aspect-video w-full rounded-lg" />
                      )}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {range && (
          <div className="flex flex-wrap items-end gap-4" data-testid="regen-seconds">
            <TimeInput
              label="شروع (ثانیه)"
              testid="regen-start-sec"
              seconds={start / fps}
              note={`فریمِ ${start}`}
              onCommit={(t) => { const f = Math.max(0, Math.min(end, Math.round(t * fps))); setStart(f); setActive("start"); seek(f); }}
            />
            <TimeInput
              label="پایان (ثانیه)"
              testid="regen-end-sec"
              seconds={(end + 1) / fps}
              note={`تا آخرِ فریمِ ${end}`}
              onCommit={(t) => { const f = Math.min(n - 1, Math.max(start, Math.round(t * fps) - 1)); setEnd(f); setActive("end"); seek(f); }}
            />
            <TimeInput
              label="طول (ثانیه)"
              testid="regen-len-sec"
              seconds={count / fps}
              note={`${count} فریم`}
              onCommit={(t) => { const f = Math.min(n - 1, Math.max(start, start + Math.max(1, Math.round(t * fps)) - 1)); setEnd(f); seek(f); }}
            />
          </div>
        )}

        {range && (
          <p className="text-xs leading-6" style={{ color: "var(--text-3)" }} data-testid="regen-keys-hint">
            کلیدها: <b dir="ltr">← →</b> دستهٔ فعال یک فریم عقب/جلو · <b>Shift</b> یک ثانیه · <b>Ctrl</b> ده فریم ·{" "}
            <b>Home / End</b> اول/آخرِ ویدیو · <b dir="ltr">[ ]</b> شروع/پایان را فعال کن (یا روی کادرش بزنید) ·{" "}
            <b>فاصله</b> پخش/توقف. ← همیشه «عقب» است، مثلِ خطِ زمانی و دکمهٔ ⏴. ({mmss(start / fps)} ← {mmss((end + 1) / fps)})
          </p>
        )}

        {range && (
          <div className="flex flex-wrap items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
            <Badge tone={tooLong || whole ? "bad" : "brand"}>
              {fa(count)} فریم · {fa((count / fps).toFixed(2))} ثانیه
            </Badge>
            <span>
              از {clock(start / fps)} تا {clock((end + 1) / fps)}
            </span>
            <Button size="sm" variant="ghost" onClick={playRange}>
              <Icon name="play" size={14} /> پخشِ بازه (با یک ثانیه قبل و بعد)
            </Button>
            {tooLong && <span style={{ color: "var(--bad)" }}>حداکثر {fa(session.max_seconds)} ثانیه</span>}
          </div>
        )}
      </Card>

      <div ref={formRef}>
        <Card className="space-y-4">
          <SectionTitle>در این تکه چه اتفاقی بیفتد؟</SectionTitle>
          <label className="flex items-center gap-2 text-sm font-bold" style={{ color: "var(--text)" }}>
            <input type="checkbox" checked={picture} data-testid="regen-picture" onChange={(e) => setPicture(e.target.checked)} />
            تصویرِ این بازه هم با مدل دوباره ساخته شود
            {!picture && <Badge tone="info">فقط صدا — روی همین سرور، چند ثانیه</Badge>}
          </label>
          {picture && (<>
          <TextArea
            rows={3}
            value={form.prompt}
            data-testid="regen-prompt"
            placeholder="مثلاً: دستِ فروشنده بطری را آرام برمی‌دارد و به سمتِ دوربین می‌چرخاند — فارسی هم کافی است."
            onChange={(e) => setForm({ ...form, prompt: e.target.value })}
          />
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Field label="مدل">
              <Select value={form.engine} data-testid="regen-engine" onChange={(e) => {
                const eng = engines.find((x) => x.key === e.target.value);
                setForm({ ...form, engine: e.target.value, quality: eng?.qualities.includes(form.quality) ? form.quality : eng?.qualities[0] ?? "480p" });
              }}>
                {engines.map((e) => (
                  <option key={e.key} value={e.key}>
                    {e.label}
                    {e.ready === false ? " (روی سرورِ پردازش کامل نیست)" : ""}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="کیفیتِ ساخت">
              <Select value={form.quality} onChange={(e) => setForm({ ...form, quality: e.target.value })}>
                {(engine?.qualities ?? ["480p"]).map((q) => (
                  <option key={q} value={q}>
                    {q === "720p" ? "۷۲۰p — جزئیاتِ بیشتر، حدودِ ۲٫۵ برابر کندتر" : "۴۸۰p — پیش‌فرض"}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Seed" hint="خالی = تصادفی؛ همان seed و همان خواسته = همان نتیجه">
              <Input value={form.seed} dir="ltr" inputMode="numeric" onChange={(e) => setForm({ ...form, seed: e.target.value.replace(/[^0-9]/g, "") })} />
            </Field>
            <Field label="نرمیِ درز" hint="چند فریم در هر درز با اصل ترکیب شود">
              <Select value={form.blend} onChange={(e) => setForm({ ...form, blend: e.target.value })}>
                <option value="auto">خودکار (~۰٫۱ ثانیه)</option>
                {[0, 2, 3, 4, 6, 8].map((b) => (
                  <option key={b} value={String(b)}>
                    {b === 0 ? "بی ترکیب" : `${fa(b)} فریم`}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
            <input type="checkbox" checked={form.context === 5} onChange={(e) => setForm({ ...form, context: e.target.checked ? 5 : 1 })} />
            پیوستگیِ حرکت (آزمایشی): به‌جای یک فریم، پنج فریم از هر طرف به مدل داده شود تا جهت و سرعتِ حرکت را هم ببیند
          </label>
          </>)}

          <div className="space-y-2 rounded-xl p-3" style={{ background: "var(--surface-2)" }}>
            <b className="text-sm" style={{ color: "var(--text)" }}>
              <Icon name="music" size={14} /> صدای همین بازه
            </b>
            {session && (
              <AudioPanel
                storeId={storeId}
                sessionId={session.id}
                value={audioForm}
                onChange={setAudioForm}
                rangeSeconds={count / fps}
                hasAudio={hasAudio}
              />
            )}
          </div>

          {picture && est && !estError && (
            <div className="rounded-xl p-3 text-sm leading-7" style={{ background: "var(--surface-2)", color: "var(--text-2)" }} data-testid="regen-estimate">
              زمانِ تقریبی: <b style={{ color: "var(--text)" }}>{minutes(est.estimate.total_seconds)}</b> (ساخت روی سرورِ پردازش ≈{" "}
              {minutes(est.estimate.generate_seconds)}، چسباندن ≈ {minutes(est.estimate.stitch_seconds)}) · مدل{" "}
              {fa(est.plan.frames_total)} فریم در {fa(est.plan.chunks.length)} تکه می‌سازد ({fa(est.plan.gen_size[0])}×
              {fa(est.plan.gen_size[1])}، {fa(Math.round(est.plan.effective_fps * 10) / 10)} فریم/ثانیه) و تکه به{" "}
              {fa(Math.round(fps * 100) / 100)} فریم/ثانیهٔ ویدیو برمی‌گردد.{" "}
              {est.estimate.smart_splice
                ? "بقیهٔ ویدیو دوباره رمزگذاری نمی‌شود (چسباندنِ هوشمند)."
                : `کلِ ویدیو دوباره رمزگذاری می‌شود (${est.estimate.smart_reason}).`}
            </div>
          )}
          {picture && estError && <Alert tone="warn">{estError}</Alert>}
          {picture && engine && engine.ready === false && (
            <Alert tone="warn" title="این مدل روی سرورِ پردازش کامل نیست">
              {engine.missing.join("، ")} — در «سرورهای پردازش › مدل‌های صدا › بسته‌های دیگر» «دانلود» را بزنید، یا START.bat را روی آن کامپیوتر دوباره باز کنید (بخشِ اصلی را خودش دانلود می‌کند).
            </Alert>
          )}
          <div className="flex flex-wrap items-center gap-3">
            <Button disabled={busy || running || !range || tooLong || (picture && whole) || audioOnlyEmpty || replaceMissing}
              onClick={() => build()} data-testid="regen-build">
              <Icon name={picture ? "sparkle" : "music"} size={15} /> {picture ? "بساز" : "اعمالِ صدا"}
            </Button>
            {audioOnlyEmpty && <span className="text-sm" style={{ color: "var(--text-3)" }}>بی ساختِ تصویر، یکی از گزینه‌های صدا را انتخاب کنید.</span>}
            {replaceMissing && <span className="text-sm" style={{ color: "var(--text-3)" }}>صدای تازه را انتخاب کنید.</span>}
            {running && <span className="text-sm" style={{ color: "var(--text-3)" }}>یک نسخه در حالِ ساخت است…</span>}
          </div>
        </Card>
      </div>

      {range && (
        <Card className="space-y-2">
          <SectionTitle>حذفِ این بازه (برش)</SectionTitle>
          <p className="text-sm leading-7" style={{ color: "var(--text-2)" }}>
            تصویر و صدای فریمِ {fa(start)} تا {fa(end)} ({fa((count / fps).toFixed(2))} ثانیه) برداشته می‌شود و دو طرف به هم
            می‌رسند؛ صدا در جای چسب ۳۰ میلی‌ثانیه نرم می‌شود و طولِ ویدیو دقیقاً همین‌قدر کوتاه‌تر. فقط چند ثانیهٔ دورِ جای
            چسب دوباره رمزگذاری می‌شود (اگر ویدیو با x264 ساخته شده باشد). پیش‌نمایشِ جداگانه دارد و مثلِ بقیه قبول/دور انداختن.
          </p>
          <Button variant="danger" disabled={busy || running || whole} onClick={cutRange} data-testid="regen-cut">
            <Icon name="trash" size={14} /> برش بزن
          </Button>
        </Card>
      )}

      {versions.length > 0 && (
        <div className="space-y-3">
          <SectionTitle>نسخه‌ها</SectionTitle>
          {versions.map((v) => (
            <VersionCard
              key={v.id}
              v={v}
              fps={fps}
              isCurrent={session.current === v.id}
              busy={busy}
              onAction={act}
              onAgain={again}
              onEdit={edit}
            />
          ))}
        </div>
      )}
    </div>
  );
}
