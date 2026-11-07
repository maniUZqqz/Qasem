import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { errorMessage } from "../../../../api/client";
import { Alert, Badge, Button, Card, EmptyState, SectionTitle, Select, Spinner, TextArea, fa } from "../../../../components/ui";
import type { Asset, Edit } from "../api";
import { DPlan, DStep, DVariant, Design, DesignerInfo, designerApi } from "./api";
import BrandForm from "./BrandForm";
import { Brand, emptyBrand } from "./brandApi";
import { COPY_FIELDS, CRITERIA_FA, EXAMPLES } from "./labels";
import StepEditor from "./StepEditor";
import "./designer.css";

type Props = {
  storeId: string;
  asset: Asset | null;
  nodeOn: boolean;
  /** بعد از «اعمال»: نسخهٔ ساخته‌شده را به صفحه بده؛ openManual = پروژه در حالتِ دستی باز شود */
  onApplied: (edit: Edit, openManual: boolean) => void;
  /** کتابخانهٔ عکس‌ها (برای انتخابِ عکسِ لوگو در «تغییرِ سبکِ برند») */
  assets?: Asset[];
  /** بازکردنِ «تنظیماتِ ادیتور» (پیش‌فرضِ هوش مصنوعی و سبکِ برند) */
  onOpenSettings?: (tab: "ai" | "brand") => void;
};

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const scoreTone = (s: number) => (s >= 85 ? "ok" : s >= 70 ? "info" : "warn");

function AiBanner({ info }: { info: DesignerInfo | null }) {
  if (!info) return null;
  const first = info.ai.first === "metis" ? "متیس" : "لوکال (کامپیوترِ خودتان)";
  return (
    <div data-testid="designer-ai-banner">
      <Alert tone="info" title="هوش مصنوعی، اگر جواب بدهد، طراحی را هوشمندتر می‌کند">
        اول {first} صدا زده می‌شود{info.ai.node_online ? " (سرورِ پردازش روشن است)" : " (سرورِ پردازش الان خاموش است)"}، اگر جواب نداد دومی. اگر هیچ‌کدام جواب ندادند،
        طراحی <b>باز هم انجام می‌شود</b>: الگوهای آماده، رنگ‌های هماهنگ با محصول، جاگیریِ بی‌سرریزِ متن و اصلاحِ خودکارِ خوانایی کار می‌کنند؛
        فقط «انتخابِ هوشمندِ الگو و نوشتنِ متن» و «نقدِ طرح» به هوش مصنوعی نیاز دارند و بالای نتیجه می‌نویسیم کدام‌ها بدونِ آن بودند.
      </Alert>
    </div>
  );
}

function AiUsed({ ai }: { ai: Design["ai"] }) {
  if (!ai || !ai.planner) return null;
  const p = ai.planner;
  const c = ai.critic;
  return (
    <ul className="dz-ai" data-testid="designer-ai-used">
      <li className={p.used ? "ok" : "no"}>
        <b>برنامه‌ریزِ هوشمند:</b> {p.used ? `${p.label ?? "هوش مصنوعی"} — ${p.notes || "الگو و متن را پیشنهاد داد"}` : `بدونِ هوش مصنوعی (${p.reason || "در دسترس نبود"}) — الگو و متن از دستورِ شما و قاعده‌های آماده ساخته شد`}
      </li>
      <li className={c?.used ? "ok" : "no"}>
        <b>نقدِ طرح:</b> {c?.used ? `${c.label ?? "هوش مصنوعی"} — ${fa(c.rounds)} دورِ نقد` : `انجام نشد (${c?.reason || "در دسترس نبود"}) — بررسیِ خودکارِ کنتراست و حاشیه انجام شد`}
      </li>
    </ul>
  );
}

const AI_CALLS: Record<string, string> = { fast: "fast", normal: "normal", best: "best" };

export default function DesignerPanel({ storeId, asset, nodeOn, onApplied, assets = [], onOpenSettings }: Props) {
  const [info, setInfo] = useState<DesignerInfo | null>(null);
  const [infoErr, setInfoErr] = useState<string | null>(null);
  const [prompt, setPrompt] = useState("");
  const [recipe, setRecipe] = useState("");
  const [fmt, setFmt] = useState("");
  const [mood, setMood] = useState("auto");
  const [quality, setQuality] = useState("normal");
  const [copy, setCopy] = useState<Record<string, string>>({});
  const [copyOpen, setCopyOpen] = useState(false);
  const [useAi, setUseAi] = useState(false);
  const [useBrand, setUseBrand] = useState(false);
  const [brandOpen, setBrandOpen] = useState(false);
  const [brand, setBrand] = useState<Brand>(emptyBrand());
  const [analysis, setAnalysis] = useState<Awaited<ReturnType<typeof designerApi.analyze>> | null>(null);
  const [design, setDesign] = useState<Design | null>(null);
  const [past, setPast] = useState<Design[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [draft, setDraft] = useState<DPlan | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState<"" | "start" | "rerender" | "apply">("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  /** شمارندهٔ «ساختِ دوباره»؛ نشانیِ پیش‌نمایش ثابت می‌ماند و مرورگر باید عکسِ تازه را بگیرد */
  const [rev, setRev] = useState(0);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    designerApi
      .info(storeId)
      .then((i) => {
        setInfo(i);
        // تیکِ «کمکِ هوش مصنوعی» از «پیش‌فرضِ فروشگاه» شروع می‌شود؛ سبکِ برند اگر ذخیره شده باشد پیش‌فرض روشن است
        setUseAi(i.settings.ai_assist);
        setUseBrand(i.settings.brand_set);
        setBrand(i.settings.brand);
      })
      .catch((e) => setInfoErr(errorMessage(e)));
  }, [storeId]);

  // عکس عوض شد ⇒ تحلیلِ فوری و طراحی‌های قبلیِ همان عکس
  useEffect(() => {
    setAnalysis(null);
    setDesign(null);
    setSel(null);
    setDraft(null);
    setError(null);
    setNotice(null);
    if (!asset) return;
    let alive = true;
    designerApi.analyze(storeId, asset.id, "").then((a) => alive && setAnalysis(a)).catch(() => undefined);
    designerApi.list(storeId, asset.id).then((l) => alive && setPast(l.filter((d) => d.state === "READY"))).catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [storeId, asset?.id]);

  const loadVariant = useCallback((d: Design, idx: number) => {
    setSel(idx);
    const p = d.variants[idx]?.plan;
    setDraft(p ? clone(p) : null);
    setDirty(false);
  }, []);

  // پیگیریِ طراحیِ در حالِ انجام
  useEffect(() => {
    if (!design || !design.active) return;
    timer.current = window.setInterval(async () => {
      try {
        const d = await designerApi.get(storeId, design.id);
        setDesign(d);
        if (!d.active) {
          if (d.state === "READY") {
            const best = Math.max(0, d.variants.findIndex((v) => v.best));
            loadVariant(d, best);
          } else if (d.state === "FAILED") setError(d.error || "طراحی انجام نشد.");
        }
      } catch {
        /* شبکه: دورِ بعد */
      }
    }, 2200);
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [design?.id, design?.active, storeId, loadVariant]);

  const toolByKey = useMemo(() => Object.fromEntries((info?.tools ?? []).map((t) => [t.key, t])), [info]);
  const usedFields = useMemo(() => new Set(recipe ? info?.recipes.find((r) => r.key === recipe)?.fields ?? [] : COPY_FIELDS.map((f) => f.key)), [recipe, info]);

  async function start() {
    if (!asset) return;
    setError(null);
    setNotice(null);
    setBusy("start");
    try {
      const d = await designerApi.create(storeId, {
        asset: asset.id, prompt: prompt.trim(), recipe, format: fmt, mood, quality, copy: Object.fromEntries(Object.entries(copy).filter(([, v]) => v.trim())),
        variants: 3, use_ai: useAi, use_brand: useBrand, ...(useBrand && brandOpen ? { brand } : {}),
      });
      setDesign(d);
      setSel(null);
      setDraft(null);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy("");
    }
  }

  async function rerender() {
    if (!design || sel === null || !draft) return;
    setBusy("rerender");
    setError(null);
    try {
      const nv = await designerApi.rerender(storeId, design.id, sel, draft);
      const variants = design.variants.map((v, i) => (i === sel ? nv : v));
      const nd = { ...design, variants };
      setDesign(nd);
      setRev((r) => r + 1);
      setDraft(nv.plan ? clone(nv.plan) : draft);
      setDirty(false);
      setNotice("دوباره ساخته شد (بدونِ هوش مصنوعی، فقط با مرحله‌های شما).");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy("");
    }
  }

  async function apply(openManual: boolean) {
    if (!design || sel === null) return;
    if (dirty && !window.confirm("تغییرهای مرحله‌ها هنوز اعمال نشده؛ اول «ساختِ دوباره» را بزنید. همین‌طور ادامه بدهم (بی تغییرها)؟")) return;
    setBusy("apply");
    setError(null);
    try {
      const r = await designerApi.apply(storeId, design.id, sel);
      setDesign({ ...design, chosen: r.design.chosen, project: r.design.project, edit: r.design.edit });
      setNotice(openManual ? "طرح ذخیره شد؛ در حالتِ دستی باز می‌شود…" : "طرح ذخیره شد؛ نسخهٔ ساخته‌شده در «کارها» و «نسخه‌ها» است. در هر زمان می‌توانید در حالتِ دستی بازش کنید.");
      onApplied(r.edit, openManual);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy("");
    }
  }

  const variant: DVariant | null = design && sel !== null ? design.variants[sel] ?? null : null;
  const editStep = (i: number, s: DStep) => {
    if (!draft) return;
    const steps = draft.steps.map((x, k) => (k === i ? s : x));
    setDraft({ ...draft, steps });
    setDirty(true);
  };

  if (!asset) {
    return (
      <Card className="mt-2">
        <div data-testid="designer-panel">
          <EmptyState icon="image" title="یک عکس انتخاب کنید" description="از کتابخانهٔ بالا یک عکسِ محصول را بزنید تا طراحِ خودکار رویش کار کند." />
        </div>
      </Card>
    );
  }

  return (
    <Card className="mt-2">
      <div data-testid="designer-panel" className="dz-root">
        <SectionTitle>طراحِ خودکار — بنویسید، طراحی می‌کند</SectionTitle>
        <p className="mb-3 text-sm" style={{ color: "var(--text-2)" }}>
          دستورتان را بنویسید (یا یک الگو بزنید). برنامه عکس را می‌سنجد، چند پیشنهادِ طراحی با متنِ فارسی، رنگ‌های هماهنگ و چیدمانِ تمیز می‌سازد و هرکدام را برای خوانایی و حاشیه می‌سنجد.
          نتیجه «لایه» است؛ بعدش در حالتِ دستی تک‌تک قابل‌ویرایش است.
        </p>
        <AiBanner info={info} />
        {infoErr && <div className="mt-2"><Alert tone="bad">{infoErr}</Alert></div>}

        <div className="dz-asset" data-testid="designer-asset">
          <img src={asset.thumb} alt="" />
          <div className="min-w-0">
            <b className="truncate">{asset.title}</b>
            {analysis ? (
              <>
                <p className="dz-muted">{analysis.description}</p>
                <span className="dz-chips" aria-label="رنگ‌های اصلیِ محصول">
                  {analysis.palette.slice(0, 5).map((c) => (
                    <i key={c.hex} className="dz-sw" style={{ background: c.hex }} title={`${c.name} — ${fa(Math.round(c.share * 100))}٪`} />
                  ))}
                </span>
              </>
            ) : (
              <p className="dz-muted"><Spinner size={13} /> در حالِ سنجشِ عکس…</p>
            )}
          </div>
        </div>

        <label className="dz-label" htmlFor="dz-prompt">چه می‌خواهید؟</label>
        <TextArea
          id="dz-prompt" rows={3} value={prompt} maxLength={600} onChange={(e) => setPrompt(e.target.value)} data-testid="designer-prompt"
          placeholder="مثلاً: تبلیغِ کفش ورزشی با تخفیف ۳۰ درصد، رنگی و پرانرژی"
        />
        <div className="dz-chips mt-2">
          {EXAMPLES.map((x) => (
            <button key={x} type="button" className="example-chip" onClick={() => setPrompt(x)}>{x}</button>
          ))}
        </div>

        <div className="dz-label mt-3">الگو</div>
        <div className="dz-recipes" role="radiogroup" aria-label="الگوی طراحی" data-testid="designer-recipes">
          <button type="button" role="radio" aria-checked={recipe === ""} className={`dz-recipe ${recipe === "" ? "is-on" : ""}`} onClick={() => setRecipe("")} data-recipe="">
            <b>خودکار</b>
            <span>از روی دستور و عکس انتخاب می‌شود</span>
          </button>
          {(info?.recipes ?? []).map((r) => (
            <button key={r.key} type="button" role="radio" aria-checked={recipe === r.key} className={`dz-recipe ${recipe === r.key ? "is-on" : ""}`} onClick={() => { setRecipe(r.key); if (!fmt) setFmt(""); }} data-recipe={r.key} title={r.help}>
              <b>{r.title}</b>
              <span>{r.help}</span>
            </button>
          ))}
        </div>

        <div className="dz-row mt-3">
          <label className="dz-field">
            <span>قاب</span>
            <Select value={fmt} onChange={(e) => setFmt(e.target.value)} data-testid="designer-format">
              <option value="">طبقِ الگو</option>
              {(info?.formats ?? []).map((f) => <option key={f.key} value={f.key}>{f.title}</option>)}
            </Select>
          </label>
          <label className="dz-field">
            <span>حال‌وهوا</span>
            <Select value={mood} onChange={(e) => setMood(e.target.value)} data-testid="designer-mood">
              {(info?.moods ?? [{ key: "auto", title: "خودکار" }]).map((m) => <option key={m.key} value={m.key}>{m.title}</option>)}
            </Select>
          </label>
          <label className="dz-field">
            <span>دقت</span>
            <Select value={quality} onChange={(e) => setQuality(e.target.value)} data-testid="designer-quality">
              {(info?.quality ?? []).map((q) => <option key={q.key} value={q.key}>{q.title} — {q.help}</option>)}
            </Select>
          </label>
        </div>

        <button type="button" className="dz-link mt-2" onClick={() => setCopyOpen((o) => !o)} aria-expanded={copyOpen} data-testid="designer-copy-toggle">
          {copyOpen ? "بستنِ متن‌ها" : "متن‌ها را خودم می‌نویسم (اختیاری)"}
        </button>
        {copyOpen && (
          <div className="dz-copy" data-testid="designer-copy">
            {COPY_FIELDS.filter((f) => usedFields.has(f.key)).map((f) => (
              <label key={f.key} className="dz-field">
                <span>{f.label}</span>
                <input className="u-input" value={copy[f.key] ?? ""} maxLength={120} placeholder={f.ph} onChange={(e) => setCopy({ ...copy, [f.key]: e.target.value })} />
              </label>
            ))}
            <p className="dz-muted wide">خالی بگذارید تا از دستور یا هوش مصنوعی گرفته شود. متنی که خودتان بنویسید هرگز عوض نمی‌شود. قیمت و ارقام به فارسی و با جداکنندهٔ هزارگان می‌آید.</p>
          </div>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button onClick={() => void start()} disabled={busy !== "" || !!design?.active || (!prompt.trim() && !recipe)} data-testid="designer-run">
            {busy === "start" ? <Spinner size={16} /> : "✨ طراحی کن"}
          </Button>
          <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
            <input type="checkbox" checked={useAi} onChange={(e) => setUseAi(e.target.checked)} data-testid="designer-use-ai" />
            از هوش مصنوعی هم کمک بگیر
          </label>
          <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
            <input type="checkbox" checked={useBrand} onChange={(e) => setUseBrand(e.target.checked)} data-testid="designer-use-brand" />
            سبکِ برند را اعمال کن
          </label>
          {!prompt.trim() && !recipe && <span className="text-sm" style={{ color: "var(--warn)" }}>دستور بنویسید یا یک الگو را بزنید.</span>}
        </div>
        <p className="dz-muted mt-2" data-testid="designer-ai-cost">
          {useAi
            ? `هوش مصنوعی روشن است: در دقتِ «${info?.quality.find((q) => q.key === quality)?.title ?? quality}» حداکثر ${fa(info?.settings.ai_cost[(AI_CALLS[quality] ?? "normal") as "fast" | "normal" | "best"] ?? 4)} فراخوانیِ بینا برای این طراحی (۱ برنامه‌ریز${quality === "fast" ? "" : " + نقدِ سه پیشنهاد" + (quality === "best" ? " در دو دور" : "")}).`
            : "هوش مصنوعی خاموش است: هیچ فراخوانی‌ای زده نمی‌شود و طراحی فوری و بی‌هزینه با قاعده‌های آماده انجام می‌شود."}{" "}
          {onOpenSettings && <button type="button" className="dz-link" onClick={() => onOpenSettings("ai")} data-testid="designer-open-settings">پیش‌فرضِ فروشگاه را عوض کنید</button>}
        </p>
        {useBrand && (
          <div className="mt-1" data-testid="designer-brand">
            {!info?.settings.brand_set && !brandOpen && (
              <p className="dz-muted">سبکِ برندی ذخیره نشده است. {onOpenSettings && <button type="button" className="dz-link" onClick={() => onOpenSettings("brand")}>الان تنظیمش کنید</button>}</p>
            )}
            <button type="button" className="dz-link" onClick={() => setBrandOpen((v) => !v)} data-testid="designer-brand-override">
              {brandOpen ? "▾ برگشت به سبکِ ذخیره‌شده" : "▸ تغییرِ سبکِ برند فقط برای این طراحی"}
            </button>
            {brandOpen && info && <BrandForm value={brand} onChange={setBrand} fonts={info.fonts} assets={assets} hasStoreLogo={info.has_logo} positions={info.settings.positions} tid="designer-brand" />}
          </div>
        )}
        {past.length > 0 && !design && (
          <div className="mt-3" data-testid="designer-past">
            <div className="dz-label">طراحی‌های قبلیِ این عکس</div>
            <div className="dz-chips">
              {past.slice(0, 6).map((d) => (
                <button key={d.id} type="button" className="example-chip" onClick={async () => { const full = await designerApi.get(storeId, d.id); setDesign(full); loadVariant(full, Math.max(0, full.variants.findIndex((v) => v.best))); }}>
                  {(d.prompt || "طراحی").slice(0, 28)} — {fa(d.variants.length)} پیشنهاد
                </button>
              ))}
            </div>
          </div>
        )}

        {error && <div className="mt-3"><Alert tone="bad">{error}</Alert></div>}
        {notice && <div className="mt-3"><Alert tone="ok">{notice}</Alert></div>}

        {design?.active && (
          <div className="dz-progress mt-4" data-testid="designer-progress" role="status" aria-live="polite">
            <div className="flex items-center gap-2 text-sm" style={{ color: "var(--text)" }}><Spinner size={16} /> {design.message || "در حالِ طراحی…"}</div>
            <div className="dz-bar"><i style={{ width: `${Math.round(design.progress * 100)}%` }} /></div>
            <ol className="dz-log">
              {design.log.slice(-6).map((l, i) => <li key={`${l.t}${i}`}>{l.text}</li>)}
            </ol>
          </div>
        )}

        {design && design.state === "READY" && (
          <div className="mt-5" data-testid="designer-result">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <b style={{ color: "var(--text)" }}>{fa(design.variants.length)} پیشنهاد</b>
              <span className="dz-muted">{design.message}</span>
              <span className="ws-spacer" />
              <Button size="sm" variant="ghost" onClick={() => { setDesign(null); setSel(null); setDraft(null); }}>طراحیِ تازه</Button>
            </div>
            <AiUsed ai={design.ai} />
            <div className="dz-variants" role="listbox" aria-label="پیشنهادهای طراحی">
              {design.variants.map((v, i) => (
                <button key={v.id} type="button" role="option" aria-selected={sel === i} className={`dz-variant ${sel === i ? "is-on" : ""}`} onClick={() => loadVariant(design, i)} data-testid={`designer-variant-${i}`}>
                  {v.preview ? <img src={`${v.preview}?r=${rev}`} alt={v.title} style={{ aspectRatio: `${v.canvas[0]} / ${v.canvas[1]}` }} loading="lazy" /> : <span className="dz-noimg" />}
                  <span className="dz-variant-meta">
                    <b>{v.title}</b>
                    <span className="dz-chips">
                      {v.best && <Badge tone="ok">پیشنهادِ برتر</Badge>}
                      <Badge tone={scoreTone(v.score)}>امتیاز {fa(Math.round(v.score))}</Badge>
                      {v.qa.fixes.length > 0 && <Badge tone="info">{fa(v.qa.fixes.length)} اصلاحِ خودکار</Badge>}
                      {v.edited && <Badge tone="neutral">ویرایش‌شده</Badge>}
                    </span>
                  </span>
                </button>
              ))}
            </div>

            {variant && draft && (
              <div className="dz-detail" data-testid="designer-detail">
                <div className="dz-checks">
                  <Badge tone={variant.qa.metrics.min_contrast === null || variant.qa.metrics.min_contrast >= 4.5 ? "ok" : variant.qa.metrics.min_contrast >= 3 ? "info" : "warn"}>
                    کنتراستِ متن {variant.qa.metrics.min_contrast === null ? "—" : `${fa(Math.round(variant.qa.metrics.min_contrast * 10) / 10)} از ۲۱`}
                  </Badge>
                  <Badge tone={variant.qa.issues.length === 0 ? "ok" : "warn"}>{variant.qa.issues.length === 0 ? "حاشیه و خوانایی سالم" : `${fa(variant.qa.issues.length)} نکتهٔ باقی‌مانده`}</Badge>
                  <Badge tone="neutral">{fa(variant.canvas[0])}×{fa(variant.canvas[1])}</Badge>
                  {variant.ai_mean !== null && <Badge tone="info">نمرهٔ هوش مصنوعی {fa(variant.ai_mean)} از ۱۰</Badge>}
                </div>
                {variant.qa.fixes.length > 0 && (
                  <div className="dz-box">
                    <b>خودکار اصلاح کردیم</b>
                    <ul>{variant.qa.fixes.map((f, i) => <li key={i}>{f}</li>)}</ul>
                  </div>
                )}
                {variant.qa.issues.length > 0 && (
                  <div className="dz-box warn">
                    <b>هنوز بد نیست ولی بهتر می‌شود</b>
                    <ul>{variant.qa.issues.map((f, i) => <li key={i}>{f}</li>)}</ul>
                  </div>
                )}
                {variant.notes.length > 0 && (
                  <div className="dz-box">
                    <ul>{variant.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
                  </div>
                )}
                {(variant.needs.node.length > 0 || variant.needs.manual.length > 0) && (
                  <Alert tone="warn" title="بخشی از کار فقط با ابزارِ دقیق‌تر ممکن است">
                    {variant.needs.node.length > 0 && <>جداکردنِ دقیقِ محصول با «سرورِ پردازش» (الان {nodeOn ? "روشن است؛ در حالتِ دستی «حذف پس‌زمینه» را بزنید" : "خاموش است"}) بهتر می‌شود. </>}
                    {variant.needs.manual.length > 0 && <>مرحله‌های «دستی» (مثلِ پرکردنِ هوشمند) را در حالتِ دستی اجرا کنید.</>}
                  </Alert>
                )}
                {variant.rounds.length > 0 && (
                  <details className="dz-box" data-testid="designer-rounds">
                    <summary><b>نقدِ هوش مصنوعی ({fa(variant.rounds.length)} دور)</b></summary>
                    {variant.rounds.map((r, i) => (
                      <div key={i} className="dz-round">
                        <p>{r.summary || "—"}</p>
                        <span className="dz-chips">
                          {Object.entries(r.scores).map(([k, v]) => <Badge key={k} tone={v >= 8 ? "ok" : v >= 6 ? "info" : "warn"}>{CRITERIA_FA[k] ?? k} {fa(v)}</Badge>)}
                        </span>
                        {r.issues.length > 0 && <ul>{r.issues.map((x, k) => <li key={k}>{x}</li>)}</ul>}
                        {r.applied.length > 0 && <p className="dz-muted">{r.accepted ? "اعمال شد: " : "امتحان شد ولی نپذیرفتیم (وارسیِ قطعی بدتر می‌شد): "}{r.applied.join("، ")}</p>}
                      </div>
                    ))}
                  </details>
                )}

                <div className="dz-label mt-3">مرحله‌ها — هرکدام را خاموش یا تنظیم کنید، بعد «ساختِ دوباره»</div>
                <ol className="dz-steps" data-testid="designer-steps">
                  {draft.steps.map((s, i) => (
                    <StepEditor key={s.id} step={s} tool={toolByKey[s.tool]} slots={info?.slots ?? []} fonts={info?.fonts ?? []} report={variant.report?.[s.id]} onChange={(ns) => editStep(i, ns)} />
                  ))}
                </ol>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button variant="secondary" onClick={() => void rerender()} disabled={busy !== "" || !dirty} data-testid="designer-rerender">
                    {busy === "rerender" ? <Spinner size={16} /> : "ساختِ دوباره با تغییرهای من"}
                  </Button>
                  <Button onClick={() => void apply(true)} disabled={busy !== ""} data-testid="designer-apply-manual" title="طرح به لایه‌های قابل‌ویرایشِ حالتِ دستی تبدیل می‌شود">
                    {busy === "apply" ? <Spinner size={16} /> : "ذخیره و باز کردن در حالتِ دستی ✎"}
                  </Button>
                  <Button variant="secondary" onClick={() => void apply(false)} disabled={busy !== ""} data-testid="designer-apply">ذخیره (نسخهٔ ساخته‌شده)</Button>
                </div>
                {dirty && <p className="dz-muted mt-1">تغییرهای مرحله‌ها هنوز در تصویر نیامده؛ «ساختِ دوباره» را بزنید (هوش مصنوعی صدا زده نمی‌شود، سریع است).</p>}
              </div>
            )}
          </div>
        )}
        {design?.state === "FAILED" && <div className="mt-3"><Alert tone="bad" title="طراحی انجام نشد">{design.error}</Alert></div>}
      </div>
    </Card>
  );
}
