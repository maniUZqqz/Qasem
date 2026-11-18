import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import Icon from "../../components/Icon";
import { useQueuedAi } from "../../components/QueuedAi";
import { Alert, Badge, Button, Card, ErrorBox, Input, PageHeader, Select, Spinner } from "../../components/ui";
import { El, Kind, Overview, ScenePage, apiError, designApi, fa } from "./api";
import ExportDialog from "./ExportDialog";
import { useDocEditor, useOverview } from "./hooks";
import { CATALOG_FIELDS, DECK_FIELDS, NOTES } from "./fields";
import { AddElementMenu, ChecksPanel, ElementInspector, Field, PageCanvas, SpecForm, Thumb, useWidth } from "./parts";
import "./design.css";

// ───────────────────────────── تعریفِ فیلدهای هر نوعِ صفحه و اسلاید

const CATALOG_TYPE_FA: Record<string, string> = { cover: "جلد", toc: "فهرست", text: "متن", grid: "شبکه", hero: "ویژه", price_list: "قیمت", lookbook: "لوک‌بوک", steps: "گام‌ها", divider: "جداکننده", back: "پشتِ جلد" };

function SettingsForm({ kind, settings, ov, apply }: { kind: Kind; settings: Record<string, any>; ov: Overview; apply: (set: Record<string, unknown>) => void }) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  const txt = (k: string, label: string) => (
    <Field label={label}>
      <Input value={draft[k] ?? settings[k] ?? ""} onChange={(e) => setDraft({ ...draft, [k]: e.target.value })} onBlur={(e) => { if (e.target.value !== (settings[k] ?? "")) apply({ [k]: e.target.value }); setDraft((d) => { const n = { ...d }; delete n[k]; return n; }); }} />
    </Field>
  );
  const chk = (k: string, label: string) => <label className="ds-check-row"><input type="checkbox" checked={!!settings[k]} onChange={(e) => apply({ [k]: e.target.checked })} /> {label}</label>;
  const fontSel = (k: string, label: string) => (
    <Field label={label}>
      <Select value={settings[k] ?? ""} onChange={(e) => apply({ [k]: e.target.value })}>
        <option value="">پیش‌فرضِ برند</option>
        {ov.fonts.map((f) => <option key={f.key} value={f.key}>{f.title} ({f.family})</option>)}
      </Select>
    </Field>
  );
  const usedFonts = Array.from(new Set([settings.heading_font || "estedad", settings.body_font || "vazirmatn"]));
  return (
    <div className="ds-form">
      {kind === "catalog" ? (
        <>
          <Field label="اندازهٔ صفحه"><Select value={settings.page_size ?? "A4"} onChange={(e) => apply({ page_size: e.target.value })}>{ov.catalog.page_sizes.map((s) => <option key={s.key} value={s.key}>{s.key === "square" ? "مربع" : s.key} ({fa(s.w)}×{fa(s.h)} میلی‌متر)</option>)}</Select></Field>
          <Field label="جهت"><Select value={settings.orientation ?? "portrait"} onChange={(e) => apply({ orientation: e.target.value })}><option value="portrait">عمودی</option><option value="landscape">افقی</option></Select></Field>
          <Field label="بلید (میلی‌متر)"><Input type="number" min={0} max={10} step={0.5} value={settings.bleed ?? 3} onChange={(e) => apply({ bleed: Number(e.target.value) })} /></Field>
          <Field label="حاشیهٔ صفحه (میلی‌متر؛ خالی = خودکار)"><Input type="number" min={0} max={40} value={settings.margin || ""} onChange={(e) => apply({ margin: Number(e.target.value) || 0 })} /></Field>
          <Field label="ستونِ شبکه"><Select value={String(settings.grid_cols ?? 2)} onChange={(e) => apply({ grid_cols: Number(e.target.value) })}>{[1, 2, 3, 4].map((n) => <option key={n} value={n}>{fa(n)}</option>)}</Select></Field>
          <Field label="ردیفِ شبکه"><Select value={String(settings.grid_rows ?? 3)} onChange={(e) => apply({ grid_rows: Number(e.target.value) })}>{[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{fa(n)}</option>)}</Select></Field>
          {txt("title", "عنوانِ پیش‌فرضِ جلد")}{txt("subtitle", "زیرعنوان")}{txt("tagline", "شعار")}{txt("date_text", "تاریخ/فصل")}
          {chk("show_sku", "نمایشِ کدِ محصول")}{chk("page_numbers", "شمارهٔ صفحه")}
        </>
      ) : (
        <>
          <Field label="قالبِ ظاهری"><Select value={settings.template ?? "clean"} onChange={(e) => apply({ template: e.target.value })}>{ov.deck.templates.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}</Select></Field>
          {txt("title", "عنوانِ ارائه")}{txt("footer_text", "نوشتهٔ پایین (خالی = نامِ فروشگاه)")}{chk("slide_numbers", "شمارهٔ اسلاید")}
        </>
      )}
      <Field label="«سبک» (پالتِ رنگیِ آماده؛ لوگو و فونتِ برند می‌ماند)">
        <Select value={settings.look ?? ""} onChange={(e) => apply({ look: e.target.value })}>
          <option value="">فقط رنگ‌های برند</option>
          {ov.looks.map((l) => <option key={l.key} value={l.key}>{l.name_fa}</option>)}
        </Select>
      </Field>
      {fontSel("heading_font", "فونتِ تیتر")}{fontSel("body_font", "فونتِ متن")}
      <Field label="رقم‌ها"><Select value={settings.digits ?? "fa"} onChange={(e) => apply({ digits: e.target.value })}><option value="fa">فارسی (۱۲۳)</option><option value="en">لاتین (123)</option><option value="keep">همان‌که نوشته‌ام</option></Select></Field>
      {chk("show_prices", "نمایشِ قیمت (همان‌طور که در فروشگاه ثبت شده)")}{chk("show_logo", "نمایشِ لوگو")}
      {txt("zero_price_label", "نوشتهٔ قیمتِ ۰ (مثلاً «فعلاً بدونِ هزینه»)")}
      <div className="ds-fonts ds-wide">
        <div className="ds-sub">فونت‌ها و مجوز</div>
        {usedFonts.map((k) => {
          const f = ov.fonts.find((x) => x.key === k);
          return f ? <div key={k} className="ds-font"><b style={{ fontFamily: `'${f.family}'` }}>{f.title}</b><span>{f.license} · {f.source}</span></div> : null;
        })}
        <p className="ds-muted">همهٔ فونت‌ها SIL OFL 1.1 هستند: استفادهٔ تجاری و تبدیل به منحنی/جاسازی مجاز است؛ فروشِ جدایِ خودِ فونت مجاز نیست. متنِ مجوز در بسته‌های تحویل می‌آید.</p>
      </div>
    </div>
  );
}

function AiBox({ storeId, docId, brief, ov, onDone }: { storeId: string; docId: number; brief: string; ov: Overview; onDone: (m: string) => void }) {
  const [text, setText] = useState(brief);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // «در صف تا روشن شدنِ سرورِ پردازش»: پیش‌نویسِ هوش مصنوعی خودکار می‌رسد و (اگر طرح در این فاصله ویرایش نشده) جای پیش‌نویسِ آماده می‌نشیند
  const qa = useQueuedAi<{ applied?: boolean; message?: string }>("deck-ai", `${storeId}:${docId}`, (r) => onDone(r?.message || "پیش‌نویسِ هوش مصنوعی رسید."));
  const run = async (use_ai: boolean) => {
    if (!window.confirm("اسلایدهای فعلی با پیش‌نویسِ تازه جایگزین می‌شوند. ادامه بدهم؟")) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await designApi.ai(storeId, docId, { brief: text, use_ai });
      qa.setQueued(r.queued);
      onDone(r.queued ? "این درخواست «در صف تا روشن شدنِ سرورِ پردازش» ماند؛ پیش‌نویسِ آماده الان جایگزین شد و نسخهٔ هوش مصنوعی خودکار می‌رسد." : r.ai.message);
    } catch (e) {
      setErr(apiError(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card>
      <div className="ds-sub">پیش‌نویسِ ارائه از خلاصه</div>
      <p className="ds-muted">خلاصه + محصولاتِ فروشگاه + پرسونا (توضیح، مخاطب، لحنِ برند). عددها فقط از دادهٔ واقعی می‌آیند؛ هر عددِ ساختگیِ هوش مصنوعی حذف می‌شود.</p>
      <textarea className="u-input" rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder="مثلاً: معرفیِ بسته‌ها به مربی‌های باشگاه" />
      <Alert tone={ov.ai.ok ? "ok" : "warn"}>{ov.ai.ok ? "هوش مصنوعی آماده است." : `هوش مصنوعی الان در دسترس نیست (${ov.ai.message}). پیش‌نویسِ قاعده‌ای همچنان کار می‌کند و با برگشتنِ آن خودکار هوشمند می‌شود.`}</Alert>
      <div className="ds-row">
        <Button type="button" disabled={busy} onClick={() => run(true)}>{busy ? <Spinner size={14} /> : <Icon name="sparkle" size={14} />} بنویس (هوش مصنوعی ⇐ قاعده‌ها)</Button>
        <Button type="button" variant="secondary" disabled={busy} onClick={() => run(false)}>فقط با قاعده‌ها</Button>
      </div>
      {qa.banner}
      {err ? <ErrorBox message={err} /> : null}
    </Card>
  );
}

const TABS: [string, string][] = [["page", "صفحه"], ["element", "عنصر"], ["settings", "تنظیمات"], ["checks", "چک‌لیست"], ["ai", "پیش‌نویس"]];

export default function DocEditor({ kind }: { kind: "catalog" | "deck" }) {
  const { id = "", docId = "" } = useParams<{ id: string; docId: string }>();
  const nav = useNavigate();
  const { ov } = useOverview(id);
  const ed = useDocEditor(id, Number(docId));
  const [sel, setSel] = useState<string | null>(null);
  const [selEl, setSelEl] = useState<string | null>(null);
  const [tab, setTab] = useState<"page" | "element" | "settings" | "checks" | "ai">("page");
  const [showExport, setShowExport] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [addType, setAddType] = useState("");
  const [title, setTitle] = useState("");
  const wrap = useRef<HTMLDivElement>(null);
  const width = Math.min(useWidth(wrap, 320), kind === "deck" ? 900 : 640);

  const doc = ed.doc;
  const scene = ed.scene;
  const key = kind === "catalog" ? "pages" : "slides";
  const specs: any[] = doc?.data?.[key] ?? [];
  useEffect(() => {
    if (doc) setTitle(doc.title);
  }, [doc?.id, doc?.title]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (scene && (!sel || !scene.pages.some((p) => p.id === sel))) setSel(scene.pages[0]?.id ?? null);
  }, [scene, sel]);

  const page: ScenePage | undefined = scene?.pages.find((p) => p.id === sel);
  const spec = specs.find((s) => s.id === sel);
  const el: El | undefined = page?.elements.find((e) => e.id === selEl);
  const defs = (kind === "catalog" ? CATALOG_FIELDS : DECK_FIELDS)[spec?.type ?? ""] ?? [];
  const typesList = kind === "catalog" ? ov?.catalog.page_types : ov?.deck.slide_types;
  const pageOps = (extra: any[]) => ed.apply(extra);
  const opName = (n: string) => (kind === "catalog" ? `${n}_page` : `${n}_slide`);
  const pkey = kind === "catalog" ? "page" : "slide";
  const hasOverride = !!(spec?.overrides && selEl && spec.overrides[selEl]);

  const idx = specs.findIndex((s) => s.id === sel);
  const del = async () => {
    if (!spec || !window.confirm("این صفحه حذف شود؟")) return;
    await pageOps([{ op: opName("delete"), [pkey]: spec.id }]);
  };

  if (ed.error && !doc) return <div className="ds-page"><ErrorBox message={ed.error} /></div>;
  if (!doc || !scene || !ov) return <div className="ds-page"><Spinner /></div>;

  return (
    <div className="ds-page">
      <PageHeader title={doc.title} subtitle={`${kind === "catalog" ? "کاتالوگ" : "ارائه"} · ${fa(scene.pages.length)} ${kind === "catalog" ? "صفحه" : "اسلاید"}${doc.source === "ai" ? " · پیش‌نویسِ هوش مصنوعی" : doc.source === "sample" ? " · نمونه" : ""}`}
        actions={
          <>
            <Link to={`/stores/${id}/design/${kind}`}><Button variant="ghost" type="button"><Icon name="back" size={14} /> فهرست</Button></Link>
            {kind === "deck" ? <Link to={`/stores/${id}/design/deck/${doc.id}/present`}><Button variant="secondary" type="button"><Icon name="play" size={14} /> نمای ارائه‌دهنده</Button></Link> : null}
            <Button type="button" onClick={() => setShowExport(true)}><Icon name="download" size={14} /> خروجی و تحویل</Button>
          </>
        } />
      {ed.notice ? <Alert tone="warn">{ed.notice}</Alert> : null}
      {msg ? <Alert tone="info">{msg}</Alert> : null}
      {ed.error ? <ErrorBox message={ed.error} /> : null}
      <div className="ds-title-edit">
        <Input value={title} onChange={(e) => setTitle(e.target.value)} onBlur={async () => { if (title.trim() && title !== doc.title) { await designApi.rename(id, doc.id, title); void ed.reload(); } }} aria-label="نامِ سند" />
        {ed.busy ? <Spinner size={16} /> : <Badge tone="ok">ذخیره شد</Badge>}
      </div>

      <div className="ds-editor">
        <aside className="ds-strip" aria-label="صفحه‌ها">
          {scene.pages.map((p, i) => (
            <Thumb key={p.id} storeId={id} docId={doc.id} page={p} rev={doc.rev} width={kind === "deck" ? 150 : 96} active={p.id === sel} label={`${fa(i + 1)}. ${kind === "catalog" ? CATALOG_TYPE_FA[p.type ?? ""] ?? p.name : p.name}`} onClick={() => { setSel(p.id); setSelEl(null); }} />
          ))}
          <div className="ds-addpage">
            <Select value={addType} onChange={(e) => setAddType(e.target.value)} aria-label="نوعِ صفحهٔ تازه">
              <option value="">+ افزودن…</option>
              {typesList?.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
            </Select>
            <Button size="sm" type="button" disabled={!addType} onClick={async () => { const r = await pageOps([{ op: opName("add"), type: addType, spec: {}, index: idx >= 0 ? idx + 1 : undefined }]); setAddType(""); if (r) { const arr = r.data[key]; setSel(arr[Math.min(arr.length - 1, (idx >= 0 ? idx + 1 : arr.length - 1))].id); } }}>افزودن</Button>
          </div>
        </aside>

        <main className="ds-stage" ref={wrap}>
          {page ? (
            <>
              <div className="ds-stagebar">
                <b>{page.name}</b>
                <div className="ds-row">
                  <Button size="sm" variant="ghost" type="button" disabled={idx <= 0} onClick={() => pageOps([{ op: opName("move"), [pkey]: spec.id, to: idx - 1 }])} aria-label="بالاتر"><Icon name="up" size={14} /></Button>
                  <Button size="sm" variant="ghost" type="button" disabled={idx < 0 || idx >= specs.length - 1} onClick={() => pageOps([{ op: opName("move"), [pkey]: spec.id, to: idx + 1 }])} aria-label="پایین‌تر"><Icon name="down" size={14} /></Button>
                  <Button size="sm" variant="secondary" type="button" onClick={() => pageOps([{ op: opName("duplicate"), [pkey]: spec.id }])}><Icon name="copy" size={14} /> نسخه</Button>
                  <Button size="sm" variant="danger" type="button" onClick={del}><Icon name="trash" size={14} /></Button>
                  {kind === "catalog" ? (
                    <Button size="sm" variant="secondary" type="button" onClick={async () => { try { const r = await designApi.designer(id, doc.id, page.id); window.open(`/panel${r.url}`, "_blank"); setMsg(r.reused ? `پروژهٔ قبلیِ همین صفحه در ادیتورِ عکس باز شد (پروژهٔ تازه‌ای ساخته نشد؛ ${fa(r.layers)} لایهٔ متنِ قابل‌ویرایش).` : `این صفحه در ادیتورِ عکس باز شد (${fa(r.layers)} لایهٔ متنِ قابل‌ویرایش).`); } catch (e) { ed.setError(apiError(e)); } }}><Icon name="image" size={14} /> ویرایش در طراح</Button>
                  ) : null}
                </div>
              </div>
              <PageCanvas storeId={id} docId={doc.id} page={page} rev={doc.rev} width={width} selected={selEl} onSelect={(x) => { setSelEl(x); if (x) setTab("element"); }}
                onMove={(e, x, y) => void pageOps([{ op: "override", [pkey]: page.id, el: e.id, set: { x, y } }])} />
              <p className="ds-muted">روی هر عنصر بزن تا ویرایشش کنی؛ بکش تا جابه‌جا شود. {kind === "catalog" ? `اندازه: ${fa(page.w)}×${fa(page.h)} میلی‌متر${page.bleed ? ` + بلید ${fa(page.bleed)}` : ""}` : ""}</p>
            </>
          ) : <p className="ds-muted">صفحه‌ای نیست.</p>}
        </main>

        <section className="ds-side">
          <div className="ds-tabs" role="tablist">
            {TABS.filter((x) => x[0] !== "ai" || kind === "deck").map(([k, l]) => (
              <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "is-on" : ""} onClick={() => setTab(k as typeof tab)} type="button">{l}</button>
            ))}
          </div>
          {tab === "page" && spec ? (
            <div className="ds-panel">
              <div className="ds-sub">{kind === "catalog" ? CATALOG_TYPE_FA[spec.type] ?? spec.type : ov.deck.slide_types.find((t) => t.key === spec.type)?.label}</div>
              <SpecForm storeId={id} defs={[...defs, NOTES()]} spec={spec} ov={ov}
                onPatch={(patch) => void pageOps([{ op: opName("update"), [pkey]: spec.id, set: patch }])} />
              {kind === "catalog" ? (
                <div className="ds-row">
                  <Button size="sm" variant="secondary" type="button" onClick={() => pageOps([{ op: "sync_products" }])}><Icon name="refresh" size={14} /> به‌روزرسانیِ محصولات از فروشگاه</Button>
                  <Button size="sm" variant="secondary" type="button" onClick={() => pageOps([{ op: "pad4" }])}>تکمیل تا مضرب ۴</Button>
                </div>
              ) : null}
            </div>
          ) : null}
          {tab === "element" ? (
            <div className="ds-panel">
              {el && page ? (
                <ElementInspector el={el} fonts={ov.fonts} storeId={id} ov={ov} hasOverride={hasOverride}
                  onSet={(patch) => void pageOps([{ op: "override", [pkey]: page.id, el: el.id, set: patch }])}
                  onClear={() => pageOps([{ op: "clear_override", [pkey]: page.id, el: el.id }])}
                  onRemove={async () => { await pageOps([{ op: "remove_element", [pkey]: page.id, el: el.id }]); setSelEl(null); }} />
              ) : <p className="ds-muted">یک عنصر را روی صفحه انتخاب کن.</p>}
              {page ? <><div className="ds-sub">افزودنِ عنصر به این صفحه</div><AddElementMenu onAdd={(element) => void pageOps([{ op: "add_element", [pkey]: page.id, element }])} /></> : null}
            </div>
          ) : null}
          {tab === "settings" ? (
            <div className="ds-panel">
              <SettingsForm kind={kind} settings={scene.settings} ov={ov} apply={(set) => void ed.apply([{ op: "set_settings", set }])} />
              {kind === "catalog" ? <div className="ds-sub">پالتِ فعلی</div> : null}
              {scene.palette ? <div className="ds-swatches">{["primary", "secondary", "accent", "bg", "text"].map((k) => <span key={k} title={`${k} ${scene.palette?.[k]}`} style={{ background: scene.palette?.[k] }} />)}</div> : null}
            </div>
          ) : null}
          {tab === "checks" ? <div className="ds-panel"><ChecksPanel checks={scene.checks} title={kind === "catalog" ? "چک‌لیستِ چاپخانه" : "بازبینیِ ارائه"} /></div> : null}
          {tab === "ai" && kind === "deck" ? <div className="ds-panel"><AiBox storeId={id} docId={doc.id} brief={doc.data.brief || ""} ov={ov} onDone={(m) => { setMsg(m); void ed.reload(); }} /></div> : null}
        </section>
      </div>
      {showExport ? <ExportDialog storeId={id} doc={doc} ov={ov} checks={scene.checks} onClose={() => setShowExport(false)} /> : null}
    </div>
  );
}
