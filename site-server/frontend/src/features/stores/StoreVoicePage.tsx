import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import {
  Alert,
  Badge,
  Button,
  Card,
  Field,
  Input,
  SectionTitle,
  Spinner,
  fa,
} from "../../components/ui";
import { Pronunciation, StoreVoice, VoiceProfileValues, VoiceSpeaker } from "../../types";
import { useFlags } from "../panel/FlagsContext";
import { useStore } from "./StoreLayout";
import VoiceTabs from "./VoiceTabs";

type Preview = {
  url: string;
  speaker: { processor?: string; voice?: string; local?: boolean };
  spoken_text: string;
  unresolved: string[];
};

/**
 * صدا و گوینده — the shop's narrator, in the shop's hands.
 *
 * Which engines exist (Edge, the offline Piper voice, Azure…) is the
 * operator's decision in the Django admin. What is decided here is everything
 * on top: male or female, a little faster or slower, and how the shop's own
 * brand names are said. The backend could do all of this before; the fields
 * simply had no screen.
 *
 * Every setting can be HEARD before saving: «بشنو» synthesises a real sample
 * through the same engine chain, polish and pronunciation table a video uses.
 * A voice setting chosen by reading a label is a guess.
 */
export default function StoreVoicePage() {
  const { storeId, setError, setNotice } = useStore();
  const [data, setData] = useState<StoreVoice | null>(null);
  const [profile, setProfile] = useState<VoiceProfileValues | null>(null);
  const [rows, setRows] = useState<Pronunciation[]>([]);
  const [text, setText] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [hearing, setHearing] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const { pageEnabled } = useFlags();

  const load = useCallback(async () => {
    try {
      const { data: payload } = await api.get<StoreVoice>(`/stores/${storeId}/voice/`);
      setData(payload);
      setProfile(payload.profile);
      setRows(payload.pronunciations);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [storeId, setError]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!data || !profile) {
    return (
      <div className="space-y-4">
        <VoiceTabs storeId={storeId} />
        <div className="py-10 text-center">
          <Spinner />
        </div>
      </div>
    );
  }

  const filledRows = rows.filter((r) => r.written.trim() || r.spoken.trim());
  const clonedVoices = (data.cloned_voices ?? []).filter((v) => v.usable);
  const clonedChosen = clonedVoices.find((v) => v.id === profile.cloned_voice) ?? null;
  const norm = (p: VoiceProfileValues) => JSON.stringify({ ...p, cloned_voice: p.cloned_voice ?? null });
  const dirty =
    norm(profile) !== norm(data.profile) ||
    JSON.stringify(filledRows) !== JSON.stringify(data.pronunciations);

  const save = async () => {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const { data: payload } = await api.patch<StoreVoice>(`/stores/${storeId}/voice/`, {
        profile,
        pronunciations: filledRows,
      });
      setData(payload);
      setProfile(payload.profile);
      setRows(payload.pronunciations);
      setNotice("تنظیمات صدا ذخیره شد — ویدیوهای بعدی با همین گوینده صداگذاری می‌شوند.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const hear = async (language: "fa" | "en", sample?: string, tag?: string) => {
    setHearing(tag ?? language);
    setError(null);
    try {
      const { data: result } = await api.post<Preview>(`/stores/${storeId}/voice/preview/`, {
        language,
        ...profile,
        text: sample ?? text,
        // Unsaved rows count: the point of hearing is deciding whether to save.
        pronunciations: filledRows,
      });
      setPreview(result);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setHearing(null);
    }
  };

  const addUnresolved = (word: string) => {
    if (rows.some((r) => r.written.toLowerCase() === word.toLowerCase())) return;
    setRows([...rows, { written: word, spoken: "" }]);
  };

  const speakers = data.speakers.fa;
  const primary = speakers.speakers[0];

  return (
    <div className="space-y-5">
      <VoiceTabs storeId={storeId} />
      <Alert tone="brand" title="صدای ویدیوهای شما">
        اینجا انتخاب می‌کنید گوینده چطور بخواند: مرد یا زن، تندتر یا آرام‌تر، و اسم برندتان
        چطور تلفظ شود. قبل از ذخیره با «بشنو» گوش بدهید — نمونه با همان موتوری ساخته می‌شود که
        ویدیو را صداگذاری می‌کند.
      </Alert>

      {data.profile_was_invalid && (
        <Alert tone="warn">
          تنظیم صدای ذخیره‌شده‌ی قبلی معتبر نبود و ویدیوها با صدای پیش‌فرض ساخته می‌شدند. یک بار
          ذخیره کنید تا درست شود.
        </Alert>
      )}

      <Card>
        <SectionTitle>گوینده</SectionTitle>
        <div className="grid gap-3 sm:grid-cols-2">
          {data.options.voices.map((voice) => {
            const active = profile.gender === voice.key && !clonedChosen;
            return (
              <button
                key={voice.key}
                type="button"
                onClick={() => setProfile({ ...profile, gender: voice.key, cloned_voice: null })}
                className="rounded-xl p-3 text-right"
                style={{
                  border: `2px solid ${active ? "var(--brand)" : "var(--line)"}`,
                  background: active ? "var(--brand-soft)" : "transparent",
                }}
              >
                <div className="flex items-center gap-2 font-bold" style={{ color: "var(--text)" }}>
                  <Icon name="mic" size={16} />
                  {voice.label}
                </div>
                <div className="mt-1 text-xs" style={{ color: "var(--text-3)" }}>
                  {voice.note}
                </div>
              </button>
            );
          })}
          {clonedVoices.map((voice) => {
            const active = clonedChosen?.id === voice.id;
            return (
              <button
                key={`clone-${voice.id}`}
                type="button"
                onClick={() => setProfile({ ...profile, cloned_voice: voice.id })}
                className="rounded-xl p-3 text-right"
                style={{
                  border: `2px solid ${active ? "var(--brand)" : "var(--line)"}`,
                  background: active ? "var(--brand-soft)" : "transparent",
                }}
              >
                <div className="flex flex-wrap items-center gap-2 font-bold" style={{ color: "var(--text)" }}>
                  <Icon name="mic" size={16} />
                  {voice.name}
                  <Badge tone="neutral">کلون‌شده · ساختهٔ ماشین</Badge>
                </div>
                <div className="mt-1 text-xs" style={{ color: "var(--text-3)" }}>
                  صدای {voice.person} — فقط نریشنِ فارسی، روی سرورِ پردازش.{" "}
                  {!voice.commercial && <span dir="ltr">{voice.license}</span>}
                </div>
              </button>
            );
          })}
          {clonedVoices.length === 0 && pageEnabled("voice_clone") && (
            <Link
              to={`/stores/${storeId}/voice/clone`}
              className="rounded-xl p-3 text-right no-underline"
              style={{ border: "2px dashed var(--line)", color: "var(--text-2)" }}
            >
              <div className="flex items-center gap-2 font-bold" style={{ color: "var(--text)" }}>
                <Icon name="plus" size={16} />
                صدای خودتان
              </div>
              <div className="mt-1 text-xs" style={{ color: "var(--text-3)" }}>
                با «کلونِ صدا» از روی چند جملهٔ خوانده‌شده بسازید.
              </div>
            </Link>
          )}
        </div>
        {clonedChosen && (
          <p className="mt-3 text-xs" style={{ color: "var(--text-3)" }}>
            نریشنِ فارسی با صدای کلون‌شدهٔ «{clonedChosen.name}» روی سرورِ پردازش ساخته می‌شود؛ اگر آن سرور خاموش
            باشد، صداگذاری با پیامِ روشن متوقف می‌شود و صدای دیگری جایش نمی‌خواند. سرعت و زیروبمی روی آن اثر ندارد؛
            نریشنِ انگلیسی با صدای {profile.gender === "female" ? "زن" : "مرد"}ِ معمولی می‌ماند.
          </p>
        )}

        <div className="mt-5 grid gap-4 sm:grid-cols-3">
          {data.options.sliders.map((slider) => (
            <Field key={slider.key} label={`${slider.label}: ${fa(profile[slider.key])}${slider.unit}`} hint={slider.hint}>
              <input
                type="range"
                min={slider.min}
                max={slider.max}
                step={1}
                value={profile[slider.key]}
                onChange={(e) => setProfile({ ...profile, [slider.key]: Number(e.target.value) })}
                className="w-full"
              />
            </Field>
          ))}
        </div>

        <div className="mt-5 flex flex-wrap items-end gap-2">
          <div className="min-w-[16rem] flex-1">
            <Field label="متن نمونه (اختیاری)" hint="خالی بماند، یک جمله‌ی نمونه خوانده می‌شود.">
              <Input
                value={text}
                maxLength={300}
                onChange={(e) => setText(e.target.value)}
                placeholder="مثلاً: کفش Nike Air با تخفیف ۳۰ درصد"
              />
            </Field>
          </div>
          <Button variant="secondary" onClick={() => void hear("fa")} disabled={hearing !== null}>
            <Icon name="play" size={14} />
            {hearing === "fa"
              ? clonedChosen
                ? "در حال ساخت روی سرورِ پردازش…"
                : "در حال ساخت…"
              : "بشنو (فارسی)"}
          </Button>
          <Button variant="secondary" onClick={() => void hear("en")} disabled={hearing !== null}>
            <Icon name="play" size={14} />
            {hearing === "en" ? "در حال ساخت…" : "بشنو (انگلیسی)"}
          </Button>
        </div>

        {preview && (
          <div
            className="mt-3 flex flex-col gap-2 rounded-xl p-3 text-sm"
            style={{ border: "1px solid var(--line)" }}
          >
            <audio key={preview.url} controls autoPlay src={preview.url} className="w-full" />
            <div className="flex flex-wrap items-center gap-2 text-xs" style={{ color: "var(--text-2)" }}>
              <span>خوانده‌شده با:</span>
              <Badge tone={preview.speaker.local ? "ok" : "info"}>
                {preview.speaker.processor ?? "—"}
              </Badge>
              <span dir="ltr" style={{ color: "var(--text-3)" }}>
                {preview.speaker.voice}
              </span>
            </div>
            <div className="text-xs" style={{ color: "var(--text-3)" }}>
              آنچه گوینده خواند: {preview.spoken_text}
            </div>
            {preview.unresolved.length > 0 && (
              <div className="flex flex-wrap items-center gap-2 text-xs" style={{ color: "var(--warn)" }}>
                این کلمه‌ها حرف‌به‌حرف خوانده می‌شوند — تلفظشان را اضافه کنید:
                {preview.unresolved.map((word) => (
                  <button
                    key={word}
                    type="button"
                    className="u-badge u-badge-warn"
                    onClick={() => addUnresolved(word)}
                  >
                    + {word}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </Card>

      <Card>
        <SectionTitle>چه موتوری می‌خواند</SectionTitle>
        <p className="mb-3 text-sm" style={{ color: "var(--text-2)" }}>
          موتورها را مدیر سیستم در پنل ادمین انتخاب می‌کند. اولی می‌خواند؛ اگر در دسترس نبود،
          بعدی جایش را می‌گیرد تا ویدیو بی‌صدا نماند.
          {data.local_only && " سیاست داده‌ی این فروشگاه «فقط لوکال» است، پس فقط موتورهای روی همین سیستم استفاده می‌شوند."}
        </p>
        {(["fa", "en"] as const).map((language) => (
          <SpeakerList
            key={language}
            title={language === "fa" ? "فارسی" : "انگلیسی"}
            rows={data.speakers[language].speakers}
            error={data.speakers[language].error}
            female={profile.gender === "female"}
          />
        ))}
        {primary && !primary.local && speakers.speakers.some((s) => s.local) && (
          <p className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
            اگر اینترنت قطع باشد، صدای آفلاین روی همین سیستم جایگزین می‌شود.
          </p>
        )}
        {dirty && (
          <p className="mt-2 text-xs" style={{ color: "var(--warn)" }}>
            این فهرست بعد از ذخیره با انتخاب تازه‌ی شما به‌روز می‌شود.
          </p>
        )}
      </Card>

      <Card>
        <SectionTitle>تلفظ اسم‌ها</SectionTitle>
        <p className="mb-3 text-sm" style={{ color: "var(--text-2)" }}>
          گوینده‌ی فارسی کلمه‌ی لاتین را حرف‌به‌حرف می‌خواند. اسم برند و کلمه‌های خاص را همان‌طور
          که می‌گویید بنویسید. متن کپشن عوض نمی‌شود — فقط صدای ویدیو.
        </p>
        <div className="flex flex-col gap-2">
          {rows.map((row, index) => (
            <div key={index} className="flex flex-wrap items-center gap-2">
              <div className="w-44">
                <Input
                  dir="ltr"
                  value={row.written}
                  placeholder="Nike"
                  onChange={(e) =>
                    setRows(rows.map((r, i) => (i === index ? { ...r, written: e.target.value } : r)))
                  }
                />
              </div>
              <span style={{ color: "var(--text-3)" }}>←</span>
              <div className="w-44">
                <Input
                  value={row.spoken}
                  placeholder="نایکی"
                  onChange={(e) =>
                    setRows(rows.map((r, i) => (i === index ? { ...r, spoken: e.target.value } : r)))
                  }
                />
              </div>
              <Button
                size="sm"
                variant="ghost"
                disabled={!row.written.trim() || !row.spoken.trim() || hearing !== null}
                onClick={() => void hear("fa", row.written, `row-${index}`)}
              >
                <Icon name="play" size={13} />
                {hearing === `row-${index}` ? "…" : "بشنو"}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setRows(rows.filter((_, i) => i !== index))}
              >
                <Icon name="trash" size={13} />
              </Button>
            </div>
          ))}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button
            size="sm"
            variant="secondary"
            disabled={rows.length >= data.max_pronunciations}
            onClick={() => setRows([...rows, { written: "", spoken: "" }])}
          >
            <Icon name="plus" size={13} />
            افزودن تلفظ
          </Button>
          <span className="text-xs" style={{ color: "var(--text-3)" }}>
            {fa(filledRows.length)} از {fa(data.max_pronunciations)}
          </span>
        </div>
        <details className="mt-4 text-sm">
          <summary className="cursor-pointer" style={{ color: "var(--text-3)" }}>
            تلفظ‌هایی که از قبل می‌دانیم ({fa(data.builtin_pronunciations.length)}) — تلفظ شما روی این‌ها اولویت دارد
          </summary>
          <div className="mt-2 flex flex-wrap gap-2">
            {data.builtin_pronunciations.map((row) => (
              <Badge key={row.written} tone="neutral">
                <span dir="ltr">{row.written}</span> ← {row.spoken}
              </Badge>
            ))}
          </div>
        </details>
      </Card>

      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={() => void save()} disabled={saving || !dirty}>
          <Icon name="check" size={15} />
          {saving ? "در حال ذخیره…" : "ذخیره تنظیمات صدا"}
        </Button>
        {!dirty && (
          <span className="text-sm" style={{ color: "var(--text-3)" }}>
            الان: {data.description}
          </span>
        )}
      </div>

      <details className="text-sm">
        <summary className="cursor-pointer" style={{ color: "var(--text-3)" }}>
          چرا سن، لهجه و احساس صدا اینجا نیست؟
        </summary>
        <div className="mt-2 flex flex-col gap-2">
          {data.options.unavailable.map((item) => (
            <p key={item.key} style={{ color: "var(--text-2)" }}>
              <b>{item.label}:</b> {item.why.replace(/\*\*/g, "")}
            </p>
          ))}
          <p style={{ color: "var(--text-3)" }}>{data.options.note}</p>
        </div>
      </details>
    </div>
  );
}

function SpeakerList({
  title,
  rows,
  error,
  female,
}: {
  title: string;
  rows: VoiceSpeaker[];
  error: string;
  female: boolean;
}) {
  return (
    <div className="mb-3">
      <div className="mb-1 text-sm font-bold" style={{ color: "var(--text)" }}>
        {title}
      </div>
      {rows.length === 0 ? (
        <Alert tone="warn">{error || "هیچ گوینده‌ای آماده نیست."}</Alert>
      ) : (
        <ol className="flex flex-col gap-1 text-sm">
          {rows.map((row, index) => (
            <li key={`${row.engine}-${index}`} className="flex flex-wrap items-center gap-2">
              <span style={{ color: "var(--text-3)" }}>{fa(index + 1)}.</span>
              <Badge tone={row.local ? "ok" : "info"}>
                {row.local ? "🖥️ آفلاین" : "☁️ آنلاین"}
              </Badge>
              <span style={{ color: "var(--text)" }}>{row.processor}</span>
              <span dir="ltr" className="text-xs" style={{ color: "var(--text-3)" }}>
                {row.voice}
              </span>
              {index === 0 && <Badge tone="brand">می‌خواند</Badge>}
              {female && !row.exact && (
                <Badge tone="warn">صدای زن ندارد؛ با صدای مرد می‌خواند</Badge>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
