import { memo, ReactNode, useRef, useState } from "react";

import { Spinner, fa } from "../../../../components/ui";
import { countRender } from "../../../../hooks/perfCount";
import type { Bin as BinData, MediaItem } from "../api";
import { Project, timecode } from "./model";
import { BinFolder, addFolder, assignToFolder, deleteFolder, filterBin } from "./r5ops";
import { useAudioKinds } from "./soundApi";
import "./sound.css";

/** فیلترِ نوعِ صدا در تبِ «صدا» (نوع از کتابخانهٔ صدا می‌آید؛ آیتمِ سطل نوع ندارد) */
type AudioFilter = "all" | "MUSIC" | "SFX" | "SPEECH";
const AUDIO_FILTERS: { key: AudioFilter; title: string }[] = [
  { key: "all", title: "همه" },
  { key: "MUSIC", title: "موسیقی" },
  { key: "SFX", title: "جلوه‌های صوتی" },
  { key: "SPEECH", title: "گفتار" },
];

const TABS: { key: keyof BinData; title: string }[] = [
  { key: "videos", title: "ویدیو" },
  { key: "audio", title: "صدا" },
  { key: "images", title: "عکس" },
  { key: "stickers", title: "استیکر" },
];

/** سطلِ رسانه: ویدیوهای فروشگاه (آپلودی، تدوین‌شده، ساخته‌شده)، صدای کتابخانه و عکس‌ها. بکشید روی تایم‌لاین یا «+». */
function BinBase({
  bin, loading, onAdd, onUpload, onProxy, proxyBusy, storeId, onGoSound, uploadSlot, folders = [], meta, onFolderOp,
}: {
  bin: BinData | null;
  loading: boolean;
  onAdd: (item: MediaItem) => void;
  onUpload: (file: File) => void;
  onProxy: (item: MediaItem) => void;
  proxyBusy: string | null;
  /** برای فیلترِ نوعِ صدا (موسیقی/جلوه/گفتار)؛ نباشد فیلتر نمایش داده نمی‌شود */
  storeId?: string;
  /** «رفتن به تبِ صدا» در حالتِ خالیِ صدا */
  onGoSound?: () => void;
  /** نوارِ پیشرفتِ آپلود (زیرِ دکمهٔ آپلود) */
  uploadSlot?: ReactNode;
  /** پوشه‌های کاربر (در پروژه ذخیره می‌شوند) و ویرایششان با یک گامِ برگشت */
  folders?: BinFolder[];
  /** برچسب و یادداشتِ رسانه‌ها (از پروژه) */
  meta?: Record<string, { tags: string[]; note: string }>;
  onFolderOp?: (label: string, fn: (p: Project) => Project) => void;
}) {
  countRender("Bin");
  const [tab, setTab] = useState<keyof BinData>("videos");
  const [audioFilter, setAudioFilter] = useState<AudioFilter>("all");
  const file = useRef<HTMLInputElement>(null);
  const kinds = useAudioKinds(storeId, tab === "audio" && !!storeId, bin?.audio.length ?? 0);
  const [q, setQ] = useState("");
  const [folderId, setFolderId] = useState<string | null>(null);
  const [naming, setNaming] = useState<string | null>(null);
  const folder = folders.find((f) => f.id === folderId) ?? null;
  const all = bin?.[tab] ?? [];
  const byKind = tab === "audio" && audioFilter !== "all" ? all.filter((it) => kinds?.[it.ref] === audioFilter) : all;
  const items = tab === "stickers" ? byKind : filterBin(byKind, q, folder, meta);
  const filtering = tab !== "stickers" && (!!q.trim() || !!folder);
  const sticker = tab === "stickers";
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
            {uploadSlot}
          </div>
        )}
        {tab !== "stickers" && onFolderOp && (
          <div className="bn-tools" data-testid="bin-tools">
            <input className="u-input bn-search" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="جستجو در رسانه‌ها…" aria-label="جستجو در رسانه‌ها" data-testid="bin-search" />
            <div className="bn-folders" role="group" aria-label="پوشه‌ها">
              <button type="button" className={`ws-chip ${folderId === null ? "is-on" : ""}`} aria-pressed={folderId === null} onClick={() => setFolderId(null)} data-testid="bin-folder-all">همه</button>
              {folders.map((f) => (
                <button key={f.id} type="button" className={`ws-chip ${folderId === f.id ? "is-on" : ""}`} aria-pressed={folderId === f.id} onClick={() => setFolderId(f.id)} data-testid="bin-folder">{f.name} ({f.refs.filter((r) => all.some((a) => a.ref === r)).length})</button>
              ))}
              {naming === null ? (
                <button type="button" className="ws-chip" onClick={() => setNaming("")} data-testid="bin-new-folder" title="پوشهٔ تازه برای دسته‌بندیِ رسانه‌ها">+ پوشه</button>
              ) : (
                <input className="u-input bn-name" autoFocus value={naming} maxLength={40} placeholder="نامِ پوشه + Enter" aria-label="نامِ پوشهٔ تازه" data-testid="bin-folder-name"
                  onChange={(e) => setNaming(e.target.value)} onBlur={() => setNaming(null)}
                  onKeyDown={(e) => {
                    if (e.key === "Escape") setNaming(null);
                    if (e.key === "Enter" && naming.trim()) {
                      onFolderOp("پوشهٔ تازه", (p) => addFolder(p, naming).project);
                      setNaming(null);
                    }
                  }} />
              )}
              {folder && <button type="button" className="ws-chip" onClick={() => { if (window.confirm(`پوشهٔ «${folder.name}» پاک شود؟ (رسانه‌ها پاک نمی‌شوند)`)) { onFolderOp("حذفِ پوشه", (p) => deleteFolder(p, folder.id)); setFolderId(null); } }} data-testid="bin-folder-delete" aria-label={`حذفِ پوشهٔ ${folder.name}`}>× حذفِ این پوشه</button>}
            </div>
          </div>
        )}
        {tab === "audio" && storeId && all.length > 0 && kinds && (
          <div className="sq-bin-chips" role="group" aria-label="نوعِ صدا" data-testid="bin-audio-filter">
            {AUDIO_FILTERS.map((f) => (
              <button key={f.key} type="button" className={`ws-chip ${audioFilter === f.key ? "is-on" : ""}`} aria-pressed={audioFilter === f.key}
                onClick={() => setAudioFilter(f.key)} data-audio-filter={f.key}>
                {f.title}{f.key === "all" ? "" : ` (${fa(all.filter((it) => kinds[it.ref] === f.key).length)})`}
              </button>
            ))}
          </div>
        )}
        {loading && <Spinner size={16} />}
        {!loading && tab === "audio" && all.length === 0 && (
          <div className="sq-bin-empty" data-testid="bin-audio-empty">
            <p className="ws-hint">هنوز صدایی ندارید. موسیقی بسازید یا از کتابخانه بیاورید — دکمهٔ «موسیقیِ پس‌زمینه» در تبِ صدا.</p>
            {onGoSound && <button type="button" className="ws-btn" onClick={onGoSound} data-testid="bin-go-sound" title="تبِ «صدا» را در پنلِ کناری باز می‌کند">🎵 رفتن به تبِ صدا</button>}
          </div>
        )}
        {!loading && tab === "audio" && all.length > 0 && byKind.length === 0 && <p className="ws-hint">در این دسته چیزی نیست.</p>}
        {!loading && filtering && byKind.length > 0 && items.length === 0 && <p className="ws-hint" data-testid="bin-no-match">چیزی با این جستجو یا در این پوشه پیدا نشد.</p>}
        {!loading && tab !== "audio" && !filtering && items.length === 0 && (
          <p className="ws-hint">
            {tab === "videos" ? "هنوز ویدیویی نیست؛ بالا آپلود کنید." : sticker ? "استیکری در دسترس نیست." : "عکسی نیست."}
          </p>
        )}
        {items.map((it) => (
          <div key={it.ref} className="mb-1">
            <div
              className="vw-item" draggable data-ref={it.ref} data-kind={it.kind}
              onDragStart={(e) => {
                e.dataTransfer.setData("text/nm-ref", it.ref);
                e.dataTransfer.effectAllowed = "copy";
              }}
              onDoubleClick={() => onAdd(it)}
              title="بکشید روی تایم‌لاین، یا دوبار کلیک"
            >
              {sticker ? <img src={it.url} alt="" width={22} height={22} style={{ objectFit: "contain" }} /> : <span aria-hidden>{it.kind === "video" ? "🎞" : it.kind === "audio" ? "🔊" : "🖼"}</span>}
              <span className="t">{it.title}</span>
              {meta?.[it.ref] && (
                <span className="bn-tags" data-testid="bin-tags" title={meta[it.ref].note || undefined}>
                  {meta[it.ref].tags.slice(0, 3).map((g) => <em key={g}>{g}</em>)}{meta[it.ref].note ? <em title={meta[it.ref].note}>📝</em> : null}
                </span>
              )}
              {onFolderOp && folders.length > 0 && tab !== "stickers" && (
                <select className="u-input bn-sel" value={folders.find((f) => f.refs.includes(it.ref))?.id ?? ""} aria-label={`پوشهٔ «${it.title}»`} data-testid="bin-item-folder"
                  onClick={(e) => e.stopPropagation()} onDoubleClick={(e) => e.stopPropagation()}
                  onChange={(e) => onFolderOp("جابه‌جاییِ رسانه به پوشه", (p) => assignToFolder(p, it.ref, e.target.value || null))}>
                  <option value="">—</option>
                  {folders.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
                </select>
              )}
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

// ۱۴۰۵/۰۸/۲۳: memo؛ فضای کار callback ها را با هویتِ ثابت می‌دهد، پس سطل با هر تیکِ پخش یا کشیدنِ تایم‌لاین دوباره ساخته نمی‌شود
export default memo(BinBase);
