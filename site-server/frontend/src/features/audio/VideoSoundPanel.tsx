import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import { Alert, Badge, Button, Card, ErrorBox, SectionTitle, Spinner } from "../../components/ui";
import { useJobRunner } from "../../hooks/useJobRunner";
import { StoreVoice } from "../../types";
import { AudioAsset, AudioOverview, listAssets, loadOverview } from "./api";
import { MusicStudio, SfxStudio } from "./Studios";

/**
 * The narrator of this store's videos, chosen where the video is made: a MOSS voice (commercial, on the
 * processing node), the shop's own cloned voice, or «مرد / زن» (whatever engine the admin put first).
 * It is the store's narrator setting — the same one «صدا و گوینده» edits — followed by «صداگذاریِ دوباره».
 */
export function NarratorPicker({
  storeId,
  voice,
  language,
  onChanged,
  onRegenerate,
  busy,
  voiced,
}: {
  storeId: string | number;
  voice: StoreVoice;
  language: string;
  onChanged: (v: StoreVoice) => void;
  onRegenerate: () => void;
  busy: boolean;
  voiced: boolean;
}) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [changed, setChanged] = useState(false);
  const p = voice.profile;
  const value = p.cloned_voice ? `clone:${p.cloned_voice}` : p.preset ? `moss:${p.preset}` : `gender:${p.gender}`;
  const lang = language === "en" ? "en" : "fa";
  const first = voice.speakers[lang].speakers[0];
  const moss = voice.moss;

  const choose = async (next: string) => {
    const [kind, id] = next.split(":");
    const profile = { ...p, cloned_voice: null as number | null, preset: "" };
    if (kind === "clone") profile.cloned_voice = Number(id);
    if (kind === "moss") {
      profile.preset = id;
      const row = moss?.presets.find((x) => x.id === id);
      if (row) profile.gender = row.gender === "female" ? "female" : "male";
    }
    if (kind === "gender") profile.gender = id === "female" ? "female" : "male";
    setSaving(true);
    setError(null);
    try {
      const { data } = await api.patch<StoreVoice>(`/stores/${storeId}/voice/`, { profile });
      onChanged(data);
      setChanged(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mb-4 flex flex-col gap-2 rounded-xl p-3" style={{ border: "1px solid var(--line)" }}>
      <div className="flex flex-wrap items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
        <Icon name="mic" size={15} />
        <span>گوینده:</span>
        <select className="u-input max-w-xs" value={value} disabled={saving || busy} aria-label="گوینده"
          onChange={(e) => void choose(e.target.value)}>
          {moss && moss.presets.length > 0 && (
            <optgroup label={`MOSS-TTS فارسی — تجاری مجاز${moss.ready ? "" : " (سرورِ پردازش آماده نیست)"}`}>
              {moss.presets.map((x) => (
                <option key={x.id} value={`moss:${x.id}`}>
                  {x.name} ({x.gender === "female" ? "زن" : "مرد"})
                </option>
              ))}
            </optgroup>
          )}
          {(voice.cloned_voices ?? []).length > 0 && (
            <optgroup label="صداهای کلون‌شدهٔ شما">
              {(voice.cloned_voices ?? []).map((c) => (
                <option key={c.id} value={`clone:${c.id}`} disabled={!c.usable}>
                  {c.name}
                  {c.commercial ? "" : " — غیرتجاری"}
                  {c.usable ? "" : " — هنوز ساخته نشده"}
                </option>
              ))}
            </optgroup>
          )}
          <optgroup label="موتورِ پیش‌فرضِ مدیر">
            <option value="gender:male">مرد</option>
            <option value="gender:female">زن</option>
          </optgroup>
        </select>
        {saving && <Spinner size={14} />}
        {first ? (
          <Badge tone={first.local ? "ok" : "info"}>{first.processor}</Badge>
        ) : (
          <Badge tone="warn">{voice.speakers[lang].error || "گوینده‌ای آماده نیست"}</Badge>
        )}
        <Link to={`/stores/${storeId}/voice`} className="text-xs" style={{ color: "var(--brand)" }}>
          تلفظ‌ها و تنظیماتِ بیشتر
        </Link>
      </div>
      {moss && !moss.ready && value.startsWith("moss:") && (
        <div className="text-xs" style={{ color: "var(--warn)" }}>
          {moss.why} تا آن موقع موتورِ بعدیِ فهرست (Edge یا Piper) می‌خواند.
        </div>
      )}
      <ErrorBox message={error} />
      {changed && voiced && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span style={{ color: "var(--text-2)" }}>گوینده عوض شد. ویدیو با گویندهٔ تازه صداگذاری شود؟</span>
          <Button size="sm" onClick={() => { setChanged(false); onRegenerate(); }} disabled={busy}>
            <Icon name="refresh" size={13} />
            صداگذاریِ دوباره
          </Button>
        </div>
      )}
    </div>
  );
}

type SoundState = {
  music: string | null;
  music_asset: number | null;
  music_licence: string;
  music_level_db: number;
  ambience: { asset: number; title: string; level_db: number; license: string } | null;
  ambience_default_db: number;
  voiced: boolean;
  video: string | null;
};

const MUSIC_LEVELS = [
  { value: -28, label: "خیلی آرام" },
  { value: -22, label: "ملایم (پیشنهادی)" },
  { value: -18, label: "واضح‌تر" },
];
const AMBIENCE_LEVELS = [
  { value: -36, label: "خیلی آرام" },
  { value: -30, label: "ملایم (پیشنهادی)" },
  { value: -25, label: "واضح‌تر" },
];

function nearest(levels: { value: number }[], v: number) {
  return levels.reduce((b, l) => (Math.abs(l.value - v) < Math.abs(b.value - v) ? l : b)).value;
}

/**
 * «صدای پس‌زمینه» of one finished video: music and an ambience bed from the shop's audio library — or made
 * right here with the same generators as the «صدا» section — laid under the narration, ducked whenever
 * someone speaks, and played back before it is published.
 */
export default function VideoSoundPanel({ storeId, scriptId }: { storeId: string | number; scriptId: number }) {
  const [state, setState] = useState<SoundState | null>(null);
  const [overview, setOverview] = useState<AudioOverview | null>(null);
  const [music, setMusic] = useState<AudioAsset[]>([]);
  const [beds, setBeds] = useState<AudioAsset[]>([]);
  const [musicId, setMusicId] = useState<string>("keep");
  const [bedId, setBedId] = useState<string>("keep");
  const [musicLevel, setMusicLevel] = useState(-22);
  const [bedLevel, setBedLevel] = useState(-30);
  const [duck, setDuck] = useState(true);
  const [make, setMake] = useState<"" | "music" | "sfx">("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const url = `/stores/${storeId}/video-scripts/${scriptId}/sound-mix/`;

  const loadState = useCallback(async () => {
    try {
      const { data } = await api.get<SoundState>(url);
      setState(data);
      setMusicLevel(nearest(MUSIC_LEVELS, data.music_level_db));
      if (data.ambience) setBedLevel(nearest(AMBIENCE_LEVELS, data.ambience.level_db));
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [url]);

  const loadAssets = useCallback(async () => {
    try {
      const [m, s] = await Promise.all([listAssets(storeId, { kind: "MUSIC" }), listAssets(storeId, { kind: "SFX" })]);
      setMusic(m.filter((a) => a.status === "READY"));
      setBeds(s.filter((a) => a.status === "READY"));
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [storeId]);

  const runner = useJobRunner(loadState);

  useEffect(() => {
    void loadState();
    void loadAssets();
    loadOverview(storeId).then(setOverview).catch(() => setOverview(null));
  }, [storeId, loadState, loadAssets]);

  const created = useCallback(
    (a: AudioAsset) => {
      if (a.status !== "READY") return;
      void loadAssets();
      if (a.kind === "MUSIC") setMusicId(String(a.id));
      if (a.kind === "SFX") setBedId(String(a.id));
    },
    [loadAssets],
  );

  const mix = async () => {
    setBusy(true);
    setError(null);
    try {
      const body: Record<string, unknown> = { music_level_db: musicLevel, ambience_level_db: bedLevel, duck, mix: true };
      if (musicId !== "keep") body.music_asset = musicId === "none" ? null : Number(musicId);
      if (bedId !== "keep") body.ambience_asset = bedId === "none" ? null : Number(bedId);
      const { data } = await api.post<{ job_id: number } & SoundState>(url, body);
      setState(data);
      runner.track(data.job_id);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (!state) return null;
  const nothing =
    (musicId === "none" || (musicId === "keep" && !state.music)) && (bedId === "none" || (bedId === "keep" && !state.ambience));

  return (
    <Card>
      <SectionTitle>صدای پس‌زمینه: موسیقی و صدای محیط</SectionTitle>
      <p className="mb-3 text-sm" style={{ color: "var(--text-2)" }}>
        از <Link to={`/stores/${storeId}/audio/library`}>کتابخانهٔ صداها</Link> بردارید یا همین‌جا بسازید؛ هر دو زیرِ
        گوینده می‌نشینند و هر وقت کسی حرف بزند خودشان آرام می‌شوند.
        {!state.voiced && " ویدیو هنوز صداگذاری نشده؛ موسیقی و صدای محیط تنها روی آن گذاشته می‌شود."}
      </p>
      <ErrorBox message={error} />
      <ErrorBox message={runner.error} />

      <div className="grid gap-4 md:grid-cols-2">
        <div className="flex flex-col gap-2">
          <b className="text-sm" style={{ color: "var(--text)" }}>
            <Icon name="music" size={14} /> موسیقی
          </b>
          <select className="u-input" value={musicId} onChange={(e) => setMusicId(e.target.value)} aria-label="موسیقی">
            <option value="keep">{state.music ? `همین که هست (${state.music})` : "بی موسیقی"}</option>
            {state.music && <option value="none">بی موسیقی</option>}
            {music.map((a) => (
              <option key={a.id} value={a.id}>{a.title}</option>
            ))}
          </select>
          <select className="u-input" value={musicLevel} onChange={(e) => setMusicLevel(Number(e.target.value))}
            aria-label="بلندیِ موسیقی">
            {MUSIC_LEVELS.map((l) => <option key={l.value} value={l.value}>{l.label}</option>)}
          </select>
          <Button size="sm" variant="ghost" onClick={() => setMake(make === "music" ? "" : "music")}>
            <Icon name="plus" size={13} /> ساختِ موسیقیِ تازه
          </Button>
        </div>
        <div className="flex flex-col gap-2">
          <b className="text-sm" style={{ color: "var(--text)" }}>
            <Icon name="cloud" size={14} /> صدای محیط
          </b>
          <select className="u-input" value={bedId} onChange={(e) => setBedId(e.target.value)} aria-label="صدای محیط">
            <option value="keep">{state.ambience ? `همین که هست (${state.ambience.title})` : "بی صدای محیطِ اضافه"}</option>
            {state.ambience && <option value="none">بی صدای محیطِ اضافه</option>}
            {beds.map((a) => (
              <option key={a.id} value={a.id}>{a.title}</option>
            ))}
          </select>
          <select className="u-input" value={bedLevel} onChange={(e) => setBedLevel(Number(e.target.value))}
            aria-label="بلندیِ صدای محیط">
            {AMBIENCE_LEVELS.map((l) => <option key={l.value} value={l.value}>{l.label}</option>)}
          </select>
          <Button size="sm" variant="ghost" onClick={() => setMake(make === "sfx" ? "" : "sfx")}>
            <Icon name="plus" size={13} /> ساختِ صدای محیطِ تازه
          </Button>
        </div>
      </div>

      {make && overview && (
        <div className="mt-3 rounded-xl p-3" style={{ border: "1px dashed var(--line)" }}>
          {make === "music" ? (
            <MusicStudio storeId={storeId} overview={overview} setError={setError} onCreated={created} compact />
          ) : (
            <SfxStudio storeId={storeId} overview={overview} setError={setError} onCreated={created} compact />
          )}
          <p className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
            وقتی آماده شد، خودش در فهرستِ بالا انتخاب می‌شود.
          </p>
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-1 text-sm" style={{ color: "var(--text-2)" }}>
          <input type="checkbox" checked={duck} onChange={(e) => setDuck(e.target.checked)} />
          وقتی گوینده حرف می‌زند آرام شود
        </label>
        <Button onClick={() => void mix()} disabled={busy || runner.running || nothing}>
          <Icon name="film" size={14} />
          {runner.running ? "در حالِ میکس…" : "میکس و پیش‌نمایش"}
        </Button>
        {runner.running && (
          <span className="flex items-center gap-2 text-sm" style={{ color: "var(--text-3)" }}>
            <Spinner size={14} />
            {runner.job?.current_step_label || "در حالِ کار…"}
          </span>
        )}
        {state.music_licence && <Badge tone="ok">مجوزِ موسیقی: {state.music_licence}</Badge>}
      </div>

      {state.video && !runner.running && (
        <div className="mt-3">
          <video key={state.video} src={state.video} controls className="w-full max-w-md rounded-xl" />
        </div>
      )}
      {!overview?.status.engines.music.ready && !overview?.status.engines.sfx.ready && overview && (
        <div className="mt-3">
          <Alert tone="info">
            ساختِ موسیقی و صدای محیطِ تازه به سرورِ پردازش نیاز دارد؛ صداهای آماده‌ی کتابخانه همین حالا هم قابلِ استفاده‌اند.
          </Alert>
        </div>
      )}
    </Card>
  );
}
