import { useCallback, useEffect, useState } from "react";

import { errorMessage } from "../../../api/client";
import Icon from "../../../components/Icon";
import { Alert, Badge, Button, ErrorBox, Field, Input, Select, fa } from "../../../components/ui";
import { AudioAsset, AudioOverview, assetFile, listAssets, loadOverview } from "../../audio/api";
import { MusicStudio, SfxStudio, SpeechStudio } from "../../audio/Studios";
import { useAuthAudio } from "../../audio/useAuthAudio";
import { AudioSpec, regenApi } from "./api";

export type AudioForm = Required<Omit<AudioSpec, "source">> & { source: string; sourceLabel: string; sourceSeconds: number };

export const DEFAULT_AUDIO: AudioForm = {
  op: "keep", gain_db: -12, source: "", sourceLabel: "", sourceSeconds: 0, offset: 0, clip_gain_db: 0,
  mix: "replace", bed_db: -14, fade_ms: 80,
};

export function specOf(a: AudioForm): AudioSpec {
  if (a.op === "keep") return { op: "keep" };
  if (a.op === "mute") return { op: "mute", fade_ms: a.fade_ms };
  if (a.op === "volume") return { op: "volume", gain_db: a.gain_db, fade_ms: a.fade_ms };
  return { op: "replace", source: a.source, offset: a.offset, clip_gain_db: a.clip_gain_db, mix: a.mix, bed_db: a.bed_db, fade_ms: a.fade_ms };
}

const OPS: { key: AudioForm["op"]; label: string; icon: "check" | "ban" | "down" | "music" }[] = [
  { key: "keep", label: "صدای اصلی بماند", icon: "check" },
  { key: "mute", label: "بی‌صدا", icon: "ban" },
  { key: "volume", label: "آرام‌تر", icon: "down" },
  { key: "replace", label: "صدای تازه", icon: "music" },
];

const MAKE = { speech: "گفتار / صدای کلون‌شده", music: "موسیقی", sfx: "صدای محیط و افکت" } as const;

/**
 * صدای همان بازه: بماند، بی‌صدا، آرام‌تر، یا صدای تازه — از فایلِ خودتان، از «کتابخانهٔ صداها» (گفتار، کلونِ صدا،
 * موسیقی، افکت) یا همین‌جا با همان سازنده‌های بخشِ «صدا». لبه‌ها همیشه نرم (crossfade) می‌شوند.
 */
export default function AudioPanel({
  storeId,
  sessionId,
  value,
  onChange,
  rangeSeconds,
  hasAudio,
}: {
  storeId: string;
  sessionId: number;
  value: AudioForm;
  onChange: (a: AudioForm) => void;
  rangeSeconds: number;
  hasAudio: boolean;
}) {
  const [assets, setAssets] = useState<AudioAsset[]>([]);
  const [overview, setOverview] = useState<AudioOverview | null>(null);
  const [tab, setTab] = useState<"upload" | "library" | "make">("library");
  const [make, setMake] = useState<keyof typeof MAKE>("speech");
  const [uploading, setUploading] = useState<number | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const audio = useAuthAudio();
  const set = (patch: Partial<AudioForm>) => onChange({ ...value, ...patch });

  const loadAssets = useCallback(async () => {
    try {
      setAssets((await listAssets(storeId)).filter((a) => a.status === "READY" && a.has_file));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [storeId]);

  useEffect(() => {
    if (value.op !== "replace") return;
    void loadAssets();
    if (!overview) loadOverview(storeId).then(setOverview).catch(() => setOverview(null));
  }, [value.op, loadAssets, overview, storeId]);

  // پیش‌شنوِ صدای انتخاب‌شده
  useEffect(() => {
    let off = false;
    setPreview(null);
    const [kind, ref] = value.source.split(":");
    if (kind === "asset" && ref) {
      audio
        .load(assetFile(storeId, Number(ref)))
        .then((u) => !off && setPreview(u))
        .catch(() => undefined);
    }
    return () => {
      off = true;
    };
  }, [value.source, storeId, audio]);

  const pickAsset = (a: AudioAsset) =>
    set({ source: `asset:${a.id}`, sourceLabel: `${a.kind_label}: ${a.title || a.text.slice(0, 40)}`, sourceSeconds: a.duration });

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    setError(null);
    setUploading(0);
    try {
      const r = await regenApi.uploadAudio(storeId, sessionId, file, setUploading);
      set({ source: r.source, sourceLabel: `فایل: ${r.name}`, sourceSeconds: r.duration });
      setPreview(r.url);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setUploading(null);
    }
  };

  const created = (a: AudioAsset) => {
    if (a.status !== "READY") return;
    void loadAssets();
    pickAsset(a);
  };

  return (
    <div className="space-y-3" data-testid="regen-audio-panel">
      <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="صدای بازه">
        {OPS.map((o) => (
          <button
            key={o.key}
            type="button"
            role="radio"
            aria-checked={value.op === o.key}
            data-testid={`regen-audio-${o.key}`}
            disabled={!hasAudio && (o.key === "mute" || o.key === "volume")}
            onClick={() => set({ op: o.key })}
            className={`u-btn u-btn-sm ${value.op === o.key ? "u-btn-primary" : "u-btn-secondary"}`}
          >
            <Icon name={o.icon} size={13} /> {o.label}
          </button>
        ))}
      </div>
      <ErrorBox message={error} />
      {!hasAudio && (
        <p className="text-xs" style={{ color: "var(--text-3)" }}>
          این ویدیو صدا ندارد؛ با «صدای تازه» برای همین بازه صدا گذاشته می‌شود.
        </p>
      )}

      {value.op === "volume" && (
        <Field label={`چقدر آرام‌تر: ${fa(value.gain_db)} دسی‌بل`}>
          <input
            type="range"
            min={-40}
            max={-1}
            step={1}
            value={value.gain_db}
            dir="ltr"
            className="w-full"
            data-testid="regen-audio-gain"
            onChange={(e) => set({ gain_db: Number(e.target.value) })}
          />
        </Field>
      )}

      {value.op === "replace" && (
        <div className="space-y-3 rounded-xl p-3" style={{ border: "1px dashed var(--line)" }}>
          <div className="flex flex-wrap gap-1.5">
            {(["library", "upload", "make"] as const).map((t) => (
              <Button key={t} size="sm" variant={tab === t ? "primary" : "ghost"} onClick={() => setTab(t)} data-testid={`regen-audio-tab-${t}`}>
                {t === "library" ? "از کتابخانهٔ صداها" : t === "upload" ? "فایلِ خودم" : "همین‌جا بساز"}
              </Button>
            ))}
          </div>

          {tab === "library" && (
            <Select
              value={value.source.startsWith("asset:") ? value.source : ""}
              data-testid="regen-audio-asset"
              onChange={(e) => {
                const a = assets.find((x) => `asset:${x.id}` === e.target.value);
                if (a) pickAsset(a);
              }}
            >
              <option value="">{assets.length ? "یک صدا انتخاب کنید…" : "کتابخانه هنوز صدای آماده ندارد"}</option>
              {assets.map((a) => (
                <option key={a.id} value={`asset:${a.id}`}>
                  {a.kind_label} · {a.title || a.text.slice(0, 40)} · {fa(Math.round(a.duration * 10) / 10)} ث
                </option>
              ))}
            </Select>
          )}

          {tab === "upload" && (
            <label className="u-btn u-btn-secondary u-btn-sm cursor-pointer">
              <Icon name="upload" size={14} />
              {uploading !== null ? `آپلود… ${fa(Math.round(uploading * 100))}٪` : "انتخابِ فایلِ صدا (mp3، wav، m4a …)"}
              <input type="file" accept="audio/*,.m4a,.opus,.mp4,.webm" className="hidden" data-testid="regen-audio-upload"
                disabled={uploading !== null} onChange={(e) => onFile(e.target.files?.[0])} />
            </label>
          )}

          {tab === "make" && (
            <div className="space-y-2">
              <Select value={make} onChange={(e) => setMake(e.target.value as keyof typeof MAKE)}>
                {Object.entries(MAKE).map(([k, l]) => (
                  <option key={k} value={k}>{l}</option>
                ))}
              </Select>
              {overview ? (
                make === "speech" ? (
                  <SpeechStudio storeId={storeId} overview={overview} setError={setError} onCreated={created} compact />
                ) : make === "music" ? (
                  <MusicStudio storeId={storeId} overview={overview} setError={setError} onCreated={created} compact />
                ) : (
                  <SfxStudio storeId={storeId} overview={overview} setError={setError} onCreated={created} compact />
                )
              ) : (
                <p className="text-xs" style={{ color: "var(--text-3)" }}>…</p>
              )}
              <p className="text-xs" style={{ color: "var(--text-3)" }}>
                وقتی آماده شد خودش انتخاب می‌شود و در «کتابخانهٔ صداها» هم می‌ماند.
              </p>
            </div>
          )}

          {value.source ? (
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
                <Badge tone="ok">انتخاب شد</Badge>
                <span data-testid="regen-audio-source">{value.sourceLabel}</span>
                {value.sourceSeconds > 0 && <span>({fa(Math.round(value.sourceSeconds * 10) / 10)} ثانیه)</span>}
              </div>
              {preview && <audio src={preview} controls className="w-full" style={{ maxWidth: 420 }} />}
              {value.sourceSeconds > 0 && value.sourceSeconds - value.offset < rangeSeconds - 0.05 && (
                <Alert tone="info">
                  صدای تازه از جای انتخاب‌شده {fa(Math.round((value.sourceSeconds - value.offset) * 10) / 10)} ثانیه است و
                  بازه {fa(Math.round(rangeSeconds * 10) / 10)} ثانیه؛ بقیهٔ بازه {value.mix === "mix" ? "فقط صدای اصلیِ آرام" : "بی‌صدا"} می‌ماند.
                </Alert>
              )}
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Field label="از ثانیهٔ چندمِ صدای تازه" hint="ابتدای صدا را می‌بُرد">
                  <Input type="number" min={0} step={0.1} dir="ltr" value={value.offset} data-testid="regen-audio-offset"
                    onChange={(e) => set({ offset: Math.max(0, Number(e.target.value) || 0) })} />
                </Field>
                <Field label={`بلندیِ صدای تازه: ${fa(value.clip_gain_db)} دسی‌بل`}>
                  <input type="range" min={-30} max={12} step={1} dir="ltr" value={value.clip_gain_db} className="w-full"
                    onChange={(e) => set({ clip_gain_db: Number(e.target.value) })} />
                </Field>
                <Field label="با صدای اصلی چه شود">
                  <Select value={value.mix} data-testid="regen-audio-mix" onChange={(e) => set({ mix: e.target.value as AudioForm["mix"] })}>
                    <option value="replace">جایش را بگیرد</option>
                    <option value="mix">زیرِ آن آرام بماند (میکس)</option>
                  </Select>
                </Field>
                {value.mix === "mix" && (
                  <Field label={`صدای اصلی: ${fa(value.bed_db)} دسی‌بل`}>
                    <input type="range" min={-40} max={-1} step={1} dir="ltr" value={value.bed_db} className="w-full"
                      onChange={(e) => set({ bed_db: Number(e.target.value) })} />
                  </Field>
                )}
              </div>
            </div>
          ) : (
            <p className="text-xs" style={{ color: "var(--text-3)" }}>هنوز صدایی انتخاب نشده.</p>
          )}
        </div>
      )}

      {value.op !== "keep" && (
        <Field label={`نرمیِ لبه‌ها: ${fa(value.fade_ms)} میلی‌ثانیه`} hint="در دو سرِ بازه صدای اصلی و صدای تازه آرام جای هم را می‌گیرند">
          <input type="range" min={0} max={300} step={10} dir="ltr" value={value.fade_ms} className="w-full"
            onChange={(e) => set({ fade_ms: Number(e.target.value) })} />
        </Field>
      )}
    </div>
  );
}
