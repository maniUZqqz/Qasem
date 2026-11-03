import { ReactNode, useEffect, useState } from "react";

import Icon from "./Icon";
import "./editors.css";

/**
 * قابِ فضای کارِ دستی (فتوشاپ‌مانند / پریمیرمانند): یک نوارِ عنوان و دکمهٔ «تمام‌صفحه».
 * تمام‌صفحه با Esc بسته می‌شود. محتوا خودش چیدمانِ چپ‌به‌راست (dir=ltr) دارد؛ متن‌ها داخلِ پنل‌ها راست‌به‌چپ‌اند.
 */
export default function Workspace({
  title,
  actions,
  children,
  testId,
}: {
  title: string;
  actions?: ReactNode;
  children: ReactNode;
  testId?: string;
}) {
  const [full, setFull] = useState(false);

  useEffect(() => {
    if (!full) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setFull(false);
    };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [full]);

  return (
    <div className={`ws-root ${full ? "is-full" : ""}`} data-testid={testId} data-full={full ? "1" : "0"}>
      <div className="ws-titlebar" dir="rtl">
        <span className="ws-title">{title}</span>
        <span className="ws-spacer" />
        {actions}
        <button
          type="button"
          className="ws-btn"
          onClick={() => setFull((v) => !v)}
          title={full ? "بستنِ تمام‌صفحه (Esc)" : "تمام‌صفحه"}
          aria-pressed={full}
          data-testid="ws-fullscreen"
        >
          <Icon name={full ? "x" : "copy"} size={15} />
          <span>{full ? "خروج از تمام‌صفحه" : "تمام‌صفحه"}</span>
        </button>
      </div>
      <div className="ws-body">{children}</div>
    </div>
  );
}
