import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, errorMessage } from "../../../api/client";
import { Alert, Badge, Button, Card, EmptyState, ErrorBox, Input, PageHeader, Select, Spinner, fa } from "../../../components/ui";
import ImagePicker from "./ImagePicker";
import IdeasPanel from "./IdeasPanel";
import {
  BgJob, CutoutNodeModel, Idea, LibraryAsset, Overview, Preview, Spec, ThumbItem, aspectStyle, applyIdea, defaultSpec, thumbsApi,
} from "./api";
import "./thumbs.css";

type Slot = "subject" | "subject2" | "background" | "extra";
const BG_TEXTURES = [
  { key: "", label: "پیش‌فرضِ سبک" },
  { key: "halftone", label: "نقطه‌چین" },
  { key: "rays", label: "پرتوها" },
  { key: "grid", label: "شبکه" },
  { key: "stripes", label: "راه‌راه" },
  { key: "grain", label: "دانهٔ فیلم" },
];
const LOGO_POS = [
  { key: "auto", label: "خودکار" }, { key: "tl", label: "بالا-چپ" }, { key: "tr", label: "بالا-راست" },
  { key: "bl", label: "پایین-چپ" }, { key: "br", label: "پایین-راست" }, { key: "tc", label: "بالا-وسط" }, { key: "bc", label: "پایین-وسط" },
];

function isCancel(e: unknown): boolean {
  return typeof e === "object" && e !== null && (e as { code?: string }).code === "ERR_CANCELED";
}

/** دانلود با توکنِ ورود (لینکِ ساده سرآیندِ Authorization ندارد). */
async function downloadBlob(path: string, filename: string) {
  const res = await api.get(path, { responseType: "blob" });
  const url = URL.createObjectURL(res.data as Blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 4000);
}

export default function ThumbnailMakerPage() {
  const { id = "" } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [ov, setOv] = useState<Overview | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [spec, setSpec] = useState<Spec | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [prevBusy, setPrevBusy] = useState(false);
  const [prevError, setPrevError] = useState<string | null>(null);
  const [assets, setAssets] = useState<Record<number, LibraryAsset>>({});
  const [picker, setPicker] = useState<Slot | null>(null);
  const [variants, setVariants] = useState(3);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [batch, setBatch] = useState<ThumbItem[]>([]);
  const [history, setHistory] = useState<ThumbItem[]>([]);
  const [editing, setEditing] = useState<number | null>(null);
  const [showLayers, setShowLayers] = useState(false);
  // پس‌زمینهٔ هوش مصنوعی
  const [bgPreset, setBgPreset] = useState("");
  const [bgText, setBgText] = useState("");
  const [bgJobs, setBgJobs] = useState<BgJob[]>([]);
  const [bgCount, setBgCount] = useState(2);
  const [bgBusy, setBgBusy] = useState(false);
  const [bgNote, setBgNote] = useState<string | null>(null);
  // حذفِ پس‌زمینه
  const [cutBusy, setCutBusy] = useState(false);
  const [cutMsg, setCutMsg] = useState<string | null>(null);
  const [cutModels, setCutModels] = useState<CutoutNodeModel[] | null>(null);
  const [cutJob, setCutJob] = useState<{ uid: string; slot: "subject" | "subject2" } | null>(null);
  const previewTop = useRef<HTMLDivElement>(null);
  const outputTop = useRef<HTMLDivElement>(null);

  // ---------- بارگیری
  const load = useCallback(async () => {
    try {
      const o = await thumbsApi.overview(id);
      setOv(o);
      setHistory(o.items);
      setSpec((cur) => cur ?? defaultSpec(o.default_format, "face_text"));
      const lib = await thumbsApi.library(id).catch(() => [] as LibraryAsset[]);
      setAssets(Object.fromEntries(lib.map((a) => [a.id, a])));
    } catch (e) {
      setLoadError(errorMessage(e));
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  // ---------- پیش‌نمایشِ زنده (با تأخیر؛ درخواستِ کهنه لغو می‌شود)
  const specKey = useMemo(() => (spec ? JSON.stringify(spec) : ""), [spec]);
  useEffect(() => {
    if (!spec) return;
    const ctl = new AbortController();
    const t = window.setTimeout(async () => {
      setPrevBusy(true);
      try {
        const p = await thumbsApi.preview(id, spec, ctl.signal);
        setPreview(p);
        setPrevError(null);
      } catch (e) {
        if (!isCancel(e)) setPrevError(errorMessage(e));
      } finally {
        if (!ctl.signal.aborted) setPrevBusy(false);
      }
    }, 650);
    return () => {
      window.clearTimeout(t);
      ctl.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, specKey]);

  // ---------- پیگیریِ تامنیل‌های منتظرِ پس‌زمینه (خودشان کامل می‌شوند)
  const anyWaiting = [...batch, ...history].some((i) => i.waiting_bg);
  useEffect(() => {
    if (!anyWaiting) return;
    const t = window.setInterval(async () => {
      try {
        const res = await thumbsApi.items(id);
        const by = new Map(res.items.map((i) => [i.id, i]));
        setHistory(res.items);
        setBatch((cur) => cur.map((i) => by.get(i.id) ?? i));
      } catch {
        /* شبکه: دورِ بعد */
      }
    }, 6000);
    return () => window.clearInterval(t);
  }, [anyWaiting, id]);

  // ---------- پیگیریِ کارهای پس‌زمینه
  const bgActive = bgJobs.filter((j) => ["QUEUED", "RUNNING"].includes(j.state)).map((j) => j.job);
  useEffect(() => {
    if (!bgActive.length) return;
    const t = window.setInterval(async () => {
      const next = await Promise.all(bgJobs.map(async (j) => {
        if (!bgActive.includes(j.job)) return j;
        try { return { ...j, ...(await thumbsApi.bgStatus(id, j.job)) }; } catch { return j; }
      }));
      setBgJobs(next);
      const done = next.filter((j) => j.state === "READY" && j.asset);
      if (done.length) setAssets((cur) => ({ ...cur, ...Object.fromEntries(done.map((j) => [j.asset!.id, j.asset!])) }));
    }, 4000);
    return () => window.clearInterval(t);
  }, [bgActive.join(","), id]);

  // ---------- پیگیریِ برشِ سرورِ پردازش
  useEffect(() => {
    if (!cutJob) return;
    const t = window.setInterval(async () => {
      try {
        const st = await thumbsApi.cutoutStatus(id, cutJob.uid);
        setCutMsg(st.message);
        if (st.state === "ready" && st.asset) {
          setAssets((cur) => ({ ...cur, [st.asset!.id]: st.asset! }));
          setSpec((s) => (s ? (cutJob.slot === "subject" ? { ...s, subject: { ...s.subject, asset: st.asset!.id } } : { ...s, subject2: { asset: st.asset!.id } }) : s));
          setCutJob(null);
          setCutMsg("پس‌زمینه برداشته شد و عکسِ بریده جایگزین شد.");
        } else if (st.state === "failed" || st.state === "cancelled") {
          setCutJob(null);
        }
      } catch {
        /* دورِ بعد */
      }
    }, 4000);
    return () => window.clearInterval(t);
  }, [cutJob, id]);

  if (loadError) return <ErrorBox message={loadError} />;
  if (!ov || !spec) return <Spinner />;

  const fmt = ov.formats.find((f) => f.key === spec.format) ?? ov.formats[0];
  const style = ov.styles.find((s) => s.key === spec.style) ?? ov.styles[0];
  const subjectAsset = spec.subject.asset ? assets[spec.subject.asset] : undefined;
  const subject2Asset = spec.subject2.asset ? assets[spec.subject2.asset] : undefined;
  const bgAsset = spec.background.asset ? assets[spec.background.asset] : undefined;
  const set = (patch: Partial<Spec>) => setSpec((s) => (s ? { ...s, ...patch } : s));
  const setContent = (key: string, value: string) => setSpec((s) => (s ? { ...s, content: { ...s.content, [key]: value } } : s));

  function pickFor(slot: Slot, a: LibraryAsset) {
    setAssets((cur) => ({ ...cur, [a.id]: a }));
    setSpec((s) => {
      if (!s) return s;
      if (slot === "subject") return { ...s, subject: { ...s.subject, asset: a.id } };
      if (slot === "subject2") return { ...s, subject2: { asset: a.id } };
      if (slot === "background") return { ...s, background: { ...s.background, kind: "photo", asset: a.id } };
      return { ...s, extra_assets: [...s.extra_assets.filter((x) => x !== a.id), a.id].slice(0, 4) };
    });
    setPicker(null);
  }

  function useIdea(idea: Idea) {
    setSpec((s) => (s ? applyIdea(s, idea, false) : s));
    setNotice(`ایدهٔ «${idea.title.replace(/\*/g, "")}» اعمال شد؛ متن‌ها را بخوانید و در صورتِ نیاز ویرایش کنید.`);
    if (idea.bg_prompt_en) setBgNote(null);
    previewTop.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function useStyle(styleKey: string, format: string) {
    setSpec((s) => (s ? { ...s, style: styleKey, format } : s));
    previewTop.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function runCutout(slot: "subject" | "subject2", model: string) {
    const a = slot === "subject" ? subjectAsset : subject2Asset;
    if (!a) return;
    setCutBusy(true);
    setCutMsg(null);
    setError(null);
    try {
      const res = await thumbsApi.cutout(id, a.id, model);
      if (res.state === "ready" && res.asset) {
        pickFor(slot, res.asset);
        setCutMsg(res.message ?? "پس‌زمینه برداشته شد.");
        setCutModels(null);
      } else if (res.state === "queued" && res.uid) {
        setCutJob({ uid: res.uid, slot });
        setCutMsg("در صفِ سرورِ پردازش؛ وقتی آماده شد خودکار جایگزین می‌شود.");
      } else {
        setCutMsg(res.message ?? "برش انجام نشد.");
        const m = await thumbsApi.cutoutModels(id).catch(() => null);
        setCutModels(m && m.node_known ? m.models : []);
      }
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setCutBusy(false);
    }
  }

  async function makeBackgrounds() {
    if (!spec) return;
    setBgBusy(true);
    setBgNote(null);
    setError(null);
    try {
      const res = await thumbsApi.bgCreate(id, {
        format: spec.format, style: spec.style, preset: bgPreset || undefined, text: bgText || undefined, count: bgCount, use_brand: spec.colors.use_brand,
      });
      setBgJobs((cur) => [...res.jobs, ...cur].slice(0, 9));
      setBgNote(res.note || null);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBgBusy(false);
    }
  }

  async function build() {
    if (!spec) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (editing) {
        const item = await thumbsApi.patch(id, editing, { spec });
        setBatch([item]);
        setNotice("تغییرها روی همان تامنیل اعمال شد.");
      } else {
        const hasAi = spec.background.kind === "ai" && !spec.background.asset;
        const res = await thumbsApi.render(id, {
          spec, variants, ai: hasAi ? { preset: bgPreset || undefined, text: bgText || undefined } : undefined,
        });
        setBatch(res.items);
        setNotice(`${fa(res.items.length)} نسخه ساخته شد.`);
        // نتیجه زیرِ ستون‌ها می‌آید؛ بعد از ساخت همان‌جا می‌بریمش تا نتیجه را ببیند.
        window.setTimeout(() => outputTop.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
      }
      const o = await thumbsApi.items(id);
      setHistory(o.items);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function editItem(it: ThumbItem) {
    try {
      const full = it.spec ? it : await thumbsApi.item(id, it.id);
      if (full.spec) {
        setSpec({ ...full.spec, background: full.spec.background.kind === "ai" && !full.spec.background.asset ? { ...full.spec.background, job: "" } : full.spec.background });
        setEditing(full.id);
        setNotice(`در حالِ ویرایشِ «${full.title}» — هر تغییر در پیش‌نمایش دیده می‌شود؛ «به‌روزرسانی» همان را عوض می‌کند.`);
        previewTop.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  async function removeItem(it: ThumbItem) {
    if (!window.confirm(`«${it.title}» پاک شود؟`)) return;
    try {
      await thumbsApi.remove(id, it.id);
      setBatch((c) => c.filter((x) => x.id !== it.id));
      setHistory((c) => c.filter((x) => x.id !== it.id));
      if (editing === it.id) setEditing(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  async function toEditor(it: ThumbItem) {
    try {
      const res = await thumbsApi.openInEditor(id, it.id);
      navigate(res.url);
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  function card(it: ThumbItem, compact = false) {
    return (
      <div key={it.id} className="th-card" data-testid="thumb-card">
        {it.urls.thumb ? <img src={it.urls.thumb} alt={it.title} loading="lazy" style={aspectStyle({ width: it.width || 16, height: it.height || 9 })} /> : <span className="dz-noimg" />}
        <div className="th-card-meta">
          {it.variant && <Badge tone="brand">{it.variant}</Badge>}
          <b>{it.style_title}</b>
          <span>{it.format_title}</span>
          {it.state === "WAITING_BG" && <Badge tone="warn">منتظرِ پس‌زمینه</Badge>}
          {it.state === "FAILED" && <Badge tone="bad">ناموفق</Badge>}
        </div>
        {it.variant_note && !compact && <div className="dz-muted">{it.variant_note}</div>}
        {it.message && <div className="dz-muted">{it.message}</div>}
        {it.warnings.map((w) => <div key={w} className="dz-muted" style={{ color: "var(--warn)" }}>{w}</div>)}
        {it.urls.png && (
          <div className="th-card-actions">
            <a className="u-btn u-btn-secondary u-btn-sm" href={it.urls.png} download={`thumbnail-${it.id}.png`}>PNG</a>
            {it.urls.jpg && <a className="u-btn u-btn-secondary u-btn-sm" href={it.urls.jpg} download={`thumbnail-${it.id}.jpg`}>JPG ({fa(it.size_kb)} کیلوبایت)</a>}
            <Button size="sm" variant="secondary" onClick={() => void editItem(it)}>ویرایش</Button>
            <Button size="sm" variant="secondary" onClick={() => void toEditor(it)}>باز کردن در ادیتور عکس</Button>
            <Button size="sm" variant="ghost" onClick={() => void downloadBlob(thumbsApi.layersUrl(id, it.id), `thumbnail-${it.id}-layers.psd`).catch((e) => setError(errorMessage(e)))}>فایل لایه‌دار</Button>
            <Button size="sm" variant="ghost" onClick={() => void removeItem(it)}>حذف</Button>
          </div>
        )}
      </div>
    );
  }

  const slotRow = (label: string, asset: LibraryAsset | undefined, slot: Slot, onClear: () => void, extra?: ReactNode) => (
    <div className="th-slot">
      {asset?.thumb ? <img src={asset.thumb} alt={asset.title} /> : <span className="th-slot-empty">+</span>}
      <div className="th-slot-body">
        <b>{asset ? asset.title || `عکس ${fa(asset.id)}` : label}</b>
        <span className="dz-muted">{asset ? `${fa(asset.width)}×${fa(asset.height)}${asset.has_alpha ? " · پس‌زمینهٔ شفاف" : ""}` : "هنوز انتخاب نشده"}</span>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" onClick={() => setPicker(slot)}>{asset ? "تعویض" : "انتخابِ عکس"}</Button>
          {asset && <Button size="sm" variant="ghost" onClick={onClear}>برداشتن</Button>}
          {extra}
        </div>
      </div>
    </div>
  );

  const cutButton = (slot: "subject" | "subject2", asset: LibraryAsset | undefined) =>
    asset && !asset.has_alpha ? (
      <Button size="sm" variant="secondary" disabled={cutBusy || !!cutJob} onClick={() => void runCutout(slot, "rvm")}>
        {cutBusy ? "در حالِ برش…" : "حذفِ پس‌زمینه"}
      </Button>
    ) : null;

  const isPortraitish = fmt.height > fmt.width;
  const brand = ov.brand;

  return (
    <>
      <PageHeader
        title="تامنیل‌ساز"
        subtitle="کاورِ یوتیوب، اینستاگرام، پینترست و پوسترِ فیلم — با ایده‌پردازی، نسخه‌های A/B و پس‌زمینهٔ هوش مصنوعی؛ متنِ فارسی همیشه درست و خوانا کشیده می‌شود"
        actions={<Link to={`/stores/${id}/photo-editor`} className="u-btn u-btn-secondary">ادیتور عکس</Link>}
      />
      <div className="th-root">
        {/* ───────────── کنترل‌ها */}
        <div className="th-controls">
          <IdeasPanel
            storeId={id}
            format={spec.format}
            formats={ov.formats}
            products={ov.products}
            onUse={useIdea}
            onUseStyle={useStyle}
          />

          <Card>
            <h2 className="th-section-title"><i>۱</i> قالب و سبک</h2>
            <div className="th-formats" role="group" aria-label="قالب">
              {ov.formats.map((f) => (
                <button key={f.key} type="button" className="th-format" aria-pressed={f.key === spec.format} onClick={() => set({ format: f.key })} title={f.note}>
                  <b>{f.title}</b>
                  <span>{fa(f.width)}×{fa(f.height)} · {f.aspect}</span>
                </button>
              ))}
            </div>
            <p className="dz-muted mt-2">{fmt.note}</p>
            <div className="th-styles mt-3" style={{ ["--th-ar" as string]: `${fmt.width} / ${fmt.height}` }}>
              {ov.styles.map((s) => (
                <button key={s.key} type="button" className="th-style" aria-pressed={s.key === spec.style} onClick={() => set({ style: s.key })} title={s.pattern}>
                  <img src={thumbsApi.sampleUrl(id, s.key, spec.format)} alt={s.title} loading="lazy" />
                  <b>{s.title}</b>
                  {s.formats.includes(spec.format) && <span className="th-rec">مناسبِ این قالب</span>}
                </button>
              ))}
            </div>
            <p className="dz-muted mt-2">{style.pattern}</p>
            {style.tips.map((t) => <p key={t} className="dz-muted">• {t}</p>)}
          </Card>

          <Card>
            <h2 className="th-section-title"><i>۲</i> متن</h2>
            <div className="th-fields">
              {style.fields.map((f) => (
                <label key={f.key} className={`dz-field ${f.key === "title" || f.key === "credits" ? "wide" : ""}`}>
                  <span>{f.label}</span>
                  <Input
                    value={spec.content[f.key as keyof Spec["content"]] ?? ""}
                    maxLength={ov.limits.text[f.key] ?? 100}
                    onChange={(e) => setContent(f.key, e.target.value)}
                    placeholder={f.key === "title" ? "مثلاً: *۷* اشتباهِ رایج در ورزش" : undefined}
                  />
                </label>
              ))}
            </div>
            <p className="dz-muted mt-2">کلمهٔ مهم را بینِ دو ستاره بگذارید تا رنگی شود: <b>*کلمه*</b> — «|» یعنی «اینجا خط را بشکن». رقم‌ها خودکار فارسی می‌شوند.</p>
          </Card>

          <Card>
            <h2 className="th-section-title"><i>۳</i> تصویرها</h2>
            <div className="flex flex-col gap-3">
              {slotRow(style.needs_second ? "سوژهٔ اول (بعد / سمتِ اول)" : style.subject === "none" ? "سوژه (اختیاری)" : "سوژه (چهره یا کالا)", subjectAsset, "subject",
                () => set({ subject: { ...spec.subject, asset: null } }), cutButton("subject", subjectAsset))}
              {style.needs_second && slotRow("سوژهٔ دوم (قبل / سمتِ دوم)", subject2Asset, "subject2", () => set({ subject2: { asset: null } }), cutButton("subject2", subject2Asset))}
              {cutMsg && <Alert tone="info"><span className="text-sm">{cutMsg}</span></Alert>}
              {cutModels && cutModels.length > 0 && (
                <div className="dz-box">
                  <b>برشِ دقیق‌تر با سرورِ پردازش (کارتِ گرافیک):</b>
                  <div className="mt-1 flex flex-wrap gap-2">
                    {cutModels.map((m) => (
                      <Button key={m.id} size="sm" variant="secondary" title={m.hint} disabled={cutBusy || !!cutJob} onClick={() => void runCutout("subject", m.id)}>
                        {m.title}
                      </Button>
                    ))}
                  </div>
                  <p className="dz-muted">اگر سرورِ پردازش خاموش باشد، درخواست در صف می‌ماند و بعداً خودکار انجام می‌شود.</p>
                </div>
              )}
              <div className="th-fields">
                <label className="dz-field">
                  <span>حالتِ سوژه</span>
                  <Select value={spec.subject.mode} onChange={(e) => set({ subject: { ...spec.subject, mode: e.target.value as Spec["subject"]["mode"] } })}>
                    <option value="auto">خودکار (بریده اگر ممکن بود)</option>
                    <option value="cutout">حتماً بریده</option>
                    <option value="photo">همان عکسِ کامل</option>
                  </Select>
                </label>
                <label className="dz-field">
                  <span>سمتِ سوژه</span>
                  <Select value={spec.subject.side} onChange={(e) => set({ subject: { ...spec.subject, side: e.target.value as Spec["subject"]["side"] } })}>
                    <option value="auto">خودکار</option>
                    <option value="left">چپ</option>
                    <option value="right">راست</option>
                  </Select>
                </label>
                <label className="dz-field wide">
                  <span>اندازهٔ سوژه</span>
                  <div className="dz-range">
                    <input type="range" min={0.6} max={1.3} step={0.05} value={spec.subject.scale} onChange={(e) => set({ subject: { ...spec.subject, scale: Number(e.target.value) } })} />
                    <b>{fa(Math.round(spec.subject.scale * 100))}٪</b>
                  </div>
                </label>
                <label className="dz-field check">
                  <input type="checkbox" checked={spec.subject.outline} onChange={(e) => set({ subject: { ...spec.subject, outline: e.target.checked } })} />
                  <span>حاشیهٔ سفیدِ دورِ سوژه</span>
                </label>
                <label className="dz-field check">
                  <input type="checkbox" checked={spec.accents.arrow} onChange={(e) => set({ accents: { ...spec.accents, arrow: e.target.checked } })} />
                  <span>فلشِ اشاره به سوژه (در سبک‌های مناسب)</span>
                </label>
              </div>
              {style.key === "pinterest_collage" && (
                <div className="dz-box">
                  <b>عکس‌های بیشتر برای کلاژ ({fa(spec.extra_assets.length)} از ۴)</b>
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    {spec.extra_assets.map((aid) => (
                      <button key={aid} type="button" className="th-bg" onClick={() => set({ extra_assets: spec.extra_assets.filter((x) => x !== aid) })} title="برای برداشتن بزنید">
                        {assets[aid]?.thumb ? <img src={assets[aid].thumb!} alt="" /> : <span className="th-bg-wait">عکس {fa(aid)}</span>}
                      </button>
                    ))}
                    {spec.extra_assets.length < 4 && <Button size="sm" variant="secondary" onClick={() => setPicker("extra")}>افزودنِ عکس</Button>}
                  </div>
                </div>
              )}
            </div>
          </Card>

          <Card>
            <h2 className="th-section-title"><i>۴</i> پس‌زمینه</h2>
            <div className="th-fields">
              <label className="dz-field">
                <span>نوع</span>
                <Select value={spec.background.kind} onChange={(e) => set({ background: { ...spec.background, kind: e.target.value as Spec["background"]["kind"] } })}>
                  <option value="auto">خودکار (رنگِ برند + بافت)</option>
                  <option value="photo">عکسِ من</option>
                  <option value="ai">هوش مصنوعی (روی کارتِ گرافیک)</option>
                </Select>
              </label>
              <label className="dz-field">
                <span>بافتِ پس‌زمینه</span>
                <Select value={spec.background.texture} onChange={(e) => set({ background: { ...spec.background, texture: e.target.value } })}>
                  {BG_TEXTURES.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
                </Select>
              </label>
            </div>
            {spec.background.kind === "photo" && (
              <div className="mt-3">
                {slotRow("عکسِ پس‌زمینه", bgAsset, "background", () => set({ background: { ...spec.background, asset: null } }))}
              </div>
            )}
            {spec.background.kind === "ai" && (
              <div className="mt-3 flex flex-col gap-3">
                <Alert tone={ov.ai_background.possible ? (ov.ai_background.online ? "ok" : "warn") : "bad"}>
                  <span className="text-sm">{ov.ai_background.message}{ov.ai_background.model ? ` (مدل: ${ov.ai_background.model})` : ""}</span>
                </Alert>
                {ov.ai_background.selftest && ov.ai_background.selftest.message && (
                  <p className="th-selftest th-wrap" data-state={ov.ai_background.selftest.state}>
                    {ov.ai_background.selftest.message}
                  </p>
                )}
                <div className="th-fields">
                  <label className="dz-field">
                    <span>صحنهٔ آماده</span>
                    <Select value={bgPreset} onChange={(e) => setBgPreset(e.target.value)}>
                      <option value="">پیشنهادِ خودکارِ سبک</option>
                      {ov.bg_presets.map((p) => <option key={p.key} value={p.key}>{p.title}</option>)}
                    </Select>
                  </label>
                  <label className="dz-field">
                    <span>تعداد</span>
                    <Select value={bgCount} onChange={(e) => setBgCount(Number(e.target.value))}>
                      {[1, 2, 3].map((n) => <option key={n} value={n}>{fa(n)}</option>)}
                    </Select>
                  </label>
                  <label className="dz-field wide">
                    <span>یا خودتان توضیح بدهید (فارسی؛ به انگلیسی ترجمه می‌شود)</span>
                    <Input value={bgText} onChange={(e) => setBgText(e.target.value)} placeholder="مثلاً: باشگاهِ مدرن با نورِ گرم و پس‌زمینهٔ محو" />
                  </label>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button size="sm" onClick={() => void makeBackgrounds()} disabled={bgBusy || !ov.ai_background.possible}>
                    {bgBusy ? "در حالِ ثبت…" : "ساختنِ پس‌زمینه"}
                  </Button>
                  <span className="dz-muted">فقط پس‌زمینه ساخته می‌شود؛ متنِ فارسی را همیشه خودِ تامنیل‌ساز می‌کشد، پس غلطِ املایی ندارد.</span>
                </div>
                {bgNote && <p className="dz-muted" style={{ color: "var(--warn)" }}>{bgNote}</p>}
                {bgJobs.length > 0 && (
                  <div className="th-bg-list">
                    {bgJobs.map((j) => (
                      j.state === "READY" && j.asset ? (
                        <button key={j.job} type="button" className="th-bg" aria-pressed={spec.background.asset === j.asset.id}
                          onClick={() => set({ background: { ...spec.background, kind: "ai", asset: j.asset!.id } })} title="انتخاب">
                          {j.asset.thumb && <img src={j.asset.thumb} alt="پس‌زمینهٔ هوش مصنوعی" />}
                        </button>
                      ) : (
                        <div key={j.job} className="th-bg">
                          <div className="th-bg-wait">{j.state === "FAILED" ? (j.error ?? "ناموفق") : j.state === "CANCELLED" ? "لغو شد" : j.message || "در صف…"}</div>
                        </div>
                      )
                    ))}
                  </div>
                )}
                {!spec.background.asset && (
                  <p className="dz-muted">اگر پس‌زمینه‌ای انتخاب نکنید، هنگامِ «ساخت» خودکار یکی ساخته می‌شود؛ تا آماده شدنش تامنیل با پس‌زمینهٔ موقت دیده می‌شود و خودش کامل می‌شود (حتی اگر سرورِ پردازش الان خاموش باشد).</p>
                )}
              </div>
            )}
            <div className="th-fields mt-3">
              <label className="dz-field">
                <span>تیره‌کردنِ پس‌زمینه</span>
                <div className="dz-range">
                  <input type="range" min={0} max={0.8} step={0.05} value={spec.background.darken} onChange={(e) => set({ background: { ...spec.background, darken: Number(e.target.value) } })} />
                  <b>{fa(Math.round(spec.background.darken * 100))}٪</b>
                </div>
              </label>
              <label className="dz-field">
                <span>محو‌کردن</span>
                <div className="dz-range">
                  <input type="range" min={0} max={30} step={1} value={spec.background.blur} onChange={(e) => set({ background: { ...spec.background, blur: Number(e.target.value) } })} />
                  <b>{fa(spec.background.blur)}</b>
                </div>
              </label>
            </div>
          </Card>

          <Card>
            <h2 className="th-section-title"><i>۵</i> رنگ، فونت و برند</h2>
            <div className="th-fields">
              <label className="dz-field check wide">
                <input type="checkbox" checked={spec.colors.use_brand} onChange={(e) => set({ colors: { ...spec.colors, use_brand: e.target.checked } })} />
                <span>
                  از رنگ‌های برندِ فروشگاه استفاده شود{" "}
                  {brand.colors.length > 0 ? <span className="th-swatches">{brand.colors.map((c) => <i key={c} style={{ background: c }} title={c} />)}</span> : <em className="dz-muted">(رنگِ برند ثبت نشده؛ رنگ‌های پیش‌فرضِ سبک)</em>}
                </span>
              </label>
              <label className="dz-field">
                <span>حال‌وهوا</span>
                <Select value={spec.colors.mood} onChange={(e) => set({ colors: { ...spec.colors, mood: e.target.value } })}>
                  <option value="">پیش‌فرضِ سبک ({style.mood_fa})</option>
                  {ov.moods.map((m) => <option key={m.key} value={m.key}>{m.title}</option>)}
                </Select>
              </label>
              <label className="dz-field">
                <span>فونتِ عنوان</span>
                <Select value={spec.font} onChange={(e) => set({ font: e.target.value })}>
                  <option value="auto">{brand.heading_font ? "فونتِ برند" : "پیش‌فرضِ سبک"}</option>
                  {ov.fonts.map((f) => <option key={f.key} value={f.key}>{f.title}</option>)}
                </Select>
              </label>
              <label className="dz-field">
                <span>رنگِ تأکید (اختیاری)</span>
                <div className="dz-color">
                  <input type="color" value={spec.colors.accent || "#ffd400"} onChange={(e) => set({ colors: { ...spec.colors, accent: e.target.value } })} />
                  {spec.colors.accent && <Button size="sm" variant="ghost" onClick={() => set({ colors: { ...spec.colors, accent: "" } })}>خودکار</Button>}
                </div>
              </label>
              <label className="dz-field">
                <span>لوگو {brand.has_logo ? "" : "(لوگو ثبت نشده)"}</span>
                <div className="flex items-center gap-2">
                  <input type="checkbox" checked={spec.logo.show} disabled={!brand.has_logo} onChange={(e) => set({ logo: { ...spec.logo, show: e.target.checked } })} />
                  <Select value={spec.logo.position} disabled={!brand.has_logo || !spec.logo.show} onChange={(e) => set({ logo: { ...spec.logo, position: e.target.value } })}>
                    {LOGO_POS.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
                  </Select>
                </div>
              </label>
            </div>
          </Card>
        </div>

        {/* ───────────── پیش‌نمایش و خروجی */}
        <div className="th-preview-col">
          <div className="th-sticky flex flex-col gap-3" ref={previewTop}>
            <Card>
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <h2 className="th-section-title" style={{ margin: 0 }}>پیش‌نمایش</h2>
                  <Badge tone="neutral">{fmt.title} · {fa(fmt.width)}×{fa(fmt.height)}</Badge>
                  {editing && <Badge tone="warn">در حالِ ویرایش</Badge>}
                </div>
                <label className="dz-field check" style={{ flexDirection: "row" }}>
                  <input type="checkbox" checked={spec.guides} onChange={(e) => set({ guides: e.target.checked })} />
                  <span>خطِ راهنمای حاشیهٔ امن (فقط در پیش‌نمایش، در فایلِ نهایی نمی‌افتد)</span>
                </label>
              </div>
              <div className={`th-preview-frame ${prevBusy ? "is-busy" : ""} ${isPortraitish ? "th-tall" : ""}`} style={aspectStyle(fmt)}>
                {preview ? <img src={preview.image} alt="پیش‌نمایشِ تامنیل" /> : <Spinner />}
                {prevBusy && <div className="th-preview-busy"><Spinner size={26} /></div>}
              </div>
              <ErrorBox message={prevError} />
              {preview && preview.warnings.length > 0 && (
                <div className="mt-2 flex flex-col gap-1">
                  {preview.warnings.map((w) => <div key={w} className="dz-muted" style={{ color: "var(--warn)" }}>⚠ {w}</div>)}
                </div>
              )}
              {spec.guides && fmt.avoid.length > 0 && (
                <p className="dz-muted mt-2">قرمز = جاهایی که پلتفرم رویشان چیزی می‌کشد: {fmt.avoid.map((a) => a.note).join("، ")}. (مرزها تقریبی‌اند.)</p>
              )}
              {preview && (
                <div className="mt-2">
                  <button type="button" className="dz-link" onClick={() => setShowLayers((v) => !v)}>
                    {showLayers ? "پنهان‌کردنِ لایه‌ها" : `لایه‌های طرح (${fa(preview.layers.length)})`}
                  </button>
                  {showLayers && <ul className="th-layers mt-1">{preview.layers.map((l, i) => <li key={`${l.name}-${i}`}>{l.name}</li>)}</ul>}
                </div>
              )}
            </Card>

            <Card>
              <h2 className="th-section-title"><i>۶</i> ساخت</h2>
              {notice && <div className="mb-2"><Alert tone="ok"><span className="text-sm">{notice}</span></Alert></div>}
              <ErrorBox message={error} />
              <div className="mt-1 flex flex-wrap items-end gap-3">
                {!editing && (
                  <label className="dz-field" style={{ minWidth: 150 }}>
                    <span>تعدادِ نسخه (A/B)</span>
                    <Select value={variants} onChange={(e) => setVariants(Number(e.target.value))}>
                      {Array.from({ length: ov.limits.max_variants }, (_, i) => i + 1).map((n) => (
                        <option key={n} value={n}>{n === 1 ? "فقط یک نسخه" : `${fa(n)} نسخه`}</option>
                      ))}
                    </Select>
                  </label>
                )}
                <Button onClick={() => void build()} disabled={busy || !hasText(spec)}>
                  {busy ? "در حالِ ساخت…" : editing ? "به‌روزرسانیِ همین تامنیل" : variants > 1 ? `ساختِ ${fa(variants)} نسخه` : "ساخت"}
                </Button>
                {editing && <Button variant="ghost" onClick={() => { setEditing(null); setNotice(null); }}>ساختِ تامنیلِ تازه</Button>}
                <Button variant="ghost" onClick={() => set({ colors: { ...spec.colors, variation: spec.colors.variation + 1 }, seed: spec.seed + 1 })}>
                  ظاهرِ دیگر
                </Button>
              </div>
              {!editing && variants > 1 && (
                <p className="dz-muted mt-2">A همین طرح است؛ B رنگ‌ها را جابه‌جا و سوژه را آن‌طرف می‌گذارد؛ C و E سبکِ دیگرِ مناسبِ همین قالب؛ D فونتِ دیگر؛ F حال‌وهوای دیگر. با هم مقایسه کنید و بهترین را بردارید.</p>
              )}
              {!hasText(spec) && <p className="dz-muted mt-2">برای ساخت دست‌کم یک متن (عنوان) بنویسید.</p>}
            </Card>
          </div>
        </div>

        {/* نتیجه و تاریخچه زیرِ هر دو ستون می‌آیند، نه داخلِ ستونِ چسبان: وگرنه کارت‌هایشان هنگامِ اسکرول روی کارتِ «ساخت» می‌افتاد (بازبینیِ ۱۱/۱۳). */}
        <div className="th-output" ref={outputTop}>
          {batch.length > 0 && (
            <Card>
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <h2 className="th-section-title" style={{ margin: 0 }}>نتیجه</h2>
                {batch[0].batch && batch.length > 1 && (
                  <Button size="sm" variant="secondary" onClick={() => void downloadBlob(thumbsApi.zipUrl(id, batch[0].batch), `thumbnails-${batch[0].batch}.zip`).catch((e) => setError(errorMessage(e)))}>
                    دانلودِ همهٔ نسخه‌ها (zip)
                  </Button>
                )}
              </div>
              <div className="th-results">{batch.map((it) => card(it))}</div>
            </Card>
          )}

          <Card>
            <h2 className="th-section-title">تاریخچه</h2>
            {history.length === 0 ? (
              <EmptyState icon="image" title="هنوز تامنیلی نساخته‌اید" description="یک طرح بسازید تا این‌جا بماند؛ هر کدام را می‌شود دوباره ویرایش یا در ادیتور عکس باز کرد." />
            ) : (
              <div className="th-results">{history.map((it) => card(it, true))}</div>
            )}
          </Card>
        </div>
      </div>

      {picker && (
        <ImagePicker
          storeId={id}
          products={ov.products}
          title={picker === "background" ? "عکسِ پس‌زمینه" : picker === "extra" ? "عکسِ بیشتر برای کلاژ" : picker === "subject2" ? "سوژهٔ دوم" : "سوژه"}
          onPick={(a) => pickFor(picker, a)}
          onClose={() => setPicker(null)}
        />
      )}
    </>
  );
}

function hasText(spec: Spec): boolean {
  return Object.values(spec.content).some((v) => (v ?? "").trim().length > 0);
}
