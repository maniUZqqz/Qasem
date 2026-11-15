import { useEffect, useMemo, useRef, useState } from "react";

import { errorMessage } from "../../api/client";
import { Alert, Badge, Button, ErrorBox, Spinner, fa } from "../../components/ui";
import { LookCheck, LookEntry, LookKind, LookSuggestion, LooksIndex, PRODUCT_KINDS, ThemeEntry, looksApi, refusalFa } from "./api";
import { lookMatches } from "./lookSearch";
import "./looks.css";

/**
 * «سبک تصویر»: انتخابِ یکی از ۱۱۶ سبکِ هنری (و یکی از ۲۴ تمِ رنگی) برای تبلیغ، بدونِ نوشتنِ دستورِ انگلیسی.
 * استفاده: استودیوی تصویر، پس‌زمینهٔ هوش مصنوعیِ تامنیل‌ساز، (بعداً) موشن.
 *
 * - جست‌وجو با همان قاعدهٔ سرور (حروفِ عربی/فارسی، نیم‌فاصله، ارقام، نام‌های آشنا مثل «lego» یا «ژیبلی»)
 * - گروه، «مناسبِ چه تبلیغی»، پیشنهاد برای همین فروشگاه (فقط از روی پروفایلِ خودش)
 * - هر کارت نمونهٔ رنگیِ داخلی (بدونِ GPU) یا، وقتی ساخته شده، تصویرِ نمونهٔ واقعی دارد
 * - ``kind`` = نوعِ تبلیغ: روی «عکسِ محصول» و «بهبودِ عکس» فقط سبک‌های نور و صحنه مجازند؛ بقیه خاکستری‌اند و کلیکشان دلیلِ فارسی را نشان می‌دهد
 */

type Props = {
  value: string;
  theme?: string;
  onChange: (look: string, theme: string) => void;
  kind?: LookKind;
  storeId?: string | number;
  /** تمِ رنگیِ ۲۴گانه کنارِ سبک؛ در تامنیل‌ساز رنگ‌بندی جای دیگری انتخاب می‌شود */
  allowTheme?: boolean;
  title?: string;
  hint?: string;
};

const AD_FIT_ALL = "";

export function useLooksIndex(enabled = true) {
  const [index, setIndex] = useState<LooksIndex | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!enabled || index) return;
    let live = true;
    looksApi
      .index()
      .then((d) => live && setIndex(d))
      .catch((e) => live && setError(errorMessage(e)));
    return () => {
      live = false;
    };
  }, [enabled, index]);
  return { index, error };
}

/** آیا این سبک برای این نوعِ تبلیغ مجاز است؟ (برای غیرفعال‌کردنِ دکمهٔ «تولید» و نشان‌دادنِ دلیل) */
export function useLookCheck(look: string, kind: LookKind): { ok: boolean; message: string } {
  const [res, setRes] = useState<LookCheck>({ ok: true });
  useEffect(() => {
    if (!look || !PRODUCT_KINDS.includes(kind)) {
      setRes({ ok: true });
      return;
    }
    let live = true;
    looksApi
      .check(look, kind)
      .then((r) => live && setRes(r))
      .catch(() => live && setRes({ ok: true }));
    return () => {
      live = false;
    };
  }, [look, kind]);
  return { ok: res.ok, message: res.message_fa ?? "" };
}

export function ThemeDots({ palette }: { palette: string[] }) {
  return (
    <span className="lk-dots" aria-hidden="true">
      {palette.slice(0, 6).map((c, i) => (
        <i key={`${c}${i}`} style={{ background: c }} />
      ))}
    </span>
  );
}

/** ۲۴ تمِ رنگی با پالتِ ۶ رنگ؛ ``value`` کلیدِ تم (بدونِ پیشوند) یا خالی */
export function ThemeChips({
  themes,
  value,
  onChange,
  disabled,
}: {
  themes: (Pick<ThemeEntry, "key" | "name_fa" | "palette"> & Partial<ThemeEntry>)[];
  value: string;
  onChange: (key: string) => void;
  disabled?: boolean;
}) {
  return (
    <div className="lk-themes" role="group" aria-label="تمِ رنگی">
      <button type="button" className="lk-theme" aria-pressed={!value} onClick={() => onChange("")} disabled={disabled}>
        <span className="lk-theme-none">بدون تم</span>
      </button>
      {themes.map((t) => (
        <button
          key={t.key}
          type="button"
          className="lk-theme"
          aria-pressed={value === t.key}
          onClick={() => onChange(t.key)}
          disabled={disabled}
          title={[t.description_fa, t.mood].filter(Boolean).join(" — ")}
        >
          <ThemeDots palette={t.palette} />
          <b>{t.name_fa}</b>
        </button>
      ))}
    </div>
  );
}

function Swatch({ look }: { look: LookEntry }) {
  const [broken, setBroken] = useState(false);
  const src = look.sample_url && !broken ? look.sample_url : look.preview_url;
  return <img src={src} alt="" loading="lazy" onError={() => setBroken(true)} />;
}

export default function LookPicker({ value, theme = "", onChange, kind, storeId, allowTheme = false, title = "سبک تصویر", hint }: Props) {
  const [open, setOpen] = useState(false);
  const { index, error } = useLooksIndex(open || !!value || allowTheme);
  const [q, setQ] = useState("");
  const [group, setGroup] = useState("");
  const [adFit, setAdFit] = useState(AD_FIT_ALL);
  const [tab, setTab] = useState<"looks" | "themes">("looks");
  const [suggest, setSuggest] = useState<LookSuggestion | null>(null);
  const [notice, setNotice] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  const product = !!kind && PRODUCT_KINDS.includes(kind);

  const selected = useMemo(() => index?.styles.find((s) => s.key === value) ?? null, [index, value]);
  const selectedTheme = useMemo(() => index?.themes.find((t) => t.key === theme) ?? null, [index, theme]);

  useEffect(() => {
    if (!open) return;
    setNotice("");
    window.setTimeout(() => searchRef.current?.focus(), 30);
  }, [open]);

  useEffect(() => {
    if (!open || storeId === undefined || suggest) return;
    looksApi
      .suggest(storeId)
      .then(setSuggest)
      .catch(() => setSuggest(null));
  }, [open, storeId, suggest]);

  const rows = useMemo(() => {
    if (!index) return [];
    const found = index.styles.filter((s) => (!group || s.group === group) && (!adFit || s.ad_fit.includes(adFit)) && (!q.trim() || lookMatches(s, q)));
    // روی «عکسِ محصول» سبک‌های مجاز اول می‌آیند (مرتب‌سازیِ پایدار: ترتیبِ گروه‌ها می‌ماند)
    return product ? [...found].sort((a, b) => Number(!a.product_safe) - Number(!b.product_safe)) : found;
  }, [index, q, group, adFit, product]);

  const safeCount = useMemo(() => (index ? index.styles.filter((s) => s.product_safe).length : 0), [index]);

  function pick(s: LookEntry) {
    const why = refusalFa(s, kind);
    if (why) {
      setNotice(why);
      return;
    }
    setNotice("");
    onChange(s.key, theme);
    setOpen(false);
  }

  function onKey(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      e.stopPropagation();
      setOpen(false);
    }
  }

  return (
    <div className="lk-root">
      <div className="lk-trigger">
        {selected ? (
          <>
            <img src={selected.sample_url ?? selected.preview_url} alt="" />
            <span className="lk-trigger-body">
              <b>{selected.name_fa}</b>
              <span className="lk-sub">
                {selected.group_fa} · {selected.realism_fa}
                {selectedTheme ? ` · تم: ${selectedTheme.name_fa}` : ""}
              </span>
            </span>
          </>
        ) : (
          <span className="lk-trigger-body">
            <b>{value ? "…" : "بدونِ سبک (خودکار)"}</b>
            <span className="lk-sub">{hint ?? "یکی از ۱۱۶ سبکِ آماده را بردارید؛ لازم نیست دستورِ انگلیسی بنویسید."}</span>
          </span>
        )}
        <span className="lk-trigger-actions">
          <Button size="sm" variant="secondary" type="button" onClick={() => setOpen(true)}>
            {value ? "تغییرِ سبک" : "انتخابِ سبک"}
          </Button>
          {(value || theme) && (
            <Button size="sm" variant="ghost" type="button" onClick={() => onChange("", "")} aria-label="برداشتنِ سبک">
              ×
            </Button>
          )}
        </span>
      </div>

      {open && (
        <div className="lk-modal" role="dialog" aria-modal="true" aria-label={title} onKeyDown={onKey} onMouseDown={(e) => e.target === e.currentTarget && setOpen(false)}>
          <div className="lk-box">
            <div className="lk-head">
              <h3>{title}</h3>
              <span className="lk-count">{index ? `${fa(rows.length)} از ${fa(index.total)} سبک` : ""}</span>
              <span style={{ flex: 1 }} />
              <Button size="sm" variant="ghost" type="button" onClick={() => setOpen(false)}>
                بستن
              </Button>
            </div>

            <div className="lk-tools">
              {allowTheme && (
                <div className="lk-tabs" role="tablist">
                  <button type="button" role="tab" className="lk-tab" aria-selected={tab === "looks"} onClick={() => setTab("looks")}>
                    سبک‌ها
                  </button>
                  <button type="button" role="tab" className="lk-tab" aria-selected={tab === "themes"} onClick={() => setTab("themes")}>
                    تمِ رنگی{selectedTheme ? ` (${selectedTheme.name_fa})` : ""}
                  </button>
                </div>
              )}
              {tab === "looks" && (
                <>
                  <input
                    ref={searchRef}
                    className="u-input"
                    value={q}
                    onChange={(e) => setQ(e.target.value)}
                    placeholder="جست‌وجو: نامِ فارسی یا انگلیسی؛ مثلاً «پیکسل»، «آبرنگ»، «lego»، «ژیبلی»"
                    aria-label="جست‌وجوی سبک"
                    inputMode="search"
                  />
                  <div className="lk-chips" role="group" aria-label="گروه">
                    <button type="button" className="lk-chip" aria-pressed={!group} onClick={() => setGroup("")}>
                      همه
                    </button>
                    {(index?.groups ?? []).map((g) => (
                      <button key={g.key} type="button" className="lk-chip" aria-pressed={group === g.key} onClick={() => setGroup(group === g.key ? "" : g.key)}>
                        {g.fa} <em>{fa(g.count)}</em>
                      </button>
                    ))}
                  </div>
                  <div className="lk-chips" role="group" aria-label="مناسبِ">
                    <span className="lk-lab">مناسبِ</span>
                    <button type="button" className="lk-chip" aria-pressed={!adFit} onClick={() => setAdFit(AD_FIT_ALL)}>
                      هر تبلیغی
                    </button>
                    {(index?.ad_fits ?? []).map((a) => (
                      <button key={a.key} type="button" className="lk-chip" aria-pressed={adFit === a.key} onClick={() => setAdFit(adFit === a.key ? AD_FIT_ALL : a.key)}>
                        {a.fa} <em>{fa(a.count)}</em>
                      </button>
                    ))}
                  </div>
                </>
              )}
              {notice && <Alert tone="warn">{notice}</Alert>}
            </div>

            <div className="lk-body">
              <ErrorBox message={error} />
              {product && tab === "looks" && (
                <p className="lk-note">
                  «عکسِ محصول» و «بهبودِ عکس» روی خودِ عکسِ محصول کار می‌کنند و محصول نباید عوض شود؛ برای همین فقط {fa(safeCount)} سبکِ نور و صحنه مجازند.
                  بقیه (کارتونی، عروسکی، پیکسلی…) را برای «پوستر تبلیغاتی» بردارید.
                </p>
              )}
              {!index && !error && <Spinner size={20} />}

              {tab === "looks" && index && suggest && suggest.looks.length > 0 && !q && !group && !adFit && (
                <section className="lk-suggest" aria-label="پیشنهاد برای فروشگاهِ شما">
                  <h4>
                    پیشنهاد برای فروشگاهِ شما{" "}
                    <small>{suggest.matched ? suggest.business_fa.join(" · ") : "عمومی"}</small>
                  </h4>
                  <p className="lk-note">{suggest.basis_fa}؛ فقط «چرا می‌خورد»، بدونِ آمار و ادعا.</p>
                  <div className="lk-sug-row">
                    {suggest.looks.map((s) => {
                      const row = index.styles.find((x) => x.key === s.look);
                      if (!row) return null;
                      const blocked = !!refusalFa(row, kind);
                      return (
                        <button key={s.look} type="button" className="lk-sug" data-usable={!blocked} onClick={() => pick(row)} title={s.reason_fa}>
                          <Swatch look={row} />
                          <b>{row.name_fa}</b>
                          <span>{s.reason_fa}</span>
                        </button>
                      );
                    })}
                  </div>
                </section>
              )}

              {tab === "looks" && index && (
                <div className="lk-grid">
                  {rows.length === 0 && <p className="lk-note">سبکی با این جست‌وجو پیدا نشد؛ واژهٔ کوتاه‌تری بنویسید یا فیلترها را بردارید.</p>}
                  {rows.map((s) => {
                    const blocked = !!refusalFa(s, kind);
                    return (
                      <button
                        key={s.key}
                        type="button"
                        className="lk-card"
                        aria-pressed={value === s.key}
                        data-usable={!blocked}
                        onClick={() => pick(s)}
                        title={blocked ? refusalFa(s, kind) : s.description_fa}
                      >
                        <Swatch look={s} />
                        <b>{s.name_fa}</b>
                        <span className="lk-sub">{s.realism_fa}</span>
                        {s.known_as && <span className="lk-known" title="فقط برای پیدا کردن؛ خروجی با هیچ استودیو یا برندی یکی نیست">نامِ آشنا: {s.known_as}</span>}
                        <span className="lk-badges">
                          {s.sample_url && <Badge tone="ok">نمونهٔ واقعی</Badge>}
                          {s.product_safe ? <Badge tone="info">مناسبِ عکسِ محصول</Badge> : <Badge>پوستر و پست</Badge>}
                          {blocked && <Badge tone="warn">برای این نوع مجاز نیست</Badge>}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}

              {tab === "themes" && index && (
                <>
                  <p className="lk-note">تمِ رنگی پالتِ ۶ رنگ، نور و حال‌وهوا را به دستورِ سبک اضافه می‌کند. در تامنیل‌ساز همین تم رنگِ متن‌ها را هم می‌دهد.</p>
                  <ThemeChips themes={index.themes} value={theme} onChange={(k) => onChange(value, k)} />
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
