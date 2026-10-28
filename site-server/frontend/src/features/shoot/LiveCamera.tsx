import { useCallback, useEffect, useRef, useState } from "react";

import Icon from "../../components/Icon";
import type { Shot } from "./api";
import { fa } from "./api";
import Portal, { LAYER } from "./Portal";
import { LiveOverlay } from "./ShotGuide";

/**
 * حالتِ «دوربینِ زنده» (فقط https یا localhost): تصویرِ دوربین تمام‌صفحه، کادر و فلش روی آن، شمارشِ معکوس،
 * و حینِ ضبط جمله‌های راهنما در زمانِ خودشان (نوشته + صدا + لرزش). اگر گوشی حسگرِ چرخش بدهد، «چند درجه
 * چرخیده‌ای» هم دیده می‌شود. ضبط سرِ مدتِ برنامه خودش می‌ایستد.
 */

type Phase = "ready" | "countdown" | "recording" | "saving";

function pickMime(): string {
  if (typeof MediaRecorder === "undefined") return "";
  const options = [
    "video/mp4;codecs=avc1.42E01E",
    "video/mp4",
    "video/webm;codecs=vp9",
    "video/webm;codecs=vp8",
    "video/webm",
  ];
  return options.find((m) => MediaRecorder.isTypeSupported?.(m)) ?? "";
}

type OrientationCtor = { requestPermission?: () => Promise<"granted" | "denied"> };

export default function LiveCamera({
  shot,
  speak,
  onCaptured,
  onClose,
}: {
  shot: Shot;
  speak: (text: string, opts?: { vibrate?: number }) => void;
  onCaptured: (blob: Blob, name: string) => void;
  onClose: () => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const recRef = useRef<MediaRecorder | null>(null);
  const timers = useRef<number[]>([]);
  const baseAlpha = useRef<number | null>(null);
  const [phase, setPhase] = useState<Phase>("ready");
  const [count, setCount] = useState(3);
  const [elapsed, setElapsed] = useState(0);
  const [cue, setCue] = useState("");
  const [turned, setTurned] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const isVideo = shot.kind === "video";

  const clearTimers = () => {
    timers.current.forEach((t) => window.clearTimeout(t));
    timers.current = [];
  };

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1080 } },
          audio: false,
        });
        if (!alive) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play().catch(() => undefined);
        }
      } catch (err) {
        setError(
          (err as Error)?.name === "NotAllowedError"
            ? "اجازهٔ دوربین داده نشد. از تنظیماتِ مرورگر اجازه بده یا «دوربینِ گوشی» را انتخاب کن."
            : "دوربین باز نشد: " + ((err as Error)?.message || "نامشخص"),
        );
      }
    })();
    return () => {
      alive = false;
      clearTimers();
      try {
        if (recRef.current && recRef.current.state !== "inactive") recRef.current.stop();
      } catch {
        /* */
      }
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  // حسگرِ چرخش: درجهٔ چرخش نسبت به لحظهٔ «شروع»
  useEffect(() => {
    const onOrient = (e: DeviceOrientationEvent) => {
      if (e.alpha == null) return;
      if (baseAlpha.current == null) baseAlpha.current = e.alpha;
      let d = e.alpha - baseAlpha.current;
      if (d > 180) d -= 360;
      if (d < -180) d += 360;
      setTurned(d);
    };
    window.addEventListener("deviceorientation", onOrient);
    return () => window.removeEventListener("deviceorientation", onOrient);
  }, []);

  const speakRef = useRef(speak);
  speakRef.current = speak;
  // فقط وقتی زاویه/نما عوض شد (نه با هر تازه‌سازیِ جلسه)
  useEffect(() => {
    setPhase("ready");
    setCue("");
    setElapsed(0);
    baseAlpha.current = null;
    const t = window.setTimeout(() => speakRef.current(shot.instruction), 300);
    return () => window.clearTimeout(t);
  }, [shot.key, shot.instruction]);

  const capturePhoto = useCallback(() => {
    const video = videoRef.current;
    if (!video || !video.videoWidth) {
      setError("تصویرِ دوربین هنوز نرسیده.");
      setPhase("ready");
      return;
    }
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")?.drawImage(video, 0, 0);
    setPhase("saving");
    canvas.toBlob(
      (blob) => {
        if (blob) {
          speak("عکس گرفته شد", { vibrate: 60 });
          onCaptured(blob, `${shot.key}.jpg`);
        } else {
          setError("عکس ساخته نشد.");
          setPhase("ready");
        }
      },
      "image/jpeg",
      0.92,
    );
  }, [onCaptured, shot.key, speak]);

  const startRecording = useCallback(() => {
    const stream = streamRef.current;
    if (!stream || shot.kind !== "video") return;
    const mime = pickMime();
    let rec: MediaRecorder;
    try {
      rec = mime ? new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 6_000_000 }) : new MediaRecorder(stream);
    } catch {
      setError("این مرورگر ضبطِ ویدیو ندارد؛ «دوربینِ گوشی» را انتخاب کن.");
      setPhase("ready");
      return;
    }
    const chunks: Blob[] = [];
    rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    rec.onstop = () => {
      const type = rec.mimeType || mime || "video/webm";
      const blob = new Blob(chunks, { type });
      setPhase("saving");
      speak("ضبط تمام شد", { vibrate: 120 });
      onCaptured(blob, `${shot.key}.${type.includes("mp4") ? "mp4" : "webm"}`);
    };
    recRef.current = rec;
    rec.start(500);
    setPhase("recording");
    baseAlpha.current = null;
    const startedAt = performance.now();
    const tick = window.setInterval(() => {
      const s = (performance.now() - startedAt) / 1000;
      setElapsed(s);
      if (s >= shot.duration + 0.3) {
        window.clearInterval(tick);
        if (rec.state !== "inactive") rec.stop();
      }
    }, 100);
    timers.current.push(tick as unknown as number);
    for (const c of shot.cues) {
      timers.current.push(
        window.setTimeout(() => {
          setCue(c.text);
          speak(c.text, { vibrate: 40 });
        }, c.at * 1000),
      );
    }
  }, [onCaptured, shot, speak]);

  const begin = async () => {
    setError(null);
    // iOS: حسگرِ چرخش فقط با اجازه و فقط با لمسِ کاربر
    const ctor = (window as unknown as { DeviceOrientationEvent?: OrientationCtor }).DeviceOrientationEvent;
    if (ctor?.requestPermission) {
      try {
        await ctor.requestPermission();
      } catch {
        /* بی‌حسگر هم کار می‌کند */
      }
    }
    setPhase("countdown");
    ["سه", "دو", "یک"].forEach((word, i) => {
      timers.current.push(
        window.setTimeout(() => {
          setCount(3 - i);
          speak(word, { vibrate: 30 });
        }, i * 900),
      );
    });
    timers.current.push(
      window.setTimeout(() => {
        if (isVideo) startRecording();
        else capturePhoto();
      }, 2700),
    );
  };

  const stopEarly = () => {
    clearTimers();
    if (recRef.current && recRef.current.state !== "inactive") recRef.current.stop();
  };

  const progress = isVideo ? Math.min(1, elapsed / Math.max(1, shot.duration)) : 0;

  return (
    <Portal>
    <div className="fixed inset-0 flex flex-col" style={{ background: "#000", color: "#fff", zIndex: LAYER.camera }} data-testid="live-camera">
      <div className="relative flex-1 overflow-hidden">
        <video ref={videoRef} playsInline muted autoPlay className="absolute inset-0 h-full w-full object-cover" />
        <LiveOverlay shot={shot} turned={phase === "recording" || phase === "ready" ? turned : null} />
        <div className="absolute inset-x-0 top-0 flex items-start justify-between gap-2 p-3" style={{ background: "linear-gradient(#000a, transparent)" }}>
          <div className="min-w-0">
            <div className="text-lg font-extrabold">{shot.title}</div>
            {isVideo && (
              <div className="text-sm opacity-90">
                {fa(shot.duration)} ثانیه
                {phase === "recording" ? ` — ${fa(Math.floor(elapsed))}` : ""}
              </div>
            )}
          </div>
          <button
            onClick={onClose}
            className="grid h-12 w-12 shrink-0 place-items-center rounded-full"
            style={{ background: "#0008" }}
            aria-label="بستن"
          >
            <Icon name="x" size={22} />
          </button>
        </div>
        {phase === "countdown" && (
          <div className="absolute inset-0 grid place-items-center text-8xl font-extrabold" style={{ textShadow: "0 2px 12px #000" }}>
            {fa(count)}
          </div>
        )}
        {phase === "recording" && cue && (
          <div className="absolute inset-x-4 top-1/3 rounded-2xl px-4 py-3 text-center text-2xl font-extrabold" style={{ background: "#000a" }} data-testid="live-cue">
            {cue}
          </div>
        )}
        {error && (
          <div className="absolute inset-x-4 top-20 rounded-xl px-4 py-3 text-sm" style={{ background: "#b91c1cdd" }}>
            {error}
          </div>
        )}
      </div>
      <div className="space-y-3 p-4" style={{ background: "#111" }}>
        <p className="text-base leading-7" data-testid="live-instruction">
          {shot.instruction}
        </p>
        <div className="flex items-center justify-center gap-6">
          {phase === "recording" ? (
            <button
              onClick={stopEarly}
              className="relative grid h-20 w-20 place-items-center rounded-full"
              style={{ background: `conic-gradient(#ef4444 ${progress * 360}deg, #444 0)` }}
              aria-label="توقف"
            >
              <span className="block h-8 w-8 rounded-md" style={{ background: "#fff" }} />
            </button>
          ) : (
            <button
              onClick={() => void begin()}
              disabled={phase !== "ready" || !!error}
              className="grid h-20 w-20 place-items-center rounded-full disabled:opacity-40"
              style={{ background: isVideo ? "#ef4444" : "#fff", border: "5px solid #ffffff55" }}
              aria-label={isVideo ? "شروعِ ضبط" : "گرفتنِ عکس"}
              data-testid="live-shutter"
            >
              {phase === "saving" ? <span className="text-sm text-black">…</span> : null}
            </button>
          )}
        </div>
        <p className="text-center text-xs opacity-70">
          {isVideo ? "دکمهٔ قرمز ⇐ شمارشِ «سه، دو، یک» ⇐ ضبط؛ سرِ وقت خودش می‌ایستد." : "دکمهٔ سفید ⇐ «سه، دو، یک» ⇐ عکس."}
        </p>
      </div>
    </div>
    </Portal>
  );
}
