import { useCallback, useEffect, useRef, useState } from "react";

import { api, studioError } from "./api";
import type { ThemeT } from "./builder/types";
import "./c21st.css";

/**
 * کاتالوگِ 21st.dev (کلِ فهرستِ عمومی با رعایتِ robots.txt). دو کاربرد:
 *  · mode="ai": تا ۳ قطعه را به‌عنوان «الهام» برای هوشِ مصنوعی علامت بزنید (به مدل فقط همین‌ها و چند قطعهٔ مرتبط می‌رسد، نه کلِ کاتالوگ).
 *  · mode="manual": قطعه‌های «قابلِ درج» (مجوزِ آزاد + تبدیل‌شده به HTMLِ امن) را ببینید، پیش‌نمایشِ زنده با پوستهٔ همین پروژه بگیرید و در صفحه بگذارید؛
 *    «نزدیک‌ترین قطعهٔ ما» برای بقیه می‌ماند.
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
  preview: boolean;
  insertable: boolean;
  conv_key: string;
  conv_state: string;
  conv_error: string;
  kind?: string;
};
type KeyState = { has_key: boolean; limit: number; used_today: number; left_today: number; how: string };
type Crawl = {
  running: boolean;
  finished: boolean;
  total: number;
  remaining: number | null;
  details_done: number;
  updated_at: string;
  errors: string[];
  cats_done: number;
  cats_total: number;
  blocked?: boolean;
  usable?: number;
  previews?: number;
};
type Pipeline = { toolchain: boolean; converted: number; insertable?: number; blocked?: number; failed: number; no_source: number; waiting?: number; license_blocked: number; node: { pending: number; jobs: number; ingested: number } };
type Listing = {
  total: number;
  page: number;
  size: number;
  items: C21Item[];
  categories: { key: string; label: string; count: number }[];
  catalog_size: number;
  insertable?: number;
  insertable_sections?: number;
  query_en?: string;
  with_preview?: number;
  crawl: Crawl;
  pipeline?: Pipeline;
  key: KeyState;
  max_ai_refs: number;
  note: string;
};
type Live = { html: string; base_css: string; page_css: string; license: string; author: string; library: string; url: string; source: { repo?: string; license?: string; path?: string }; texts: number; images: number };

const fa = (n: number) => n.toLocaleString("fa-IR");

/** تصویرِ پیش‌نمایش: API با توکنِ ورود کار می‌کند و <img> نمی‌تواند توکن بفرستد؛ پس با axios به‌صورتِ blob می‌گیریم (فقط وقتی کارت دیده شد). */
function PreviewImg({ id }: { id: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [seen, setSeen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") {
      setSeen(true);
      return;
    }
    const io = new IntersectionObserver((e) => e.some((x) => x.isIntersecting) && (setSeen(true), io.disconnect()), { rootMargin: "120px" });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  useEffect(() => {
    if (!seen) return;
    let live = true;
    let made: string | null = null;
    api
      .get<Blob>(`/studio/c21st/image/${id}/`, { responseType: "blob" })
      .then((r) => {
        if (!live) return;
        made = URL.createObjectURL(r.data);
        setUrl(made);
      })
      .catch(() => undefined);
    return () => {
      live = false;
      if (made) URL.revokeObjectURL(made);
    };
  }, [seen, id]);
  return (
    <div ref={ref} className="c21-thumb" aria-hidden="true">
      {url ? <img src={url} alt="" loading="lazy" /> : <span />}
    </div>
  );
}

export default function C21stBrowser({
  mode,
  picked = [],
  onPick,
  onAddNearest,
  onAddC21,
  slug,
  theme,
}: {
  mode: "ai" | "manual";
  picked?: string[];
  onPick?: (ids: string[]) => void;
  onAddNearest?: (type: string) => void;
  onAddC21?: (key: string, withAi?: boolean) => void | string | Promise<void | string>;
  slug?: string;
  theme?: ThemeT;
}) {
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const [usable, setUsable] = useState(mode === "ai");               // الهام برای AI فقط از قطعه‌های با مجوزِ آزاد؛ بقیه فقط کاتالوگ‌اند
  const [insertable, setInsertable] = useState(mode === "manual");
  const [kind, setKind] = useState<"" | "section" | "widget">("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Listing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [keyText, setKeyText] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [live, setLive] = useState<Live | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(() => {
    api
      .get<Listing>("/studio/c21st/", { params: { q, cat, usable: usable ? 1 : 0, insertable: insertable ? 1 : 0, kind: insertable ? kind : "", page, size: 12 } })
      .then((r) => {
        setData(r.data);
        setError(null);
      })
      .catch((e) => setError(studioError(e)));
  }, [q, cat, usable, insertable, kind, page]);

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(load, q ? 250 : 0);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [load, q]);

  // خزش یا تبدیل در حالِ انجام است ⇒ هر ۱۵ ثانیه وضعیت را تازه کن
  const running = Boolean(data?.crawl.running) || (data !== null && !data.crawl.finished && data.catalog_size > 0 && data.crawl.remaining !== null && (data.crawl.remaining ?? 0) > 0);
  useEffect(() => {
    if (!running) return;
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [running, load]);

  useEffect(() => {
    if (!open || !slug) {
      setLive(null);
      return;
    }
    let ok = true;
    setLive(null);
    api
      .get<Live>(`/studio/projects/${slug}/builder/c21/${open}/preview/`, { params: theme?.style ? { style: theme.style } : {} })
      .then((r) => ok && setLive(r.data))
      .catch((e) => { if (ok) { setMsg(studioError(e)); setOpen(null); } });
    return () => {
      ok = false;
    };
  }, [open, slug, theme?.style]);

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
  const conv = data.pipeline;
  return (
    <div className="c21" data-testid="c21st-browser">
      <p className="c21-note">{data.note}</p>

      <div className="c21-bar">
        <span className="c21-note" data-testid="c21st-stats">
          {empty ? "کاتالوگ هنوز خالی است." : `${fa(data.catalog_size)} قطعه در کاتالوگ · ${fa(data.crawl.usable ?? 0)} با مجوزِ آزاد · ${fa(data.insertable ?? 0)} قابلِ درج (${fa(data.insertable_sections ?? 0)} بخشِ صفحه)`}
          {data.crawl.running ? " · در حالِ به‌روزرسانی…" : data.crawl.remaining ? ` · ${fa(data.crawl.remaining)} مورد مانده` : ""}
        </span>
        <span className="c21-actions">
          <button type="button" className="c21-btn" disabled={busy !== null || data.crawl.running} data-testid="c21st-crawl"
                  onClick={() => void act("crawl", async () => (await api.post<{ message: string }>("/studio/c21st/crawl/", {})).data.message)}>
            {data.crawl.running ? "در حالِ کار…" : empty ? "ساختنِ کاتالوگ" : "به‌روزرسانی"}
          </button>
          <button type="button" className="c21-btn" disabled={busy !== null || !conv?.toolchain} data-testid="c21st-convert" title={conv?.toolchain ? "قطعه‌های با مجوزِ آزادِ کتابخانه‌های دارای مخزنِ عمومی را به قطعهٔ قابلِ درج تبدیل می‌کند" : "جعبه‌ابزارِ تبدیل نصب نیست"}
                  onClick={() => void act("convert", async () => (await api.post<{ message: string }>("/studio/c21st/convert/", {})).data.message)}>
            تبدیلِ قطعه‌ها
          </button>
        </span>
      </div>
      {data.crawl.blocked && <p className="c21-warn">سرور از 21st.dev ۴۰۳ گرفت؛ خزش به کارِ «crawl21.run» روی سرورِ گرافیکی سپرده می‌شود و با روشن‌شدنِ آن خودکار ادامه پیدا می‌کند.</p>}
      {conv && (
        <p className="c21-note" data-testid="c21st-pipeline">
          تبدیل: {fa(conv.insertable ?? conv.converted)} قطعهٔ قابلِ درج از {fa(conv.converted)} تبدیل‌شده{conv.blocked ? ` (${fa(conv.blocked)} بسته: خالی، نخوانا، سرریز یا رویِ‌هم‌افتاده)` : ""} · {fa(conv.no_source)} بدونِ کدِ عمومی{conv.waiting ? ` · ${fa(conv.waiting)} در انتظارِ تبدیل` : ""} · {fa(conv.license_blocked)} مجوزِ مخزن آزاد نبود · {fa(conv.failed)} ناموفق
          {conv.node.pending ? ` · ${fa(conv.node.pending)} کارِ خزشِ سرورِ گرافیکی در انتظار` : ""}
        </p>
      )}
      {empty && <p className="c21-note">خودکار هم ساخته می‌شود (هر شش ساعت یک نوبتِ چهاردقیقه‌ای تا تمام شود)؛ می‌توانید همین حالا هم شروع کنید.</p>}

      {!empty && (
        <>
          <div className="c21-filters">
            <input className="c21-input" placeholder="جست‌وجو (قیمت، پرسش‌های متداول، منو، فوتر، دکمه … یا hero، pricing)" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} aria-label="جست‌وجو در کاتالوگ" data-testid="c21st-search" />
            <select className="c21-input" value={cat} onChange={(e) => { setCat(e.target.value); setPage(1); }} aria-label="دسته">
              <option value="">همهٔ دسته‌ها</option>
              {data.categories.map((c) => <option key={c.key} value={c.key}>{c.label} ({fa(c.count)})</option>)}
            </select>
            <label className="c21-check"><input type="checkbox" checked={insertable} onChange={(e) => { setInsertable(e.target.checked); setPage(1); }} data-testid="c21st-insertable" /> فقط قابلِ درج</label>
            {insertable && (
              <select className="c21-input" value={kind} onChange={(e) => { setKind(e.target.value as "" | "section" | "widget"); setPage(1); }} aria-label="نوعِ قطعه" data-testid="c21st-kind">
                <option value="">بخش و ابزارک</option>
                <option value="section">فقط بخش‌های صفحه</option>
                <option value="widget">فقط ابزارک‌ها (دکمه، کارت کوچک …)</option>
              </select>
            )}
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
                  {it.preview && <PreviewImg id={it.id} />}
                  <div className="c21-head">
                    <b className="c21-title">{it.title}</b>
                    <span className={`c21-badge ${it.usable ? "ok" : ""}`} title={it.usable ? "مجوزِ آزاد" : "فقط دیدن؛ کد و الهامِ کد گرفته نمی‌شود"}>{it.license}</span>
                  </div>
                  <small className="c21-note" dir="ltr">{it.author}{it.library ? ` · ${it.library}` : ""}</small>
                  {it.description && <p className="c21-desc" dir="ltr">{it.description}</p>}
                  {it.tags.length > 0 && <div className="c21-tags">{it.tags.slice(0, 5).map((t) => <span key={t} dir="ltr">{t}</span>)}</div>}
                  {it.insertable && <span className="c21-badge ok" data-testid="c21-insertable">قابلِ درج{it.kind === "section" ? " · بخشِ صفحه" : it.kind === "widget" ? " · ابزارک" : ""}</span>}
                  {!it.insertable && it.conv_state === "failed" && <small className="c21-note" title={it.conv_error}>تبدیل نشد</small>}
                  <div className="c21-actions">
                    <a className="c21-link" href={it.url} target="_blank" rel="noopener noreferrer" dir="ltr">21st.dev</a>
                    {mode === "manual" && it.insertable && slug && (
                      <button type="button" className="c21-link" onClick={() => setOpen(open === it.conv_key ? null : it.conv_key)} data-testid="c21-preview">
                        {open === it.conv_key ? "بستنِ پیش‌نمایش" : "پیش‌نمایشِ زنده"}
                      </button>
                    )}
                    {mode === "manual" && it.insertable && onAddC21 && (
                      <button type="button" className="c21-btn" disabled={busy !== null} data-testid="c21-add"
                              onClick={() => void act(`add:${it.id}`, async () => { const extra = await onAddC21(it.conv_key); return `«${it.title}» به صفحه اضافه شد؛ متن‌ها (عبارت‌های رایج فارسی شده‌اند) و تصویرها را روی بوم ویرایش کنید.${extra ? " " + extra : ""}`; })}>
                        افزودن به صفحه
                      </button>
                    )}
                    {mode === "manual" && it.insertable && onAddC21 && (
                      <button type="button" className="c21-btn" disabled={busy !== null} data-testid="c21-add-ai" title="بقیهٔ متن‌های انگلیسیِ قطعه را با هوش مصنوعی فارسی می‌کند؛ اگر هوش مصنوعی در دسترس نباشد قطعه با ترجمهٔ عبارت‌های رایج اضافه می‌شود و دلیل نوشته می‌شود"
                              onClick={() => void act(`addai:${it.id}`, async () => { const extra = await onAddC21(it.conv_key, true); return `«${it.title}» به صفحه اضافه شد.${extra ? " " + extra : ""}`; })}>
                        افزودن + فارسی‌سازیِ متن با AI
                      </button>
                    )}
                    {mode === "ai" && (
                      <button type="button" className="c21-btn" aria-pressed={on} disabled={!it.usable || (!on && picked.length >= max)} onClick={() => toggle(it.id)}
                              title={it.usable ? undefined : "مجوزِ آزاد ندارد؛ فقط در کاتالوگ دیده می‌شود و به هوشِ مصنوعی داده نمی‌شود"}>
                        {!it.usable ? "فقط در کاتالوگ" : on ? "برداشتنِ الهام" : it.insertable ? "پیشنهاد به AI (HTMLِ آماده)" : "الهام برای AI"}
                      </button>
                    )}
                    {mode === "manual" && !it.insertable && it.nearest.map((n) => (
                      <button key={n.key} type="button" className="c21-btn" onClick={() => onAddNearest?.(n.type)} title="نزدیک‌ترین قطعهٔ آمادهٔ خودمان">
                        افزودنِ «{n.label}»
                      </button>
                    ))}
                    {it.usable && !it.has_code && !it.insertable && (
                      <button type="button" className="c21-link" disabled={busy !== null || !data.key.has_key || data.key.left_today <= 0}
                              title={data.key.has_key ? `سهمِ امروز: ${fa(data.key.left_today)} از ${fa(data.key.limit)}` : "کلیدِ API لازم است"}
                              onClick={() => void act(`code:${it.id}`, async () => { await api.post("/studio/c21st/code/", { id: it.id }); return `کدِ «${it.title}» گرفته شد؛ حالا برشِ کوتاهی از آن به‌عنوان الهام به AI می‌رسد.`; })}>
                        گرفتنِ کد
                      </button>
                    )}
                    {it.has_code && <span className="c21-badge ok">کد گرفته شده</span>}
                  </div>
                  {open === it.conv_key && (
                    <div className="c21-live" data-testid="c21-live">
                      {!live && <p className="c21-note">در حالِ ساختنِ پیش‌نمایش…</p>}
                      {live && (
                        <>
                          <iframe
                            title={`پیش‌نمایشِ ${it.title}`}
                            sandbox="allow-same-origin"
                            className="c21-frame"
                            srcDoc={`<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>${live.base_css}\n${live.page_css}\nbody{margin:0;background:var(--bg)}</style></head><body>${live.html}</body></html>`}
                          />
                          <small className="c21-note" dir="ltr">{live.author}{live.library ? ` · ${live.library}` : ""} · {live.license}{live.source?.repo ? ` · ${live.source.repo}` : ""}</small>
                          <small className="c21-note">{fa(live.texts)} متنِ قابلِ ویرایش · {fa(live.images)} تصویر</small>
                        </>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
            {data.items.length === 0 && <p className="c21-note">چیزی پیدا نشد.{insertable ? " (فیلترِ «فقط قابلِ درج» روشن است؛ اگر هنوز چیزی تبدیل نشده «تبدیلِ قطعه‌ها» را بزنید یا فیلتر را بردارید.)" : ""}</p>}
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
        <summary>کلیدِ API ِ 21st.dev (برای گرفتنِ کدِ قطعه‌هایی که مخزنِ عمومی ندارند){data.key.has_key ? " — ثبت شده" : " — اختیاری"}</summary>
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
