import { useCallback, useEffect, useRef, useState } from "react";

import { api, errorMessage } from "../../api/client";
import SubtitleSwitch from "../../components/SubtitleSwitch";
import MusicLibrary from "./MusicLibrary";
import { useJobRunner } from "../../hooks/useJobRunner";
import {
  Alert,
  Button,
  Card,
  ErrorBox,
  Input,
  SectionTitle,
  Spinner,
  fa,
} from "../../components/ui";

type Subtitles = {
  url: string | null;
  lines: number;
  possible: boolean;
  reason: string;
  /** null = follow the shop default. See SubtitleSwitch for why three states. */
  enabled: boolean | null;
  burned: boolean | null;
  effective_enabled: boolean;
  effective_burned: boolean;
  word_level: boolean;
  word_level_note: string;
};

type Music = {
  music: string | null;
  level_db: number;
  ceiling_db: number;
  video: string | null;
  licence: string;
  /** The library track's own licence (CC-BY, CC0…); empty for the shop's file. */
  track_licence?: string;
  attribution: string;
  needs_credit: boolean;
};

/** How loud the shop's own background sits, in words instead of decibels.
 *  The value is the offset the backend applies to the admin's background
 *  loudness; the admin's ceiling caps it whatever is chosen here. */
const LEVELS = [
  { value: "-28", label: "خیلی آرام (فقط حس شود)" },
  { value: "-22", label: "ملایم (پیشنهادی)" },
  { value: "-18", label: "کمی واضح‌تر" },
];

/** The option closest to a stored level. A track saved before these three
 *  choices existed (say −20) must show — and re-submit — what the select
 *  displays, not a value the shop cannot see. */
function nearestLevel(db: number): string {
  if (!Number.isFinite(db)) return "-22";
  return LEVELS.reduce((best, l) =>
    Math.abs(Number(l.value) - db) < Math.abs(Number(best.value) - db) ? l : best,
  ).value;
}

/**
 * Subtitles and music for one finished video. §7, §8.
 *
 * The two halves are opposites and the page says so:
 *
 * - **Subtitles are free**, because we wrote the narration. Nothing to
 *   recognise, nothing to pay for.
 * - **Music is the shop's**, because a track with an imperfect licence becomes
 *   a copyright strike on *their* page, weeks later. The licence note is above
 *   the upload button, not in terms nobody reads.
 */
export default function SubtitleMusicPanel({
  storeId,
  scriptId,
}: {
  storeId: string | number;
  scriptId: number;
}) {
  const [subtitles, setSubtitles] = useState<Subtitles | null>(null);
  const [music, setMusic] = useState<Music | null>(null);
  const [level, setLevel] = useState("-22");
  // Duck under the narrator — the default, and almost always right. Off only
  // for a video with no narration worth protecting.
  const [duck, setDuck] = useState(true);
  const [busy, setBusy] = useState(false);
  const [showLibrary, setShowLibrary] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const [subs, track] = await Promise.all([
        api.get(`/stores/${storeId}/video-scripts/${scriptId}/subtitles/`),
        api.get(`/stores/${storeId}/video-scripts/${scriptId}/music/`),
      ]);
      setSubtitles(subs.data);
      setMusic(track.data);
      setLevel(nearestLevel(Number(track.data.level_db)));
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [storeId, scriptId]);

  const runner = useJobRunner(load);

  useEffect(() => {
    load();
  }, [load]);

  async function setSubtitleFlag(key: "enabled" | "burned", next: boolean | null) {
    setError(null);
    try {
      const { data } = await api.patch(
        `/stores/${storeId}/video-scripts/${scriptId}/subtitles/`,
        { [key]: next },
      );
      setSubtitles(data);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function buildSubtitles() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const { data } = await api.post(
        `/stores/${storeId}/video-scripts/${scriptId}/subtitles/`,
      );
      runner.track(data.job_id);
      setNotice("ساخت زیرنویس شروع شد.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function upload(file: File) {
    setBusy(true);
    setError(null);
    const body = new FormData();
    body.append("music", file);
    try {
      await api.put(`/stores/${storeId}/video-scripts/${scriptId}/music/`, body);
      setNotice("موسیقی آپلود شد.");
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function mix() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const { data } = await api.post(
        `/stores/${storeId}/video-scripts/${scriptId}/music/`,
        { level_db: Number(level), duck },
      );
      runner.track(data.job_id);
      setNotice("گذاشتن موسیقی شروع شد.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (!subtitles || !music) return null;

  const tooLoud = Number(level) > music.ceiling_db;

  return (
    <Card>
      <SectionTitle>زیرنویس و موسیقی</SectionTitle>
      <ErrorBox message={error} />
      <ErrorBox message={runner.error} />
      {notice && (
        <div className="mb-3">
          <Alert tone="ok">{notice}</Alert>
        </div>
      )}
      {runner.running && (
        <div className="mb-3 flex items-center gap-2">
          <Spinner size={18} />
          <span className="text-sm" style={{ color: "var(--text-2)" }}>
            {runner.job?.current_step_label || "در حال کار…"}
          </span>
        </div>
      )}

      {/* --- subtitles ------------------------------------------------ */}
      <div className="mb-5">
        <p className="mb-2 text-sm font-bold" style={{ color: "var(--text)" }}>
          زیرنویس
        </p>

        {!subtitles.possible ? (
          <Alert tone="neutral">{subtitles.reason}</Alert>
        ) : (
          <>
            <p className="mb-2 text-sm leading-7" style={{ color: "var(--text-2)" }}>
              زیرنویس این ویدیو **رایگان** است — متنش را خودمان نوشته‌ایم، پس
              چیزی برای تشخیص دادن نیست. {fa(subtitles.lines)} خط می‌شود.
            </p>
            <div className="mb-3 flex flex-col gap-2">
              <SubtitleSwitch
                label="زیرنویس"
                value={subtitles.enabled}
                effective={subtitles.effective_enabled}
                onChange={(next) => setSubtitleFlag("enabled", next)}
                disabled={busy}
              />
              <SubtitleSwitch
                label="روی تصویر بسوزد"
                value={subtitles.burned}
                effective={subtitles.effective_burned}
                onChange={(next) => setSubtitleFlag("burned", next)}
                disabled={busy}
                hint="سوخته روی همه‌ی پلتفرم‌ها می‌ماند؛ فایل جدا قابل ویرایش است"
              />
            </div>

            <div className="flex flex-wrap gap-2">
              <Button
                onClick={buildSubtitles}
                disabled={busy || runner.running || !subtitles.effective_enabled}
              >
                بساز
              </Button>
              {subtitles.url && (
                <a href={subtitles.url} download>
                  <Button variant="secondary">دانلود فایل SRT</Button>
                </a>
              )}
            </div>
            {!subtitles.word_level && (
              <p className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
                {subtitles.word_level_note}
              </p>
            )}
          </>
        )}
      </div>

      {/* --- music ---------------------------------------------------- */}
      <div className="border-t pt-4" style={{ borderColor: "var(--line)" }}>
        <p className="mb-2 text-sm font-bold" style={{ color: "var(--text)" }}>
          موسیقی یا صدای پس‌زمینه‌ی خودتان
        </p>

        <div className="mb-3">
          <Alert tone="info" title="ملایم، زیر همه‌ی صداها">
            یا از موسیقی رایگان و قابل‌استفاده انتخاب کنید، یا فایل خودتان را آپلود
            کنید (آهنگ، صدای مغازه، هر صدایی که حال‌وهوای برندتان است). این پایین‌ترین
            لایه‌ی صداست: زیر گوینده، زیر افکت‌ها و زیر صدای محیط، و هر وقت گوینده حرف
            می‌زند خودش آرام‌تر می‌شود تا مزاحم صدای اصلی نشود.{" "}
            <b>ما فایل موسیقی همراه محصول نمی‌دهیم</b> — {music.licence}
          </Alert>
        </div>

        <div className="mb-3 flex flex-wrap gap-2">
          <Button
            variant={showLibrary ? "primary" : "secondary"}
            onClick={() => setShowLibrary((v) => !v)}
          >
            {showLibrary ? "بستن کتابخانه" : "موسیقی رایگان"}
          </Button>
          <span className="self-center text-xs" style={{ color: "var(--text-3)" }}>
            یا فایل خودتان:
          </span>
          <input
            ref={fileInput}
            type="file"
            accept="audio/*"
            className="text-sm"
            disabled={busy}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) upload(file);
            }}
          />
        </div>

        {showLibrary && (
          <MusicLibrary
            storeId={storeId}
            scriptId={scriptId}
            onPicked={() => {
              setShowLibrary(false);
              setNotice("آهنگ انتخاب شد.");
              void load();
            }}
          />
        )}

        {music.music && (
          <>
            <p className="mt-2 text-sm" style={{ color: "var(--text-2)" }}>
              فایل فعلی: <b>{music.music}</b>
              {music.track_licence && (
                <span className="u-badge u-badge-neutral" style={{ marginInlineStart: 8 }}>
                  {music.track_licence}
                </span>
              )}
            </p>
            {music.needs_credit && (
              <div className="mt-2">
                <Alert tone="warn" title="این آهنگ ذکر منبع لازم دارد">
                  عیناً این را در توضیحات پست بنویسید:
                  <code
                    dir="ltr"
                    className="mt-1 block break-all rounded-lg p-2 text-xs"
                    style={{ background: "var(--surface-2)" }}
                  >
                    {music.attribution}
                  </code>
                </Alert>
              </div>
            )}
            <div className="mt-3 flex flex-wrap items-end gap-2">
              <div className="w-48">
                <select
                  className="u-input"
                  value={level}
                  onChange={(e) => setLevel(e.target.value)}
                >
                  {LEVELS.map((l) => (
                    <option key={l.value} value={l.value}>
                      {l.label}
                    </option>
                  ))}
                </select>
              </div>
              <label className="flex items-center gap-1 text-sm" style={{ color: "var(--text-2)" }}>
                <input type="checkbox" checked={duck} onChange={(e) => setDuck(e.target.checked)} />
                موقع حرف زدن گوینده آرام‌تر شود
              </label>
              <Button onClick={mix} disabled={busy || runner.running}>
                روی ویدیو بگذار
              </Button>
              {music.video && (
                <a href={music.video} target="_blank" rel="noreferrer">
                  <Button variant="secondary">نسخه‌ی با موسیقی</Button>
                </a>
              )}
            </div>
            <p className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
              پیش‌فرض «ملایم» است. هر انتخابی باشد، پس‌زمینه هیچ‌وقت از سقفی که مدیر
              سیستم گذاشته بلندتر نمی‌شود و وقتی گوینده حرف می‌زند خودش پایین می‌آید.
            </p>
            {tooLoud && (
              <p className="mt-1 text-xs" style={{ color: "var(--warn)" }}>
                بلندتر از {fa(music.ceiling_db)} پذیرفته نمی‌شود — از آن بالاتر
                صدای گوینده شنیده نمی‌شود و ویدیو کار خودش را نمی‌کند.
              </p>
            )}
          </>
        )}
      </div>
    </Card>
  );
}
