import { useCallback, useEffect, useRef, useState } from "react";

import { api, studioError } from "./api";
import "./c21st.css";

/**
 * کاتالوگِ 21st.dev (فهرستِ عمومیِ صفحه‌های .md ؛ کد نه). دو کاربرد:
 *  · mode="ai": تا ۳ قطعه را به‌عنوان «الهام» برای هوشِ مصنوعی علامت بزنید (به مدل فقط همین‌ها می‌رسد، نه کلِ کاتالوگ).
 *  · mode="manual": «نزدیک‌ترین قطعهٔ ما» را به بوم اضافه کنید.
 * کدِ قطعه فقط با کلیدِ API ِ خودِ مالک و فقط برای مجوزهای آزاد گرفته می‌شود (۲ قطعه در روز در حسابِ رایگان).
 */
export type C21Item = {
  id: string;
  title: string;
  description: string;
  author: string;
  library: string;
  license: string;
  usable: boolean;
  tags: string[];
  deps: string[];
  cats: string[];
  url: string;
  has_code: boolean;
  nearest: { key: string; label: string; type: string }[];
};
type KeyState = { has_key: boolean; limit: number; used_today: number; left_today: number; how: string };
type Crawl = { running: boolean; finished: boolean; total: number; remaining: number | null; details_done: number; updated_at: string; errors: string[]; cats_done: number; cats_total: number };
type Listing = {
  total: number;
  page: number;
  size: number;
  items: C21Item[];
  categories: { key: string; label: string; count: number }[];
  catalog_size: number;
  crawl: Crawl;
  key: KeyState;
  max_ai_refs: number;
  note: string;
};

const fa = (n: number) => n.toLocaleString("fa-IR");

export default function C21stBrowser({
  mode,
  picked = [],
  onPick,
  onAddNearest,
}: {
  mode: "ai" | "manual";
  picked?: string[];
  onPick?: (ids: string[]) => void;
  onAddNearest?: (type: string) => void;
}) {
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const [usable, setUsable] = useState(false);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Listing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [keyText, setKeyText] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(() => {
    api
      .get<Listing>("/studio/c21st/", { params: { q, cat, usable: usable ? 1 : 0, page, size: 12 } })
      .then((r) => { setData(r.data); setError(null); })
      .catch((e) => setError(studioError(e)));
  }, [q, cat, usable, page]);

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(load, q ? 250 : 0);
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [load, q]);

  // خزش در حالِ انجام است ⇒ هر ۱۵ ثانیه وضعیت را تازه کن
  const running = Boolean(data?.crawl.running) || (data !== null && !data.crawl.finished && data.catalog_size > 0 && data.crawl.remaining !== null && (data.crawl.remaining ?? 0) > 0);
  useEffect(() => {
    if (!running) return;
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [running, load]);

  async function act(name: string, fn: () => Promise<string | void>) {
    setBusy(name);
    setMsg(null);
    try {
      const m = await fn();
      if (m) setMsg(m);
      load();
    } catch (e) {
      setMsg(studioError(e));
    } finally {
      setBusy(null);
    }
  }

  const max = data?.max_ai_refs ?? 3;
  const toggle = (id: string) => {
    if (!onPick) return;
    if (picked.includes(id)) onPick(picked.filter((x) => x !== id));
    else if (picked.length < max) onPick([...picked, id]);
  };

  if (error && !data) return <p className="c21-warn">{error}</p>;
  if (!data) return <p className="c21-note">در حالِ خواندنِ کاتالوگ…</p>;
  const empty = data.catalog_size === 0;
  return (
    <div className="c21" data-testid="c21st-browser">
      <p className="c21-note">{data.note}</p>

      <div className="c21-bar">
        <span className="c21-note">
          {empty ? "کاتالوگ هنوز خالی است." : `${fa(data.catalog_size)} قطعه در کاتالوگ`}
          {data.crawl.running ? " · در حالِ به‌روزرسانی…" : data.crawl.remaining ? ` · ${fa(data.crawl.remaining)} مورد مانده` : ""}
        </span>
        <button type="button" className="c21-btn" disabled={busy !== null || data.crawl.running} data-testid="c21st-crawl"
                onClick={() => void act("crawl", async () => (await api.post<{ message: string }>("/studio/c21st/crawl/", {})).data.message)}>
          {data.crawl.running ? "در حالِ کار…" : empty ? "ساختنِ کاتالوگ" : "به‌روزرسانی"}
        </button>
      </div>
      {empty && <p className="c21-note">خودکار هم ساخته می‌شود (هر شش ساعت یک نوبتِ چهاردقیقه‌ای تا تمام شود)؛ می‌توانید همین حالا هم شروع کنید.</p>}

      {!empty && (
        <>
          <div className="c21-filters">
            <input className="c21-input" placeholder="جست‌وجو (hero، pricing، gradient …)" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} aria-label="جست‌وجو در کاتالوگ" />
            <select className="c21-input" value={cat} onChange={(e) => { setCat(e.target.value); setPage(1); }} aria-label="دسته">
              <option value="">همهٔ دسته‌ها</option>
              {data.categories.map((c) => <option key={c.key} value={c.key}>{c.label} ({fa(c.count)})</option>)}
            </select>
            <label className="c21-check"><input type="checkbox" checked={usable} onChange={(e) => { setUsable(e.target.checked); setPage(1); }} /> فقط مجوزِ آزاد</label>
          </div>

          {mode === "ai" && (
            <p className="c21-note" data-testid="c21st-picked">
              الهام برای هوشِ مصنوعی: {fa(picked.length)} از {fa(max)} {picked.length > 0 && <button type="button" className="c21-link" onClick={() => onPick?.([])}>پاک‌کردن</button>}
            </p>
          )}

          <div className="c21-list">
            {data.items.map((it) => {
              const on = picked.includes(it.id);
              return (
                <div key={it.id} className={`c21-item ${on ? "on" : ""}`} data-c21={it.id}>
                  <div className="c21-head">
                    <b className="c21-title">{it.title}</b>
                    <span className={`c21-badge ${it.usable ? "ok" : ""}`} title={it.usable ? "مجوزِ آزاد" : "فقط دیدن؛ کد و الهامِ کد گرفته نمی‌شود"}>{it.license}</span>
                  </div>
                  <small className="c21-note" dir="ltr">{it.author}{it.library ? ` · ${it.library}` : ""}</small>
                  {it.description && <p className="c21-desc" dir="ltr">{it.description}</p>}
                  {it.tags.length > 0 && <div className="c21-tags">{it.tags.slice(0, 5).map((t) => <span key={t} dir="ltr">{t}</span>)}</div>}
                  <div className="c21-actions">
                    <a className="c21-link" href={it.url} target="_blank" rel="noopener noreferrer" dir="ltr">پیش‌نمایشِ زنده در 21st.dev</a>
                    {mode === "ai" && (
                      <button type="button" className="c21-btn" aria-pressed={on} disabled={!on && picked.length >= max} onClick={() => toggle(it.id)}>
                        {on ? "برداشتنِ الهام" : "الهام برای AI"}
                      </button>
                    )}
                    {mode === "manual" && it.nearest.map((n) => (
                      <button key={n.key} type="button" className="c21-btn" onClick={() => onAddNearest?.(n.type)} title="نزدیک‌ترین قطعهٔ آمادهٔ خودمان">
                        افزودنِ «{n.label}»
                      </button>
                    ))}
                    {it.usable && !it.has_code && (
                      <button type="button" className="c21-link" disabled={busy !== null || !data.key.has_key || data.key.left_today <= 0}
                              title={data.key.has_key ? `سهمِ امروز: ${fa(data.key.left_today)} از ${fa(data.key.limit)}` : "کلیدِ API لازم است"}
                              onClick={() => void act(`code:${it.id}`, async () => { await api.post("/studio/c21st/code/", { id: it.id }); return `کدِ «${it.title}» گرفته شد؛ حالا برشِ کوتاهی از آن به‌عنوان الهام به AI می‌رسد.`; })}>
                        گرفتنِ کد
                      </button>
                    )}
                    {it.has_code && <span className="c21-badge ok">کد گرفته شده</span>}
                  </div>
                </div>
              );
            })}
            {data.items.length === 0 && <p className="c21-note">چیزی پیدا نشد.</p>}
          </div>
          {data.total > data.size && (
            <div className="c21-bar">
              <button type="button" className="c21-btn" disabled={page <= 1} onClick={() => setPage(page - 1)}>قبلی</button>
              <span className="c21-note">صفحهٔ {fa(page)} از {fa(Math.ceil(data.total / data.size))}</span>
              <button type="button" className="c21-btn" disabled={page * data.size >= data.total} onClick={() => setPage(page + 1)}>بعدی</button>
            </div>
          )}
        </>
      )}

      <details className="c21-key" data-testid="c21st-key">
        <summary>کلیدِ API ِ 21st.dev (برای گرفتنِ کدِ قطعه‌ها){data.key.has_key ? " — ثبت شده" : " — لازم است"}</summary>
        <p className="c21-note">{data.key.how}</p>
        {data.key.has_key ? (
          <div className="c21-bar">
            <span className="c21-note">سهمِ امروز: {fa(data.key.left_today)} از {fa(data.key.limit)}</span>
            <button type="button" className="c21-link" onClick={() => void act("key", async () => { await api.delete("/studio/c21st/key/"); return "کلید پاک شد."; })}>پاک‌کردنِ کلید</button>
          </div>
        ) : (
          <div className="c21-bar">
            <input className="c21-input" dir="ltr" type="password" autoComplete="off" placeholder="کلید را بچسبانید" value={keyText} onChange={(e) => setKeyText(e.target.value)} aria-label="کلیدِ API" />
            <button type="button" className="c21-btn" disabled={!keyText.trim() || busy !== null}
                    onClick={() => void act("key", async () => { await api.post("/studio/c21st/key/", { key: keyText.trim() }); setKeyText(""); return "کلید ذخیره شد (در پنل نمایش داده نمی‌شود)."; })}>
              ذخیره
            </button>
          </div>
        )}
      </details>
      {msg && <p className="c21-note" role="status">{msg}</p>}
    </div>
  );
}
