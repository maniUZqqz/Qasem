import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api, errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import {
  Alert,
  Badge,
  Button,
  Card,
  Field,
  Input,
  Meter,
  SectionTitle,
  Spinner,
  TextArea,
  fa,
} from "../../components/ui";
import { useStore } from "./StoreLayout";
import VoiceTabs from "./VoiceTabs";

/**
 * کلونِ صدا — صدای خودِ فروشگاه، از روی چند جمله که صاحبِ صدا می‌خواند.
 *
 * ترتیبِ کار همان ترتیبِ صفحه است: رضایت ⇐ خواندنِ جمله‌ها (ضبط در مرورگر یا فایل) و وارسیِ
 * فوریِ هر تکه روی سایت ⇐ «ساختِ صدا» روی سرورِ پردازش (که هر تکه را دوباره، این بار با
 * گفتار‌به‌متن، می‌شنود) ⇐ آزمایش با هر متن ⇐ «استفاده در محتوا».
 *
 * ضبط بی‌افت است: صدا مستقیم از میکروفون (بی حذفِ نویز و بی تنظیمِ خودکارِ بلندیِ مرورگر، که
 * رنگِ صدا را عوض می‌کنند) به WAVِ ۱۶ بیتی تبدیل می‌شود — نه opus/webm ِ فشرده.
 */

type NodeVerdict = { ok?: boolean; message?: string; heard?: string; wer?: number | null; snr?: number | null };

type CloneClip = {
  index: number;
  text: string;
  source: string;
  original_name: string;
  seconds: number;
  snr: number | null;
  level: number | null;
  clipped: number;
  ok: boolean;
  message: string;
  node: NodeVerdict;
  updated_at: string;
};

type JobState = {
  uid: string;
  state: string;
  label: string;
  progress: number;
  message: string;
  node: string | null;
  final: boolean;
  error: string;
  audio?: boolean;
  check?: number | null;
};

type ClonedVoiceT = {
  id: number;
  name: string;
  person: string;
  purpose: string;
  status: "DRAFT" | "BUILDING" | "READY" | "FAILED";
  status_label: string;
  usable: boolean;
  in_use: boolean;
  engine: string;
  engine_label: string;
  license: string;
  commercial: boolean;
  consent: { text: string; at: string; by: string };
  node_name: string;
  revision: number;
  built_at: string | null;
  error: string;
  report: { accepted?: number; rejected?: number; minutes?: number; check?: number | null; took?: number; sample_text?: string };
  clips_ok: number;
  clips_total: number;
  seconds_ok: number;
  needs_rebuild: boolean;
  has_preview: boolean;
  has_reference: boolean;
  build: JobState | null;
  clips?: CloneClip[];
};

type ScriptLine = { index: number; text: string; group: string };

type NodeRow = {
  name: string;
  online: boolean;
  agent: string | null;
  voice_up: boolean;
  clone_ready: boolean | null;
  last_seen_text: string;
  gpu: string | null;
};

type CloneList = {
  voices: ClonedVoiceT[];
  script: ScriptLine[];
  limits: {
    min_clips: number;
    recommended_clips: number;
    min_seconds: number;
    max_seconds: number;
    max_upload_mb: number;
    custom_index_base: number;
  };
  nodes: { online: boolean; nodes: NodeRow[]; message: string };
  consent_template: string;
  default_purpose: string;
  engine: { id: string; label: string; license: string; commercial: boolean };
  in_use: number | null;
};

type ClipResult = { clip: CloneClip; check: { ok: boolean; message: string; seconds: number; snr: number; level: number }; voice: ClonedVoiceT };

const STATUS_TONE: Record<ClonedVoiceT["status"], "neutral" | "info" | "ok" | "bad"> = {
  DRAFT: "neutral",
  BUILDING: "info",
  READY: "ok",
  FAILED: "bad",
};

// ───────────────────────────────────────────── recording (lossless PCM → WAV)

type Level = { db: number; peak: number; seconds: number; clipped: number };

function encodeWav(chunks: Float32Array[], rate: number): Blob {
  const length = chunks.reduce((n, c) => n + c.length, 0);
  const buffer = new ArrayBuffer(44 + length * 2);
  const view = new DataView(buffer);
  const text = (offset: number, s: string) => {
    for (let i = 0; i < s.length; i += 1) view.setUint8(offset + i, s.charCodeAt(i));
  };
  text(0, "RIFF");
  view.setUint32(4, 36 + length * 2, true);
  text(8, "WAVE");
  text(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, length * 2, true);
  let offset = 44;
  for (const chunk of chunks) {
    for (let i = 0; i < chunk.length; i += 1) {
      const s = Math.max(-1, Math.min(1, chunk[i]));
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      offset += 2;
    }
  }
  return new Blob([buffer], { type: "audio/wav" });
}

type Mic = {
  ctx: AudioContext;
  stream: MediaStream;
  source: MediaStreamAudioSourceNode;
  proc: ScriptProcessorNode;
};

function useRecorder(maxSeconds: number) {
  const mic = useRef<Mic | null>(null);
  const active = useRef(false);
  const chunks = useRef<Float32Array[]>([]);
  const level = useRef<Level>({ db: -90, peak: 0, seconds: 0, clipped: 0 });
  const onLimit = useRef<(() => void) | null>(null);
  const [open, setOpen] = useState(false);

  const ensure = useCallback(async (): Promise<Mic> => {
    if (mic.current) {
      if (mic.current.ctx.state === "suspended") await mic.current.ctx.resume();
      return mic.current;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("این مرورگر ضبطِ صدا ندارد (یا صفحه روی https نیست) — فایل آپلود کنید.");
    }
    // Browser "voice processing" (noise suppression, AGC, echo cancellation) reshapes the timbre the clone
    // is supposed to learn — off, so the recording is the person's real voice.
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: false, noiseSuppression: false, autoGainControl: false },
    });
    const Ctx =
      window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const ctx = new Ctx();
    const source = ctx.createMediaStreamSource(stream);
    const proc = ctx.createScriptProcessor(4096, 1, 1);
    proc.onaudioprocess = (event) => {
      const input = event.inputBuffer.getChannelData(0);
      let sum = 0;
      let peak = 0;
      let clipped = 0;
      for (let i = 0; i < input.length; i += 1) {
        const v = Math.abs(input[i]);
        sum += v * v;
        if (v > peak) peak = v;
        if (v >= 0.985) clipped += 1;
      }
      const rms = Math.sqrt(sum / input.length);
      const current = level.current;
      current.db = rms > 0 ? 20 * Math.log10(rms) : -90;
      if (active.current) {
        chunks.current.push(new Float32Array(input));
        current.peak = Math.max(current.peak, peak);
        current.clipped += clipped;
        current.seconds += input.length / ctx.sampleRate;
        if (current.seconds >= maxSeconds && onLimit.current) {
          const stop = onLimit.current;
          onLimit.current = null;
          window.setTimeout(stop, 0);
        }
      }
    };
    source.connect(proc);
    proc.connect(ctx.destination); // silent: the output buffer is never written
    mic.current = { ctx, stream, source, proc };
    setOpen(true);
    return mic.current;
  }, [maxSeconds]);

  const start = useCallback(
    async (limit: () => void) => {
      await ensure();
      chunks.current = [];
      level.current = { db: -90, peak: 0, seconds: 0, clipped: 0 };
      onLimit.current = limit;
      active.current = true;
    },
    [ensure],
  );

  const stop = useCallback((): { blob: Blob; seconds: number; peak: number; clipped: number } | null => {
    if (!active.current || !mic.current) return null;
    active.current = false;
    onLimit.current = null;
    const take = { ...level.current };
    const blob = encodeWav(chunks.current, mic.current.ctx.sampleRate);
    chunks.current = [];
    return { blob, seconds: take.seconds, peak: take.peak, clipped: take.clipped };
  }, []);

  const release = useCallback(() => {
    active.current = false;
    const m = mic.current;
    mic.current = null;
    setOpen(false);
    if (!m) return;
    try {
      m.proc.disconnect();
      m.source.disconnect();
      m.stream.getTracks().forEach((t) => t.stop());
      void m.ctx.close();
    } catch {
      // already closed
    }
  }, []);

  useEffect(() => release, [release]);

  return { start, stop, release, ensure, level, open };
}

/** Live level from the recorder's ref — re-renders only itself, ten times a second. */
function LevelMeter({ level, recording, maxSeconds }: { level: React.MutableRefObject<Level>; recording: boolean; maxSeconds: number }) {
  const [snap, setSnap] = useState<Level>(level.current);
  useEffect(() => {
    const id = window.setInterval(() => setSnap({ ...level.current }), 100);
    return () => window.clearInterval(id);
  }, [level]);
  const width = Math.max(0, Math.min(100, ((snap.db + 60) / 60) * 100));
  const hot = snap.db > -3 || (recording && snap.clipped > 0);
  const quiet = snap.db < -45;
  return (
    <div className="flex flex-col gap-1">
      <div className="u-meter" style={{ height: 10 }}>
        <span
          style={{
            width: `${width}%`,
            background: hot ? "var(--bad)" : quiet ? "var(--warn)" : "var(--ok)",
            transition: "width .08s linear",
          }}
        />
      </div>
      <div className="flex flex-wrap items-center gap-3 text-xs" style={{ color: "var(--text-3)" }}>
        <span>بلندی: {fa(Math.round(snap.db))} dB</span>
        {recording && (
          <span>
            زمان: {fa(snap.seconds.toFixed(1))} از {fa(maxSeconds)} ثانیه
          </span>
        )}
        {hot && <span style={{ color: "var(--bad)" }}>خیلی بلند — کمی دورتر</span>}
        {!hot && quiet && <span style={{ color: "var(--warn)" }}>آرام — نزدیک‌تر یا بلندتر</span>}
      </div>
    </div>
  );
}

// ───────────────────────────────────────────── audio through the API (recordings are not public files)

function useAuthAudio() {
  const urls = useRef<string[]>([]);
  const player = useRef<HTMLAudioElement | null>(null);
  useEffect(
    () => () => {
      player.current?.pause();
      urls.current.forEach((u) => URL.revokeObjectURL(u));
    },
    [],
  );
  const load = useCallback(async (path: string): Promise<string> => {
    const { data } = await api.get<Blob>(path, { responseType: "blob" });
    const url = URL.createObjectURL(data);
    urls.current.push(url);
    return url;
  }, []);
  const play = useCallback(
    async (path: string) => {
      const url = await load(path);
      player.current?.pause();
      player.current = new Audio(url);
      await player.current.play();
    },
    [load],
  );
  return useMemo(() => ({ load, play }), [load, play]);
}

// ───────────────────────────────────────────── page

export default function StoreVoiceClonePage() {
  const { storeId, store, setError, setNotice } = useStore();
  const [params, setParams] = useSearchParams();
  const [list, setList] = useState<CloneList | null>(null);
  const [voice, setVoice] = useState<ClonedVoiceT | null>(null);
  const [creating, setCreating] = useState(false);
  const selectedId = Number(params.get("voice") || 0) || null;
  const base = `/stores/${storeId}/voice/clones/`;

  const select = useCallback(
    (id: number | null) => {
      const next = new URLSearchParams(params);
      if (id) next.set("voice", String(id));
      else next.delete("voice");
      setParams(next, { replace: true });
    },
    [params, setParams],
  );

  const loadList = useCallback(async () => {
    try {
      const { data } = await api.get<CloneList>(base);
      setList(data);
      return data;
    } catch (err) {
      setError(errorMessage(err));
      return null;
    }
  }, [base, setError]);

  const loadVoice = useCallback(
    async (id: number) => {
      try {
        const { data } = await api.get<ClonedVoiceT>(`${base}${id}/`);
        setVoice(data);
        return data;
      } catch (err) {
        setError(errorMessage(err));
        return null;
      }
    },
    [base, setError],
  );

  useEffect(() => {
    void loadList().then((data) => {
      if (data && !selectedId && data.voices.length) select(data.voices[0].id);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadList]);

  useEffect(() => {
    if (selectedId) void loadVoice(selectedId);
    else setVoice(null);
  }, [selectedId, loadVoice]);

  // a build in progress: follow it
  const building = voice?.status === "BUILDING";
  useEffect(() => {
    if (!building || !voice) return;
    const id = window.setInterval(async () => {
      const fresh = await loadVoice(voice.id);
      if (fresh && fresh.status !== "BUILDING") {
        void loadList();
        if (fresh.status === "READY") setNotice(`صدای «${fresh.name}» ساخته شد — پایین‌تر آزمایشش کنید.`);
      }
    }, 3000);
    return () => window.clearInterval(id);
  }, [building, voice?.id, loadVoice, loadList, setNotice]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!list) {
    return (
      <div className="space-y-4">
        <VoiceTabs storeId={storeId} />
        <div className="py-10 text-center">
          <Spinner />
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <VoiceTabs storeId={storeId} />

      <Alert tone="brand" title="کلونِ صدا: صدای خودتان برای ویدیوها">
        صاحبِ صدا چند جمله را می‌خواند (اینجا ضبط کنید یا فایل بدهید)؛ هر تکه همان لحظه وارسی می‌شود. بعد
        «ساختِ صدا» را بزنید تا سرورِ پردازش صدا را بسازد؛ از آن به بعد هر متنی با همان صدا خوانده می‌شود.
        کیفیت بیشتر به <b>ضبط</b> بستگی دارد تا مدل: اتاقِ ساکت و بی‌پژواک، فاصلهٔ ثابتِ ۱۵ تا ۲۰ سانتی‌متر، صدای
        واضح و طبیعی.
      </Alert>

      <Alert tone="warn" title="مجوز و رضایت">
        فقط با <b>رضایتِ کتبیِ صاحبِ صدا</b>؛ صدای ساخته‌شده «ساختهٔ ماشین» است و برای فریب یا جعلِ هویت به کار
        نمی‌رود. موتورِ فعلی ({list.engine.label}) مجوزِ <span dir="ltr">{list.engine.license}</span> دارد
        {list.engine.commercial ? "." : " — یعنی برای استفادهٔ تجاری (ویدیوی فروش) آزاد نیست؛ برای کارِ تجاری باید مدلِ تجاری‌مجاز روی سرورِ پردازش نصب شود."}
      </Alert>

      <NodeStatus nodes={list.nodes} />

      <Card>
        <SectionTitle
          action={
            !creating && (
              <Button size="sm" onClick={() => setCreating(true)}>
                <Icon name="plus" size={13} />
                صدای تازه
              </Button>
            )
          }
        >
          صداهای کلون‌شده
        </SectionTitle>
        {list.voices.length === 0 && !creating && (
          <p className="text-sm" style={{ color: "var(--text-3)" }}>
            هنوز صدایی نساخته‌اید. «صدای تازه» را بزنید.
          </p>
        )}
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {list.voices.map((v) => {
            const active = v.id === selectedId;
            return (
              <button
                key={v.id}
                type="button"
                onClick={() => {
                  setCreating(false);
                  select(v.id);
                }}
                className="rounded-xl p-3 text-right"
                style={{
                  border: `2px solid ${active ? "var(--brand)" : "var(--line)"}`,
                  background: active ? "var(--brand-soft)" : "transparent",
                }}
              >
                <div className="flex flex-wrap items-center gap-2 font-bold" style={{ color: "var(--text)" }}>
                  <Icon name="mic" size={15} />
                  {v.name}
                  <Badge tone={STATUS_TONE[v.status]}>{v.status_label}</Badge>
                  {v.in_use && <Badge tone="brand">گوینده‌ی ویدیوها</Badge>}
                </div>
                <div className="mt-1 text-xs" style={{ color: "var(--text-3)" }}>
                  صدای {v.person} · {fa(v.clips_ok)} جملهٔ پذیرفته ({fa(Math.round(v.seconds_ok))} ثانیه)
                </div>
              </button>
            );
          })}
        </div>
        {creating && (
          <NewVoiceForm
            list={list}
            storeName={store.name}
            base={base}
            onCancel={() => setCreating(false)}
            onCreated={async (created) => {
              setCreating(false);
              await loadList();
              select(created.id);
              setNotice("رضایت ثبت شد. حالا جمله‌ها را بخوانید.");
            }}
            setError={setError}
          />
        )}
      </Card>

      {voice && !creating && (
        <VoiceWorkspace
          key={voice.id}
          voice={voice}
          setVoice={setVoice}
          list={list}
          base={base}
          storeId={storeId}
          reloadList={loadList}
          reloadVoice={() => loadVoice(voice.id)}
          onDeleted={async () => {
            const data = await loadList();
            select(data?.voices[0]?.id ?? null);
          }}
          setError={setError}
          setNotice={setNotice}
        />
      )}
    </div>
  );
}

function NodeStatus({ nodes }: { nodes: CloneList["nodes"] }) {
  if (nodes.online) {
    const on = nodes.nodes.filter((n) => n.online);
    return (
      <div className="flex flex-wrap items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
        <Badge tone="ok">سرورِ پردازش روشن است</Badge>
        {on.map((n) => (
          <span key={n.name} dir="ltr" className="text-xs" style={{ color: "var(--text-3)" }}>
            {n.name}
            {n.gpu ? ` · ${n.gpu.split(",")[0]}` : ""}
            {n.clone_ready === false ? " · سرویسِ کلون بارِ اول خودکار نصب می‌شود (~۰٫۷ GB)" : ""}
          </span>
        ))}
      </div>
    );
  }
  return (
    <Alert tone="warn" title="سرورِ پردازش خاموش است">
      {nodes.message} ضبط و وارسیِ جمله‌ها بی آن هم انجام می‌شود؛ فقط «ساختِ صدا» و شنیدنِ صدای ساخته‌شده به آن
      نیاز دارد.
    </Alert>
  );
}

function NewVoiceForm({
  list,
  storeName,
  base,
  onCancel,
  onCreated,
  setError,
}: {
  list: CloneList;
  storeName: string;
  base: string;
  onCancel: () => void;
  onCreated: (voice: ClonedVoiceT) => void | Promise<void>;
  setError: (m: string | null) => void;
}) {
  const [name, setName] = useState("");
  const [person, setPerson] = useState("");
  const [purpose, setPurpose] = useState(list.default_purpose);
  const [consent, setConsent] = useState(false);
  const [saving, setSaving] = useState(false);
  const consentText = list.consent_template
    .replace("{person}", person.trim() || "…")
    .replace("{purpose}", purpose.trim() || list.default_purpose)
    .replace("{store}", storeName);

  const submit = async () => {
    setSaving(true);
    setError(null);
    try {
      const { data } = await api.post<ClonedVoiceT>(base, { name, person, purpose, consent });
      await onCreated(data);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mt-4 flex flex-col gap-3 rounded-xl p-4" style={{ border: "1px solid var(--line)" }}>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="نامِ صدا" hint="همان که در فهرستِ گوینده‌ها دیده می‌شود">
          <Input value={name} maxLength={60} onChange={(e) => setName(e.target.value)} placeholder="مثلاً: صدای مهدی" />
        </Field>
        <Field label="صاحبِ صدا (کسی که می‌خواند)">
          <Input value={person} maxLength={120} onChange={(e) => setPerson(e.target.value)} placeholder="نام و نام خانوادگی" />
        </Field>
        <Field label="کاربرد">
          <Input value={purpose} maxLength={300} onChange={(e) => setPurpose(e.target.value)} />
        </Field>
      </div>
      <label
        className="flex items-start gap-2 rounded-lg p-3 text-sm"
        style={{ background: "var(--surface-2)", color: "var(--text-2)" }}
      >
        <input type="checkbox" className="mt-1" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
        <span>
          <b style={{ color: "var(--text)" }}>رضایت‌نامه (لازم): </b>
          {consentText}
          <span className="mt-1 block text-xs" style={{ color: "var(--text-3)" }}>
            این متن با نامِ شما، زمان و نشانیِ اینترنتی کنارِ صدا نگه داشته می‌شود.
          </span>
        </span>
      </label>
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => void submit()} disabled={saving || !consent || !name.trim() || !person.trim()}>
          <Icon name="check" size={14} />
          {saving ? "در حال ثبت…" : "ثبتِ رضایت و شروع"}
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          انصراف
        </Button>
      </div>
    </div>
  );
}

function VoiceWorkspace({
  voice,
  setVoice,
  list,
  base,
  storeId,
  reloadList,
  reloadVoice,
  onDeleted,
  setError,
  setNotice,
}: {
  voice: ClonedVoiceT;
  setVoice: (v: ClonedVoiceT) => void;
  list: CloneList;
  base: string;
  storeId: string;
  reloadList: () => Promise<CloneList | null>;
  reloadVoice: () => Promise<ClonedVoiceT | null>;
  onDeleted: () => Promise<void>;
  setError: (m: string | null) => void;
  setNotice: (m: string | null) => void;
}) {
  const limits = list.limits;
  const recorder = useRecorder(limits.max_seconds);
  const audio = useAuthAudio();
  const clips = useMemo(() => new Map((voice.clips ?? []).map((c) => [c.index, c])), [voice.clips]);
  const firstOpen = list.script.find((s) => !clips.get(s.index)?.ok)?.index ?? list.script[0]?.index ?? 1;
  const [current, setCurrent] = useState<number>(firstOpen);
  const [recordingIndex, setRecordingIndex] = useState<number | null>(null);
  const [uploadingIndex, setUploadingIndex] = useState<number | null>(null);
  const [lastResult, setLastResult] = useState<Record<number, string>>({});
  const [autoNext, setAutoNext] = useState(true);
  const [customText, setCustomText] = useState("");
  const fileInput = useRef<HTMLInputElement | null>(null);
  const fileTarget = useRef<{ index: number; text: string } | null>(null);
  const locked = voice.status === "BUILDING";
  const url = `${base}${voice.id}/`;
  // browsers give the microphone only to https (or localhost) pages; on plain http only uploads work
  const canRecord = window.isSecureContext && !!navigator.mediaDevices?.getUserMedia;

  const customClips = (voice.clips ?? []).filter((c) => c.index >= limits.custom_index_base);
  const nextCustomIndex = customClips.length
    ? Math.max(...customClips.map((c) => c.index)) + 1
    : limits.custom_index_base;

  const nextAfter = useCallback(
    (index: number, accepted: Set<number>) => {
      const after = list.script.find((s) => s.index > index && !accepted.has(s.index));
      return after?.index ?? list.script.find((s) => !accepted.has(s.index))?.index ?? index;
    },
    [list.script],
  );

  const upload = useCallback(
    async (index: number, text: string, file: Blob, name: string, source: "record" | "upload") => {
      setUploadingIndex(index);
      setError(null);
      try {
        const form = new FormData();
        form.append("index", String(index));
        form.append("text", text);
        form.append("source", source);
        form.append("file", file, name);
        const { data } = await api.post<ClipResult>(`${url}clips/`, form);
        setLastResult((r) => ({ ...r, [index]: data.check.message }));
        if (index >= limits.custom_index_base && data.check.ok) setCustomText("");
        const fresh = await reloadVoice();
        if (data.check.ok && autoNext && index < limits.custom_index_base && fresh) {
          const accepted = new Set((fresh.clips ?? []).filter((c) => c.ok).map((c) => c.index));
          setCurrent(nextAfter(index, accepted));
        }
      } catch (err) {
        setLastResult((r) => ({ ...r, [index]: errorMessage(err) }));
        setError(errorMessage(err));
      } finally {
        setUploadingIndex(null);
      }
    },
    [url, reloadVoice, autoNext, limits.custom_index_base, nextAfter, setError],
  );

  const stopRecording = useCallback(() => {
    const index = recordingIndex;
    const take = recorder.stop();
    setRecordingIndex(null);
    if (index === null || !take) return;
    if (take.seconds < 0.4) {
      setLastResult((r) => ({ ...r, [index]: "ضبط خیلی کوتاه بود — دوباره." }));
      return;
    }
    const line = list.script.find((s) => s.index === index);
    const text = line?.text ?? clips.get(index)?.text ?? customText.trim();
    void upload(index, text, take.blob, `take-${index}.wav`, "record");
  }, [recordingIndex, recorder, list.script, clips, customText, upload]);

  const stopRef = useRef(stopRecording);
  stopRef.current = stopRecording;

  const startRecording = useCallback(
    async (index: number) => {
      if (recordingIndex !== null) return;
      setError(null);
      try {
        await recorder.start(() => stopRef.current());
        setRecordingIndex(index);
      } catch (err) {
        setError(err instanceof Error ? `میکروفون باز نشد: ${err.message}` : "میکروفون باز نشد.");
      }
    },
    [recordingIndex, recorder, setError],
  );

  // Space = start/stop on the current sentence (not while typing)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== "Space" || locked || !canRecord) return;
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) return;
      e.preventDefault();
      if (recordingIndex !== null) stopRef.current();
      else if (uploadingIndex === null) void startRecording(current);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [current, recordingIndex, uploadingIndex, locked, canRecord, startRecording]);

  const pickFile = (index: number, text: string) => {
    fileTarget.current = { index, text };
    fileInput.current?.click();
  };

  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    const target = fileTarget.current;
    if (!file || !target) return;
    if (file.size > limits.max_upload_mb * 1024 * 1024) {
      setError(`فایل بزرگ‌تر از ${fa(limits.max_upload_mb)} مگابایت است — فقط همان یک جمله را بفرستید.`);
      return;
    }
    void upload(target.index, target.text, file, file.name, "upload");
  };

  const removeClip = async (index: number) => {
    try {
      const { data } = await api.delete<ClonedVoiceT>(`${url}clips/${index}/`);
      setVoice(data);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const currentLine = list.script.find((s) => s.index === current) ?? list.script[0];
  const currentClip = currentLine ? clips.get(currentLine.index) : undefined;
  const acceptedCount = voice.clips_ok;
  const enough = acceptedCount >= limits.min_clips;
  const groups = useMemo(() => {
    const out: { group: string; lines: ScriptLine[] }[] = [];
    for (const line of list.script) {
      const last = out[out.length - 1];
      if (last && last.group === line.group) last.lines.push(line);
      else out.push({ group: line.group, lines: [line] });
    }
    return out;
  }, [list.script]);

  return (
    <>
      <input
        ref={fileInput}
        type="file"
        accept="audio/*,.wav,.mp3,.m4a,.ogg,.oga,.opus,.webm,.flac,.aac"
        className="hidden"
        onChange={onFile}
      />

      <Card>
        <SectionTitle
          action={
            <Button
              size="sm"
              variant="ghost"
              onClick={async () => {
                if (!window.confirm(`صدای «${voice.name}» و همهٔ ضبط‌هایش پاک شود؟ این کار برنمی‌گردد.`)) return;
                try {
                  await api.delete(url);
                  setNotice("صدا و همهٔ ضبط‌هایش پاک شد (نسخهٔ روی سرورِ پردازش هم پاک می‌شود).");
                  await onDeleted();
                } catch (err) {
                  setError(errorMessage(err));
                }
              }}
            >
              <Icon name="trash" size={13} />
              پاک کردنِ صدا
            </Button>
          }
        >
          <span className="flex flex-wrap items-center gap-2">
            {voice.name}
            <Badge tone={STATUS_TONE[voice.status]}>{voice.status_label}</Badge>
            <Badge tone="neutral">ساختهٔ ماشین</Badge>
          </span>
        </SectionTitle>
        <div className="flex flex-col gap-2 text-sm" style={{ color: "var(--text-2)" }}>
          <div>
            {fa(acceptedCount)} جملهٔ پذیرفته ({fa(Math.round(voice.seconds_ok))} ثانیه) — دست‌کم {fa(limits.min_clips)}،
            برای بهترین نتیجه {fa(limits.recommended_clips)} جمله یا بیشتر.
          </div>
          <Meter used={Math.min(acceptedCount, limits.recommended_clips)} total={limits.recommended_clips} />
          <details className="text-xs" style={{ color: "var(--text-3)" }}>
            <summary className="cursor-pointer">رضایت‌نامهٔ ثبت‌شده</summary>
            <p className="mt-1">{voice.consent.text}</p>
            <p>
              ثبت: {voice.consent.by || "—"} · {new Date(voice.consent.at).toLocaleString("fa-IR")}
            </p>
          </details>
        </div>
      </Card>

      {!locked && currentLine && (
        <Card>
          <SectionTitle>
            خواندنِ جمله‌ها ({fa(currentLine.index)} از {fa(list.script.length)})
          </SectionTitle>
          <ul className="mb-3 list-disc pr-5 text-xs" style={{ color: "var(--text-3)" }}>
            <li>اتاقِ ساکت، پنکه و کولر خاموش؛ میکروفون یا هدست ۱۵ تا ۲۰ سانتی‌متر، همیشه همان فاصله.</li>
            <li>هر جمله را کامل، شمرده و طبیعی بخوانید — همان‌طور که می‌خواهید ویدیو خوانده شود.</li>
            <li>کلیدِ فاصله (Space) ضبط را شروع و تمام می‌کند؛ بعد از هر جملهٔ پذیرفته، جملهٔ بعد می‌آید.</li>
          </ul>
          {currentLine.group && (
            <div className="mb-1 text-xs" style={{ color: "var(--text-3)" }}>
              {currentLine.group}
            </div>
          )}
          {!canRecord && (
            <div className="mb-3">
              <Alert tone="warn" title="ضبط در مرورگر روی این نشانی بسته است">
                مرورگرها میکروفون را فقط به صفحه‌های https (یا localhost) می‌دهند و این پنل الان روی http باز است.
                دو راه: (۱) هر جمله را با گوشی یا برنامهٔ ضبطِ صدا ضبط کنید و با «فایل» بفرستید (wav، m4a، mp3، ogg)؛
                (۲) در Chrome نشانیِ <span dir="ltr">chrome://flags/#unsafely-treat-insecure-origin-as-secure</span> را باز
                کنید، <span dir="ltr">{window.location.origin}</span> را اضافه و Chrome را دوباره باز کنید.
              </Alert>
            </div>
          )}
          <p className="mb-4 rounded-xl p-4 text-xl leading-loose" style={{ background: "var(--surface-2)", color: "var(--text)" }}>
            {currentLine.text}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            {recordingIndex === currentLine.index ? (
              <Button variant="danger" onClick={() => stopRef.current()}>
                <Icon name="check" size={14} />
                تمام (ارسال)
              </Button>
            ) : (
              <Button
                onClick={() => void startRecording(currentLine.index)}
                disabled={!canRecord || recordingIndex !== null || uploadingIndex !== null}
              >
                <Icon name="mic" size={14} />
                {currentClip ? "ضبطِ دوباره" : "ضبط"}
              </Button>
            )}
            <Button
              variant="secondary"
              onClick={() => pickFile(currentLine.index, currentLine.text)}
              disabled={recordingIndex !== null || uploadingIndex !== null}
            >
              <Icon name="upload" size={14} />
              فایل
            </Button>
            {currentClip && (
              <Button variant="ghost" onClick={() => void audio.play(`${url}clips/${currentLine.index}/audio/`)}>
                <Icon name="play" size={14} />
                پخشِ ضبط
              </Button>
            )}
            <Button
              variant="ghost"
              onClick={() => setCurrent(Math.max(list.script[0].index, currentLine.index - 1))}
              disabled={recordingIndex !== null}
            >
              <Icon name="back" size={14} />
              قبلی
            </Button>
            <Button
              variant="ghost"
              onClick={() => setCurrent(Math.min(list.script[list.script.length - 1].index, currentLine.index + 1))}
              disabled={recordingIndex !== null}
            >
              بعدی
              <Icon name="next" size={14} />
            </Button>
            <label className="flex items-center gap-1 text-xs" style={{ color: "var(--text-3)" }}>
              <input type="checkbox" checked={autoNext} onChange={(e) => setAutoNext(e.target.checked)} />
              بعد از جملهٔ پذیرفته، برو به بعدی
            </label>
          </div>
          {recorder.open && (
            <div className="mt-3">
              <LevelMeter level={recorder.level} recording={recordingIndex !== null} maxSeconds={limits.max_seconds} />
            </div>
          )}
          {uploadingIndex === currentLine.index && (
            <div className="mt-2 flex items-center gap-2 text-sm" style={{ color: "var(--text-3)" }}>
              <Spinner size={16} /> در حالِ وارسی…
            </div>
          )}
          <ClipVerdict clip={currentClip} last={lastResult[currentLine.index]} />
        </Card>
      )}

      <Card>
        <details open={!locked && acceptedCount > 0}>
          <summary className="cursor-pointer text-lg font-bold" style={{ color: "var(--text)" }}>
            همهٔ جمله‌ها ({fa(list.script.length)}) و نمونه‌های خودتان
          </summary>
          <div className="mt-3 flex flex-col gap-4">
            {groups.map((g) => (
              <div key={g.group || "-"}>
                {g.group && (
                  <div className="mb-1 text-xs font-bold" style={{ color: "var(--text-3)" }}>
                    {g.group}
                  </div>
                )}
                <ol className="flex flex-col gap-1">
                  {g.lines.map((line) => (
                    <ClipRow
                      key={line.index}
                      index={line.index}
                      text={line.text}
                      clip={clips.get(line.index)}
                      active={line.index === current}
                      locked={locked || recordingIndex !== null || uploadingIndex !== null}
                      uploading={uploadingIndex === line.index}
                      onSelect={() => {
                        setCurrent(line.index);
                        window.scrollTo({ top: 0, behavior: "smooth" });
                      }}
                      onPlay={() => void audio.play(`${url}clips/${line.index}/audio/`)}
                      onFile={() => pickFile(line.index, line.text)}
                      onDelete={() => void removeClip(line.index)}
                    />
                  ))}
                </ol>
              </div>
            ))}

            <div>
              <div className="mb-1 text-xs font-bold" style={{ color: "var(--text-3)" }}>
                جمله‌های خودتان (مثلاً متنِ معمولِ ویدیوهایتان)
              </div>
              <ol className="flex flex-col gap-1">
                {customClips.map((clip) => (
                  <ClipRow
                    key={clip.index}
                    index={clip.index}
                    text={clip.text}
                    clip={clip}
                    active={false}
                    locked={locked || recordingIndex !== null || uploadingIndex !== null}
                    uploading={uploadingIndex === clip.index}
                    onPlay={() => void audio.play(`${url}clips/${clip.index}/audio/`)}
                    onFile={() => pickFile(clip.index, clip.text)}
                    onDelete={() => void removeClip(clip.index)}
                  />
                ))}
              </ol>
              {!locked && (
                <div className="mt-2 flex flex-wrap items-end gap-2">
                  <div className="min-w-[16rem] flex-1">
                    <Input
                      value={customText}
                      maxLength={400}
                      onChange={(e) => setCustomText(e.target.value)}
                      placeholder="جمله‌ای که می‌خوانید را دقیقاً همین‌جا بنویسید"
                    />
                  </div>
                  {recordingIndex === nextCustomIndex ? (
                    <Button variant="danger" onClick={() => stopRef.current()}>
                      تمام (ارسال)
                    </Button>
                  ) : (
                    <Button
                      variant="secondary"
                      disabled={!canRecord || !customText.trim() || recordingIndex !== null || uploadingIndex !== null}
                      onClick={() => void startRecording(nextCustomIndex)}
                    >
                      <Icon name="mic" size={13} />
                      ضبط
                    </Button>
                  )}
                  <Button
                    variant="secondary"
                    disabled={!customText.trim() || recordingIndex !== null || uploadingIndex !== null}
                    onClick={() => pickFile(nextCustomIndex, customText.trim())}
                  >
                    <Icon name="upload" size={13} />
                    فایل
                  </Button>
                </div>
              )}
              {recordingIndex === nextCustomIndex && recorder.open && (
                <div className="mt-2">
                  <LevelMeter level={recorder.level} recording maxSeconds={limits.max_seconds} />
                </div>
              )}
            </div>
          </div>
        </details>
      </Card>

      <BuildCard
        voice={voice}
        setVoice={setVoice}
        list={list}
        url={url}
        enough={enough}
        reloadList={reloadList}
        setError={setError}
      />

      {voice.usable && (
        <ReadyCard
          voice={voice}
          setVoice={setVoice}
          url={url}
          storeId={storeId}
          audio={audio}
          reloadList={reloadList}
          setError={setError}
          setNotice={setNotice}
        />
      )}
    </>
  );
}

function ClipVerdict({ clip, last }: { clip?: CloneClip; last?: string }) {
  if (!clip && !last) return null;
  const node = clip?.node ?? {};
  return (
    <div className="mt-3 flex flex-col gap-1 text-sm">
      {clip && (
        <div style={{ color: clip.ok ? "var(--ok)" : "var(--bad)" }}>
          {clip.ok ? "✓ " : "✗ "}
          {clip.message}
          <span className="mr-2 text-xs" style={{ color: "var(--text-3)" }}>
            {fa(clip.seconds.toFixed(1))} ثانیه · نویز {clip.snr !== null ? `${fa(Math.round(clip.snr))} dB` : "—"}
          </span>
        </div>
      )}
      {!clip && last && <div style={{ color: "var(--bad)" }}>{last}</div>}
      {node.ok !== undefined && (
        <div className="text-xs" style={{ color: node.ok ? "var(--text-3)" : "var(--bad)" }}>
          سرورِ پردازش: {node.ok ? "پذیرفت" : node.message}
          {node.heard ? ` — شنید: «${node.heard}»` : ""}
        </div>
      )}
    </div>
  );
}

function ClipRow({
  index,
  text,
  clip,
  active,
  locked,
  uploading,
  onSelect,
  onPlay,
  onFile,
  onDelete,
}: {
  index: number;
  text: string;
  clip?: CloneClip;
  active: boolean;
  locked: boolean;
  uploading: boolean;
  onSelect?: () => void;
  onPlay: () => void;
  onFile: () => void;
  onDelete: () => void;
}) {
  const nodeBad = clip?.node?.ok === false;
  return (
    <li
      className="flex flex-wrap items-center gap-2 rounded-lg px-2 py-1 text-sm"
      style={{ background: active ? "var(--brand-soft)" : "transparent" }}
    >
      <span className="w-8 text-xs" style={{ color: "var(--text-3)" }}>
        {index < 1000 ? fa(index) : "+"}
      </span>
      <span className="min-w-[12rem] flex-1" style={{ color: "var(--text)" }}>
        {onSelect ? (
          <button type="button" className="text-right" onClick={onSelect}>
            {text}
          </button>
        ) : (
          text
        )}
      </span>
      {uploading ? (
        <Spinner size={14} />
      ) : clip ? (
        <Badge tone={clip.ok && !nodeBad ? "ok" : "bad"}>
          {clip.ok && !nodeBad ? `✓ ${fa(clip.seconds.toFixed(1))}ث` : nodeBad ? "سرور نپذیرفت" : "دوباره بخوانید"}
        </Badge>
      ) : (
        <Badge tone="neutral">ضبط نشده</Badge>
      )}
      {clip && (
        <Button size="sm" variant="ghost" onClick={onPlay} title={clip.message}>
          <Icon name="play" size={12} />
        </Button>
      )}
      <Button size="sm" variant="ghost" disabled={locked} onClick={onFile} title="آپلودِ فایل برای همین جمله">
        <Icon name="upload" size={12} />
      </Button>
      {clip && (
        <Button size="sm" variant="ghost" disabled={locked} onClick={onDelete} title="حذف">
          <Icon name="trash" size={12} />
        </Button>
      )}
    </li>
  );
}

function BuildCard({
  voice,
  setVoice,
  list,
  url,
  enough,
  reloadList,
  setError,
}: {
  voice: ClonedVoiceT;
  setVoice: (v: ClonedVoiceT) => void;
  list: CloneList;
  url: string;
  enough: boolean;
  reloadList: () => Promise<CloneList | null>;
  setError: (m: string | null) => void;
}) {
  const [consent, setConsent] = useState(false);
  const [starting, setStarting] = useState(false);
  const build = voice.build;
  const building = voice.status === "BUILDING";

  const start = async () => {
    setStarting(true);
    setError(null);
    try {
      const { data } = await api.post<ClonedVoiceT>(`${url}build/`, { consent: true });
      setVoice(data);
      setConsent(false);
      void reloadList();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setStarting(false);
    }
  };

  return (
    <Card>
      <SectionTitle>ساختِ صدا</SectionTitle>
      {building && build ? (
        <div className="flex flex-col gap-2 text-sm" style={{ color: "var(--text-2)" }}>
          <div className="flex flex-wrap items-center gap-2">
            <Spinner size={16} />
            <b style={{ color: "var(--text)" }}>{build.label}</b>
            {build.node && <span dir="ltr">{build.node}</span>}
            <span>{fa(Math.round(build.progress * 100))}٪</span>
          </div>
          <Meter used={Math.round(build.progress * 100)} total={100} />
          <div className="text-xs" style={{ color: "var(--text-3)" }}>
            {build.message || "در صفِ سرورِ پردازش"} — بارِ اول روی هر سرور، سرویسِ صدا خودش نصب می‌شود و چند دقیقه
            بیشتر طول می‌کشد. این صفحه را می‌توانید ببندید.
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-3 text-sm" style={{ color: "var(--text-2)" }}>
          {voice.status === "FAILED" && voice.error && <Alert tone="bad">{voice.error}</Alert>}
          {voice.status === "READY" && voice.error && <Alert tone="warn">{voice.error}</Alert>}
          {voice.needs_rebuild && (
            <Alert tone="info">بعد از آخرین ساخت جمله اضافه یا عوض شده؛ دوباره بسازید تا در صدا اثر کند.</Alert>
          )}
          {!enough && (
            <p>
              دست‌کم {fa(list.limits.min_clips)} جملهٔ پذیرفته لازم است (الان {fa(voice.clips_ok)}).
            </p>
          )}
          <label className="flex items-start gap-2">
            <input type="checkbox" className="mt-1" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            <span>
              صاحبِ صدا ({voice.person}) هنوز رضایت دارد و همان رضایت‌نامهٔ ثبت‌شده را پذیرفته است.
            </span>
          </label>
          <div>
            <Button onClick={() => void start()} disabled={!enough || !consent || starting}>
              <Icon name="sparkle" size={14} />
              {starting ? "در حالِ فرستادن…" : voice.revision > 0 ? "ساختِ دوباره" : "ساختِ صدا"}
            </Button>
          </div>
          {!list.nodes.online && (
            <p className="text-xs" style={{ color: "var(--warn)" }}>
              سرورِ پردازش الان خاموش است؛ ساخت شروع نمی‌شود تا روشن شود.
            </p>
          )}
        </div>
      )}
    </Card>
  );
}

function ReadyCard({
  voice,
  setVoice,
  url,
  storeId,
  audio,
  reloadList,
  setError,
  setNotice,
}: {
  voice: ClonedVoiceT;
  setVoice: (v: ClonedVoiceT) => void;
  url: string;
  storeId: string;
  audio: ReturnType<typeof useAuthAudio>;
  reloadList: () => Promise<CloneList | null>;
  setError: (m: string | null) => void;
  setNotice: (m: string | null) => void;
}) {
  const [text, setText] = useState("");
  const [job, setJob] = useState<JobState | null>(null);
  const [spoken, setSpoken] = useState("");
  const [result, setResult] = useState<string | null>(null);
  const [samples, setSamples] = useState<{ preview?: string; reference?: string }>({});
  const [using, setUsing] = useState(false);
  const report = voice.report ?? {};

  // follow a test job until it is done, then fetch its audio through the API
  useEffect(() => {
    if (!job || job.final) return;
    const id = window.setInterval(async () => {
      try {
        const { data } = await api.get<{ job: JobState }>(`${url}test/${job.uid}/`);
        setJob(data.job);
        if (data.job.state === "COMPLETED" && data.job.audio) {
          setResult(await audio.load(`${url}test/${data.job.uid}/audio/`));
        }
      } catch (err) {
        setError(errorMessage(err));
        setJob(null);
      }
    }, 2000);
    return () => window.clearInterval(id);
  }, [job, url, audio, setError]);

  const speak = async () => {
    setError(null);
    setResult(null);
    try {
      const { data } = await api.post<{ job: JobState; spoken_text: string }>(`${url}test/`, { text });
      setSpoken(data.spoken_text);
      setJob(data.job);
      if (data.job.state === "COMPLETED") setResult(await audio.load(`${url}test/${data.job.uid}/audio/`));
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const loadSample = async (kind: "preview" | "reference") => {
    try {
      const src = await audio.load(`${url}sample/?kind=${kind}`);
      setSamples((s) => ({ ...s, [kind]: src }));
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const setUse = async (use: boolean) => {
    setUsing(true);
    try {
      const { data } = await api.post<ClonedVoiceT>(`${url}use/`, { use });
      setVoice({ ...voice, in_use: data.in_use });
      void reloadList();
      setNotice(
        use
          ? `از این به بعد نریشنِ فارسیِ ویدیوها با صدای «${voice.name}» ساخته می‌شود. اگر سرورِ پردازش خاموش باشد، صداگذاری با پیامِ روشن متوقف می‌شود — صدای دیگری جایش نمی‌خواند.`
          : "گوینده به صدای قبلیِ فروشگاه برگشت.",
      );
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setUsing(false);
    }
  };

  const busy = job !== null && !job.final;

  return (
    <Card>
      <SectionTitle>
        <span className="flex flex-wrap items-center gap-2">
          آزمایش و استفاده
          <Badge tone="neutral">ساختهٔ ماشین</Badge>
        </span>
      </SectionTitle>
      <div className="flex flex-col gap-4 text-sm" style={{ color: "var(--text-2)" }}>
        <div className="flex flex-wrap items-center gap-3 text-xs" style={{ color: "var(--text-3)" }}>
          <span>
            ساخته شده {voice.built_at ? new Date(voice.built_at).toLocaleString("fa-IR") : ""} روی{" "}
            <span dir="ltr">{voice.node_name || "—"}</span>
          </span>
          {report.accepted !== undefined && (
            <span>
              {fa(report.accepted)} جمله پذیرفته{report.rejected ? `، ${fa(report.rejected)} رد` : ""}
            </span>
          )}
          {typeof report.check === "number" && (
            <span>درست‌خوانیِ جملهٔ نمونه با گفتار‌به‌متن: {fa(Math.round((1 - report.check) * 100))}٪</span>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {voice.has_preview &&
            (samples.preview ? (
              <audio controls src={samples.preview} />
            ) : (
              <Button variant="secondary" onClick={() => void loadSample("preview")}>
                <Icon name="play" size={14} />
                جملهٔ نمونه با صدای ساخته‌شده
              </Button>
            ))}
          {voice.has_reference &&
            (samples.reference ? (
              <audio controls src={samples.reference} />
            ) : (
              <Button variant="ghost" onClick={() => void loadSample("reference")}>
                <Icon name="play" size={14} />
                تکهٔ مرجع (صدای واقعی)
              </Button>
            ))}
        </div>

        <Field label="هر متنی بنویسید و با صدای ساخته‌شده بشنوید" hint="حداکثر ۴۰۰ نویسه؛ خالی بماند، جملهٔ نمونه خوانده می‌شود. تلفظ‌های فروشگاه و عددها مثلِ نریشنِ ویدیو اعمال می‌شود.">
          <TextArea rows={3} maxLength={400} value={text} onChange={(e) => setText(e.target.value)} />
        </Field>
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => void speak()} disabled={busy}>
            <Icon name="play" size={14} />
            {busy ? "در حالِ ساخت…" : "بشنو"}
          </Button>
          {job && !job.final && (
            <span className="flex items-center gap-2 text-xs" style={{ color: "var(--text-3)" }}>
              <Spinner size={14} />
              {job.label}
              {job.node ? ` روی ${job.node}` : ""} {job.message ? `— ${job.message}` : ""}
            </span>
          )}
        </div>
        {job?.state === "FAILED" && <Alert tone="bad">{job.error || "ساخت نشد."}</Alert>}
        {result && (
          <div className="flex flex-col gap-1">
            <audio key={result} controls autoPlay src={result} className="w-full" />
            {spoken && (
              <span className="text-xs" style={{ color: "var(--text-3)" }}>
                آنچه خوانده شد: {spoken}
                {typeof job?.check === "number" ? ` · خطای واژه با گفتار‌به‌متن ${fa(Math.round(job.check * 100))}٪` : ""}
              </span>
            )}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3 border-t pt-3" style={{ borderColor: "var(--line)" }}>
          {voice.in_use ? (
            <>
              <Badge tone="brand">گوینده‌ی فارسیِ ویدیوهای فروشگاه است</Badge>
              <Button variant="ghost" disabled={using} onClick={() => void setUse(false)}>
                برگرداندنِ گوینده‌ی قبلی
              </Button>
            </>
          ) : (
            <Button disabled={using} onClick={() => void setUse(true)}>
              <Icon name="check" size={14} />
              استفاده در محتوا
            </Button>
          )}
          <Link to={`/stores/${storeId}/voice`} className="text-xs" style={{ color: "var(--brand)" }}>
            تنظیماتِ گوینده و تلفظ‌ها
          </Link>
        </div>
        <p className="text-xs" style={{ color: "var(--text-3)" }}>
          «استفاده در محتوا» یعنی صداگذاریِ ویدیوهای فارسی با همین صدا (روی سرورِ پردازش). نریشنِ انگلیسی با گوینده‌ی
          معمولی می‌ماند. سرعت و زیروبمیِ صفحهٔ گوینده روی صدای کلون‌شده اثر ندارد.
        </p>
      </div>
    </Card>
  );
}
