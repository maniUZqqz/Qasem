import { useState } from "react";

import { errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import { Button, Field, Input, TextArea, fa } from "../../components/ui";
import AssetCard from "./AssetCard";
import { AudioAsset, AudioOverview, createAsset } from "./api";
import { EngineStatus, VoicePicker, randomSeed } from "./parts";

type Common = {
  storeId: string | number;
  overview: AudioOverview;
  setError: (m: string | null) => void;
  /** a new sound was made (or finished): the video studio selects it, the library reloads */
  onCreated?: (a: AudioAsset) => void;
  /** inside the video studio: fewer explanations, keep it to one row */
  compact?: boolean;
};

function useResults(onCreated?: (a: AudioAsset) => void) {
  const [results, setResults] = useState<AudioAsset[]>([]);
  const add = (a: AudioAsset) => {
    setResults((r) => [a, ...r.filter((x) => x.id !== a.id)].slice(0, 6));
    onCreated?.(a);
  };
  const drop = (id: number) => setResults((r) => r.filter((x) => x.id !== id));
  return { results, add, drop };
}

function Results({ storeId, results, drop, setError, onCreated, compact }: {
  storeId: string | number;
  results: AudioAsset[];
  drop: (id: number) => void;
  setError: (m: string | null) => void;
  onCreated?: (a: AudioAsset) => void;
  compact?: boolean;
}) {
  if (!results.length) return null;
  return (
    <div className="mt-3 flex flex-col gap-2">
      {results.map((a) => (
        <AssetCard key={a.id} storeId={storeId} asset={a} setError={setError} onDeleted={drop} onChange={onCreated}
          compact={compact} />
      ))}
    </div>
  );
}

/** Text to speech: MOSS (default, commercial), a cloned voice, Piper or Edge. */
export function SpeechStudio({ storeId, overview, setError, onCreated, compact }: Common) {
  const firstReady = overview.voices.find((v) => v.available)?.id ?? overview.voices[0]?.id ?? "";
  const [voice, setVoice] = useState(firstReady);
  const [text, setText] = useState("");
  const [speed, setSpeed] = useState(1);
  const [busy, setBusy] = useState(false);
  const { results, add, drop } = useResults(onCreated);
  const chosen = overview.voices.find((v) => v.id === voice);

  const make = async (variation = false) => {
    setBusy(true);
    setError(null);
    try {
      add(await createAsset(storeId, { kind: "speech", text, voice, speed, ...(variation ? { seed: randomSeed() } : {}) }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      {!compact && <EngineStatus overview={overview} keys={["moss"]} />}
      <Field label={`متن (حداکثر ${fa(overview.limits.speech_chars)} نویسه)`}
        hint="عددها و اسمِ برندها همان‌طور خوانده می‌شوند که در «صدا و گوینده › تلفظ‌ها» نوشته‌اید.">
        <TextArea rows={compact ? 3 : 5} maxLength={overview.limits.speech_chars} value={text}
          onChange={(e) => setText(e.target.value)} placeholder="مثلاً: کفش‌های تابستانی رسید؛ تا جمعه با ارسال رایگان." />
      </Field>
      <div>
        <div className="mb-1 text-sm font-medium" style={{ color: "var(--text-2)" }}>صدا</div>
        <VoicePicker voices={overview.voices} value={voice} onChange={setVoice} compact={compact} />
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-64">
          <Field label={`سرعت: ${fa(speed.toFixed(2))}×`}>
            <input type="range" min={overview.limits.speed[0]} max={overview.limits.speed[1]} step={0.05} value={speed}
              onChange={(e) => setSpeed(Number(e.target.value))} className="w-full" aria-label="سرعت" />
          </Field>
        </div>
        <Button onClick={() => void make()} disabled={busy || !text.trim() || !chosen?.available}>
          <Icon name="mic" size={14} />
          {busy ? "در حال فرستادن…" : "بساز"}
        </Button>
        <Button variant="secondary" onClick={() => void make(true)} disabled={busy || !text.trim() || !chosen?.available}
          title="همان متن، یک خوانشِ دیگر">
          <Icon name="refresh" size={14} />
          نسخهٔ دیگر
        </Button>
        {chosen && !chosen.commercial && (
          <span className="text-xs" style={{ color: "var(--warn)" }}>این صدا مجوزِ استفادهٔ تجاری ندارد ({chosen.license}).</span>
        )}
      </div>
      <Results storeId={storeId} results={results} drop={drop} setError={setError} onCreated={onCreated} compact={compact} />
    </div>
  );
}

/** Ambience and effects with MOSS-SoundEffect: a ready suggestion or a description (Persian is translated). */
export function SfxStudio({ storeId, overview, setError, onCreated, compact }: Common) {
  const [preset, setPreset] = useState("");
  const [description, setDescription] = useState("");
  const [secondsValue, setSeconds] = useState(compact ? 20 : 8);
  const [busy, setBusy] = useState(false);
  const { results, add, drop } = useResults(onCreated);
  const ready = overview.status.engines.sfx.ready;
  const beds = overview.sfx_presets.filter((p) => p.kind === "bed");
  const spots = overview.sfx_presets.filter((p) => p.kind !== "bed");

  const make = async (variation = false) => {
    setBusy(true);
    setError(null);
    try {
      add(await createAsset(storeId, {
        kind: "sfx", preset: description.trim() ? "" : preset, description, seconds: secondsValue,
        ...(variation ? { seed: randomSeed() } : {}),
      }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const chip = (p: { key: string; label: string; prompt: string }) => (
    <button key={p.key} type="button" onClick={() => { setPreset(p.key); setDescription(""); }} title={p.prompt}
      className={`u-badge ${preset === p.key && !description ? "u-badge-brand" : "u-badge-neutral"}`}>
      {p.label}
    </button>
  );

  return (
    <div className="flex flex-col gap-3">
      <EngineStatus overview={overview} keys={["sfx"]} />
      <div>
        <div className="mb-1 text-xs font-bold" style={{ color: "var(--text-3)" }}>صدای محیط</div>
        <div className="flex flex-wrap gap-1">{beds.map(chip)}</div>
      </div>
      {!compact && (
        <div>
          <div className="mb-1 text-xs font-bold" style={{ color: "var(--text-3)" }}>افکتِ لحظه‌ای</div>
          <div className="flex flex-wrap gap-1">{spots.map(chip)}</div>
        </div>
      )}
      <Field label="یا خودتان بنویسید چه صدایی می‌خواهید"
        hint="فارسی هم بنویسید به انگلیسی برگردانده می‌شود (مدل با توضیحِ انگلیسی آموزش دیده). بی‌گفتار و بی‌موسیقی بهتر جواب می‌دهد.">
        <Input value={description} onChange={(e) => setDescription(e.target.value)} maxLength={300}
          placeholder="مثلاً: باران ملایم روی شیشه و رعدِ دور" />
      </Field>
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-56">
          <Field label={`مدت: ${fa(secondsValue)} ثانیه`}>
            <input type="range" min={overview.limits.sfx[0]} max={overview.limits.sfx[1]} step={1} value={secondsValue}
              onChange={(e) => setSeconds(Number(e.target.value))} className="w-full" aria-label="مدت" />
          </Field>
        </div>
        <Button onClick={() => void make()} disabled={busy || !ready || (!preset && !description.trim())}>
          <Icon name="cloud" size={14} />
          {busy ? "در حال فرستادن…" : "بساز"}
        </Button>
        <Button variant="secondary" onClick={() => void make(true)} disabled={busy || !ready || (!preset && !description.trim())}>
          <Icon name="refresh" size={14} />
          نسخهٔ دیگر
        </Button>
      </div>
      <Results storeId={storeId} results={results} drop={drop} setError={setError} onCreated={onCreated} compact={compact} />
    </div>
  );
}

/** Instrumental background music with ACE-Step: a mood (or a description), a length, a tempo. */
export function MusicStudio({ storeId, overview, setError, onCreated, compact }: Common) {
  const [style, setStyle] = useState(overview.music_styles[0]?.id ?? "");
  const [description, setDescription] = useState("");
  const [secondsValue, setSeconds] = useState(30);
  const [bpm, setBpm] = useState("");
  const [busy, setBusy] = useState(false);
  const { results, add, drop } = useResults(onCreated);
  const ready = overview.status.engines.music.ready;

  const make = async (variation = false) => {
    setBusy(true);
    setError(null);
    try {
      add(await createAsset(storeId, {
        kind: "music", style, description, seconds: secondsValue, bpm: bpm ? Number(bpm) : undefined,
        ...(variation ? { seed: randomSeed() } : {}),
      }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <EngineStatus overview={overview} keys={["music"]} />
      <div className="flex flex-wrap gap-1">
        {overview.music_styles.map((s) => (
          <button key={s.id} type="button" onClick={() => setStyle(s.id)} title={s.prompt}
            className={`u-badge ${style === s.id ? "u-badge-brand" : "u-badge-neutral"}`}>
            {s.label}
          </button>
        ))}
      </div>
      <Field label="توضیحِ بیشتر (اختیاری)" hint="مثلاً «با پیانو، شاد ولی آرام». موسیقی همیشه بی‌کلام ساخته می‌شود.">
        <Input value={description} onChange={(e) => setDescription(e.target.value)} maxLength={300} />
      </Field>
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-56">
          <Field label={`مدت: ${fa(secondsValue)} ثانیه`}>
            <input type="range" min={overview.limits.music[0]} max={overview.limits.music[1]} step={5} value={secondsValue}
              onChange={(e) => setSeconds(Number(e.target.value))} className="w-full" aria-label="مدت" />
          </Field>
        </div>
        {!compact && (
          <div className="w-32">
            <Field label="ضرب‌آهنگ (BPM)">
              <Input type="number" min={50} max={200} value={bpm} onChange={(e) => setBpm(e.target.value)} placeholder="خودکار" />
            </Field>
          </div>
        )}
        <Button onClick={() => void make()} disabled={busy || !ready || (!style && !description.trim())}>
          <Icon name="music" size={14} />
          {busy ? "در حال فرستادن…" : "بساز"}
        </Button>
        <Button variant="secondary" onClick={() => void make(true)} disabled={busy || !ready}>
          <Icon name="refresh" size={14} />
          نسخهٔ دیگر
        </Button>
      </div>
      <Results storeId={storeId} results={results} drop={drop} setError={setError} onCreated={onCreated} compact={compact} />
    </div>
  );
}
