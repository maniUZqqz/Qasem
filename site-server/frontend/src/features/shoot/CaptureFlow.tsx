import { ChangeEvent, ReactNode, useEffect, useMemo, useRef, useState } from "react";

import { errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import { Alert, Badge, Button, Card } from "../../components/ui";
import { useFeature } from "../panel/FlagsContext";
import LiveCamera from "./LiveCamera";
import Portal, { LAYER } from "./Portal";
import { ShotDiagram } from "./ShotGuide";
import {
  Session,
  Shot,
  Take,
  UploadStopped,
  fa,
  liveSupport,
  newUploadId,
  shootApi,
  shotsOf,
  shrinkPhoto,
  uploadTake,
} from "./api";
import { useCueVoice } from "./voice";

/**
 * یک زاویه/نما در هر صفحه، به ترتیبِ برنامه: دستور + نقشه + تمرین ⇐ دوربین ⇐ آپلودِ تکه‌تکه ⇐ وارسی ⇐
 * «قبول شد، بعدی» یا «دوباره بگیر». هر زاویه را هر وقت خواستی با دکمه‌های بالای صفحه دوباره می‌گیری.
 *
 * دو حالت با یک برنامه: «دوربینِ زنده» (فقط https/localhost: راهنما حینِ ضبط) و «دوربینِ گوشی (گام‌به‌گام)» که
 * روی همین پنلِ http کار می‌کند: دستور و تمرین پیش از باز شدنِ دوربینِ خودِ گوشی.
 */

type Upload = { progress: number; blob?: Blob; name?: string; id?: string; mode?: string; error?: string };

const big = { minHeight: 56, fontSize: "1.02rem" } as const;

export default function CaptureFlow({
  storeId,
  session,
  onSession,
  kinds,
  footer,
}: {
  storeId: number | string;
  session: Session;
  onSession: (s: Session) => void;
  kinds: ("photo" | "video")[];
  footer?: ReactNode;
}) {
  const shots = useMemo(() => shotsOf(session.plan, kinds), [session.plan, kinds]);
  const support = useMemo(liveSupport, []);
  const liveFlag = useFeature("shoot.live");
  const canLive = support.ok && liveFlag;
  const [mode, setMode] = useState<"live" | "native">(canLive ? "live" : "native");
  const accepted = (key: string) => session.takes.some((t) => t.shot === key && t.accepted);
  const [idx, setIdx] = useState(() => Math.max(0, shots.findIndex((s) => !accepted(s.key))));
  const [voiceOn, setVoiceOn] = useState(true);
  const speak = useCueVoice(session.voice?.clips, voiceOn);
  const [liveOpen, setLiveOpen] = useState(false);
  const [upload, setUpload] = useState<Upload | null>(null);
  const [result, setResult] = useState<Take | null>(null);
  const [practice, setPractice] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showWhy, setShowWhy] = useState(false);

  const shot: Shot | undefined = shots[Math.min(idx, shots.length - 1)];
  const takes = shot ? session.takes.filter((t) => t.shot === shot.key) : [];
  const doneCount = shots.filter((s) => accepted(s.key)).length;
  const videoLiveOk = support.video;

  useEffect(() => {
    setResult(null);
    setUpload(null);
    setError(null);
  }, [shot?.key]);

  // روی گوشی نتیجه زیرِ کارتِ زاویه است: خودش جلوی چشم بیاید
  const resultRef = useRef<HTMLDivElement>(null);
  const verdictRef = useRef<HTMLDivElement>(null);
  const showing = result?.id ?? (upload ? (upload.error ? "err" : "up") : null);
  useEffect(() => {
    if (showing !== null) (verdictRef.current ?? resultRef.current)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [showing]);

  if (!shot) {
    return <Alert tone="warn">برنامه هیچ زاویه یا نمایی ندارد.</Alert>;
  }

  const go = (i: number) => {
    setIdx(Math.max(0, Math.min(shots.length - 1, i)));
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const send = async (raw: Blob, name: string, how: string, retry?: Upload) => {
    setResult(null);
    setError(null);
    const id = retry?.id || newUploadId();
    let blob = retry?.blob || raw;
    setUpload({ progress: 0, blob, name, id, mode: how });
    try {
      if (!retry && shot.kind === "photo") blob = await shrinkPhoto(raw);
      setUpload({ progress: 0, blob, name, id, mode: how });
      const take = await uploadTake({
        storeId,
        sessionId: session.id,
        shot: shot.key,
        kind: shot.kind,
        blob,
        name,
        mode: how,
        uploadId: retry ? id : undefined,
        onProgress: (p) => setUpload((u) => (u ? { ...u, progress: p } : u)),
      });
      setUpload(null);
      setResult(take);
      onSession({ ...session, takes: [...session.takes.filter((t) => t.id !== take.id), take] });
      speak(take.ok ? "عالی! بعدی" : "بهتر است دوباره بگیری", { vibrate: take.ok ? 50 : 200 });
    } catch (err) {
      setUpload({
        progress: 0,
        blob,
        name,
        id,
        mode: how,
        error: err instanceof UploadStopped ? err.message : errorMessage(err),
      });
    }
  };

  const onFile = (e: ChangeEvent<HTMLInputElement>, how: string) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (file) void send(file, file.name || `${shot.key}`, how);
  };

  const setAccepted = async (take: Take, value: boolean) => {
    try {
      const t = await shootApi.setTake(storeId, session.id, take.id, value);
      onSession({ ...session, takes: session.takes.map((x) => (x.id === t.id ? t : x)) });
      if (result?.id === t.id) setResult(t);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const removeTake = async (take: Take) => {
    try {
      await shootApi.deleteTake(storeId, session.id, take.id);
      onSession({ ...session, takes: session.takes.filter((x) => x.id !== take.id) });
      if (result?.id === take.id) setResult(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const isVideo = shot.kind === "video";
  const accept = isVideo ? "video/*" : "image/*";
  const liveForThis = mode === "live" && canLive && (!isVideo || videoLiveOk);
  const cameraButton = (label: string, variant: "primary" | "secondary" = "primary") =>
    liveForThis ? (
      <Button variant={variant} className="w-full" style={big} onClick={() => setLiveOpen(true)} data-testid="open-live">
        <Icon name={isVideo ? "film" : "image"} size={18} />
        {label}
      </Button>
    ) : (
      <label className={`u-btn u-btn-${variant} w-full cursor-pointer`} style={big} data-testid="open-native">
        <Icon name={isVideo ? "film" : "image"} size={18} />
        {label}
        <input
          type="file"
          accept={accept}
          capture="environment"
          className="hidden"
          data-testid="native-input"
          onChange={(e) => onFile(e, "native")}
        />
      </label>
    );

  return (
    <div className="space-y-4 pb-24" data-testid="capture-flow">
      {/* نوارِ پیشرفت: هر زاویه یک دکمه (برای «دوباره بگیر» ِ هر زاویه‌ای) */}
      <div className="flex gap-2 overflow-x-auto pb-1" style={{ scrollbarWidth: "thin" }}>
        {shots.map((s, i) => {
          const ok = accepted(s.key);
          const tried = session.takes.some((t) => t.shot === s.key);
          const active = i === idx;
          return (
            <button
              key={s.key}
              onClick={() => go(i)}
              className="shrink-0 rounded-full px-3 text-sm font-semibold"
              style={{
                minHeight: 40,
                background: active ? "var(--brand)" : ok ? "var(--ok-soft)" : "var(--surface-2)",
                color: active ? "#fff" : ok ? "var(--ok)" : tried ? "var(--warn)" : "var(--text-2)",
                border: "1px solid var(--line)",
              }}
              data-testid={`chip-${s.key}`}
            >
              {ok ? "✓ " : tried ? "! " : ""}
              {fa(i + 1)}. {s.title}
            </button>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 text-sm" style={{ color: "var(--text-3)" }}>
        <span>
          {fa(doneCount)} از {fa(shots.length)} قبول شده
        </span>
        <label className="flex items-center gap-2" style={{ minHeight: 40 }}>
          <input type="checkbox" checked={voiceOn} onChange={(e) => setVoiceOn(e.target.checked)} />
          راهنمای صوتی
        </label>
      </div>

      {/* حالت */}
      <div className="grid grid-cols-2 gap-2">
        <button
          onClick={() => canLive && setMode("live")}
          disabled={!canLive}
          className="rounded-xl px-3 py-3 text-sm font-bold disabled:opacity-50"
          style={{
            background: mode === "live" && canLive ? "var(--brand)" : "var(--surface-2)",
            color: mode === "live" && canLive ? "#fff" : "var(--text-2)",
            border: "1px solid var(--line)",
          }}
          data-testid="mode-live"
        >
          دوربینِ زنده
          <span className="block text-xs font-normal opacity-80">راهنما حینِ ضبط</span>
        </button>
        <button
          onClick={() => setMode("native")}
          className="rounded-xl px-3 py-3 text-sm font-bold"
          style={{
            background: mode === "native" || !canLive ? "var(--brand)" : "var(--surface-2)",
            color: mode === "native" || !canLive ? "#fff" : "var(--text-2)",
            border: "1px solid var(--line)",
          }}
          data-testid="mode-native"
        >
          دوربینِ گوشی
          <span className="block text-xs font-normal opacity-80">گام‌به‌گام، روی http هم</span>
        </button>
      </div>
      {!canLive && (
        <div className="text-sm" style={{ color: "var(--text-3)" }}>
          <button className="underline" onClick={() => setShowWhy((v) => !v)} data-testid="why-native">
            چرا دوربینِ زنده خاموش است؟
          </button>
          {showWhy && (
            <p className="mt-1 leading-6" data-testid="why-native-text">
              {support.ok && !liveFlag ? "ادمین حالتِ دوربینِ زنده را خاموش کرده است." : support.reason}
            </p>
          )}
        </div>
      )}
      {mode === "live" && canLive && isVideo && !videoLiveOk && (
        <Alert tone="warn">این مرورگر ضبطِ زنده ندارد؛ برای ویدیو دوربینِ گوشی باز می‌شود.</Alert>
      )}

      {/* کارتِ زاویه/نما */}
      <Card>
        <div className="mb-2 flex items-center justify-between gap-2">
          <Badge tone={isVideo ? "info" : "brand"}>
            {isVideo ? "ویدیو" : "عکس"} — {fa(idx + 1)} از {fa(shots.length)}
          </Badge>
          {accepted(shot.key) && <Badge tone="ok">✓ قبول شده</Badge>}
        </div>
        <h2 className="text-xl font-extrabold" style={{ color: "var(--text)" }} data-testid="shot-title">
          {shot.title}
        </h2>
        <p className="mt-2 text-lg leading-8" style={{ color: "var(--text)" }} data-testid="shot-instruction">
          {shot.instruction}
        </p>
        <div className="my-3 flex justify-center">
          <ShotDiagram shot={shot} animate={practice} />
        </div>
        <div className="mb-3 flex justify-center">
          <button className="text-sm underline" style={{ color: "var(--text-3)" }} onClick={() => setPractice((v) => !v)}>
            {practice ? "توقفِ تمرین" : "دیدنِ تمرینِ حرکت"}
          </button>
        </div>
        {shot.tip && (
          <p className="mb-2 text-sm" style={{ color: "var(--text-2)" }}>
            نکته: {shot.tip}
          </p>
        )}
        {idx === 0 && (
          <div className="mb-3 rounded-xl p-3 text-sm leading-6" style={{ background: "var(--surface-2)", color: "var(--text-2)" }}>
            <div>زمینه: {session.plan.setup.background}</div>
            <div>نور: {session.plan.setup.lighting}</div>
            {session.plan.setup.tips.map((t) => (
              <div key={t}>• {t}</div>
            ))}
          </div>
        )}
        {isVideo && (
          <div className="mb-3 rounded-xl p-3 text-sm leading-7" style={{ background: "var(--surface-2)" }} data-testid="cue-list">
            {!liveForThis && (
              <div className="mb-1 font-bold" style={{ color: "var(--text)" }}>
                دوربین که باز شد: ضبط را بزن، این کارها را بکن، حدودِ {fa(shot.duration)} ثانیه بعد توقف را بزن.
              </div>
            )}
            {shot.cues.map((c) => (
              <div key={c.at + c.text} style={{ color: "var(--text-2)" }}>
                ثانیهٔ {fa(c.at)}: {c.text}
              </div>
            ))}
          </div>
        )}
        <div className="space-y-2">
          {cameraButton(liveForThis ? "باز کردنِ دوربینِ زنده" : isVideo ? "باز کردنِ دوربینِ گوشی و ضبط" : "باز کردنِ دوربینِ گوشی")}
          <div className="flex items-center justify-between gap-2">
            <button className="text-sm underline" style={{ color: "var(--text-3)" }} onClick={() => speak(shot.instruction)}>
              دوباره بگو
            </button>
            <label className="cursor-pointer text-sm underline" style={{ color: "var(--text-3)" }}>
              انتخاب از گالری
              <input type="file" accept={accept} className="hidden" onChange={(e) => onFile(e, "upload")} data-testid="gallery-input" />
            </label>
          </div>
        </div>
      </Card>

      {error && <Alert tone="bad">{error}</Alert>}

      <div ref={resultRef} />
      {upload && (
        <Card>
          {upload.error ? (
            <div className="space-y-3">
              <Alert tone="bad">{upload.error}</Alert>
              {upload.blob && (
                <Button className="w-full" style={big} onClick={() => void send(upload.blob!, upload.name || shot.key, upload.mode || "native", upload)}>
                  <Icon name="refresh" size={17} />
                  ارسالِ دوباره (از همان‌جا)
                </Button>
              )}
            </div>
          ) : (
            <div data-testid="uploading">
              <div className="mb-2 text-sm font-semibold" style={{ color: "var(--text)" }}>
                {upload.progress < 1 ? `ارسال… ${fa(Math.round(upload.progress * 100))}٪` : "در حالِ بررسیِ کیفیت…"}
              </div>
              <div className="u-meter">
                <span style={{ width: `${Math.max(4, upload.progress * 100)}%` }} />
              </div>
            </div>
          )}
        </Card>
      )}

      {result && (
        <Card>
          <div data-testid="take-result" data-ok={result.ok ? "1" : "0"}>
            <div className="mb-3 overflow-hidden rounded-xl" style={{ background: "#000" }}>
              {result.kind === "video" ? (
                <video src={result.preview || result.url} controls playsInline muted className="max-h-60 w-full" />
              ) : (
                <img src={result.thumb || result.url} alt="" className="max-h-60 w-full object-contain" />
              )}
            </div>
            <div
              ref={verdictRef}
              className="rounded-xl p-3 text-base font-bold"
              style={{
                background: result.ok ? "var(--ok-soft)" : "var(--bad-soft)",
                color: result.ok ? "var(--ok)" : "var(--bad)",
              }}
            >
              {result.ok ? "✓ قبول شد" : "✗ بهتر است دوباره بگیری"}
            </div>
            {result.problems.length > 0 && (
              <ul className="mt-2 space-y-1 text-sm leading-6" style={{ color: "var(--text-2)" }}>
                {result.problems.map((p) => (
                  <li key={p.code}>• {p.message}</li>
                ))}
              </ul>
            )}
            {result.where && (
              <p className="mt-1 text-xs" style={{ color: "var(--text-3)" }}>
                بررسی: {result.where}
              </p>
            )}
            <div className="mt-3 grid gap-2">
              {result.ok ? (
                <>
                  <Button className="w-full" style={big} onClick={() => go(idx + 1)} disabled={idx >= shots.length - 1} data-testid="next-shot">
                    {idx >= shots.length - 1 ? "همهٔ زاویه‌ها تمام شد" : "بعدی"}
                    <Icon name="next" size={17} />
                  </Button>
                  {cameraButton("دوباره بگیر", "secondary")}
                </>
              ) : (
                <>
                  {cameraButton("دوباره بگیر")}
                  <Button
                    variant="secondary"
                    className="w-full"
                    style={big}
                    onClick={async () => {
                      await setAccepted(result, true);
                      if (idx < shots.length - 1) go(idx + 1);
                    }}
                    data-testid="accept-anyway"
                  >
                    با همین ادامه بده
                  </Button>
                </>
              )}
            </div>
          </div>
        </Card>
      )}

      {takes.length > 0 && (
        <Card>
          <div className="mb-2 text-sm font-bold" style={{ color: "var(--text)" }}>
            برداشت‌های این {isVideo ? "نما" : "زاویه"} ({fa(takes.length)})
          </div>
          <div className="grid grid-cols-3 gap-2">
            {takes.map((t) => (
              <div key={t.id} className="rounded-xl p-1" style={{ border: `2px solid ${t.accepted ? "var(--ok)" : "var(--line)"}` }}>
                <img src={t.thumb || t.url} alt="" className="h-20 w-full rounded-lg object-cover" />
                <div className="mt-1 flex items-center justify-between gap-1">
                  <button
                    className="text-xs font-semibold"
                    style={{ color: t.accepted ? "var(--ok)" : "var(--text-3)", minHeight: 32 }}
                    onClick={() => void setAccepted(t, !t.accepted)}
                  >
                    {t.accepted ? "✓ قبول" : "قبول کن"}
                  </button>
                  <button className="text-xs" style={{ color: "var(--bad)", minHeight: 32 }} onClick={() => void removeTake(t)} aria-label="حذف">
                    <Icon name="trash" size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {doneCount === shots.length && footer}

      {/* ناوبریِ پایین: یک‌دستی */}
      <Portal>
      <div
        className="fixed inset-x-0 bottom-0 flex gap-2 p-3"
        style={{ background: "var(--bg)", borderTop: "1px solid var(--line-strong)", boxShadow: "var(--shadow)", zIndex: LAYER.bar }}
        data-testid="bottom-nav"
      >
        <Button variant="secondary" className="flex-1" style={big} onClick={() => go(idx - 1)} disabled={idx === 0}>
          <Icon name="back" size={17} />
          قبلی
        </Button>
        {idx < shots.length - 1 ? (
          <Button variant={accepted(shot.key) ? "primary" : "secondary"} className="flex-1" style={big} onClick={() => go(idx + 1)} data-testid="nav-next">
            {accepted(shot.key) ? "بعدی" : "رد شو"}
            <Icon name="next" size={17} />
          </Button>
        ) : (
          <div className="flex-1 self-center text-center text-sm" style={{ color: "var(--text-3)" }}>
            {fa(doneCount)} از {fa(shots.length)} قبول
          </div>
        )}
      </div>
      </Portal>

      {liveOpen && (
        <LiveCamera
          shot={shot}
          speak={speak}
          onClose={() => setLiveOpen(false)}
          onCaptured={(blob, name) => {
            setLiveOpen(false);
            void send(blob, name, "live");
          }}
        />
      )}
    </div>
  );
}
