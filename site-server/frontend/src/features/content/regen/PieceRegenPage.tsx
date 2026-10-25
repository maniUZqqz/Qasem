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
import { clock, Engine, Estimate, minutes, regenApi, Session, Source, Version } from "./api";
import RangePicker from "./RangePicker";
import VersionCard from "./VersionCard";

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
                <video src={s.url} preload="metadata" muted playsInline className="aspect-video w-full rounded-lg object-cover" style={{ background: "#000" }} />
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

  const active = session?.state === "PREPARING" || (session?.versions ?? []).some((v) => v.active);
  useEffect(() => {
    if (!active) return;
    const t = window.setInterval(load, 3000);
    return () => window.clearInterval(t);
  }, [active, load]);

  // تا بررسیِ ویدیو تمام نشده، info خالی است (همهٔ کلیدها null)
  const info = session?.state === "READY" && session.info?.n_frames ? session.info : undefined;
  const fps = info?.fps || 30;
  const n = info?.n_frames || 0;
  const maxCount = Math.max(1, Math.floor((session?.max_seconds ?? 20) * fps));

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

  async function build(override?: Partial<Form> & { start?: number; end?: number }) {
    if (!session || !range) return;
    setBusy(true);
    setError(null);
    const f = { ...form, ...override };
    try {
      await regenApi.create(storeId, session.id, {
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

  function again(v: Version) {
    setRange([v.start, v.end]);
    build({ prompt: v.prompt, engine: v.engine, quality: v.quality, seed: "", context: v.context,
            blend: v.blend === null ? "auto" : String(v.blend), start: v.start, end: v.end });
  }

  function edit(v: Version) {
    setRange([v.start, v.end]);
    setForm({ prompt: v.prompt, engine: v.engine, quality: v.quality, seed: "", context: v.context, blend: v.blend === null ? "auto" : String(v.blend) });
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
          preload="auto"
          data-testid="regen-player"
          className="mx-auto w-full rounded-lg"
          style={{ background: "#000", maxHeight: 420 }}
        />

        <div className="flex flex-wrap items-center justify-between gap-2 text-sm" style={{ color: "var(--text-2)" }}>
          <span data-testid="regen-playhead">
            جای پخش: فریمِ <b style={{ color: "var(--text)" }}>{fa(playhead)}</b> · {clock(playhead / fps)}
          </span>
          <div className="flex flex-wrap gap-1.5">
            <Button size="sm" variant="ghost" onClick={() => seek(playhead - 1)} title="یک فریم عقب">
              ⏴ فریم
            </Button>
            <Button size="sm" variant="ghost" onClick={() => seek(playhead + 1)} title="یک فریم جلو">
              فریم ⏵
            </Button>
            <Button size="sm" variant="secondary" onClick={() => setStart(playhead)} data-testid="regen-set-start">
              شروع = همین فریم
            </Button>
            <Button size="sm" variant="secondary" onClick={() => setEnd(playhead)} data-testid="regen-set-end">
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
            onChange={(s, e) => setRange([s, e])}
            onSeek={seek}
          />
        )}

        {range && (
          <div className="grid gap-4 md:grid-cols-2">
            {(["start", "end"] as const).map((which) => {
              const value = which === "start" ? start : end;
              const set = which === "start" ? setStart : setEnd;
              const img = which === "start" ? before : after;
              const boundary = which === "start" ? start - 1 : end + 1;
              return (
                <div key={which} className="space-y-2">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-sm font-bold" style={{ color: "var(--text)" }}>
                      {which === "start" ? "اولین فریمِ تکه" : "آخرین فریمِ تکه"}
                    </span>
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

          {est && !estError && (
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
          {estError && <Alert tone="warn">{estError}</Alert>}
          {engine && engine.ready === false && (
            <Alert tone="warn" title="این مدل روی سرورِ پردازش کامل نیست">
              {engine.missing.join("، ")} — در «سرورهای پردازش › مدل‌های صدا › بسته‌های دیگر» «دانلود» را بزنید، یا START.bat را روی آن کامپیوتر دوباره باز کنید (بخشِ اصلی را خودش دانلود می‌کند).
            </Alert>
          )}
          <div className="flex flex-wrap items-center gap-3">
            <Button disabled={busy || running || !range || tooLong || whole} onClick={() => build()} data-testid="regen-build">
              <Icon name="sparkle" size={15} /> بساز
            </Button>
            {running && <span className="text-sm" style={{ color: "var(--text-3)" }}>یک نسخه در حالِ ساخت است…</span>}
          </div>
        </Card>
      </div>

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
