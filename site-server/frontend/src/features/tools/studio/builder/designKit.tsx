/** سبکِ طراحی و قطعه‌های آماده در ویرایشگرِ دیداری: انتخابگرِ سبک (پوسته) و کتابخانهٔ قطعه‌ها (افزودن). */
import { CSSProperties, useEffect, useMemo, useState } from "react";

import { api, studioError } from "../api";
import type { Catalog, CompMeta, Doc } from "./doc";
import { Svg } from "./fields";
import type { StyleT, ThemeOptions, ThemeT } from "./types";

/** کشیدنِ یک آیتم از فهرست به بوم (فقط با ماوس؛ روی لمس همان «افزودن» است). */
export function press(e: React.PointerEvent, go: (x: number, y: number) => void) {
  if (e.pointerType === "touch" || e.button !== 0) return;
  const sx = e.clientX;
  const sy = e.clientY;
  const move = (ev: PointerEvent) => {
    if (Math.abs(ev.clientX - sx) + Math.abs(ev.clientY - sy) > 6) {
      cleanup();
      go(ev.clientX, ev.clientY);
    }
  };
  const cleanup = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", cleanup);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", cleanup);
}

/* ─────────── سبک ─────────── */

/** توکنِ CSSِ سبک (که به متغیرهای سایتِ مشتری اشاره دارد) ⇒ مقدارِ قابلِ نمایش در پنل با رنگ‌های خودِ سبک. */
function resolve(v: string | undefined, s: StyleT): string | undefined {
  if (!v) return undefined;
  const c = s.theme.colors;
  const out = v
    .replace(/var\(--card\)/g, c.surface)
    .replace(/var\(--line\)/g, c.line)
    .replace(/var\(--bg\)/g, c.bg)
    .replace(/var\(--ink\)/g, c.text)
    .replace(/var\(--brand-ink,#fff\)/g, c.on_primary)
    .replace(/var\(--brand\)/g, c.primary)
    .replace(/var\(--r,16px\)/g, `${s.theme.radius}px`);
  return out.includes("var(") ? undefined : out;
}

const BTN_RADIUS: Record<string, number> = { round: 99, soft: 7, square: 2 };

function StyleThumb({ s }: { s: StyleT }) {
  const t = s.tokens;
  const c = s.theme.colors;
  const bg = resolve(t.page_bg, s) ?? c.bg;
  const card: CSSProperties = {
    flex: 1,
    height: 26,
    background: resolve(t.card_bg, s) ?? c.surface,
    border: resolve(t.card_bd, s) ?? `1px solid ${c.line}`,
    boxShadow: resolve(t.card_sh, s),
    borderRadius: Math.min(resolve(t.card_r, s) === "0" ? 0 : s.theme.radius, 14),
    backdropFilter: resolve(t.bf, s),
  };
  return (
    <span className="nbe-style-thumb" style={{ background: bg }} aria-hidden="true">
      <i style={{ width: "52%", height: 7, borderRadius: 4, background: c.text, opacity: 0.92 }} />
      <span style={{ display: "flex", gap: 6 }}>
        <i style={card} />
        <i style={card} />
      </span>
      <i style={{ width: "34%", height: 13, borderRadius: BTN_RADIUS[s.theme.button] ?? 99, background: c.primary, boxShadow: resolve(t.btn_sh, s) }} />
    </span>
  );
}

export function StylePicker({
  slug,
  theme,
  doc,
  target,
  pageId,
  options,
  onApply,
}: {
  slug: string;
  theme: ThemeT;
  doc: Doc;
  target: string;
  pageId?: number;
  options: ThemeOptions;
  onApply: (theme: ThemeT, doc: Doc | null) => void;
}) {
  const styles = options.styles ?? [];
  const [pick, setPick] = useState<string>(theme.style ?? "");
  const [keepBrand, setKeepBrand] = useState(false);
  const [layout, setLayout] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const cur = styles.find((s) => s.key === pick);
  const fontName = (k: string) => options.fonts.find((f) => f.value === k)?.label ?? k;

  async function apply(style: string) {
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      const { data } = await api.post<{ theme: ThemeT; doc?: Doc }>(`/studio/projects/${slug}/builder/style/apply/`, {
        style,
        keep_brand: keepBrand,
        apply_layout: layout,
        theme,
        doc,
        target,
        page: pageId,
      });
      onApply(data.theme, data.doc ?? null);
      setDone(style ? "سبک نشست. اگر دوست نداشتی، «برگرداندن» (Ctrl+Z) را بزن یا سبکِ دیگری انتخاب کن." : "لایهٔ سبک برداشته شد.");
    } catch (err) {
      setError(studioError(err));
    } finally {
      setBusy(false);
    }
  }

  if (!styles.length) return null;
  return (
    <section className="nbe-styles" data-testid="styles">
      <h4 className="nbe-h">سبکِ طراحی</h4>
      <p className="nbe-note">یک حس‌وحالِ آماده برای کلِ سایت: رنگ، قلم، گردی، سایه و چیدمانِ بخش‌ها. بعدش هر چیز را خودت هم عوض می‌کنی.</p>
      <div className="nbe-style-grid">
        {styles.map((s) => (
          <button
            key={s.key}
            type="button"
            className={`nbe-style ${pick === s.key ? "pick" : ""} ${theme.style === s.key ? "on" : ""}`}
            data-style={s.key}
            onClick={() => setPick(s.key)}
            title={s.desc}
          >
            <StyleThumb s={s} />
            <b>{s.label}</b>
            <small dir="ltr">{s.en}</small>
          </button>
        ))}
      </div>
      {cur && (
        <div className="nbe-style-detail" data-testid="style-detail">
          <p className="nbe-note">
            <b>{cur.mood}.</b> {cur.desc}
          </p>
          <p className="nbe-note">
            قلمِ تیتر: {fontName(cur.theme.font_head)} · قلمِ متن: {fontName(cur.theme.font_body)}
          </p>
          <label className="nbe-toggle">
            <input type="checkbox" checked={layout} onChange={(e) => setLayout(e.target.checked)} />
            چیدمانِ بخش‌های همین صفحه هم با سبک جور شود
          </label>
          <label className="nbe-toggle">
            <input type="checkbox" checked={keepBrand} onChange={(e) => setKeepBrand(e.target.checked)} />
            رنگِ اصلیِ برندم همان بماند
          </label>
          <div className="nbe-row">
            <button type="button" className="nbe-add" data-testid="apply-style" disabled={busy} onClick={() => void apply(cur.key)}>
              {busy ? "در حالِ اعمال…" : theme.style === cur.key ? "دوباره اعمال کن" : "اعمالِ این سبک"}
            </button>
            {theme.style && (
              <button type="button" className="nbe-link danger" disabled={busy} onClick={() => void apply("")}>
                برداشتنِ سبک
              </button>
            )}
          </div>
        </div>
      )}
      {error && <p className="nbe-warn">{error}</p>}
      {done && <p className="nbe-note">{done}</p>}
      <p className="nbe-note nbe-attrib">
        تعریفِ سبک‌ها (توکن، پالت و جفتِ قلم) با کمک از داده‌های ui-ux-pro-max-skill (مجوز MIT، Next Level Builder) نوشته شده؛ قلم‌ها همه فارسی‌پذیر و آزادند.
      </p>
    </section>
  );
}

/* ─────────── قطعه‌های آماده ─────────── */
type Preview = { key: string; html: string; base_css: string; page_css: string; title: string; src: CompMeta["src"] };

function originLabel(src: CompMeta["src"]): string {
  return src.origin === "adapted" ? `بازنویسی‌شده از ${src.library} · ${src.license}` : "طراحیِ خودمان";
}

export function ComponentsPanel({
  catalog,
  target,
  theme,
  slug,
  onAdd,
  onDragStart,
}: {
  catalog: Catalog;
  target: string;
  theme: ThemeT;
  slug: string;
  onAdd: (type: string) => void;
  onDragStart: (type: string, x: number, y: number) => void;
}) {
  const meta = catalog.components;
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [prev, setPrev] = useState<Preview | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const items = useMemo(() => {
    const word = q.trim();
    const rows = (meta?.items ?? []).filter(
      (c) => c.scope.includes(target) && (!cat || c.cat === cat) && (!word || c.label.includes(word) || c.desc.includes(word) || c.tags.some((t) => t.includes(word))),
    );
    const style = theme.style;
    return style ? [...rows].sort((a, b) => Number(b.styles.includes(style)) - Number(a.styles.includes(style))) : rows;
  }, [meta, q, cat, target, theme.style]);

  useEffect(() => {
    if (!open) {
      setPrev(null);
      return;
    }
    let live = true;
    setErr(null);
    api
      .get<Preview>(`/studio/projects/${slug}/builder/components/${open}/preview/`, { params: theme.style ? { style: theme.style } : {} })
      .then((r) => live && setPrev(r.data))
      .catch((e) => live && setErr(studioError(e)));
    return () => {
      live = false;
    };
  }, [open, slug, theme.style]);

  if (!meta) return <p className="nbe-note">فهرستِ قطعه‌ها نیامد.</p>;
  const cats = meta.categories.filter((c) => (meta.items ?? []).some((i) => i.cat === c.key && i.scope.includes(target)));
  return (
    <div data-testid="components">
      <input className="nbe-input" placeholder="جست‌وجوی قطعه…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="جست‌وجوی قطعه" />
      <div className="nbe-chips" role="tablist">
        <button type="button" className={!cat ? "on" : ""} onClick={() => setCat("")}>
          همه
        </button>
        {cats.map((c) => (
          <button key={c.key} type="button" className={cat === c.key ? "on" : ""} data-cat={c.key} onClick={() => setCat(c.key)}>
            {c.label}
          </button>
        ))}
      </div>
      <div className="nbe-parts">
        {items.map((c) => (
          <div key={c.key} className={`nbe-part ${open === c.key ? "open" : ""}`} data-part={c.key}>
            <button type="button" className="nbe-part-main" onPointerDown={(e) => press(e, (x, y) => onDragStart(c.type, x, y))} onClick={() => onAdd(c.type)} title="روی صفحه بکش یا بزن تا اضافه شود">
              <b>{c.label}</b>
              <small>{c.desc}</small>
            </button>
            <div className="nbe-part-foot">
              {theme.style && c.styles.includes(theme.style) && <em className="nbe-badge ok">جورِ این سبک</em>}
              <span className="nbe-badge" title={c.src.origin === "adapted" ? `${c.src.copyright} — ${c.src.license}` : "بی‌کدِ شخصِ ثالث"}>
                {originLabel(c.src)}
              </span>
              <button type="button" className="nbe-link" onClick={() => setOpen(open === c.key ? null : c.key)}>
                {open === c.key ? "بستن" : "پیش‌نمایش"}
              </button>
            </div>
            {open === c.key && (
              <div className="nbe-part-prev">
                {err && <p className="nbe-warn">{err}</p>}
                {!prev && !err && <p className="nbe-note">در حالِ ساختنِ پیش‌نمایش…</p>}
                {prev && prev.key === c.key && (
                  <>
                    <iframe
                      title={`پیش‌نمایشِ ${c.label}`}
                      sandbox="allow-same-origin"
                      className="nbe-part-frame"
                      srcDoc={`<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>${prev.base_css}\n${prev.page_css}\nbody{margin:0;background:var(--bg)}</style></head><body>${prev.html}</body></html>`}
                    />
                    <div className="nbe-row">
                      <button type="button" className="nbe-add" onClick={() => onAdd(c.type)}>
                        افزودن به صفحه
                      </button>
                      {prev.src.source_url && (
                        <a className="nbe-link" href={prev.src.source_url} target="_blank" rel="noopener noreferrer" dir="ltr">
                          منبع و مجوز ({prev.src.license})
                        </a>
                      )}
                      {prev.src.listing_url && (
                        <a className="nbe-link" href={prev.src.listing_url} target="_blank" rel="noopener noreferrer" dir="ltr">
                          21st.dev
                        </a>
                      )}
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        ))}
        {!items.length && <p className="nbe-note">قطعه‌ای با این جست‌وجو پیدا نشد.</p>}
      </div>
      <p className="nbe-note">قطعه را بکش و روی صفحه بینداز، یا روی آن بزن. متن‌ها نمونه‌اند؛ روی هر نوشته بزن و متنِ خودت را بنویس.</p>
    </div>
  );
}

export { Svg };
