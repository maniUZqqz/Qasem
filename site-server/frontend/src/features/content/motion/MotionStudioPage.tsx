import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Alert, Badge, Button, Card, ErrorBox, Field, Input, PageHeader, SectionTitle, Select, Spinner, TextArea, fa } from "../../../components/ui";
import {
  AudioCfg,
  Brand,
  Catalog,
  Library,
  NodeInfo,
  Overview,
  PlanDTO,
  PlanRow,
  QUALITY_LABELS,
  RenderRow,
  Scene,
  SoundInfo,
  Source,
  Spec,
  errText,
  motionApi,
} from "./api";
import PlanList from "./PlanList";
import PlayerFrame, { PlayerHandle, PlayerMeta } from "./PlayerFrame";
import { ChatEdit, ChatLine, HistoryBar, PlanJson, QaPanel, SoundPanel } from "./PlanTools";
import RenderHistory from "./RenderHistory";
import ScenePlan from "./ScenePlan";
import StyleGallery from "./StyleGallery";

type Mode = "template" | "ai" | "code";

const MODES: { key: Mode; title: string; help: string; icon: "sparkle" | "bulb" | "settings" }[] = [
  { key: "template", title: "قالبی", help: "سبک + قالبِ صحنه + متنِ شما؛ بدونِ نیاز به هوش مصنوعی", icon: "sparkle" },
  { key: "ai", title: "هوش مصنوعی", help: "ایده را به فارسی بنویسید؛ سناریوی صحنه‌ها از قطعه‌های آماده ساخته می‌شود و می‌توانید ویرایشش کنید", icon: "bulb" },
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
        رندرِ نهایی روی کارتِ گرافیکِ سرورِ پردازش انجام می‌شود{d.gpu ? " (با شتاب‌دهیِ GPU)" : ""}؛ نقدِ تصویری هم با مدلِ بینا روی همان سرور اجرا می‌شود.
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
      <Alert tone="info" title="رندرِ نهایی و نقدِ تصویری منتظرِ سرورِ پردازش می‌مانند">
        {node.message} اگر عجله دارید «رندر روی سایت» را بزنید (محدود به {fa(limits.max_total_site)} ثانیه و {fa(limits.site_max_short_side)}p). کنترلِ کیفیتِ قاعده‌ای در هر حال خودکار اجرا می‌شود.
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
  const [lib, setLib] = useState<Library | null>(null);
  const [sound, setSound] = useState<SoundInfo | null>(null);
  const [ov, setOv] = useState<Overview | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [mode, setMode] = useState<Mode>(() => (storeGet("nm.motion.mode", "template") as Mode) || "template");
  const [styleId, setStyleId] = useState(() => storeGet("nm.motion.style", "flat-vector"));
  const [aspect, setAspect] = useState(() => storeGet("nm.motion.aspect", "9:16"));
  const [lang, setLang] = useState<"fa" | "en">("fa");
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [useBrand, setUseBrand] = useState(true);
  const [showLogo, setShowLogo] = useState(true);
  const [intensity, setIntensity] = useState(1);
  const [platform, setPlatform] = useState<string>("");
  const [captions, setCaptions] = useState<Spec["captions"]>(undefined);
  const [audio, setAudio] = useState<AudioCfg | undefined>(undefined);
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

  // طرحِ زندهٔ سرور (تاریخچه، چت، کنترلِ کیفیت)
  const [plan, setPlan] = useState<PlanDTO | null>(null);
  const [planBusy, setPlanBusy] = useState(false);
  const [chat, setChat] = useState<ChatLine[]>([]);
  const [qaOnRender, setQaOnRender] = useState(true);
  const [critiqueOnRender, setCritiqueOnRender] = useState(false);
  const [tab, setTab] = useState<"plan" | "json">("plan");
  const lastSaved = useRef("");
  const justApplied = useRef(false);
  // the first spec after the page opened is the untouched sample: it is NOT saved (a plan is created by the first real edit, a chat/QA/render call, or "طرحِ تازه" + an edit)
  const baseline = useRef<string | null>(null);
  const [tick, setTick] = useState(0);
  const [plansList, setPlansList] = useState<PlanRow[]>([]);
  const planKey = `nm.motion.plan.${id}`;

  const refreshPlans = useCallback(async () => {
    try {
      setPlansList(await motionApi.plans(id));
    } catch {
      /* فهرست بعداً دوباره خوانده می‌شود */
    }
  }, [id]);

  // ───────────────────────── loading
  useEffect(() => {
    let live = true;
    Promise.all([motionApi.catalog(), motionApi.library(), motionApi.overview(id), motionApi.sources(id).catch(() => [] as Source[]), motionApi.sound(id).catch(() => null)])
      .then(([c, l, o, s, snd]) => {
        if (!live) return;
        setCatalog(c);
        setLib(l);
        setOv(o);
        setSources(s);
        setSound(snd);
        setQuality(storeGet("nm.motion.quality", o.limits.default_quality));
        if (!c.styles.some((x) => x.id === styleId)) setStyleId(c.styles[0].id);
        setScenes(o.sample_spec.scenes.map((x) => ({ ...x })) as Scene[]);
        setCode(o.code.samples[0]?.code || "");
        setPlatform("reels");
        baseline.current = null;
        // returning owner: the plans list, and the plan that was open last time (if it still exists)
        motionApi
          .plans(id)
          .then(async (rows) => {
            if (!live) return;
            setPlansList(rows);
            const last = Number(storeGet(planKey, "0"));
            if (last && rows.some((r) => r.id === last)) {
              try {
                const p = await motionApi.plan(id, last);
                if (live) applyPlan(p);
              } catch {
                /* طرحِ قبلی پاک شده؛ از نمونه شروع می‌شود */
              }
            }
          })
          .catch(() => undefined);
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
  const spec: Spec = useMemo(
    () => ({
      version: 2,
      style: styleId,
      aspect,
      fps: 30,
      lang,
      digits: "auto",
      brand,
      scenes,
      intensity,
      ...(platform ? { platform } : {}),
      ...(captions?.on ? { captions } : {}),
      ...(audio && Object.keys(audio).length ? { audio } : {}),
    }),
    [styleId, aspect, lang, brand, scenes, intensity, platform, captions, audio],
  );

  /** طرحی که از سرور آمد (برگشت، چت، کنترلِ کیفیت…) را در فرم می‌نشاند */
  const applyPlan = useCallback((p: PlanDTO) => {
    const s = p.spec;
    justApplied.current = true;
    setTick((t) => t + 1);                  // the effect below must run even when the form ends up unchanged (it consumes the flag)
    storeSet(`nm.motion.plan.${id}`, String(p.id));
    setPlan(p);
    setStyleId(s.style);
    setAspect(s.aspect);
    setLang((s.lang as "fa" | "en") || "fa");
    setScenes((s.scenes as Scene[]).map((x) => ({ ...x })));
    setIntensity(s.intensity ?? 1);
    setPlatform(s.platform ?? "");
    setCaptions(s.captions);
    setAudio(s.audio);
    if (s.brand) {
      setUseBrand(s.brand.use_brand_colors !== false);
      setShowLogo(s.brand.show_logo !== false);
    }
  }, [id]);

  // ذخیرهٔ خودکارِ طرح (هر ویرایش یک نسخه؛ ویرایش‌های پشتِ‌سرهم یکی می‌شوند)
  useEffect(() => {
    if (!ov || mode === "code" || !scenes.length) return;
    const body = JSON.stringify(spec);
    if (justApplied.current) {
      justApplied.current = false;
      lastSaved.current = body;
      return;
    }
    if (!plan && baseline.current === null) {
      baseline.current = body;              // the sample as it was loaded: nothing to save yet
      return;
    }
    if (!plan && body === baseline.current) return;
    if (body === lastSaved.current) return;
    const t = window.setTimeout(async () => {
      try {
        if (!plan) {
          const p = await motionApi.createPlan(id, spec, title);
          lastSaved.current = body;
          storeSet(planKey, String(p.id));
          setPlan(p);
          refreshPlans();
        } else {
          const r = await motionApi.savePlan(id, plan.id, spec, title);
          lastSaved.current = body;
          setPlan(r.plan);
        }
      } catch {
        /* طرحِ نامعتبر را پیش‌نمایش گزارش می‌کند */
      }
    }, 1300);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spec, mode, ov, id, tick]);

  // نتیجهٔ کنترلِ کیفیت / نقدِ تصویری در پس‌زمینه می‌رسد
  const bgRunning = plan?.qa?.state === "running" || plan?.critique?.state === "waiting" || plan?.critique?.state === "running";
  useEffect(() => {
    if (!bgRunning || !plan) return;
    const t = window.setInterval(async () => {
      try {
        const p = await motionApi.plan(id, plan.id);
        setPlan((cur) => (cur ? { ...cur, qa: p.qa, critique: p.critique, history: p.history, can_undo: p.can_undo, can_redo: p.can_redo, rev: p.rev } : cur));
        if (p.rev !== plan.rev) applyPlan(p);
      } catch {
        /* وارسیِ بعدی */
      }
    }, 3000);
    return () => window.clearInterval(t);
  }, [bgRunning, plan, id, applyPlan]);

  // live preview (debounced; stale answers are dropped)
  const seq = useRef(0);
  useEffect(() => {
    if (!ov || mode === "code" || !scenes.length) return;
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
  }, [spec, mode, ov, id, scenes.length]);

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
    const t = (lib?.templates ?? catalog?.templates ?? []).find((x) => x.id === tid);
    if (!t || !lib) return;
    setScenes(t.scenes.map((s) => ({ ...(lib.components.find((c) => c.id === s)?.sample ?? { type: s, duration: 4 }) })) as Scene[]);
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
      const r = await motionApi.ai(id, { idea, style: styleId, aspect, lang, brand, platform: platform || undefined });
      setScenes(r.spec.scenes as Scene[]);
      if (r.spec.platform) setPlatform(r.spec.platform);
      if (r.title && !title) setTitle(r.title);
      setAiNote(
        r.source === "ai"
          ? { tone: "ok", text: `سناریو نوشته شد (${fa(r.components?.length ?? 0)} قطعهٔ مرتبط به مدل داده شد)؛ پیش‌نمایش را ببینید و هر متنی را که می‌خواهید ویرایش کنید.${r.message ? " " + r.message : ""}` }
          : { tone: "warn", text: r.message },
      );
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

  /** طرح را همین حالا روی سرور بنشان (پیش از چت، کنترلِ کیفیت یا رندر) */
  const ensurePlan = async (): Promise<PlanDTO> => {
    const body = JSON.stringify(spec);
    if (plan && body === lastSaved.current) return plan;
    if (!plan) {
      const p = await motionApi.createPlan(id, spec, title);
      lastSaved.current = body;
      storeSet(planKey, String(p.id));
      setPlan(p);
      refreshPlans();
      return p;
    }
    const r = await motionApi.savePlan(id, plan.id, spec, title);
    lastSaved.current = body;
    setPlan(r.plan);
    return r.plan;
  };

  const openPlan = async (r: PlanRow) => {
    setPlanBusy(true);
    setError(null);
    try {
      applyPlan(await motionApi.plan(id, r.id));
      setChat([]);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      setError(errText(e));
    } finally {
      setPlanBusy(false);
    }
  };

  const deletePlanRow = async (r: PlanRow) => {
    if (!window.confirm(`طرحِ «${r.title || "بی‌نام"}» پاک شود؟ (ویدیوهای رندرشده در تاریخچه و رسانه می‌مانند.)`)) return;
    setPlanBusy(true);
    try {
      await motionApi.deletePlan(id, r.id);
      if (plan?.id === r.id) {
        setPlan(null);
        lastSaved.current = "";
        storeSet(planKey, "");
      }
      await refreshPlans();
    } catch (e) {
      setError(errText(e));
    } finally {
      setPlanBusy(false);
    }
  };

  /** از نمونه شروع کن؛ طرحِ فعلی در فهرست می‌ماند */
  const newPlan = () => {
    if (!ov || !lib) return;
    setPlan(null);
    setChat([]);
    lastSaved.current = "";
    justApplied.current = false;
    baseline.current = null;
    storeSet(planKey, "");
    setTitle("");
    setScenes(ov.sample_spec.scenes.map((x) => ({ ...x })) as Scene[]);
    setCaptions(undefined);
    setAudio(undefined);
    setIntensity(1);
    setPlatform("reels");
    setTick((t) => t + 1);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const planCall = async (fn: (p: PlanDTO) => Promise<PlanDTO | void>) => {
    setPlanBusy(true);
    setError(null);
    try {
      const p = await ensurePlan();
      const out = await fn(p);
      if (out) applyPlan(out);
    } catch (e) {
      setError(errText(e));
    } finally {
      setPlanBusy(false);
    }
  };

  const onChat = async (text: string) => {
    await planCall(async (p) => {
      const r = await motionApi.chat(id, p.id, text);
      setChat((c) => [...c, { q: text, say: r.say, source: r.source, applied: r.applied, message: r.message, changes: r.changes }]);
      return r.applied ? r.plan : undefined;
    });
  };

  const applyJson = async (s: Spec): Promise<string | null> => {
    try {
      const p = await ensurePlan();
      const r = await motionApi.savePlan(id, p.id, s, title);
      applyPlan(r.plan);
      if (r.notes?.length) setNotice(r.notes.join("؛ "));
      return null;
    } catch (e) {
      return errText(e);
    }
  };

  const render = async (target: "node" | "site") => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      storeSet("nm.motion.quality", quality);
      let res: { render: RenderRow; node: NodeInfo };
      if (mode === "code") {
        const body: Record<string, unknown> = { mode: "code", title, quality, target, code };
        if (meta) {
          body.width = meta.width;
          body.height = meta.height;
        }
        res = await motionApi.render(id, body);
      } else {
        const p = await ensurePlan();
        res = await motionApi.renderPlan(id, p.id, { mode, title, quality, target, qa: qaOnRender, critique: critiqueOnRender });
      }
      setOv((o) => (o ? { ...o, node: res.node, renders: [res.render, ...o.renders.filter((x) => x.id !== res.render.id)] } : o));
      setNotice(
        res.render.target === "site"
          ? "رندر روی سایت شروع شد: ابتدا کنترلِ کیفیت و (اگر خواسته باشید) صدا، بعد رندر."
          : res.render.state === "WAITING_NODE"
            ? "رندر در صفِ سرورِ پردازش است و با روشن شدنِ آن خودکار انجام می‌شود."
            : "کنترلِ کیفیت و صدا انجام می‌شود، سپس رندر به سرورِ پردازش می‌رود.",
      );
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
        setPlan(null);
        lastSaved.current = "";
        setStyleId(full.spec.style);
        setAspect(full.spec.aspect);
        setLang((full.spec.lang as "fa" | "en") || "fa");
        setScenes(full.spec.scenes as Scene[]);
        setPlatform(full.spec.platform ?? "");
        setCaptions(full.spec.captions);
        setAudio(full.spec.audio);
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

  const findings = useMemo(() => {
    const out: Record<number, { severity: "error" | "warn" | "info"; message: string }[]> = {};
    for (const f of plan?.qa?.remaining ?? []) if (f.scene !== null && f.scene !== undefined) (out[f.scene] ||= []).push({ severity: f.severity, message: f.message });
    return out;
  }, [plan?.qa]);

  if (!catalog || !ov || !lib) {
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
        subtitle="موشن‌گرافیک از روی کد (Remotion): قطعه‌های آمادهٔ فارسی، کنترلِ کیفیتِ خودکار، گویندهٔ فارسی و موسیقی، رندرِ نهایی روی کارتِ گرافیک"
        actions={
          <div className="flex items-center gap-2">
            <Badge tone="brand">{fa(catalog.styles.length)} سبک</Badge>
            <Badge tone="info">{fa(lib.components.length)} قطعه</Badge>
          </div>
        }
      />
      <NodeBanner node={ov.node} site={ov.site} limits={ov.limits} />
      <div className="mt-3 space-y-3">
        <ErrorBox message={error} />
        {notice ? <Alert tone="info">{notice}</Alert> : null}
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1fr)_440px]">
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

          {mode !== "code" ? <PlanList rows={plansList} currentId={plan?.id ?? null} busy={planBusy} onOpen={openPlan} onDelete={deletePlanRow} onNew={newPlan} /> : null}

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
                      مدل فقط قطعه‌های مرتبط را می‌بیند و خروجیِ JSON ِ مقیّد می‌دهد؛ هوش مصنوعی در دسترس نباشد، یک پیش‌نویسِ ساده از روی متنت ساخته می‌شود.
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
                    {(lib.templates ?? catalog.templates).map((t) => (
                      <Button key={t.id} variant="secondary" size="sm" type="button" onClick={() => loadTemplate(t.id)}>
                        {t.name}
                      </Button>
                    ))}
                  </div>
                  <div className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
                    قالب را بزنید تا صحنه‌ها با متنِ نمونه پر شوند؛ بعد متن‌ها را عوض کنید یا از «افزودنِ صحنه» قطعهٔ دلخواه را بگذارید.
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
                <SectionTitle
                  action={
                    <div className="flex gap-1">
                      <Button variant={tab === "plan" ? "primary" : "secondary"} size="sm" type="button" onClick={() => setTab("plan")}>
                        کارت‌های صحنه
                      </Button>
                      <Button variant={tab === "json" ? "primary" : "secondary"} size="sm" type="button" onClick={() => setTab("json")}>
                        JSON خام
                      </Button>
                    </div>
                  }
                >
                  طرحِ صحنه‌ها
                </SectionTitle>
                {tab === "plan" ? (
                  <ScenePlan scenes={scenes} onChange={setScenes} lib={lib} sources={sources} onUpload={upload} maxScenes={ov.limits.max_scenes} brandColors={ov.brand.colors} findings={findings} />
                ) : (
                  <Card>
                    <PlanJson spec={spec} onApply={applyJson} />
                  </Card>
                )}
              </div>

              {plan?.warnings?.length ? (
                <Alert tone="warn" title="یک نکته دربارهٔ صدا">
                  {plan.warnings.join(" ")}
                </Alert>
              ) : null}

              <Card>
                <SectionTitle>صدا، زیرنویس و پلتفرم</SectionTitle>
                <SoundPanel
                  spec={spec}
                  lib={lib}
                  sound={sound}
                  onChange={(p) => {
                    if ("audio" in p) setAudio(p.audio);
                    if ("platform" in p) setPlatform(p.platform ?? "");
                    if ("captions" in p) setCaptions(p.captions);
                  }}
                />
              </Card>
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
                  کدِ نوشته‌شده همیشه از همان اسکنرِ امنیتی می‌گذرد. (قطعه‌های آماده فقط در حالتِ قالبی/هوشمند هستند؛ کدِ آزاد برای جاهایی است که قطعه‌ای نیست.)
                </div>
              </Card>
            </>
          )}
        </div>

        {/* ───────── پیش‌نمایش و رندر */}
        <div className="min-w-0 space-y-4 xl:sticky xl:top-4 xl:self-start xl:max-h-[calc(100vh-2rem)] xl:overflow-y-auto">
          <Card>
            <SectionTitle>پیش‌نمایشِ زنده</SectionTitle>
            <PlayerFrame ref={player} onMeta={onMeta} onError={mode === "code" ? onPlayerError : undefined} aspect={mode === "code" && meta ? meta.width / meta.height : (aspectDef?.width ?? 9) / (aspectDef?.height ?? 16)} maxHeight={480} />
            {previewErr && mode !== "code" ? (
              <div className="mt-3">
                <ErrorBox message={previewErr} />
              </div>
            ) : null}
            <div className="mt-3 text-xs leading-6" style={{ color: "var(--text-3)" }}>
              {mode === "code"
                ? meta
                  ? `${fa(meta.width)}×${fa(meta.height)} · ${fa(meta.fps)} فریم‌بر‌ثانیه · ${fa((meta.durationInFrames / meta.fps).toFixed(1))} ثانیه`
                  : "منتظرِ کد…"
                : `${fa(total.toFixed(1))} ثانیه (حداکثر ${fa(totalMax)})`}
              {" "}— پیش‌نمایش با همان موتورِ رندر ساخته می‌شود (بی‌صدا)؛ صدا هنگامِ رندر ساخته و ترکیب می‌شود.
            </div>
            {mode !== "code" ? (
              <div className="mt-3">
                <HistoryBar
                  plan={plan}
                  busy={planBusy}
                  onUndo={() => planCall(async (p) => motionApi.planStep(id, p.id, "undo"))}
                  onRedo={() => planCall(async (p) => motionApi.planStep(id, p.id, "redo"))}
                  onRestore={(n) => planCall(async (p) => motionApi.restore(id, p.id, n))}
                />
              </div>
            ) : null}
          </Card>

          {mode !== "code" ? (
            <Card>
              <SectionTitle>ویرایش با چت</SectionTitle>
              <ChatEdit lines={chat} busy={planBusy} disabled={!scenes.length} onSend={onChat} />
            </Card>
          ) : null}

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
            {mode !== "code" ? (
              <div className="mt-3 space-y-1 text-sm" style={{ color: "var(--text-2)" }}>
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={qaOnRender} onChange={(e) => setQaOnRender(e.target.checked)} /> کنترلِ کیفیت و اصلاحِ خودکار پیش از رندر
                </label>
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={critiqueOnRender} onChange={(e) => setCritiqueOnRender(e.target.checked)} /> نقدِ تصویری با مدلِ بینا هم انجام شود (در صفِ سرورِ پردازش؛ نتیجه به طرح برمی‌گردد)
                </label>
              </div>
            ) : null}
            <div className="mt-4 flex flex-wrap gap-2">
              <Button type="button" onClick={() => render("node")} disabled={busy || !codeOk || !scenes.length}>
                <Icon name="rocket" size={15} /> {ov.node.state === "none" ? "رندر" : "رندر روی سرورِ پردازش"}
              </Button>
              {nodeWaiting && canSite ? (
                <Button type="button" variant="secondary" onClick={() => render("site")} disabled={busy || !codeOk} title={`محدود: ${fa(ov.limits.max_total_site)} ثانیه، ${fa(ov.limits.site_max_short_side)}p`}>
                  <Icon name="cloud" size={15} /> رندر روی سایت
                </Button>
              ) : null}
            </div>
            <div className="mt-2 text-xs leading-6" style={{ color: "var(--text-3)" }}>
              ویدیو بعد از پایانِ رندر در «رسانهٔ فروشگاه» و سطلِ ادیتورِ ویدیو (با نامِ «موشن — …») می‌آید و با «باز کردن در ادیتورِ ویدیو» روی خطِ زمانِ دستی می‌نشیند.
            </div>
          </Card>

          {mode !== "code" ? (
            <Card>
              <SectionTitle>کنترلِ کیفیت و نقدِ تصویری</SectionTitle>
              <QaPanel
                qa={plan?.qa}
                critique={plan?.critique}
                busy={planBusy}
                hasPlan={!!scenes.length}
                onQa={() => planCall(async (p) => (await motionApi.runQa(id, p.id, true, true)) as PlanDTO)}
                onCritique={() => planCall(async (p) => (await motionApi.runCritique(id, p.id)) as PlanDTO)}
              />
            </Card>
          ) : null}
        </div>
      </div>

      <div className="mt-8">
        <SectionTitle>تاریخچه</SectionTitle>
        <RenderHistory renders={ov.renders} storeId={id} onAct={act} onDelete={del} onReuse={reuse} nodeWaiting={nodeWaiting} />
      </div>
    </div>
  );
}
