import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import { Alert, Card, EmptyState, SectionTitle, Spinner, fa } from "../../components/ui";
import AssetCard from "./AssetCard";
import { useAudio } from "./AudioLayout";
import { AssetKind, AudioAsset, listAssets } from "./api";
import { MusicStudio, SfxStudio, SpeechStudio } from "./Studios";

function Waiting() {
  return (
    <div className="py-10 text-center">
      <Spinner />
    </div>
  );
}

export function AudioSpeechPage() {
  const { storeId, overview, setError } = useAudio();
  if (!overview) return <Waiting />;
  return (
    <Card>
      <SectionTitle>گفتار: متن به صدا</SectionTitle>
      <p className="mb-4 text-sm" style={{ color: "var(--text-2)" }}>
        پیش‌فرض <b>MOSS-TTS فارسی</b> روی سرورِ پردازش است (مجوزِ Apache-2.0، استفادهٔ تجاری مجاز). صدای خودتان را در
        «کلونِ صدا» بسازید تا این‌جا هم باشد. Piper روی همین سرور و بی‌اینترنت می‌خواند؛ Edge آنلاین و غیررسمی است.
      </p>
      <SpeechStudio storeId={storeId} overview={overview} setError={setError} />
    </Card>
  );
}

export function AudioSfxPage() {
  const { storeId, overview, setError } = useAudio();
  if (!overview) return <Waiting />;
  return (
    <Card>
      <SectionTitle>صدای محیط و افکت</SectionTitle>
      <p className="mb-4 text-sm" style={{ color: "var(--text-2)" }}>
        با <b>MOSS-SoundEffect</b> روی سرورِ پردازش (Apache-2.0): باران، خیابان، کافه، قدم، باز شدنِ جعبه… تا ۳۰ ثانیه.
        صدای محیطی که این‌جا می‌سازید در استودیوی ویدیو زیرِ گوینده می‌نشیند.
      </p>
      <SfxStudio storeId={storeId} overview={overview} setError={setError} />
    </Card>
  );
}

export function AudioMusicPage() {
  const { storeId, overview, setError } = useAudio();
  if (!overview) return <Waiting />;
  return (
    <Card>
      <SectionTitle>موسیقیِ زمینه</SectionTitle>
      <p className="mb-4 text-sm" style={{ color: "var(--text-2)" }}>
        موسیقیِ بی‌کلام با <b>ACE-Step 1.5</b> روی سرورِ پردازش (مجوزِ MIT؛ خروجی برای استفادهٔ تجاری آزاد است)، بی‌آن‌که
        نگرانِ کپی‌رایتِ آهنگِ کسِ دیگری باشید.
      </p>
      <MusicStudio storeId={storeId} overview={overview} setError={setError} />
    </Card>
  );
}

const FILTERS: { key: "" | AssetKind; label: string }[] = [
  { key: "", label: "همه" },
  { key: "SPEECH", label: "گفتار" },
  { key: "SFX", label: "صدای محیط و افکت" },
  { key: "MUSIC", label: "موسیقی" },
];

export function AudioLibraryPage() {
  const { storeId, setError } = useAudio();
  const [kind, setKind] = useState<"" | AssetKind>("");
  const [rows, setRows] = useState<AudioAsset[] | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await listAssets(storeId, { kind: kind || undefined, saved: true }));
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [storeId, kind, setError]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <Card>
      <SectionTitle>کتابخانهٔ صداها</SectionTitle>
      <div className="mb-3 flex flex-wrap gap-1">
        {FILTERS.map((f) => (
          <button key={f.key || "all"} type="button" onClick={() => setKind(f.key)}
            className={`u-badge ${kind === f.key ? "u-badge-brand" : "u-badge-neutral"}`}>
            {f.label}
          </button>
        ))}
      </div>
      <Alert tone="info">
        برای گذاشتنِ موسیقی یا صدای محیط زیرِ یک ویدیو: <Link to={`/stores/${storeId}/studio`}>تولید محتوا</Link> ›
        استودیوی ویدیو › «صدای پس‌زمینه». گفتار را می‌توانید دانلود کنید. چیزی که ذخیره نکنید، فردا پاک می‌شود.
      </Alert>
      <div className="mt-3 flex flex-col gap-2">
        {rows === null ? (
          <Waiting />
        ) : rows.length === 0 ? (
          <EmptyState icon="music" title="هنوز صدایی در کتابخانه نیست"
            action={<span className="text-sm" style={{ color: "var(--text-3)" }}>در گفتار، صدای محیط یا موسیقی چیزی بسازید و «ذخیره در کتابخانه» را بزنید.</span>} />
        ) : (
          <>
            <div className="text-xs" style={{ color: "var(--text-3)" }}>
              {fa(rows.length)} صدا
            </div>
            {rows.map((a) => (
              <AssetCard key={a.id} storeId={storeId} asset={a} setError={setError}
                onDeleted={(id) => setRows((r) => (r ?? []).filter((x) => x.id !== id))}
                onChange={(fresh) => {
                  if (!fresh.saved) setRows((r) => (r ?? []).filter((x) => x.id !== fresh.id));
                }}
                extra={a.used_in.length ? (
                  <span className="text-xs" style={{ color: "var(--text-3)" }}>
                    <Icon name="film" size={12} /> در ویدیوهای {a.used_in.map((u) => fa(u.script)).join("، ")}
                  </span>
                ) : undefined} />
            ))}
          </>
        )}
      </div>
    </Card>
  );
}
