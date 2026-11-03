import { useRef, useState } from "react";

import { Spinner, fa } from "../../../../components/ui";
import type { Bin as BinData, MediaItem } from "../api";
import { timecode } from "./model";

const TABS: { key: keyof BinData; title: string }[] = [
  { key: "videos", title: "ویدیو" },
  { key: "audio", title: "صدا" },
  { key: "images", title: "عکس" },
];

/** سطلِ رسانه: ویدیوهای فروشگاه (آپلودی، تدوین‌شده، ساخته‌شده)، صدای کتابخانه و عکس‌ها. بکشید روی تایم‌لاین یا «+». */
export default function Bin({
  bin, loading, onAdd, onUpload, onProxy, proxyBusy,
}: {
  bin: BinData | null;
  loading: boolean;
  onAdd: (item: MediaItem) => void;
  onUpload: (file: File) => void;
  onProxy: (item: MediaItem) => void;
  proxyBusy: string | null;
}) {
  const [tab, setTab] = useState<keyof BinData>("videos");
  const file = useRef<HTMLInputElement>(null);
  const items = bin?.[tab] ?? [];
  return (
    <div className="vw-bin" data-testid="bin" dir="rtl">
      <div className="ws-tabs">
        {TABS.map((t) => (
          <button key={t.key} type="button" className={tab === t.key ? "is-on" : ""} onClick={() => setTab(t.key)} data-bin-tab={t.key}>
            {t.title} {bin ? `(${fa(bin[t.key].length)})` : ""}
          </button>
        ))}
      </div>
      <div className="vw-scroll">
        {tab === "videos" && (
          <div className="mb-2">
            <input ref={file} type="file" accept="video/*" hidden data-testid="bin-upload" onChange={(e) => { const f = e.target.files?.[0]; if (f) onUpload(f); if (file.current) file.current.value = ""; }} />
            <button type="button" className="ws-btn w-full justify-center" onClick={() => file.current?.click()}>+ آپلودِ ویدیوی تازه</button>
          </div>
        )}
        {loading && <Spinner size={16} />}
        {!loading && items.length === 0 && (
          <p className="ws-hint">
            {tab === "videos" ? "هنوز ویدیویی نیست؛ بالا آپلود کنید." : tab === "audio" ? "صدایی در کتابخانه نیست (بخش «صدا» در پنل)." : "عکسی نیست."}
          </p>
        )}
        {items.map((it) => (
          <div key={it.ref} className="mb-1">
            <div
              className="vw-item" draggable data-ref={it.ref}
              onDragStart={(e) => {
                e.dataTransfer.setData("text/nm-ref", it.ref);
                e.dataTransfer.effectAllowed = "copy";
              }}
              onDoubleClick={() => onAdd(it)}
              title="بکشید روی تایم‌لاین، یا دوبار کلیک"
            >
              <span aria-hidden>{it.kind === "video" ? "🎞" : it.kind === "audio" ? "🔊" : "🖼"}</span>
              <span className="t">{it.title}</span>
              <small dir="ltr">{it.kind === "image" ? "" : timecode(it.duration).slice(0, 5)}</small>
              <button type="button" className="ws-btn" onClick={() => onAdd(it)} aria-label="افزودن به تایم‌لاین" data-add={it.ref}>+</button>
            </div>
            {it.kind === "video" && (it.proxy === "needed" || it.proxy === "ready") && (
              <div className="px-1 pb-1 text-[11px]" style={{ color: it.proxy === "ready" ? "var(--ok)" : "var(--warn)" }}>
                {it.proxy === "ready" ? (
                  "پیش‌نمایشِ سبک آماده است (خروجی با فایلِ اصلی)"
                ) : (
                  <>
                    {it.height > 576 ? `${fa(it.height)}p — برای پیش‌نمایشِ روان ` : "این قالب را مرورگر نمی‌خواند — "}
                    <button type="button" className="ws-link" disabled={proxyBusy === it.ref} onClick={() => onProxy(it)} data-proxy={it.ref}>
                      {proxyBusy === it.ref ? "در حالِ ساخت…" : "پیش‌نمایشِ سبک بساز"}
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
