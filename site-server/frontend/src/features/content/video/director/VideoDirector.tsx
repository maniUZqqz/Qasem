import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { errorMessage } from "../../../../api/client";
import { Alert, Badge, Button, Card, Spinner, TextArea, fa } from "../../../../components/ui";
import { useJobRunner } from "../../../../hooks/useJobRunner";
import type { Bin, MediaItem } from "../api";
import { videoApi } from "../api";
import { DirectorCatalogue, DirectorResult, DirectorVariant, EditorSettings, ParamSpec, PlanStep, ToolSpec, directorApi } from "./api";
import SilenceReview from "../autoedit/SilenceReview";
import SizesPanel from "../autoedit/SizesPanel";
import DraftsList from "./DraftsList";
import EditorSettingsCard from "./EditorSettings";
import "./director.css";

const EXAMPLES = [
  "ریلزِ معرفیِ محصول، ۲۰ ثانیه، سریع و پرانرژی با موسیقی",
  "جعبه‌گشایی برای تیک‌تاک؛ سکوت‌ها حذف و زیرنویس درشت",
  "حراجِ ۳۰٪ تخفیف برای استوری؛ برش‌های تند و برچسبِ تخفیف",
  "اسلایدشوی عکس‌ها برای پستِ اینستاگرام، آرام و لوکس",
  "نظرِ مشتری را کوتاه کن و زیرنویس بگذار",
];
const PACES = [{ key: "", title: "خودکار" }, { key: "fast", title: "تند" }, { key: "normal", title: "متعادل" }, { key: "slow", title: "آرام" }];
const DURATIONS = [0, 12, 15, 20, 30, 45, 60];
const GROUP_FA: Record<string, string> = { structure: "ساختار", text: "متن", visual: "تصویر", audio: "صدا" };
const KIND_ICON: Record<string, string> = { video: "🎞", image: "🖼", audio: "🎵" };

type Choice = { recipe: string; platform: string; duration: number; pace: string; music: "auto" | "none" | string; background: "" | "keep" | "blur" | "color" | "image"; backgroundRef: string };

function useCatalogue(storeId: string) {
  const [cat, setCat] = useState<DirectorCatalogue | null>(null);
  useEffect(() => {
    let stop = false;
    void directorApi.catalogue(storeId).then((c) => !stop && setCat(c)).catch(() => undefined);
    return () => {
      stop = true;
    };
  }, [storeId]);
  return [cat, setCat] as const;
}

/** یک مرحله: کلید، شرح، دلیل، نتیجه و ویرایشِ پارامترها (از مشخصاتِ ابزار) */
function StepRow({ step, spec, onChange }: { step: PlanStep; spec: ToolSpec | undefined; onChange: (s: PlanStep) => void }) {
  const [open, setOpen] = useState(false);
  const on = step.on !== false;
  const setParam = (name: string, value: unknown) => onChange({ ...step, params: { ...step.params, [name]: value } });
  const tone = step.skipped ? "neutral" : step.ok === false ? "warn" : "ok";
  return (
    <li className={`dr-step ${on ? "" : "is-off"} ${step.ok === false ? "is-fail" : ""}`} data-testid="dr-step" data-tool={step.tool}>
      <div className="dr-step-head">
        <label className="dr-switch" title={on ? "این مرحله اجرا می‌شود؛ برای برداشتنش خاموشش کنید" : "این مرحله خاموش است"}>
          <input type="checkbox" checked={on} onChange={(e) => onChange({ ...step, on: e.target.checked })} data-testid="dr-step-on" />
          <span className="dr-switch-track" />
        </label>
        <div className="dr-step-main">
          <div className="dr-step-title">
            <b>{step.title}</b>
            {spec && <Badge tone="neutral">{GROUP_FA[spec.group] ?? spec.group}</Badge>}
            {(step.round ?? 0) > 0 && <Badge tone="info">{(step.round ?? 0) >= 90 ? "پیشنهادِ هوش مصنوعی" : "اصلاحِ خودکار"}</Badge>}
          </div>
          <div className="dr-step-text">{step.text}</div>
          {step.why && <div className="dr-step-why">چرا: {step.why}</div>}
          {step.message && on && (
            <div className={`dr-step-msg tone-${tone}`} data-testid="dr-step-msg">
              {step.ok === false ? "انجام نشد: " : ""}
              {step.message}
            </div>
          )}
        </div>
        {spec && spec.params.length > 0 && (
          <button type="button" className="ws-btn dr-edit-btn" onClick={() => setOpen((v) => !v)} aria-expanded={open} title="عددها و گزینه‌های این مرحله را عوض کنید" data-testid="dr-step-edit">
            {open ? "بستن" : "ویرایش"}
          </button>
        )}
      </div>
      {open && spec && (
        <div className="dr-params" data-testid="dr-params">
          {spec.params.filter((p) => p.kind !== "list").map((p) => (
            <ParamField key={p.name} spec={p} value={step.params[p.name]} onChange={(v) => setParam(p.name, v)} />
          ))}
        </div>
      )}
    </li>
  );
}

function ParamField({ spec, value, onChange }: { spec: ParamSpec; value: unknown; onChange: (v: unknown) => void }) {
  const label = `${spec.title}${spec.unit ? ` (${spec.unit})` : ""}`;
  if (spec.kind === "bool")
    return (
      <label className="dr-field dr-field-check">
        <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} /> <span>{label}</span>
      </label>
    );
  if (spec.kind === "choice")
    return (
      <label className="dr-field">
        <span>{label}</span>
        <select className="u-input" value={String(value ?? spec.default ?? "")} onChange={(e) => onChange(e.target.value)}>
          {(spec.choices ?? []).map((c) => (
            <option key={c} value={c}>{c || "—"}</option>
          ))}
        </select>
      </label>
    );
  if (spec.kind === "num" || spec.kind === "int")
    return (
      <label className="dr-field">
        <span>{label}</span>
        <input
          className="u-input" type="number" dir="ltr" value={value === undefined || value === null ? "" : Number(value)}
          min={spec.min} max={spec.max} step={spec.kind === "int" ? 1 : 0.1}
          onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))}
        />
      </label>
    );
  return (
    <label className="dr-field">
      <span>{label}</span>
      <input className="u-input" value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

function Critique({ v }: { v: DirectorVariant }) {
  const c = v.critique;
  return (
    <div className="dr-critique" data-testid="dr-critique">
      <div className="dr-critique-head">
        <b>نقدِ تدوین (بر پایهٔ فهرستِ کارِ یک تدوینگرِ حرفه‌ای)</b>
        <Badge tone={c.score >= 80 ? "ok" : c.score >= 60 ? "warn" : "bad"}>امتیاز {fa(c.score)} از {fa(100)}</Badge>
      </div>
      <ul>
        {c.items.map((i) => (
          <li key={i.key} className={i.ok ? "is-ok" : `is-${i.severity}`}>
            <span aria-hidden>{i.ok ? "✓" : i.severity === "bad" ? "✗" : "!"}</span> <b>{i.title}</b> — {i.detail}
          </li>
        ))}
      </ul>
      {c.vision && (
        <div className="dr-vision" data-testid="dr-vision">
          <b>نقدِ تصویریِ پیش‌نمایش (مدلِ بینایی)</b>
          {(c.vision.issues ?? []).length === 0 ? <div>مشکلِ مهمی دیده نشد.</div> : (
            <ul>{(c.vision.issues ?? []).map((i, k) => <li key={k}>{i.frame ? `فریم ${fa(i.frame)}: ` : ""}{i.what} {i.fix ? `← ${i.fix}` : ""}</li>)}</ul>
          )}
        </div>
      )}
    </div>
  );
}

export default function VideoDirector({ storeId, onOpenProject }: { storeId: string; onOpenProject: (projectId: number) => void }) {
  const [cat, setCat] = useCatalogue(storeId);
  const [bin, setBin] = useState<Bin | null>(null);
  const [binTab, setBinTab] = useState<"videos" | "images" | "audio">("videos");
  const [picked, setPicked] = useState<string[]>([]);
  const [sizesFor, setSizesFor] = useState<number | null>(null);
  const [prompt, setPrompt] = useState("");
  const [choice, setChoice] = useState<Choice>({ recipe: "", platform: "", duration: 0, pace: "", music: "auto", background: "", backgroundRef: "" });
  // خاموش تا وقتی تنظیمِ فروشگاه برسد: اگر پیش‌فرضِ مالک «خاموش» باشد و کسی پیش از رسیدنِ کاتالوگ «ساخت» را بزند، اعتبار خرج نشود
  const [useAi, setUseAi] = useState(false);
  /** تیکِ هوش مصنوعی تا وقتی کاربر دست نزده از «پیش‌فرضِ فروشگاه» می‌آید */
  const aiTouched = useRef(false);
  const [opened, setOpened] = useState<Record<number, number>>({});
  const [draftsKey, setDraftsKey] = useState(0);
  const [openBusy, setOpenBusy] = useState(false);
  const [preview, setPreview] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DirectorResult | null>(null);
  const [vkey, setVkey] = useState("a");
  const [plans, setPlans] = useState<Record<string, PlanStep[]>>({});
  const [dirty, setDirty] = useState<Record<string, boolean>>({});
  const [follow, setFollow] = useState("");
  const [starting, setStarting] = useState(false);
  const lastJob = useRef<{ id: number | null; kind: "run" | "rerun"; variant: string }>({ id: null, kind: "run", variant: "a" });
  const resultRef = useRef<DirectorResult | null>(null);
  resultRef.current = result;
  useEffect(() => {
    if (cat?.settings && !aiTouched.current) setUseAi(cat.settings.ai_default);
  }, [cat?.settings]);
  const onSettings = useCallback((st: EditorSettings) => setCat((c) => (c ? { ...c, settings: st } : c)), [setCat]);

  const loadBin = useCallback(async () => {
    try {
      setBin(await videoApi.bin(storeId));
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [storeId]);
  useEffect(() => {
    void loadBin();
  }, [loadBin]);

  const toPlans = (variants: DirectorVariant[]) => Object.fromEntries(variants.map((v) => [v.key, v.plan.map((s) => ({ ...s, on: s.on !== false }))]));

  const onDone = useCallback(async () => {
    const jobId = lastJob.current.id;
    if (!jobId) return;
    try {
      const job = await directorApi.job(jobId);
      const res = job.result as unknown as DirectorResult | undefined;
      if (!res || !res.variants) return;
      if (lastJob.current.kind === "rerun" && resultRef.current) {
        const key = lastJob.current.variant;
        const nv = res.variants[0];
        const merged: DirectorResult = {
          ...resultRef.current,
          degraded: [...res.degraded],
          variants: resultRef.current.variants.map((v) => (v.key === key ? { ...nv, key } : v)),
        };
        setResult(merged);
        setPlans((cur) => ({ ...cur, [key]: nv.plan.map((s) => ({ ...s, on: s.on !== false })) }));
        setDirty((cur) => ({ ...cur, [key]: false }));
      } else {
        setResult(res);
        setPlans(toPlans(res.variants));
        setDirty({});
        setOpened({});
        setVkey(res.primary || res.variants[0]?.key || "a");
      }
      setDraftsKey((k) => k + 1);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);
  const runner = useJobRunner(onDone);
  const running = runner.running || starting;

  const toggle = (ref: string) => setPicked((cur) => (cur.includes(ref) ? cur.filter((r) => r !== ref) : [...cur, ref]));
  const items: MediaItem[] = bin ? bin[binTab] : [];
  const picks = useMemo(() => picked.map((r) => [...(bin?.videos ?? []), ...(bin?.images ?? []), ...(bin?.audio ?? [])].find((m) => m.ref === r)).filter(Boolean) as MediaItem[], [picked, bin]);

  function options() {
    const override: Record<string, unknown> = {};
    if (choice.recipe) override.recipe = choice.recipe;
    if (choice.platform) override.platform = choice.platform;
    if (choice.duration) override.duration = choice.duration;
    if (choice.pace) override.pace = choice.pace;
    if (choice.music === "none") override.music = false;
    if (choice.background) override.background = choice.background;
    if (choice.background === "image" && choice.backgroundRef) override.background_ref = choice.backgroundRef;
    return { use_ai: useAi, preview, music_ref: choice.music !== "auto" && choice.music !== "none" ? choice.music : "", override };
  }

  async function start(text: string) {
    setError(null);
    if (!picks.some((m) => m.kind !== "audio")) {
      setError("اول دست‌کم یک ویدیو یا عکس را از فهرستِ بالا انتخاب کنید.");
      return;
    }
    setStarting(true);
    try {
      runner.begin();
      const refs = picked;
      const r = await directorApi.run(storeId, { prompt: text, refs, options: options() });
      lastJob.current = { id: r.job_id, kind: "run", variant: "a" };
      runner.track(r.job_id);
    } catch (err) {
      runner.fail(errorMessage(err));
    } finally {
      setStarting(false);
    }
  }

  async function rerun(v: DirectorVariant) {
    if (!result) return;
    setError(null);
    setStarting(true);
    try {
      runner.begin();
      const steps = (plans[v.key] ?? v.plan).map((s) => ({ id: s.id, tool: s.tool, params: s.params, why: s.why ?? "", on: s.on !== false }));
      const r = await directorApi.rerun(storeId, { brief: result.brief, steps, refs: picked, variant: v.key, draft_id: v.draft_id });
      lastJob.current = { id: r.job_id, kind: "rerun", variant: v.key };
      runner.track(r.job_id);
    } catch (err) {
      runner.fail(errorMessage(err));
    } finally {
      setStarting(false);
    }
  }

  const variant = result?.variants.find((v) => v.key === vkey) ?? result?.variants[0];
  /** «باز کردن در تدوینِ دستی»: همین لحظه پیش‌نویس پروژهٔ واقعی می‌شود (بار دوم همان پروژه باز می‌شود) */
  async function openVariant(v: DirectorVariant) {
    const known = v.project_id ?? (v.draft_id ? opened[v.draft_id] : undefined);
    if (known) {
      onOpenProject(known);
      return;
    }
    if (!v.draft_id) return;
    setOpenBusy(true);
    setError(null);
    try {
      const r = await directorApi.openDraft(storeId, v.draft_id);
      setOpened((cur) => ({ ...cur, [v.draft_id!]: r.project_id }));
      setDraftsKey((k) => k + 1);
      onOpenProject(r.project_id);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setOpenBusy(false);
    }
  }
  const specOf = (tool: string) => cat?.tools.find((t) => t.tool === tool);

  /** «چند سایز»: پروژه باید واقعی باشد؛ اگر پیش‌نویس است همین‌جا (بدونِ رفتن به ادیتور) پروژه می‌شود */
  async function showSizes(v: DirectorVariant) {
    setError(null);
    let pid = v.project_id ?? (v.draft_id ? opened[v.draft_id] : undefined);
    if (!pid && v.draft_id) {
      setOpenBusy(true);
      try {
        const r = await directorApi.openDraft(storeId, v.draft_id);
        pid = r.project_id;
        setOpened((cur) => ({ ...cur, [v.draft_id!]: r.project_id }));
        setDraftsKey((k) => k + 1);
      } catch (err) {
        setError(errorMessage(err));
      } finally {
        setOpenBusy(false);
      }
    }
    if (pid) setSizesFor(pid);
  }

  return (
    <div className="dr-root" data-testid="director">
      <Card>
        <div className="dr-title">
          <h2>کارگردان — از روی یک دستور، ویدیوی کامل بساز</h2>
          <p className="dr-sub">
            فیلم‌ها و عکس‌ها را انتخاب کنید و بنویسید چه می‌خواهید. تحلیل می‌کنم، تدوین می‌کنم و <b>یک پروژهٔ قابل‌ویرایش</b> می‌دهم؛ هر مرحله را می‌بینید، خاموش یا اصلاح می‌کنید و دوباره اجرا می‌شود. هر نتیجه را در «دستی» هم می‌شود ادامه داد.
          </p>
        </div>

        {cat && (
          <div className="dr-status" data-testid="dr-status">
            <Badge tone={cat.ai.node ? "ok" : "warn"}>{cat.ai.node ? "سرورِ پردازش روشن است" : "سرورِ پردازش خاموش است"}</Badge>
            <Badge tone={cat.captions.ok ? "ok" : "neutral"}>{cat.captions.ok ? "تشخیصِ گفتار (زیرنویسِ خودکار) آماده است" : "تشخیصِ گفتار در دسترس نیست"}</Badge>
            <span className="dr-hint">قالب‌های آماده بدون هوش مصنوعی هم کار می‌کنند؛ بخشی که به هوش مصنوعی نیاز داشت در نتیجه گفته می‌شود.</span>
          </div>
        )}

        <div className="dr-section">
          <div className="dr-label">۱ · چه چیزهایی در ویدیو باشد؟ <span className="dr-count">{fa(picked.length)} انتخاب‌شده</span></div>
          <div className="dr-tabs" role="tablist">
            {([["videos", "ویدیوها"], ["images", "عکس‌ها"], ["audio", "صدا و موسیقی"]] as const).map(([k, t]) => (
              <button key={k} type="button" role="tab" aria-selected={binTab === k} className={`ws-chip ${binTab === k ? "is-on" : ""}`} onClick={() => setBinTab(k)} data-testid={`dr-tab-${k}`}>
                {t} {bin ? fa(bin[k].length) : ""}
              </button>
            ))}
          </div>
          {!bin ? <Spinner size={16} /> : items.length === 0 ? (
            <p className="dr-hint">{binTab === "videos" ? "هنوز ویدیویی نیست؛ بالای همین صفحه «ویدیوی تازه» را آپلود کنید." : binTab === "images" ? "عکسی نیست؛ از «ادیتور عکس» یا عکس‌های محصول بیاورید." : "موسیقی‌ای نیست؛ در تدوینِ دستی «موسیقیِ پس‌زمینه» را بزنید یا در بخشِ «صدا» بسازید."}</p>
          ) : (
            <div className="dr-tiles" data-testid="dr-tiles">
              {items.map((it) => {
                const idx = picked.indexOf(it.ref);
                return (
                  <button key={it.ref} type="button" className={`dr-tile ${idx >= 0 ? "is-picked" : ""}`} onClick={() => toggle(it.ref)} aria-pressed={idx >= 0} data-ref={it.ref} title={it.title}>
                    {idx >= 0 && <b className="dr-order">{fa(idx + 1)}</b>}
                    <span className="dr-ico" aria-hidden>{KIND_ICON[it.kind]}</span>
                    <span className="dr-name">{it.title}</span>
                    <small>{it.kind === "image" ? "عکس" : `${fa(Math.round(it.duration))} ثانیه`}</small>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div className="dr-section">
          <div className="dr-label">۲ · چه ویدیویی می‌خواهید؟</div>
          <TextArea rows={2} value={prompt} maxLength={600} onChange={(e) => setPrompt(e.target.value)} data-testid="dr-prompt"
            placeholder="مثلاً: ریلزِ معرفیِ محصول، ۲۰ ثانیه، سریع و پرانرژی با موسیقی — یا خالی بگذارید تا خودم تصمیم بگیرم" />
          <div className="dr-chips">
            {EXAMPLES.map((x) => <button key={x} type="button" className="example-chip" onClick={() => setPrompt(x)}>{x}</button>)}
          </div>
        </div>

        <details className="dr-more" open>
          <summary>۳ · انتخاب‌های دلخواه (اگر نگویید، خودکار تصمیم می‌گیرم)</summary>
          <div className="dr-opts">
            <div>
              <div className="dr-sublabel">نوعِ ویدیو</div>
              <div className="dr-chips">
                <button type="button" className={`ws-chip ${choice.recipe === "" ? "is-on" : ""}`} onClick={() => setChoice({ ...choice, recipe: "" })}>خودکار</button>
                {(cat?.recipes ?? []).map((r) => (
                  <button key={r.key} type="button" className={`ws-chip ${choice.recipe === r.key ? "is-on" : ""}`} title={r.hint} onClick={() => setChoice({ ...choice, recipe: r.key })} data-testid={`dr-recipe-${r.key}`}>{r.title}</button>
                ))}
              </div>
            </div>
            <div>
              <div className="dr-sublabel">برای کجا؟</div>
              <div className="dr-chips">
                <button type="button" className={`ws-chip ${choice.platform === "" ? "is-on" : ""}`} onClick={() => setChoice({ ...choice, platform: "" })}>خودکار (ریلز)</button>
                {(cat?.platforms ?? []).map((p) => (
                  <button key={p.key} type="button" className={`ws-chip ${choice.platform === p.key ? "is-on" : ""}`} onClick={() => setChoice({ ...choice, platform: p.key })} data-testid={`dr-platform-${p.key}`}>{p.title}</button>
                ))}
              </div>
            </div>
            <div className="dr-row">
              <label className="dr-field"><span>مدت</span>
                <select className="u-input" value={choice.duration} onChange={(e) => setChoice({ ...choice, duration: Number(e.target.value) })} data-testid="dr-duration">
                  {DURATIONS.map((d) => <option key={d} value={d}>{d ? `${fa(d)} ثانیه` : "خودکار"}</option>)}
                </select>
              </label>
              <label className="dr-field"><span>ریتمِ برش‌ها</span>
                <select className="u-input" value={choice.pace} onChange={(e) => setChoice({ ...choice, pace: e.target.value })} data-testid="dr-pace">
                  {PACES.map((p) => <option key={p.key} value={p.key}>{p.title}</option>)}
                </select>
              </label>
              <label className="dr-field"><span>موسیقی</span>
                <select className="u-input" value={choice.music} onChange={(e) => setChoice({ ...choice, music: e.target.value })} data-testid="dr-music">
                  <option value="auto">خودکار (از کتابخانه یا همین انتخاب‌ها)</option>
                  <option value="none">بدونِ موسیقی</option>
                  {(bin?.audio ?? []).map((a) => <option key={a.ref} value={a.ref}>{a.title}</option>)}
                </select>
              </label>
              <label className="dr-field"><span>پس‌زمینهٔ پشتِ گوینده</span>
                <select className="u-input" value={choice.background} onChange={(e) => setChoice({ ...choice, background: e.target.value as Choice["background"] })} data-testid="dr-background"
                  title="سوژه با پردازشِ گرافیکیِ سرورِ پردازش جدا می‌شود؛ اگر سرور خاموش باشد این مرحله در صف می‌ماند و خودکار انجام می‌شود">
                  <option value="">همان که هست</option>
                  <option value="blur">محو (سوژه واضح بماند)</option>
                  <option value="color">رنگِ ساده</option>
                  <option value="image">جایگزین با عکس</option>
                </select>
              </label>
              {choice.background === "image" && (
                <label className="dr-field"><span>عکسِ پس‌زمینه</span>
                  <select className="u-input" value={choice.backgroundRef} onChange={(e) => setChoice({ ...choice, backgroundRef: e.target.value })} data-testid="dr-background-image"
                    title="یکی از عکس‌های رسانه‌هایتان؛ سوژه روی آن می‌نشیند">
                    <option value="">{(bin?.images ?? []).length ? "یک عکس انتخاب کنید" : "عکسی در رسانه‌ها نیست؛ اول عکس آپلود کنید"}</option>
                    {(bin?.images ?? []).map((m) => <option key={m.ref} value={m.ref}>{m.title}</option>)}
                  </select>
                </label>
              )}
            </div>
            <div className="dr-row">
              <label className="dr-check"><input type="checkbox" checked={useAi} onChange={(e) => { aiTouched.current = true; setUseAi(e.target.checked); }} disabled={!cat?.settings} data-testid="dr-use-ai" /> هوش مصنوعی کمک کند (درکِ دقیقِ دستور، تیتر، نقد)</label>
              <label className="dr-check"><input type="checkbox" checked={preview} onChange={(e) => setPreview(e.target.checked)} data-testid="dr-preview" /> پیش‌نمایشِ کم‌حجم بساز و نقد کن (فقط وقتی هوش مصنوعی جواب بدهد)</label>
            </div>
            {cat?.settings && <p className="dr-hint" data-testid="dr-ai-cost">{cat.settings.cost_note}</p>}
          </div>
        </details>

        <details className="dr-more" data-testid="dr-settings">
          <summary>تنظیمات (پیش‌فرضِ کمکِ هوش مصنوعی، مدتِ نگهداریِ پیش‌نویس)</summary>
          <EditorSettingsCard storeId={storeId} onChange={onSettings} />
        </details>

        <div className="dr-go">
          <Button onClick={() => void start(prompt)} disabled={running || picked.length === 0} data-testid="dr-run">
            {running ? <><Spinner size={16} /> در حال ساختن…</> : "✨ بساز"}
          </Button>
          {picked.length === 0 && <span className="dr-hint">اول چیزی انتخاب کنید.</span>}
        </div>
        {running && (
          <div className="dr-progress" data-testid="dr-progress">
            <Spinner size={16} /> <span>{runner.job?.current_step_label || "در حال کار…"}</span>
            {typeof runner.job?.progress_step === "number" && runner.job.total_steps === 100 && <small>{fa(runner.job.progress_step)}٪</small>}
          </div>
        )}
        {(error || runner.error) && <div className="mt-3"><Alert tone="bad" title="انجام نشد">{error || runner.error}</Alert></div>}
      </Card>

      {result && variant && (
        <Card>
          <div className="dr-result" data-testid="dr-result">
            <div className="dr-result-head">
              <b>نتیجه</b>
              <Badge tone="brand">{result.recipe_title ?? "ویدیو"}</Badge>
              {result.platform && <Badge tone="neutral">{result.platform}</Badge>}
              {result.brief?.duration ? <Badge tone="neutral">هدف: {fa(Number(result.brief.duration))} ثانیه</Badge> : null}
              {result.brief?.title ? <Badge tone="neutral">تیتر: {String(result.brief.title)}</Badge> : null}
            </div>

            {result.ai.ok ? (
              <Alert tone={result.ai.via === "node" ? "ok" : "info"} title={result.ai.via === "node" ? "هوش مصنوعی روی سرورِ پردازش جواب داد" : "هوش مصنوعیِ پشتیبان جواب داد"}>
                {result.ai.model ? `مدل: ${result.ai.model}. ` : ""}دستور را فهمید{result.ai.used_for_steps ? " و برای بهتر شدنِ تدوین پیشنهاد داد" : ""}.
              </Alert>
            ) : result.ai.enabled === false ? null : (
              <div data-testid="dr-ai-error">
                <Alert tone="warn" title="هوش مصنوعی جواب نداد؛ با قالب‌های آماده ساخته شد">
                  <span data-testid="dr-ai-error-text">{result.ai.error || "در دسترس نبود."}</span>
                  {(result.ai.needed_for ?? []).length > 0 && <div className="dr-needed">این بخش‌ها به هوش مصنوعی نیاز داشت: {(result.ai.needed_for ?? []).join("، ")}.</div>}
                </Alert>
              </div>
            )}
            {result.degraded.length > 0 && (
              <div data-testid="dr-degraded">
                <Alert tone="info" title="چیزهایی که انجام نشد یا ناقص بود">
                  <ul className="dr-list">{result.degraded.map((d, i) => <li key={i}>{d}</li>)}</ul>
                </Alert>
              </div>
            )}

            {result.preview?.url && (
              <div className="dr-preview" data-testid="dr-preview-video">
                <div className="dr-sublabel">پیش‌نمایشِ کم‌حجمِ نسخهٔ پیشنهادی ({fa(Math.round(result.preview.seconds ?? 0))} ثانیه)</div>
                <video controls src={result.preview.url} className="dr-video" playsInline />
              </div>
            )}

            <p className="dr-hint" data-testid="dr-draft-note">
              این نسخه‌ها فعلاً «پیش‌نویسِ سبک»‌اند (فیلم‌ها کپی نشده‌اند) و اگر باز نشوند {fa(result.draft_days ?? 7)} روز می‌مانند. هر کدام را در «تدوینِ دستی» باز کنید پروژهٔ واقعی می‌شود و دیگر خودکار پاک نمی‌شود.
            </p>
            <div className="dr-variants" role="tablist" aria-label="نسخه‌ها">
              {result.variants.map((v, i) => (
                <button key={v.key} type="button" role="tab" aria-selected={vkey === v.key} className={`dr-variant ${vkey === v.key ? "is-on" : ""}`} onClick={() => setVkey(v.key)} data-testid={`dr-variant-${v.key}`}>
                  <b>نسخهٔ {fa(i + 1)}</b>
                  <span>{v.title}</span>
                  <Badge tone={v.score >= 80 ? "ok" : v.score >= 60 ? "warn" : "bad"}>{fa(v.score)}</Badge>
                  {v.key === result.primary && <small>پیشنهادِ من</small>}
                </button>
              ))}
            </div>

            <div className="dr-actions">
              {(variant.project_id || variant.draft_id) && <Button onClick={() => void openVariant(variant)} disabled={openBusy} data-testid="dr-open-manual">باز کردن در تدوینِ دستی</Button>}
              <Button variant="secondary" onClick={() => void rerun(variant)} disabled={running || !dirty[variant.key]} data-testid="dr-rerun" title="مرحله‌ها را با تغییرهای شما از اول اجرا می‌کند (بدونِ هوش مصنوعی)">
                اجرای دوباره با تغییرها
              </Button>
              {!dirty[variant.key] && <span className="dr-hint">مرحله‌ای را خاموش یا ویرایش کنید تا این دکمه روشن شود.</span>}
              <Button variant="secondary" onClick={() => void showSizes(variant)} disabled={openBusy || !(variant.project_id || variant.draft_id)} data-testid="dr-sizes">
                چند سایز (ریلز، یوتیوب، …)
              </Button>
            </div>

            {(plans[variant.key] ?? variant.plan).some((s) => s.tool === "smart_cuts" && s.on !== false) && picked.filter((r) => r.startsWith("video:")).slice(0, 1).map((r) => (
              <div key={r} className="mt-3" data-testid="dr-silence">
                <SilenceReview storeId={storeId} refId={r} doneLabel="ثبت پاسخ‌ها و ساختِ دوباره" onDone={() => void rerun(variant)} />
              </div>
            ))}
            {sizesFor && <div className="mt-3"><SizesPanel storeId={storeId} projectId={sizesFor} /></div>}

            {variant.problems && variant.problems.length > 0 && <Alert tone="warn" title="این مرحله‌ها خوانده نشد">{variant.problems.join(" · ")}</Alert>}
            <Critique v={variant} />

            <div className="dr-steps-head">
              <b>مرحله‌های این نسخه</b>
              <span className="dr-hint">{fa((plans[variant.key] ?? variant.plan).length)} مرحله — هر مرحله یک کارِ همان ابزارهای ادیتورِ دستی است</span>
            </div>
            <ol className="dr-steps" data-testid="dr-steps">
              {(plans[variant.key] ?? variant.plan).map((s, i) => (
                <StepRow key={`${s.id}-${i}`} step={s} spec={specOf(s.tool)}
                  onChange={(ns) => { setPlans((cur) => ({ ...cur, [variant.key]: (cur[variant.key] ?? variant.plan).map((x, j) => (j === i ? ns : x)) })); setDirty((cur) => ({ ...cur, [variant.key]: true })); }} />
              ))}
            </ol>

            <div className="dr-follow" data-testid="dr-follow">
              <div className="dr-sublabel">هنوز نشد؟ دستورِ بعدی را بنویسید (از اول با همان انتخاب‌ها ساخته می‌شود)</div>
              <div className="dr-follow-row">
                <input className="u-input" value={follow} onChange={(e) => setFollow(e.target.value)} placeholder="مثلاً: کوتاه‌ترش کن و رنگ‌ها گرم‌تر باشد"
                  onKeyDown={(e) => { if (e.key === "Enter" && follow.trim()) { void start(`${prompt}. ${follow}`); setPrompt(`${prompt}. ${follow}`); setFollow(""); } }} data-testid="dr-follow-input" />
                <Button variant="secondary" onClick={() => { void start(`${prompt}. ${follow}`); setPrompt(`${prompt}. ${follow}`); setFollow(""); }} disabled={running || !follow.trim()} data-testid="dr-follow-run">اصلاح کن</Button>
              </div>
            </div>
          </div>
        </Card>
      )}

      <Card>
        <details className="dr-more" data-testid="dr-drafts-box" open={false}>
          <summary>پیش‌نویس‌های قبلی (بازنشده)</summary>
          <DraftsList storeId={storeId} refreshKey={draftsKey} onOpen={onOpenProject} />
        </details>
      </Card>
    </div>
  );
}
