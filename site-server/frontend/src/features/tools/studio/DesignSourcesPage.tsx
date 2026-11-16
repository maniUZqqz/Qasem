import { useCallback, useEffect, useRef, useState } from "react";

import { api, studioError } from "./api";
import { Loading, SectionHead } from "./common";
import "./designsrc.css";

/**
 * «منبع‌های طراحی»: کلِ مخزنِ ui-ux-pro-max-skill (MIT) که روی سرور آینه و وارد شده — سبک‌ها، پالت‌ها، جفتِ قلم‌ها، رهنمودهای UX، الگوهای صفحه، نمودارها،
 * محصولات، قاعده‌های تصمیم، پشته‌ها، آیکون‌ها، حرکت، اسلاید، هویتِ برند، قلم‌های گوگل و مستندها — با جست‌وجو؛ کنارِ هر سبک و قلم معادلِ سایت‌ساز نشان داده می‌شود.
 * تبِ آخر: وضعیتِ کاتالوگِ 21st.dev (خزش، قطعه‌های قابلِ درج، کارِ سرورِ گرافیکی).
 */
type Row = Record<string, unknown>;
type Kind = { key: string; label: string; desc: string; count: number };
type Index = {
  source: { source: string; license: string; copyright: string; commit: string; commit_date: string; retrieved: string; mirror: string };
  kinds: Kind[];
  styles: { total: number; hand: number; generated: number; dataset_rows: number; groups: { label: string; count: number }[] };
  fonts: { bundled: number; pairings: number; latin_mapped: number };
  c21st: { catalog: number; usable: number; previews: number };
  note: string;
};
type Listing = { kind: string; label: string; desc: string; total: number; page: number; size: number; items: Row[]; facets: Record<string, { value: string; count: number }[]> };

const FACET_FA: Record<string, string> = { type: "نوع", status: "وضعیت", rtl: "راست‌به‌چپ", stack: "پشته", category: "دسته", severity: "شدت", file: "فایل", skill: "مهارت", arabic: "عربی/فارسی" };
const FIELD_FA: Record<string, string> = {
  keywords: "کلیدواژه‌ها", best_for: "مناسبِ", avoid: "نباید برای", effects: "افکت‌ها", primary_colors: "رنگ‌های اصلی", secondary_colors: "رنگ‌های دوم", css: "کلیدواژه‌های CSS",
  variables: "متغیرهای طراحی", checklist: "چک‌لیست", accessibility: "دسترس‌پذیری", ai_prompt: "پرامپتِ AI", performance: "کارایی", frameworks: "چارچوب‌ها", era: "دوره", complexity: "پیچیدگی",
  mood: "حال‌وهوا", notes: "یادداشت", description: "توضیح", do: "درست", dont: "نادرست", code_good: "نمونهٔ خوب", code_bad: "نمونهٔ بد", sections: "ترتیبِ بخش‌ها", cta: "دعوت به اقدام",
  color_strategy: "راهبردِ رنگ", conversion: "بهینه‌سازیِ تبدیل", duration: "مدت", easing: "منحنی", trigger: "محرک", gsap: "نمونهٔ GSAP", best: "بهترین نمودار", secondary: "جایگزین‌ها",
  when: "چه زمانی", when_not: "چه زمانی نه", volume: "حجمِ داده", color: "رنگ", a11y_notes: "دسترس‌پذیری", a11y_fallback: "جایگزینِ دسترس‌پذیر", library: "کتابخانه", primary_style: "سبکِ اصلی",
  secondary_styles: "سبک‌های دیگر", landing: "الگوی صفحه", dashboard: "داشبورد", palette: "پالت", pattern: "الگو", style_priority: "اولویتِ سبک", color_mood: "حال‌وهوای رنگ",
  typography_mood: "حال‌وهوای قلم", rules: "قاعده‌ها", anti: "ضدالگوها", reasoning: "استدلال", usage: "کاربرد", import_code: "کدِ وارد کردن", role: "نقش", style: "سبک", guideline: "رهنمود",
  docs_url: "مستند", applies_to: "برای", use_case: "کاربرد", layout_name: "چیدمان", deliverable: "محصولِ هویتی", html: "HTML", classes: "دسته‌بندی", subsets: "زیرمجموعه‌ها",
};
const TITLE: Record<string, string> = {
  styles: "name", colors: "product", fonts: "name", ux: "issue", landing: "name", motion: "category", charts: "data_type", products: "product", reasoning: "category", icons: "name",
  app: "issue", react: "issue", stacks: "guideline", google_fonts: "family", slides: "layout_name", brand: "deliverable", docs: "title",
};
const MAIN: Record<string, string[]> = {
  styles: ["keywords", "best_for", "avoid", "effects"], colors: ["notes"], fonts: ["mood", "best_for", "notes"], ux: ["description", "do", "dont"], landing: ["sections", "cta", "color_strategy", "conversion"],
  motion: ["keywords", "duration", "easing", "do", "dont"], charts: ["best", "when", "when_not", "color"], products: ["primary_style", "landing", "palette", "notes"],
  reasoning: ["pattern", "style_priority", "color_mood", "typography_mood", "anti"], icons: ["keywords", "role", "usage"], app: ["description", "do", "dont"], react: ["description", "do", "dont"],
  stacks: ["description", "do", "dont"], google_fonts: ["classes", "keywords"], slides: ["use_case", "keywords"], brand: ["description", "keywords"], docs: [],
};
const CHIPS: Record<string, string[]> = { styles: ["type", "status", "rtl"], ux: ["category", "severity", "platform"], stacks: ["stack", "category", "severity"], products: ["rtl"], reasoning: ["severity"], react: ["category", "severity"],
  app: ["category", "severity"], icons: ["category", "library"], google_fonts: ["category"], slides: ["file"], brand: ["file"], docs: ["skill"], motion: ["tier"], charts: ["a11y_grade"], fonts: ["category"], landing: [] , colors: []};
const COLOR_KEYS: [string, string][] = [["primary", "اصلی"], ["secondary", "دوم"], ["accent", "تأکید"], ["background", "زمینه"], ["foreground", "متن"], ["card", "کارت"], ["muted", "کم‌رنگ"], ["border", "حاشیه"], ["destructive", "خطا"]];

const fa = (n: number) => n.toLocaleString("fa-IR");
const str = (v: unknown) => (typeof v === "string" ? v : v === undefined || v === null ? "" : String(v));

function Swatches({ row }: { row: Row }) {
  return (
    <div className="ds-swatches" dir="ltr">
      {COLOR_KEYS.map(([k, label]) => {
        const v = str(row[k]);
        return /^#[0-9a-fA-F]{6}$/.test(v) ? (
          <span key={k} className="ds-sw" title={`${label} ${v}`}>
            <i style={{ background: v }} />
            <small>{v}</small>
          </span>
        ) : null;
      })}
    </div>
  );
}

function DocText({ path }: { path: string }) {
  const [text, setText] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api
      .get<{ text: string }>("/studio/design-sources/docs/read/", { params: { path } })
      .then((r) => setText(r.data.text))
      .catch((e) => setErr(studioError(e)));
  }, [path]);
  if (err) return <p className="ds-warn">{err}</p>;
  if (text === null) return <p className="ds-note">در حالِ خواندن…</p>;
  return <pre className="ds-pre" dir="ltr">{text}</pre>;
}

function Card({ kind, row, open, onToggle }: { kind: string; row: Row; open: boolean; onToggle: () => void }) {
  const title = str(row[TITLE[kind]]) || str(row.name) || "—";
  const site = row.site as { key: string; label: string; source: string; primary: string; bg: string; text: string } | null | undefined;
  const fa2 = row.fa as { heading: { label: string; family: string }; body: { label: string; family: string } } | undefined;
  const shown = new Set([TITLE[kind], ...(MAIN[kind] ?? []), ...(CHIPS[kind] ?? [])]);
  const rest = Object.entries(row).filter(([k, v]) => typeof v === "string" && !shown.has(k) && v && !["n", "id", "text", "snippet", "path"].includes(k));
  return (
    <article className="ds-card" data-kind={kind} data-row={str(row.id) || str(row.n)}>
      <header>
        <b className="ds-title" dir="auto">{title}</b>
        {(CHIPS[kind] ?? []).map((c) => (row[c] ? <span key={c} className="ds-chip" data-chip={c} dir="ltr">{str(row[c])}</span> : null))}
        {kind === "google_fonts" && Boolean(row.arabic) && <span className="ds-chip ok">عربی/فارسی‌پذیر</span>}
        {kind === "google_fonts" && Boolean(row.bundled) && <span className="ds-chip ok" data-testid="ds-bundled">در سایت‌ساز</span>}
      </header>
      {kind === "colors" && <Swatches row={row} />}
      {kind === "colors" && Array.isArray(row.used_by) && (row.used_by as string[]).length > 0 && <p className="ds-note">سبک‌هایی که از این پالت ساخته شده‌اند: {(row.used_by as string[]).join("، ")}</p>}
      {kind === "styles" && site && (
        <p className="ds-site" data-testid="ds-site">
          <span className="ds-dot" style={{ background: site.primary, outline: `2px solid ${site.bg}` }} />
          در سایت‌ساز: <b>{site.label}</b> ({site.source === "hand" ? "نوشتهٔ دست" : "ساخته‌شده خودکار"})
        </p>
      )}
      {kind === "fonts" && fa2 && (
        <p className="ds-site" data-testid="ds-fa">
          معادلِ فارسیِ مجوزدار: <b>{fa2.heading.label}</b> (تیتر) + <b>{fa2.body.label}</b> (متن)
        </p>
      )}
      <dl className="ds-fields">
        {(MAIN[kind] ?? []).map((k) => (row[k] ? (
          <div key={k}>
            <dt>{FIELD_FA[k] ?? k}</dt>
            <dd dir="auto">{str(row[k])}</dd>
          </div>
        ) : null))}
      </dl>
      {kind === "docs" && <p className="ds-note" dir="ltr">{str(row.snippet)}</p>}
      {(rest.length > 0 || kind === "docs") && (
        <button type="button" className="ds-more" onClick={onToggle} aria-expanded={open}>
          {open ? "بستن" : kind === "docs" ? "خواندنِ متنِ کامل" : "جزئیاتِ بیشتر"}
        </button>
      )}
      {open && kind === "docs" && <DocText path={str(row.path)} />}
      {open && kind !== "docs" && (
        <dl className="ds-fields ds-rest">
          {rest.map(([k, v]) => (
            <div key={k}>
              <dt>{FIELD_FA[k] ?? k}</dt>
              <dd dir="auto">{String(v)}</dd>
            </div>
          ))}
        </dl>
      )}
    </article>
  );
}

function C21Tab() {
  const [data, setData] = useState<{ crawl: Record<string, unknown>; pipeline: Record<string, unknown> } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api.get("/studio/c21st/pipeline/").then((r) => setData(r.data)).catch((e) => setErr(studioError(e)));
  }, []);
  if (!data) return <Loading error={err} />;
  const c = data.crawl as Record<string, number | boolean | string | null>;
  const p = data.pipeline as Record<string, number | boolean | Record<string, number>>;
  const node = p.node as Record<string, number>;
  return (
    <div className="ds-c21" data-testid="ds-c21">
      <p className="ds-note">
        کاتالوگِ 21st.dev با رعایتِ robots.txt خزیده می‌شود (نقشهٔ سایت، صفحهٔ هر قطعه، کتابخانه‌ها، تصویرِ پیش‌نمایش). فقط قطعه‌هایی که مجوزِ آزاد دارند و کدشان در مخزنِ عمومیِ GitHub هست به «قطعهٔ قابلِ درج» تبدیل
        می‌شوند؛ بقیه فقط برای دیدن‌اند. اگر سرور مسدود شود همین کار را سرورِ گرافیکی با مرورگرِ بی‌سر می‌کند.
      </p>
      <dl className="ds-fields">
        <div><dt>قطعه در کاتالوگ</dt><dd>{fa(Number(c.total ?? 0))}</dd></div>
        <div><dt>با مجوزِ آزاد</dt><dd>{fa(Number(c.usable ?? 0))}</dd></div>
        <div><dt>پیش‌نمایشِ تصویری</dt><dd>{fa(Number(c.previews ?? 0))}</dd></div>
        <div><dt>کتابخانه‌ها</dt><dd>{fa(Number(c.libraries ?? 0))}</dd></div>
        <div><dt>قطعهٔ قابلِ درج</dt><dd data-testid="ds-converted">{fa(Number(p.converted ?? 0))}</dd></div>
        <div><dt>بدونِ کدِ عمومی</dt><dd>{fa(Number(p.no_source ?? 0))}</dd></div>
        <div><dt>مجوزِ مخزن آزاد نبود</dt><dd>{fa(Number(p.license_blocked ?? 0))}</dd></div>
        <div><dt>تبدیلِ ناموفق</dt><dd>{fa(Number(p.failed ?? 0))}</dd></div>
        <div><dt>کارِ خزشِ سرورِ گرافیکی</dt><dd>{fa(Number(node?.pending ?? 0))} در انتظار · {fa(Number(node?.jobs ?? 0))} کلاً</dd></div>
        <div><dt>جعبه‌ابزارِ تبدیل</dt><dd>{p.toolchain ? "نصب است" : "نصب نیست (deploy/c21/install.sh)"}</dd></div>
      </dl>
      <p className="ds-note">قطعه‌ها را از «سایت‌ساز ⇐ ویرایشگرِ دیداری ⇐ افزودن ⇐ قطعه‌های آماده ⇐ کاتالوگِ 21st.dev» ببینید، پیش‌نمایش بگیرید و در صفحه بگذارید.</p>
    </div>
  );
}

export default function DesignSourcesPage() {
  const [index, setIndex] = useState<Index | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState("styles");
  const [q, setQ] = useState("");
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [arabic, setArabic] = useState(false);
  const [bundled, setBundled] = useState(false);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Listing | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    api.get<Index>("/studio/design-sources/").then((r) => setIndex(r.data)).catch((e) => setError(studioError(e)));
  }, []);

  const load = useCallback(() => {
    if (kind === "c21st") return;
    setBusy(true);
    api
      .get<Listing>(`/studio/design-sources/${kind}/`, { params: { q, page, size: 20, ...filters, arabic: arabic ? 1 : undefined, bundled: bundled ? 1 : undefined } })
      .then((r) => {
        setData(r.data);
        setError(null);
      })
      .catch((e) => setError(studioError(e)))
      .finally(() => setBusy(false));
  }, [kind, q, page, filters, arabic, bundled]);

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(load, q ? 250 : 0);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [load, q]);

  if (!index) return <Loading error={error} />;
  const pick = (k: string) => {
    setKind(k);
    setQ("");
    setFilters({});
    setArabic(false);
    setBundled(false);
    setPage(1);
    setOpen(null);
    setData(null);
  };
  const src = index.source;
  return (
    <div className="ds" data-testid="design-sources">
      <SectionHead title="منبع‌های طراحی" hint={`کلِ مخزنِ ui-ux-pro-max-skill · MIT · ${src.copyright}`} />
      <p className="ds-note" data-testid="ds-note">
        {index.note} · نسخه <span dir="ltr">{src.commit.slice(0, 8)}</span> (<span dir="ltr">{src.commit_date.slice(0, 10)}</span>) ·{" "}
        <a href={src.source} target="_blank" rel="noopener noreferrer" dir="ltr">{src.source.replace("https://", "")}</a>
      </p>
      <p className="ds-note">
        {fa(index.styles.total)} سبک در سایت‌ساز ({fa(index.styles.hand)} نوشتهٔ دست + {fa(index.styles.generated)} خودکار از ردیف‌های مخزن، هر کدام با آزمونِ تباین و قلمِ فارسی) · {fa(index.fonts.bundled)} قلمِ فارسی‌پذیرِ آزاد ·
        {" "}{fa(index.fonts.latin_mapped)} قلمِ لاتین به قلمِ فارسی نگاشته شده.
      </p>
      <nav className="ds-tabs" role="tablist" data-testid="ds-tabs">
        {index.kinds.map((k) => (
          <button key={k.key} type="button" role="tab" aria-selected={kind === k.key} className={kind === k.key ? "on" : ""} data-kind={k.key} onClick={() => pick(k.key)}>
            {k.label} <small>{fa(k.count)}</small>
          </button>
        ))}
        <button type="button" role="tab" aria-selected={kind === "c21st"} className={kind === "c21st" ? "on" : ""} data-kind="c21st" onClick={() => pick("c21st")}>
          قطعه‌های 21st.dev <small>{fa(index.c21st.catalog)}</small>
        </button>
      </nav>
      {kind === "c21st" ? (
        <C21Tab />
      ) : (
        <>
          <p className="ds-note">{index.kinds.find((k) => k.key === kind)?.desc}</p>
          <div className="ds-filters">
            <input className="ds-input" placeholder="جست‌وجو (انگلیسی؛ برای سبک‌ها فارسی هم)…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} aria-label="جست‌وجو" data-testid="ds-search" />
            {data && Object.entries(data.facets).map(([col, opts]) => (
              <select key={col} className="ds-input" value={filters[col] ?? ""} aria-label={FACET_FA[col] ?? col}
                      onChange={(e) => { setFilters({ ...filters, [col]: e.target.value }); setPage(1); }}>
                <option value="">{FACET_FA[col] ?? col}: همه</option>
                {opts.map((o) => <option key={o.value} value={o.value}>{o.value} ({fa(o.count)})</option>)}
              </select>
            ))}
            {kind === "google_fonts" && (
              <>
                <label className="ds-check"><input type="checkbox" checked={arabic} onChange={(e) => { setArabic(e.target.checked); setPage(1); }} /> فقط عربی/فارسی‌پذیر</label>
                <label className="ds-check"><input type="checkbox" checked={bundled} onChange={(e) => { setBundled(e.target.checked); setPage(1); }} /> فقط آنچه در سایت‌ساز هست</label>
              </>
            )}
          </div>
          {error && <p className="ds-warn">{error}</p>}
          {data && <p className="ds-note" data-testid="ds-total">{fa(data.total)} ردیف{busy ? " …" : ""}</p>}
          <div className="ds-list">
            {data?.items.map((row, i) => {
              const id = `${kind}:${str(row.id) || str(row.n) || str(row.path) || i}`;
              return <Card key={id} kind={kind} row={row} open={open === id} onToggle={() => setOpen(open === id ? null : id)} />;
            })}
            {data && data.items.length === 0 && <p className="ds-note">چیزی پیدا نشد.</p>}
          </div>
          {data && data.total > data.size && (
            <div className="ds-pager">
              <button type="button" className="ds-btn" disabled={page <= 1} onClick={() => setPage(page - 1)}>قبلی</button>
              <span className="ds-note">صفحهٔ {fa(page)} از {fa(Math.ceil(data.total / data.size))}</span>
              <button type="button" className="ds-btn" disabled={page * data.size >= data.total} onClick={() => setPage(page + 1)}>بعدی</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
