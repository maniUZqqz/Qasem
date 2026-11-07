import axios from "axios";
import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";

import "./version-badge.css";
import { parseVersionInfo, tooltipFor, type VersionInfo } from "./versionInfo";

/**
 * نشانِ نسخه — یک قرصِ کوچک در گوشهٔ پایینِ هر صفحه («v2.60»).
 *
 * فقط یک بار، در سطحِ `App` و بیرون از `<Routes>` رندر می‌شود؛ پس روی ورود،
 * ثبت‌نام، صفحه‌های قاب‌دار و ویرایشگرهای تمام‌صفحهٔ عکس و ویدیو هم هست.
 *
 * گوشه: پایین-انتها (در RTL پایین-چپ). سایدبارِ پنل در RTL سمتِ راست (ابتدا) است و
 * پایینش «خروج» و سهمیه؛ پس انتها آزاد می‌ماند. فضای کارِ تمام‌صفحهٔ ویدیو/عکس و ویرایشگرِ
 * سه‌بعدی (دکمه‌های ترکِ تایم‌لاین پایین-چپ است)، سایت‌ساز و فیلم‌برداریِ هدایت‌شده جای دیگری
 * می‌نشینند — همه در version-badge.css با توضیحِ علت.
 *
 * کلیک: `/panel/changelog` در *زبانهٔ تازه* — داخلِ ویرایشگر یک کلیکِ ناخواسته
 * نباید پروژهٔ ذخیره‌نشده را با رفتن به صفحهٔ دیگر از دست بدهد.
 *
 * داده: `GET /api/v1/version/` با axiosِ ساده (بی‌توکن؛ توکنِ منقضی نباید آن را
 * بشکند)، یک بار در حافظهٔ ماژول و ده دقیقه در sessionStorage. شکست ⇒ هیچ چیز
 * رندر نمی‌شود.
 */

const STORE_KEY = "nm-version-v1";
const TTL_MS = 10 * 60 * 1000;

let memory: VersionInfo | null = null;
let inflight: Promise<VersionInfo | null> | null = null;

function readStored(): VersionInfo | null {
  try {
    const raw = sessionStorage.getItem(STORE_KEY);
    if (!raw) return null;
    const saved = JSON.parse(raw) as { at?: number; info?: unknown };
    if (typeof saved.at !== "number" || Date.now() - saved.at > TTL_MS) return null;
    return parseVersionInfo(saved.info);
  } catch {
    return null; // حالتِ خصوصی یا ذخیره‌سازیِ بسته
  }
}

function writeStored(info: VersionInfo) {
  try {
    sessionStorage.setItem(STORE_KEY, JSON.stringify({ at: Date.now(), info }));
  } catch {
    /* مهم نیست: فقط کش است */
  }
}

/** نسخه را می‌خواند؛ شکست ⇒ null (و دفعهٔ بعد دوباره امتحان می‌شود). */
export function loadVersion(): Promise<VersionInfo | null> {
  if (memory) return Promise.resolve(memory);
  const stored = readStored();
  if (stored) {
    memory = stored;
    return Promise.resolve(stored);
  }
  if (!inflight) {
    inflight = axios
      .get("/api/v1/version/", { timeout: 8000, headers: { Accept: "application/json" } })
      .then((r) => {
        const info = parseVersionInfo(r.data);
        if (info) {
          memory = info;
          writeStored(info);
        }
        return info;
      })
      .catch(() => null)
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

export default function VersionBadge() {
  const [info, setInfo] = useState<VersionInfo | null>(memory);
  // فیلم‌برداریِ هدایت‌شده یک نوارِ ثابتِ پایین دارد؛ قرص بالاتر می‌نشیند (version-badge.css)
  const lift = /\/shoot(\/|$)/.test(useLocation().pathname);

  useEffect(() => {
    let alive = true;
    loadVersion().then((v) => {
      if (alive && v) setInfo(v);
    });
    return () => {
      alive = false;
    };
  }, []);

  if (!info) return null;
  return (
    <a
      className={lift ? "nm-ver nm-ver--lift" : "nm-ver"}
      href="/panel/changelog"
      target="_blank"
      rel="noopener noreferrer"
      title={tooltipFor(info)}
      aria-label={`نسخهٔ ${info.version} — چه چیزی تازه است`}
      data-testid="version-badge"
    >
      v{info.version}
    </a>
  );
}
