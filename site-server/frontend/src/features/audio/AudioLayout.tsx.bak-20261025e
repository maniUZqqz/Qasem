import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, NavLink, Outlet, useOutletContext, useParams } from "react-router-dom";

import { api, errorMessage } from "../../api/client";
import Icon, { type IconName } from "../../components/Icon";
import { Alert, ErrorBox, Spinner, fa } from "../../components/ui";
import { Store } from "../../types";
import { useFlags } from "../panel/FlagsContext";
import { AudioOverview, loadOverview } from "./api";

/**
 * «صدا» — گفتار، کلونِ صدا، صدای محیط و افکت، موسیقیِ زمینه و کتابخانه، کنارِ هم.
 *
 * مدل‌های سنگین (MOSS-TTS، MOSS-SoundEffect، ACE-Step) فقط روی سرورِ پردازش اجرا می‌شوند؛ هر صفحه بالای
 * خودش می‌گوید موتورش آماده است یا دقیقاً چه کاری لازم است (روشن کردنِ سرور، Download-Models.bat). هر چه
 * ساخته شود در کتابخانهٔ فروشگاه می‌ماند و در استودیوی ویدیو زیرِ گوینده گذاشته می‌شود.
 */
export type AudioCtx = {
  storeId: string;
  store: Store;
  overview: AudioOverview | null;
  reloadOverview: () => Promise<void>;
  setError: (m: string | null) => void;
  setNotice: (m: string | null) => void;
  /** the clone page hides the «گوینده | کلونِ صدا» tabs it shows under the store */
  inAudioSection: true;
};

export function useAudio() {
  return useOutletContext<AudioCtx>();
}

const TABS: { key: string; to: string; label: string; icon: IconName; end?: boolean }[] = [
  { key: "audio_speech", to: "", label: "گفتار", icon: "mic", end: true },
  { key: "audio_clone", to: "clone", label: "کلونِ صدا", icon: "sparkle" },
  { key: "audio_sfx", to: "sfx", label: "صدای محیط و افکت", icon: "cloud" },
  { key: "audio_music", to: "music", label: "موسیقیِ زمینه", icon: "music" },
  { key: "audio_library", to: "library", label: "کتابخانهٔ صداها", icon: "inbox" },
];

export default function AudioLayout() {
  const { id: storeId } = useParams<{ id: string }>();
  const { pageEnabled } = useFlags();
  const [store, setStore] = useState<Store | null>(null);
  const [overview, setOverview] = useState<AudioOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const reloadOverview = useCallback(async () => {
    if (!storeId) return;
    try {
      setOverview(await loadOverview(storeId));
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [storeId]);

  useEffect(() => {
    if (!storeId) return;
    api
      .get<Store>(`/stores/${storeId}/`)
      .then(({ data }) => setStore(data))
      .catch((err) => setError(errorMessage(err)));
    void reloadOverview();
  }, [storeId, reloadOverview]);

  const ctx = useMemo<AudioCtx | null>(
    () =>
      storeId && store
        ? { storeId, store, overview, reloadOverview, setError, setNotice, inAudioSection: true }
        : null,
    [storeId, store, overview, reloadOverview],
  );

  if (!storeId) return null;
  const used = overview?.limits.used_today ?? 0;
  const limit = overview?.limits.daily_seconds ?? 0;

  return (
    <div className="u-rise space-y-5">
      <div>
        <Link to={`/stores/${storeId}`} className="u-back">
          <Icon name="back" size={15} />
          بازگشت به فروشگاه
        </Link>
        <h1 className="mt-1 text-2xl font-extrabold" style={{ color: "var(--text)" }}>
          صدا{store ? ` — ${store.name}` : ""}
        </h1>
        <p className="text-xs" style={{ color: "var(--text-3)" }}>
          گفتار، صدای خودتان، صدای محیط و موسیقیِ بی‌کلام برای ویدیوها. هر چه بسازید در «کتابخانهٔ صداها» می‌ماند و
          در استودیوی ویدیو زیرِ گوینده می‌نشیند.
          {limit > 0 && ` امروز ${fa(Math.round(used / 60))} از ${fa(Math.round(limit / 60))} دقیقهٔ مجاز ساخته شده.`}
        </p>
      </div>

      <nav className="u-tabs">
        {TABS.filter((t) => pageEnabled(t.key)).map((t) => (
          <NavLink key={t.key} to={t.to} end={t.end} className={({ isActive }) => `u-tab ${isActive ? "active" : ""}`}>
            <span className="flex items-center gap-1.5">
              <Icon name={t.icon} size={15} />
              {t.label}
            </span>
          </NavLink>
        ))}
      </nav>

      <ErrorBox message={error} />
      {notice && <Alert tone="ok">{notice}</Alert>}

      {ctx ? (
        <Outlet context={ctx} />
      ) : (
        <div className="py-10 text-center">
          <Spinner />
        </div>
      )}
    </div>
  );
}
