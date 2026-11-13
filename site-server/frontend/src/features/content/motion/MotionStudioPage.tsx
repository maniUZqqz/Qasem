import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Alert, Badge, Button, Card, ErrorBox, Field, Input, PageHeader, SectionTitle, Select, Spinner, TextArea, fa } from "../../../components/ui";
import {
  Brand,
  Catalog,
  NodeInfo,
  Overview,
  QUALITY_LABELS,
  RenderRow,
  Scene,
  SceneType,
  Source,
  Spec,
  errText,
  motionApi,
} from "./api";
import PlayerFrame, { PlayerHandle, PlayerMeta } from "./PlayerFrame";
import RenderHistory from "./RenderHistory";
import SceneEditor, { DEFAULT_SCENE } from "./SceneEditor";
import StyleGallery from "./StyleGallery";

type Mode = "template" | "ai" | "code";

const MODES: { key: Mode; title: string; help: string; icon: "sparkle" | "bulb" | "settings" }[] = [
  { key: "template", title: "قالبی", help: "سبک + قالبِ صحنه + متنِ شما؛ بدونِ نیاز به هوش مصنوعی", icon: "sparkle" },
  { key: "ai", title: "هوش مصنوعی", help: "ایده را به فارسی بنویسید؛ سناریوی صحنه‌ها نوشته می‌شود و می‌توانید ویرایشش کنید", icon: "bulb" },
  { key: "code", title: "کد (Remotion)", help: "کدِ ترکیب را ببینید و ویرایش کنید؛ پیش‌نمایشِ زنده و رندر به MP4", icon: "settings" },
];

function storeGet(key: string, d: string): string {
  try {
    return localStorage.getItem(key) ?? d;
  } catch {
    return d;
  }
}
function storeSet(key: string, v: string) {
  try {
    localStorage.setItem(key, v);
  } catch {
    /* حافظهٔ مرورگر بسته است */
  }
}

function NodeBanner({ node, site, limits }: { node: NodeInfo; site: Overview["site"]; limits: Overview["limits"] }) {
  const d = node.detail || {};
  if (node.state === "ready")
    return (
      <Alert tone="ok" title="سرورِ پردازش آماده است">
        رندرِ نهایی روی کارتِ گرافیکِ سرورِ پردازش انجام می‌شود{d.gpu ? " (با شتاب‌دهیِ GPU)" : ""}.
      </Alert>
    );
  if (node.state === "installing")
    return (
      <Alert tone="info" title="ابزارِ موشن روی سرورِ پردازش در حالِ نصبِ خودکار است">
        {d.message || node.message} {d.progress ? `(${fa(Math.round(Number(d.progress) * 100))}٪)` : ""} — نیازی به کارِ دستی نیست؛ رندرها در صف می‌مانند و بعد از نصب خودکار انجام می‌شوند.
      </Alert>
    );
  if (node.state === "failed")
    return (
      <Alert tone="warn" title="نصبِ ابزارِ موشن روی سرورِ پردازش گیر کرد">
        {node.message} سرور خودش چند دقیقه بعد دوباره امتحان می‌کند. در همین حال می‌توانید «رندر روی سایت» را بزنید.
      </Alert>
    );
  if (node.state === "offline" || node.state === "outdated" || node.state === "checking")
    return (
      <Alert tone="info" title="رندرِ نهایی منتظرِ سرورِ پردازش می‌ماند">
        {node.message} اگر عجله دارید «رندر روی سایت» را بزنید (محدود به {fa(limits.max_total_site)} ثانیه و {fa(limits.site_max_short_side)}p).
      </Alert>
    );
  return (
    <Alert tone="info" title="هنوز سرورِ پردازشی ثبت نشده">
      رندر روی سایت انجام می‌شود (حداکثر {fa(limits.max_total_site)} ثانیه و {fa(limits.site_max_short_side)}p، یکی‌یکی).{site.ready ? "" : ` ⚠ ${site.reasons.join("؛ ")}`}
    </Alert>
  );
}

export default function MotionStudioPage() {
  const { id = "" } = useParams<{ id: string }>();
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [ov, setOv] = useState<Overview | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [mode, setMode] = useState<Mode>(() => (storeGet("nm.motion.mode", "template") as Mode) || "template");
  const [styleId, setStyleId] = useState(() => storeGet("nm.motion.style", "flat-vector"));
  const [aspect, setAspect] = useState(() => storeGet("nm.motion.aspect", "9:16"));
  const [lang, setLang] = useState<"fa" | "en">("fa");
  const [scenes, setScenes] = useState<Scene[]>([{ ...DEFAULT_SCENE.title }]);
  const [useBrand, setUseBrand] = useState(true);
  const [showLogo, setShowLogo] = useState(true);
  const [intensity, setIntensity] = useState(1);
  const [quality, setQuality] = useState("720");
  const [title, setTitle] = useState("");
  const [idea, setIdea] = useState("");
  const [aiNote, setAiNote] = useState<{ tone: "ok" | "warn"; text: string } | null>(null);
  const [code, setCode] = useState("");
  const [codeIdea, setCodeIdea] = useState("");
  const [codeErr, setCodeErr] = useState<string | null>(null);
  const [meta, setMeta] = useState<PlayerMeta | null>(null);
  const [previewErr, setPreviewErr] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const player = useRef<PlayerHandle>(null);

  // ───────────────────────── loading
  useEffect(() => {
    let live = true;
    Promise.all([motionApi.catalog(), motionApi.overview(id), motionApi.sources(id).catch(() => [] as Source[])])
      .then(([c, o, s]) => {
        if (!live) return;
        setCatalog(c);
        setOv(o);
        setSources(s);
        setQuality(storeGet("nm.motion.quality", o.limits.default_quality));
        if (!c.styles.some((x) => x.id === styleId)) setStyleId(c.styles[0].id);
        setScenes(o.sample_spec.scenes.map((x) => ({ ...x })) as Scene[]);
        setCode(o.code.samples[0]?.code || "");
      })
      .catch((e) => live && setError(errText(e)));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const refresh = useCallback(async () => {
    try {
      const o = await motionApi.overview(id);
      setOv(o);
    } catch {
      /* وارسیِ بعدی */
    }
  }, [id]);

  const anyActive = !!ov?.renders.some((r) => r.active);
  useEffect(() => {
    if (!anyActive) return;
    const t = window.setInterval(refresh, 3500);
    return () => window.clearInterval(t);
  }, [anyActive, refresh]);

  // ───────────────────────── the spec the form describes
  const brand: Brand = useMemo(
    () => ({
      name: ov?.brand.name,
      colors: ov?.brand.colors,
      use_brand_colors: useBrand,
      show_logo: showLogo,
      ...(showLogo && ov?.brand.logo ? { logo: ov.brand.logo } : {}),
    }),
    [ov, useBrand, showLogo],
  );
  const spec: Spec = useMemo(() => ({ style: styleId, aspect, fps: 30, lang, digits: "auto", brand, scenes, intensity }), [styleId, aspect, lang, brand, scenes, intensity]);

  // live preview (debounced; stale answers are dropped)
  const seq = useRef(0);
  useEffect(() => {
    if (!ov || mode === "code") return;
    const n = ++seq.current;
    const t = window.setTimeout(async () => {
      try {
        const r = await motionApi.preview(id, spec);
        if (n !== seq.current) return;
        setPreviewErr(null);
        setTotal(r.total_s);
        player.current?.send({ type: "template", spec: r.spec });
      } catch (e) {
        if (n === seq.current) setPreviewErr(errText(e));
      }
    }, 550);
    return () => window.clearTimeout(t);
  }, [spec, mode, ov, id]);

  // code: compile + preview inside the sandboxed player; the site also scans it (safety rules)
  useEffect(() => {
    if (mode !== "code" || !code) return;
    const t = window.setTimeout(async () => {
      player.current?.send({ type: "code", code });
      try {
        const r = await motionApi.checkCode(id, code);
        setCodeErr(r.ok ? null : `${r.error}${r.line ? ` (خطِ ${fa(r.line)})` : ""}`);
      } catch {
        /* بررسیِ سایت در دسترس نیست؛ خطاهای پخش‌کننده می‌آید */
      }
    }, 700);
    return () => window.clearTimeout(t);
  }, [code, mode, id]);

  const onPlayerError = useCallback((m: string, line?: number) => setCodeErr(`${m}${line ? ` (خطِ ${fa(line)})` : ""}`), []);
  const onMeta = useCallback((m: PlayerMeta) => setMeta(m), []);

  // ───────────────────────── actions
  const loadTemplate = (tid: string) => {
    const t = catalog?.templates.find((x) => x.id === tid);
    if (!t) return;
    setScenes(t.scenes.map((s) => ({ ...DEFAULT_SCENE[s as SceneType] })));
  };

  const upload = async (f: File) => {
    try {
      const r = await motionApi.upload(id, f);
      const a = r.assets[0];
      if (a) setSources((s) => [{ ref: a.ref, title: a.title, url: a.url, group: "بارگذاری‌شده" }, ...s]);
      setNotice("تصویر بارگذاری شد؛ از فهرست انتخابش کنید.");
    } catch (e) {
      setError(errText(e));
    }
  };

  const makeScript = async () => {
    setBusy(true);
    setError(null);
    setAiNote(null);
    try {
      const r = await motionApi.ai(id, { idea, style: styleId, aspect, lang, brand });
      setScenes(r.spec.scenes as Scene[]);
      if (r.title && !title) setTitle(r.title);
      setAiNote(r.source === "ai" ? { tone: "ok", text: "سناریو نوشته شد؛ پیش‌نمایش را ببینید و هر متنی را که می‌خواهید ویرایش کنید." } : { tone: "warn", text: r.message });
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  };

  const makeCode = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await motionApi.aiCode(id, { idea: codeIdea, style: styleId, aspect });
      setCode(r.code);
      if (r.warning) setNotice(r.warning);
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  };

  const render = async (target: "node" | "site") => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const body: Record<string, unknown> = { mode: mode === "code" ? "code" : mode, title, quality, target };
      if (mode === "code") {
        body.code = code;
        if (meta) {
          body.width = meta.width;
          body.height = meta.height;
        }
      } else body.spec = spec;
      storeSet("nm.motion.quality", quality);
      const r = await motionApi.render(id, body);
      setOv((o) => (o ? { ...o, node: r.node, renders: [r.render, ...o.renders.filter((x) => x.id !== r.render.id)] } : o));
      setNotice(r.render.target === "site" ? "رندر روی سایت شروع شد." : r.render.state === "WAITING_NODE" ? "رندر در صفِ سرورِ پردازش است و با روشن شدنِ آن خودکار انجام می‌شود." : "رندر به سرورِ پردازش رفت.");
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  };

  const act = async (r: RenderRow, a: "cancel" | "site" | "retry") => {
    try {
      await motionApi.act(id, r.id, a);
      await refresh();
    } catch (e) {
      setError(errText(e));
    }
  };
  const del = async (r: RenderRow) => {
    if (!window.confirm("این مورد از تاریخچه پاک شود؟ (ویدیوی ساخته‌شده در رسانهٔ فروشگاه می‌ماند.)")) return;
    try {
      await motionApi.remove(id, r.id);
      await refresh();
    } catch (e) {
      setError(errText(e));
    }
  };
  const reuse = async (r: RenderRow) => {
    try {
      const full = await motionApi.one(id, r.id, true);
      if (full.mode === "code") {
        setMode("code");
        setCode(full.code || "");
      } else if (full.spec) {
        setMode(full.mode);
        setStyleId(full.spec.style);
        setAspect(full.spec.aspect);
        setLang((full.spec.lang as "fa" | "en") || "fa");
        setScenes(full.spec.scenes as Scene[]);
      }
      setTitle(full.title);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      setError(errText(e));
    }
  };

  const changeMode = (m: Mode) => {
    setMode(m);
    storeSet("nm.motion.mode", m);
  };
  const pickStyle = (s: string) => {
    setStyleId(s);
    storeSet("nm.motion.style", s);
  };

  if (!catalog || !ov) {
    return (
      <div>
        <PageHeader title="استودیوی موشن" />
        <ErrorBox message={error} />
        {!error && (
          <div className="flex justify-center py-16">
            <Spinner />
          </div>
        )}
      </div>
    );
  }

  const nodeWaiting = ov.node.state !== "none";
  const canSite = ov.site.ready;
  const aspectDef = catalog.aspects.find((a) => a.id === aspect);
  const totalMax = ov.node.state === "none" ? ov.limits.max_total_site : ov.limits.max_total_node;
  const codeOk = mode !== "code" || (!!code.trim() && !codeErr);

  return (
    <div>
      <PageHeader
        title="استودیوی موشن"
        subtitle="ویدیوی موشن‌گرافیک از روی کد (Remotion): بیش از ۶۰ سبکِ واقعاً متفاوت، رندرِ نهایی روی کارتِ گرافیک"
        actions={<Badge tone="brand">{fa(catalog.styles.length)} سبک</Badge>}
      />
      <NodeBanner node={ov.node} site={ov.site} limits={ov.limits} />
      <div className="mt-3 space-y-3">
        <ErrorBox message={error} />
        {notice ? <Alert tone="info">{notice}</Alert> : null}
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
        {/* ───────── کنترل‌ها */}
        <div className="min-w-0 space-y-5">
          <div className="flex flex-wrap gap-2" role="tablist">
            {MODES.map((m) => (
              <button
                key={m.key}
                type="button"
                role="tab"
                aria-selected={mode === m.key}
                onClick={() => changeMode(m.key)}
                className={`u-btn ${mode === m.key ? "u-btn-primary" : "u-btn-secondary"}`}
                title={m.help}
              >
                <Icon name={m.icon} size={16} /> {m.title}
              </button>
            ))}
          </div>
          <div className="text-sm" style={{ color: "var(--text-3)" }}>
            {MODES.find((m) => m.key === mode)?.help}
          </div>

          {mode !== "code" ? (
            <>
              {mode === "ai" ? (
                <Card>
                  <SectionTitle>ایده</SectionTitle>
                  <Field label="ایده‌ات را به فارسی بنویس" hint="مثلاً: معرفیِ چغر برای مربی‌ها؛ سه مزیت و دعوت به ثبت‌نام. فقط چیزهایی که خودت بگویی در ویدیو می‌آید.">
                    <TextArea rows={4} value={idea} onChange={(e) => setIdea(e.target.value)} placeholder="ایده یا متنِ خام…" />
                  </Field>
                  <div className="mt-3 flex flex-wrap items-center gap-3">
                    <Button type="button" onClick={makeScript} disabled={busy || idea.trim().length < 3}>
                      <Icon name="sparkle" size={15} /> {busy ? "در حال نوشتن…" : "ساختِ سناریو"}
                    </Button>
                    <span className="text-xs" style={{ color: "var(--text-3)" }}>
                      هوش مصنوعی در دسترس نباشد، یک پیش‌نویسِ ساده از روی متنت ساخته می‌شود.
                    </span>
                  </div>
                  {aiNote ? (
                    <div className="mt-3">
                      <Alert tone={aiNote.tone}>{aiNote.text}</Alert>
                    </div>
                  ) : null}
                </Card>
              ) : (
                <Card>
                  <SectionTitle>قالب</SectionTitle>
                  <div className="flex flex-wrap gap-2">
                    {catalog.templates.map((t) => (
                      <Button key={t.id} variant="secondary" size="sm" type="button" onClick={() => loadTemplate(t.id)}>
                        {t.name}
                      </Button>
                    ))}
                  </div>
                  <div className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
                    قالب را بزنید تا صحنه‌ها با متنِ نمونه پر شوند؛ بعد متن‌ها را عوض کنید.
                  </div>
                </Card>
              )}

              <Card>
                <SectionTitle>سبک</SectionTitle>
                <StyleGallery catalog={catalog} value={styleId} onChange={pickStyle} compact />
              </Card>

              <Card>
                <SectionTitle>اندازه و برند</SectionTitle>
                <div className="grid gap-3 sm:grid-cols-3">
                  <Field label="نسبتِ تصویر">
                    <Select
                      value={aspect}
                      onChange={(e) => {
                        setAspect(e.target.value);
                        storeSet("nm.motion.aspect", e.target.value);
                      }}
                    >
                      {catalog.aspects.map((a) => (
                        <option key={a.id} value={a.id}>
                          {fa(a.id)} — {a.name}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="زبانِ متن">
                    <Select value={lang} onChange={(e) => setLang(e.target.value as "fa" | "en")}>
                      <option value="fa">فارسی (راست‌به‌چپ)</option>
                      <option value="en">English</option>
                    </Select>
                  </Field>
                  <Field label="شدتِ حرکت" hint={fa(intensity.toFixed(1))}>
                    <input type="range" min={0.5} max={1.5} step={0.1} value={intensity} onChange={(e) => setIntensity(Number(e.target.value))} className="w-full" />
                  </Field>
                </div>
                <div className="mt-3 flex flex-wrap gap-5 text-sm" style={{ color: "var(--text-2)" }}>
                  <label className="flex items-center gap-2">
                    <input type="checkbox" checked={useBrand} onChange={(e) => setUseBrand(e.target.checked)} /> رنگ‌های برندِ فروشگاه (
                    {ov.brand.colors.length ? ov.brand.colors.map((c) => <span key={c} className="mx-0.5 inline-block h-3 w-3 rounded-full align-middle" style={{ background: c }} />) : "تعریف نشده"})
                  </label>
                  <label className="flex items-center gap-2" title={ov.brand.logo ? "" : "فروشگاه لوگو ندارد (در پروفایلِ برند بگذارید)"}>
                    <input type="checkbox" checked={showLogo} disabled={!ov.brand.logo} onChange={(e) => setShowLogo(e.target.checked)} /> لوگوی فروشگاه
                  </label>
                </div>
              </Card>

              <div>
                <SectionTitle>صحنه‌ها</SectionTitle>
                <SceneEditor scenes={scenes} onChange={setScenes} sources={sources} onUpload={upload} maxScenes={ov.limits.max_scenes} />
              </div>
            </>
          ) : (
            <>
              <Card>
                <SectionTitle
                  action={
                    <Select value="" onChange={(e) => e.target.value && setCode(ov.code.samples.find((s) => s.id === e.target.value)?.code || "")} style={{ width: 240 }}>
                      <option value="">نمونهٔ آماده…</option>
                      {ov.code.samples.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.title}
                        </option>
                      ))}
                    </Select>
                  }
                >
                  کدِ ترکیب (TSX)
                </SectionTitle>
                <textarea
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  spellCheck={false}
                  dir="ltr"
                  rows={26}
                  onKeyDown={(e) => {
                    if (e.key === "Tab") {
                      e.preventDefault();
                      const t = e.currentTarget;
                      const s = t.selectionStart;
                      setCode(code.slice(0, s) + "  " + code.slice(t.selectionEnd));
                      requestAnimationFrame(() => t.setSelectionRange(s + 2, s + 2));
                    }
                  }}
                  className="u-input w-full"
                  style={{ fontFamily: "ui-monospace, Menlo, Consolas, monospace", fontSize: 13, lineHeight: 1.6, whiteSpace: "pre", overflow: "auto", textAlign: "left" }}
                />
                {codeErr ? (
                  <div className="mt-3">
                    <Alert tone="bad" title="مشکل در کد">
                      <span dir="auto">{codeErr}</span>
                    </Alert>
                  </div>
                ) : (
                  <div className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
                    کد در یک صفحهٔ ایزوله اجرا می‌شود (بدونِ شبکه و بدونِ دسترسی به فایل). فقط این ماژول‌ها: {ov.code.allowed_imports.join("، ")}. اندازه و مدت را در <code dir="ltr">export const config</code> تعیین کنید.
                  </div>
                )}
              </Card>
              <Card>
                <SectionTitle>بنویس، کد بسازد (هوش مصنوعی)</SectionTitle>
                <div className="flex flex-wrap items-end gap-3">
                  <div className="min-w-[240px] flex-1">
                    <Input value={codeIdea} onChange={(e) => setCodeIdea(e.target.value)} placeholder="مثلاً: عنوانِ «تخفیفِ ویژه» با ذره‌های رنگی" />
                  </div>
                  <Button type="button" variant="secondary" onClick={makeCode} disabled={busy || codeIdea.trim().length < 3}>
                    <Icon name="sparkle" size={15} /> بنویس
                  </Button>
                </div>
                <div className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
                  کدِ نوشته‌شده همیشه از همان اسکنرِ امنیتی می‌گذرد.
                </div>
              </Card>
            </>
          )}
        </div>

        {/* ───────── پیش‌نمایش و رندر */}
        <div className="min-w-0 space-y-4 xl:sticky xl:top-4 xl:self-start">
          <Card>
            <SectionTitle>پیش‌نمایشِ زنده</SectionTitle>
            <PlayerFrame ref={player} onMeta={onMeta} onError={mode === "code" ? onPlayerError : undefined} aspect={mode === "code" && meta ? meta.width / meta.height : (aspectDef?.width ?? 9) / (aspectDef?.height ?? 16)} maxHeight={520} />
            {previewErr && mode !== "code" ? <div className="mt-3"><ErrorBox message={previewErr} /></div> : null}
            <div className="mt-3 text-xs leading-6" style={{ color: "var(--text-3)" }}>
              {mode === "code"
                ? meta
                  ? `${fa(meta.width)}×${fa(meta.height)} · ${fa(meta.fps)} فریم‌بر‌ثانیه · ${fa((meta.durationInFrames / meta.fps).toFixed(1))} ثانیه`
                  : "منتظرِ کد…"
                : `${fa(total.toFixed(1))} ثانیه (حداکثر ${fa(totalMax)})`}
              {" "}— پیش‌نمایش با همان موتورِ رندر ساخته می‌شود؛ خروجیِ نهایی با کیفیتِ کامل است.
            </div>
          </Card>
          <Card>
            <SectionTitle>رندر</SectionTitle>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="نام (اختیاری)">
                <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="خودکار از متنِ اول" />
              </Field>
              <Field label="کیفیت (ضلعِ کوتاه)">
                <Select value={quality} onChange={(e) => setQuality(e.target.value)}>
                  {ov.limits.qualities.map((q) => (
                    <option key={q} value={q}>
                      {QUALITY_LABELS[q] || q}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <Button type="button" onClick={() => render("node")} disabled={busy || !codeOk}>
                <Icon name="rocket" size={15} /> {ov.node.state === "none" ? "رندر" : "رندر روی سرورِ پردازش"}
              </Button>
              {nodeWaiting && canSite ? (
                <Button type="button" variant="secondary" onClick={() => render("site")} disabled={busy || !codeOk} title={`محدود: ${fa(ov.limits.max_total_site)} ثانیه، ${fa(ov.limits.site_max_short_side)}p`}>
                  <Icon name="cloud" size={15} /> رندر روی سایت
                </Button>
              ) : null}
            </div>
            <div className="mt-2 text-xs leading-6" style={{ color: "var(--text-3)" }}>
              ویدیو بعد از پایانِ رندر در «رسانهٔ فروشگاه» و سطلِ ادیتورِ ویدیو (با نامِ «موشن — …») می‌آید.
            </div>
          </Card>
        </div>
      </div>

      <div className="mt-8">
        <SectionTitle>تاریخچه</SectionTitle>
        <RenderHistory renders={ov.renders} storeId={id} onAct={act} onDelete={del} onReuse={reuse} nodeWaiting={nodeWaiting} />
      </div>
    </div>
  );
}
