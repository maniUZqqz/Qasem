import { useEffect, useState } from "react";

import Icon from "./Icon";

const KEY = "upmarket-theme";

/**
 * تیره ⇄ روشن، به‌ازای هر مرورگر ذخیره می‌شود.
 *
 * پیش‌فرض تیره است چون طراحی پنل روی زمینه‌ی تیره و هاله‌های رنگی بنا
 * شده؛ روشن نسخه‌ی دوم است نه نسخه‌ی اصلی. کسی که قبلاً روشن را انتخاب
 * کرده باشد، انتخابش سر جایش می‌ماند.
 */
export default function ThemeToggle() {
  // شروع از همان چیزی که اسکریپتِ درون‌خطیِ index.html پیش از اولین رنگ‌آمیزی روی
  // <html> گذاشته؛ اگر نبود (محیط بی‌اسکریپت)، از localStorage — که در حالت
  // خصوصی یا با داده‌ی مسدود ممکن است خطا بدهد.
  const [dark, setDark] = useState(() => {
    const applied = document.documentElement.getAttribute("data-theme");
    if (applied === "light" || applied === "dark") return applied === "dark";
    try {
      return (localStorage.getItem(KEY) ?? "dark") === "dark";
    } catch {
      return true;
    }
  });

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
    try {
      localStorage.setItem(KEY, dark ? "dark" : "light");
    } catch {
      /* private mode — the choice just will not persist */
    }
  }, [dark]);

  return (
    <button
      onClick={() => setDark((v) => !v)}
      className="u-btn u-btn-ghost u-btn-sm"
      style={{ padding: 7 }}
      aria-label={dark ? "تم روشن" : "تم تیره"}
      title={dark ? "تم روشن" : "تم تیره"}
    >
      <Icon name={dark ? "sun" : "moon"} size={17} />
    </button>
  );
}
