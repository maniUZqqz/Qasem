import { useCallback, useEffect, useRef, useState } from "react";

import { errorMessage } from "../../../api/client";
import { Alert, Badge, Button, ErrorBox, Input, Spinner, fa } from "../../../components/ui";
import { CommonsPoster, RefRow, thumbsApi } from "./api";

type Tab = "url" | "commons" | "upload";

const TABS: { key: Tab; label: string }[] = [
  { key: "url", label: "نشانیِ پین یا عکس" },
  { key: "commons", label: "پوسترِ فیلمِ آزاد" },
  { key: "upload", label: "عکسِ خودم" },
];

const SIDE_FA: Record<string, string> = { left: "چپ", right: "راست", center: "وسط" };
const ZONE_FA: Record<string, string> = { top: "بالا", bottom: "پایین", left: "چپ", right: "راست" };

/**
 * «مرجع»: یک پینِ پینترست، یک پوسترِ فیلمِ آزاد یا عکسِ خودتان ⇒ رنگ، حال‌وهوا و چیدمان تحلیل می‌شود و ایده‌ها با همان حس ساخته می‌شوند.
 * عکسِ مرجع هرگز وارد خروجی نمی‌شود؛ فقط تحلیل می‌شود (رنگ‌ها و جای سوژه و متن).
 */
export default function ReferenceBoard({
  storeId,
  selected,
  onSelect,
  paletteMode,
  onPaletteMode,
  hasBrand,
}: {
  storeId: string;
  selected: string;
  onSelect: (id: string) => void;
  paletteMode: "brand" | "reference";
  onPaletteMode: (m: "brand" | "reference") => void;
  hasBrand: boolean;
}) {
  const [refs, setRefs] = useState<RefRow[] | null>(null);
  const [note, setNote] = useState("");
  const [tab, setTab] = useState<Tab>("url");
  const [url, setUrl] = useState("");
  const [q, setQ] = useState("");
  const [results, setResults] = useState<CommonsPoster[] | null>(null);
  const [resNote, setResNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    thumbsApi.references(storeId).then((r) => { setRefs(r.references); setNote(r.pinterest_note); }).catch((e) => setError(errorMessage(e)));
  }, [storeId]);
  useEffect(load, [load]);

  async function add(fn: () => Promise<RefRow>, key: string) {
    setBusy(key);
    setError(null);
    try {
      const row = await fn();
      setRefs((list) => [row, ...(list ?? [])]);
      onSelect(row.id);
    } catch (e) {
      // پینترست: عکس از سرور (ایران) باز نمی‌شود، ولی سرور نشانیِ عکس را می‌دهد؛ اگر مرورگرِ شما به آن می‌رسد (VPN) خودش می‌گیرد و بارگذاری می‌کند
      const extra = (e as { response?: { data?: { error?: { image_url?: string; title?: string } } } }).response?.data?.error;
      if (extra?.image_url) {
        try {
          const res = await fetch(extra.image_url, { mode: "cors", referrerPolicy: "no-referrer" });
          const blob = await res.blob();
          if (!res.ok || !blob.type.startsWith("image/")) throw new Error("not an image");
          const row = await thumbsApi.refUpload(storeId, new File([blob], "pin.jpg", { type: blob.type }), extra.title);
          setRefs((list) => [row, ...(list ?? [])]);
          onSelect(row.id);
        } catch {
          setError(`${errorMessage(e)} مرورگرِ شما هم نتوانست آن را بگیرد (پینترست در ایران فیلتر است؛ با VPN امتحان کنید).`);
        }
      } else {
        setError(errorMessage(e));
      }
    } finally {
      setBusy(null);
    }
  }

  async function search() {
    if (q.trim().length < 2) {
      setError("چیزی بنویسید؛ مثلاً «film noir» یا «sport poster».");
      return;
    }
    setBusy("search");
    setError(null);
    try {
      const r = await thumbsApi.refSearch(storeId, q);
      setResults(r.results);
      setResNote(r.note);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  async function remove(id: string) {
    try {
      await thumbsApi.refRemove(storeId, id);
      setRefs((list) => (list ?? []).filter((r) => r.id !== id));
      if (selected === id) onSelect("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  const current = refs?.find((r) => r.id === selected) ?? null;

  return (
    <div className="th-refs" data-testid="thumb-references">
      <h3 className="mb-1 text-sm font-extrabold" style={{ color: "var(--text)" }}>ایده از روی مرجع (پینترست، پوسترِ فیلم، عکسِ خودتان)</h3>
      <p className="dz-muted mb-2">
        یک نمونه را بیاورید؛ رنگ‌ها، حال‌وهوا و جای سوژه و متنِ آن تحلیل می‌شود و «ایده بده» با همان حس پیشنهاد می‌دهد. عکسِ مرجع در خروجی نمی‌آید.
      </p>

      <div className="th-reftabs" role="tablist" aria-label="منبعِ مرجع">
        {TABS.map((t) => (
          <button key={t.key} type="button" role="tab" aria-selected={tab === t.key} className="th-reftab" onClick={() => setTab(t.key)}>{t.label}</button>
        ))}
      </div>

      {tab === "url" && (
        <div className="mt-2">
          <div className="flex flex-wrap gap-2">
            <div style={{ flex: "1 1 260px", minWidth: 0 }}>
              <Input dir="ltr" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://www.pinterest.com/pin/…  یا نشانیِ مستقیمِ یک عکس"
                     onKeyDown={(e) => e.key === "Enter" && url.trim() && void add(() => thumbsApi.refAddUrl(storeId, url), "url")} />
            </div>
            <Button size="sm" disabled={!url.trim() || busy !== null} onClick={() => void add(() => thumbsApi.refAddUrl(storeId, url), "url").then(() => setUrl(""))}>
              {busy === "url" ? "در حالِ گرفتن…" : "افزودن و تحلیل"}
            </Button>
          </div>
          {note && <p className="dz-muted mt-1 th-wrap">{note}</p>}
        </div>
      )}

      {tab === "commons" && (
        <div className="mt-2">
          <div className="flex flex-wrap gap-2">
            <div style={{ flex: "1 1 220px", minWidth: 0 }}>
              <Input dir="ltr" value={q} onChange={(e) => setQ(e.target.value)} placeholder="film noir، sport، adventure …" onKeyDown={(e) => e.key === "Enter" && void search()} />
            </div>
            <Button size="sm" variant="secondary" disabled={busy !== null} onClick={() => void search()}>{busy === "search" ? "در حالِ جست‌وجو…" : "جست‌وجوی پوستر"}</Button>
          </div>
          {results && (
            <>
              {resNote && <p className="dz-muted mt-1 th-wrap">{resNote}</p>}
              {results.length === 0 ? (
                <p className="dz-muted mt-2">پوسترِ آزادی با این واژه پیدا نشد؛ واژهٔ انگلیسیِ دیگری امتحان کنید.</p>
              ) : (
                <div className="th-refgrid mt-2">
                  {results.map((p) => (
                    <div key={p.id} className="th-refcard">
                      <img src={p.thumb_url} alt={p.title} loading="lazy" referrerPolicy="no-referrer" />
                      <div className="th-refmeta">
                        <b className="th-wrap">{p.title}</b>
                        <span className="dz-muted th-wrap">{p.license}{p.author ? ` · ${p.author}` : ""}</span>
                        <Button size="sm" variant="secondary" disabled={busy !== null} onClick={() => void add(() => thumbsApi.refAddCommons(storeId, p), `c${p.id}`)}>
                          {busy === `c${p.id}` ? "…" : "استفاده به‌عنوان مرجع"}
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}

      {tab === "upload" && (
        <div className="mt-2">
          <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp" hidden
                 onChange={(e) => { const f = e.target.files?.[0]; if (f) void add(() => thumbsApi.refUpload(storeId, f), "upload"); e.target.value = ""; }} />
          <Button size="sm" variant="secondary" disabled={busy !== null} onClick={() => fileRef.current?.click()}>{busy === "upload" ? "در حالِ تحلیل…" : "انتخابِ عکس از دستگاه"}</Button>
          <p className="dz-muted mt-1">JPEG، PNG یا WebP، تا ۸ مگابایت.</p>
        </div>
      )}

      {busy && <div className="mt-2"><Spinner size={16} /></div>}
      <div className="mt-2"><ErrorBox message={error} /></div>

      {refs === null ? (
        !error && <div className="mt-2"><Spinner size={16} /></div>
      ) : refs.length > 0 ? (
        <div className="mt-3">
          <div className="dz-muted mb-1">مرجع‌های شما (یکی را برای ایده‌پردازی انتخاب کنید)</div>
          <div className="th-refgrid">
            {refs.map((r) => (
              <div key={r.id} className="th-refcard" data-selected={r.id === selected}>
                <button type="button" className="th-refpick" aria-pressed={r.id === selected} onClick={() => onSelect(r.id === selected ? "" : r.id)} title="انتخاب / برداشتنِ انتخاب">
                  <img src={r.image} alt={r.title || "مرجع"} loading="lazy" />
                </button>
                <div className="th-refmeta">
                  <b className="th-wrap">{r.title || "بدون‌نام"}</b>
                  <div className="flex flex-wrap items-center gap-1"><Badge tone="neutral">{r.source_label}</Badge><Badge tone="info">{r.analysis.mood_fa}</Badge></div>
                  <div className="th-chips" aria-label="رنگ‌های غالب">
                    {r.analysis.palette.map((c) => <i key={c.hex} style={{ background: c.hex }} title={`${c.name} ${fa(Math.round(c.share * 100))}٪`} />)}
                  </div>
                  <Button size="sm" variant="ghost" onClick={() => void remove(r.id)}>حذف</Button>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <p className="dz-muted mt-3">هنوز مرجعی ندارید.</p>
      )}

      {current && (
        <Alert tone="info">
          <div className="text-sm th-wrap" data-testid="thumb-ref-summary">
            <b>برداشت از «{current.title || "مرجع"}»: </b>{current.analysis.summary}
            <div className="mt-1">
              سوژه: {SIDE_FA[current.analysis.layout.subject_side] ?? "وسط"} · جای متن: {ZONE_FA[current.analysis.layout.text_zone] ?? "پایین"} ·
              سبک‌های نزدیک: {current.analysis.styles.map((s) => s.title).join("، ")}
            </div>
            {(current.license || current.author) && (
              <div className="dz-muted mt-1">
                منبع: {current.page_url ? <a href={current.page_url} target="_blank" rel="noreferrer noopener" dir="ltr">{current.title}</a> : current.title}
                {current.author ? ` — ${current.author}` : ""}{current.license ? ` (${current.license})` : ""}
              </div>
            )}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-3 text-sm">
            <label className="dz-field check">
              <input type="radio" name="th-palette-mode" checked={paletteMode === "brand"} onChange={() => onPaletteMode("brand")} />
              <span>رنگِ برندِ خودم بماند{hasBrand ? "" : " (برندی ثبت نشده؛ رنگ‌های حال‌وهوا)"}</span>
            </label>
            <label className="dz-field check">
              <input type="radio" name="th-palette-mode" checked={paletteMode === "reference"} onChange={() => onPaletteMode("reference")} />
              <span>رنگ‌ها از مرجع بیاید</span>
            </label>
          </div>
        </Alert>
      )}
    </div>
  );
}
