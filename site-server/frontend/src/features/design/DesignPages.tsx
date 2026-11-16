import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import Icon from "../../components/Icon";
import { Alert, Badge, Button, Card, EmptyState, ErrorBox, Input, PageHeader, Select, Spinner, TextArea } from "../../components/ui";
import { useAuth } from "../auth/AuthContext";
import { DocSummary, Kind, KIND_FA, KIND_PATH, Overview, apiError, designApi, fa } from "./api";
import { useOverview } from "./hooks";
import { Field, ProductPicker } from "./parts";
import "./design.css";

const KIND_INFO: Record<Kind, { icon: "file" | "play" | "edit"; text: string }> = {
  catalog: { icon: "file", text: "از محصولاتِ فروشگاه کاتالوگِ چندصفحه‌ای: جلد، فهرست، شبکه، محصولِ ویژه، فهرستِ قیمت و لوک‌بوک؛ خروجیِ چاپی با بلید و علامت برش." },
  deck: { icon: "play", text: "اسلایدهای عنوان، فهرست، محصول، مقایسه، آمارِ واقعی، خط زمان، تیم و دعوت به اقدام؛ یادداشتِ گوینده، نمای ارائه‌دهنده، PPTX/PDF و ویدیو." },
  ui: { icon: "edit", text: "فریم‌های دسکتاپ، تبلت و گوشی با قطعه‌های سایت‌ساز و سبک‌های ui-ux-pro-max؛ Auto Layout، حالتِ روشن/تیره، راهنمای سبک، نمونهٔ کلیک‌پذیر و «ساختِ سایت از این طرح»." },
};

function DocRow({ storeId, d, onDelete }: { storeId: string; d: DocSummary; onDelete: (d: DocSummary) => void }) {
  return (
    <div className="ds-docrow">
      <Link to={`/stores/${storeId}/design/${KIND_PATH[d.kind]}/${d.id}`} className="ds-docrow-main">
        <b>{d.title}</b>
        <span className="ds-muted">{KIND_FA[d.kind]} · {fa(d.count)} {d.kind === "catalog" ? "صفحه" : d.kind === "deck" ? "اسلاید" : "فریم"} · {new Date(d.updated_at).toLocaleDateString("fa-IR")}</span>
      </Link>
      <span className="ds-row">
        {d.source === "sample" ? <Badge tone="info">نمونه</Badge> : d.source === "ai" ? <Badge tone="brand">هوش مصنوعی</Badge> : null}
        {d.site ? <Badge tone="ok">سایت ساخته شد</Badge> : null}
        <Button size="sm" variant="ghost" type="button" aria-label="حذف" onClick={() => onDelete(d)}><Icon name="trash" size={14} /></Button>
      </span>
    </div>
  );
}

// ───────────────────────────── خانهٔ استودیو

export function DesignHomePage() {
  const { id = "" } = useParams<{ id: string }>();
  const { user } = useAuth();
  const { ov, error, reload } = useOverview(id);
  const nav = useNavigate();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  if (error) return <div className="ds-page"><ErrorBox message={error} /></div>;
  if (!ov) return <div className="ds-page"><Spinner /></div>;
  const sample = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await designApi.sample(id, !!user?.is_staff);
      const made = Object.values(r.created ?? {}).filter(Boolean).length;
      setMsg(made ? `${fa(made)} پیش‌نویس ساخته شد${r.site ? "؛ طرحِ UI هم به سایت‌ساز (پیش‌نویس) رفت" : ""}.` : "نمونه‌ها از قبل ساخته شده‌اند.");
      await reload();
    } catch (e) {
      setErr(apiError(e));
    } finally {
      setBusy(false);
    }
  };
  const del = async (d: DocSummary) => {
    if (!window.confirm(`«${d.title}» پاک شود؟`)) return;
    await designApi.remove(id, d.id).catch((e) => setErr(apiError(e)));
    await reload();
  };
  const isChagher = ov.store.name.includes("چغر");
  return (
    <div className="ds-page">
      <PageHeader title="استودیوی طراحی" subtitle="کاتالوگ، ارائه و طراحیِ UI/UX — بر پایهٔ محصولات، برند، سبک و پرسونای همین فروشگاه"
        actions={<><Link to={`/stores/${id}/design/guide`}><Button variant="secondary" type="button"><Icon name="bulb" size={14} /> راهنمای فایل‌ها</Button></Link><Button type="button" disabled={busy} onClick={sample}>{busy ? <Spinner size={14} /> : <Icon name="sparkle" size={14} />} {isChagher ? "نمونهٔ آمادهٔ چغر" : "نمونهٔ آماده"}</Button></>} />
      {msg ? <Alert tone="ok">{msg}</Alert> : null}
      {err ? <ErrorBox message={err} /> : null}
      {isChagher ? <Alert tone="info" title="نمونهٔ آمادهٔ چغر">یک کاتالوگ، یک ارائهٔ کوتاه و یک طرحِ صفحهٔ فرود فقط از محصولات و واقعیت‌های ثبت‌شدهٔ چغر؛ طرحِ UI به‌صورتِ پیش‌نویس به سایت‌ساز می‌رود (چیزی منتشر نمی‌شود).</Alert> : null}
      <div className="ds-kinds">
        {(["catalog", "deck", "ui"] as Kind[]).map((k) => (
          <Card key={k}>
            <div className="ds-kind">
              <span className="ds-kind-icon"><Icon name={KIND_INFO[k].icon} size={22} /></span>
              <div>
                <h2>{KIND_FA[k]}</h2>
                <p className="ds-muted">{KIND_INFO[k].text}</p>
                <div className="ds-row">
                  <Link to={`/stores/${id}/design/${KIND_PATH[k]}`}><Button type="button">{fa(ov.docs.filter((d) => d.kind === k).length)} سند · باز کن / بساز</Button></Link>
                </div>
              </div>
            </div>
          </Card>
        ))}
      </div>
      <div className="ds-statusrow">
        <Alert tone={ov.ai.ok ? "ok" : "warn"} title="هوش مصنوعی">{ov.ai.ok ? "آماده است." : `الان در دسترس نیست (${ov.ai.message}). همهٔ بخش‌ها با قاعده‌های آماده کار می‌کنند و با برگشتنِ آن هوشمند می‌شوند.`}</Alert>
        <Alert tone={ov.node.state === "online" ? "ok" : "info"} title="سرورِ پردازش (ویدیو)">{ov.node.message}</Alert>
      </div>
      <h2 className="ds-h2">آخرین سندها</h2>
      {!ov.docs.length ? <EmptyState icon="empty" title="هنوز سندی نساخته‌ای">از یکی از سه بخشِ بالا شروع کن یا «نمونهٔ آماده» را بزن.</EmptyState> : null}
      {ov.docs.slice(0, 12).map((d) => <DocRow key={d.id} storeId={id} d={d} onDelete={del} />)}
    </div>
  );
}

// ───────────────────────────── فهرست و ساخت

function CatalogForm({ ov, onCreate, busy }: { ov: Overview; onCreate: (title: string, opts: Record<string, unknown>) => void; busy: boolean }) {
  const [title, setTitle] = useState("");
  const [size, setSize] = useState("A4");
  const [look, setLook] = useState("");
  const [digits, setDigits] = useState("fa");
  const [prices, setPrices] = useState(true);
  const [layout, setLayout] = useState("mix");
  const [picked, setPicked] = useState<number[]>([]);
  const [featured, setFeatured] = useState<number[]>([]);
  return (
    <Card>
      <div className="ds-sub">کاتالوگِ تازه</div>
      <div className="ds-form">
        <Field label="نام"><Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={`کاتالوگ ${ov.store.name}`} /></Field>
        <Field label="اندازه"><Select value={size} onChange={(e) => setSize(e.target.value)}>{ov.catalog.page_sizes.map((s) => <option key={s.key} value={s.key}>{s.key === "square" ? "مربع" : s.key} ({fa(s.w)}×{fa(s.h)})</option>)}</Select></Field>
        <Field label="چیدمانِ محصول‌ها"><Select value={layout} onChange={(e) => setLayout(e.target.value)}><option value="mix">شبکه + فهرستِ قیمت</option><option value="grid">فقط شبکه</option><option value="list">فقط فهرستِ قیمت</option></Select></Field>
        <Field label="«سبک» (پالتِ رنگ)"><Select value={look} onChange={(e) => setLook(e.target.value)}><option value="">رنگ‌های برند</option>{ov.looks.map((l) => <option key={l.key} value={l.key}>{l.name_fa}</option>)}</Select></Field>
        <Field label="رقم‌ها"><Select value={digits} onChange={(e) => setDigits(e.target.value)}><option value="fa">فارسی</option><option value="en">لاتین</option></Select></Field>
        <label className="ds-check-row"><input type="checkbox" checked={prices} onChange={(e) => setPrices(e.target.checked)} /> نمایشِ قیمت (همان‌طور که ثبت شده)</label>
        <Field label={`محصول‌ها (${picked.length ? fa(picked.length) + " انتخاب" : "خالی = همهٔ محصول‌های موجود"})`} wide><ProductPicker products={ov.products} value={picked} onChange={setPicked} /></Field>
        <Field label="محصولِ ویژه (یک صفحهٔ کامل)" wide><ProductPicker products={ov.products} single value={featured} onChange={setFeatured} /></Field>
      </div>
      <Button type="button" disabled={busy} onClick={() => onCreate(title, { products: picked, featured, layout, settings: { page_size: size, look, digits, show_prices: prices } })}>{busy ? <Spinner size={14} /> : <Icon name="plus" size={14} />} ساختِ کاتالوگ</Button>
    </Card>
  );
}

function DeckForm({ ov, onCreate, busy }: { ov: Overview; onCreate: (title: string, opts: Record<string, unknown>) => void; busy: boolean }) {
  const [title, setTitle] = useState("");
  const [brief, setBrief] = useState("");
  const [ai, setAi] = useState(true);
  const [tpl, setTpl] = useState("bold");
  const [look, setLook] = useState("");
  const [picked, setPicked] = useState<number[]>([]);
  const [facts, setFacts] = useState<{ value: string; label: string; source: string }[]>([]);
  return (
    <Card>
      <div className="ds-sub">ارائهٔ تازه</div>
      <div className="ds-form">
        <Field label="نام"><Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={`ارائهٔ ${ov.store.name}`} /></Field>
        <Field label="قالبِ ظاهری"><Select value={tpl} onChange={(e) => setTpl(e.target.value)}>{ov.deck.templates.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}</Select></Field>
        <Field label="«سبک» (پالتِ رنگ)"><Select value={look} onChange={(e) => setLook(e.target.value)}><option value="">رنگ‌های برند</option>{ov.looks.map((l) => <option key={l.key} value={l.key}>{l.name_fa}</option>)}</Select></Field>
        <Field label="خلاصه: ارائه برای چه کسی و دربارهٔ چیست؟" wide><TextArea rows={3} value={brief} onChange={(e) => setBrief(e.target.value)} placeholder="مثلاً: معرفیِ بسته‌ها به مربی‌های باشگاه" /></Field>
        <label className="ds-check-row"><input type="checkbox" checked={ai} onChange={(e) => setAi(e.target.checked)} /> پیش‌نویس را هوش مصنوعی بنویسد {ov.ai.ok ? "" : "(الان در دسترس نیست؛ با قاعده‌ها ساخته می‌شود)"}</label>
        <Field label={`محصول‌های ارائه (${picked.length ? fa(picked.length) + " انتخاب" : "خالی = خودکار"})`} wide><ProductPicker products={ov.products} value={picked} onChange={setPicked} /></Field>
        <div className="ds-objs ds-wide">
          <div className="ds-sub">عددهای واقعی برای اسلایدِ آمار (اختیاری؛ منبع الزامی است — خالی = تعدادِ محصول و بازهٔ قیمتِ ثبت‌شده)</div>
          {facts.map((f, i) => (
            <div key={i} className="ds-obj">
              <Field label="عدد"><Input value={f.value} onChange={(e) => setFacts(facts.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} /></Field>
              <Field label="برچسب"><Input value={f.label} onChange={(e) => setFacts(facts.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} /></Field>
              <Field label="منبع"><Input value={f.source} onChange={(e) => setFacts(facts.map((x, j) => (j === i ? { ...x, source: e.target.value } : x)))} /></Field>
              <Button size="sm" variant="ghost" type="button" onClick={() => setFacts(facts.filter((_, j) => j !== i))}><Icon name="trash" size={14} /></Button>
            </div>
          ))}
          <Button size="sm" variant="secondary" type="button" onClick={() => setFacts([...facts, { value: "", label: "", source: "" }])}><Icon name="plus" size={14} /> افزودنِ عدد</Button>
        </div>
      </div>
      <Button type="button" disabled={busy} onClick={() => onCreate(title, { brief, use_ai: ai, products: picked, facts: facts.filter((f) => f.value && f.label && f.source), settings: { template: tpl, look } })}>{busy ? <Spinner size={14} /> : <Icon name="sparkle" size={14} />} ساختِ ارائه</Button>
    </Card>
  );
}

function UiForm({ ov, onCreate, busy }: { ov: Overview; onCreate: (title: string, opts: Record<string, unknown>) => void; busy: boolean }) {
  const [title, setTitle] = useState("");
  const [tpl, setTpl] = useState("landing");
  const [style, setStyle] = useState("");
  const [devs, setDevs] = useState<string[]>(["desktop", "phone"]);
  const [brand, setBrand] = useState("");
  return (
    <Card>
      <div className="ds-sub">طرحِ UI/UX تازه (پیش از سایت‌ساز)</div>
      <div className="ds-form">
        <Field label="نام"><Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={`طرحِ سایتِ ${ov.store.name}`} /></Field>
        <Field label="شروع از"><Select value={tpl} onChange={(e) => setTpl(e.target.value)}><option value="landing">صفحهٔ فرود (سربرگ، قهرمان، ویژگی‌ها، گام‌ها، قیمت، پرسش، دعوت، پابرگ)</option><option value="blank">فریمِ خالی</option></Select></Field>
        <Field label="سبکِ طراحی" wide>
          <div className="ds-styles">
            <button type="button" className={`ds-style ${style === "" ? "is-on" : ""}`} onClick={() => setStyle("")}><b>پیش‌فرض</b><small>ساده</small></button>
            {ov.ui.styles.map((s) => (
              <button type="button" key={s.key} className={`ds-style ${style === s.key ? "is-on" : ""}`} onClick={() => setStyle(s.key)} title={s.desc}>
                <span className="ds-style-dots">{["primary", "bg", "surface", "text"].map((k) => <i key={k} style={{ background: s.colors[k] }} />)}</span><b>{s.label}</b><small>{s.mood}</small>
              </button>
            ))}
          </div>
        </Field>
        <div className="ds-field"><span>دستگاه‌ها</span><div className="ds-row">{ov.ui.devices.map((d) => <label key={d.key} className="ds-check-row"><input type="checkbox" checked={devs.includes(d.key)} onChange={(e) => setDevs(e.target.checked ? [...devs, d.key] : devs.filter((x) => x !== d.key))} /> {d.label} ({fa(d.w)})</label>)}</div></div>
        <Field label="رنگِ برند (خالی = رنگِ فروشگاه)"><Input type="text" dir="ltr" value={brand} maxLength={7} onChange={(e) => setBrand(e.target.value)} placeholder="#126f85" /></Field>
      </div>
      <Button type="button" disabled={busy || !devs.length} onClick={() => onCreate(title, { template: tpl, devices: devs, settings: { style, brand_color: /^#[0-9a-fA-F]{6}$/.test(brand) ? brand : "" } })}>{busy ? <Spinner size={14} /> : <Icon name="plus" size={14} />} ساختِ طرح</Button>
    </Card>
  );
}

export function DesignListPage({ kind }: { kind: Kind }) {
  const { id = "" } = useParams<{ id: string }>();
  const nav = useNavigate();
  const { ov, error, reload } = useOverview(id);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  if (error) return <div className="ds-page"><ErrorBox message={error} /></div>;
  if (!ov) return <div className="ds-page"><Spinner /></div>;
  const docs = ov.docs.filter((d) => d.kind === kind);
  const create = async (title: string, opts: Record<string, unknown>) => {
    setBusy(true);
    setErr(null);
    try {
      const d = await designApi.create(id, kind, title, opts);
      nav(`/stores/${id}/design/${KIND_PATH[kind]}/${d.id}`);
    } catch (e) {
      setErr(apiError(e));
    } finally {
      setBusy(false);
    }
  };
  const del = async (d: DocSummary) => {
    if (!window.confirm(`«${d.title}» پاک شود؟`)) return;
    await designApi.remove(id, d.id).catch((e) => setErr(apiError(e)));
    await reload();
  };
  return (
    <div className="ds-page">
      <PageHeader title={kind === "catalog" ? "کاتالوگ محصولات" : kind === "deck" ? "ارائه (اسلاید)" : "طراحی UI/UX"} subtitle={KIND_INFO[kind].text}
        actions={<><Link to={`/stores/${id}/design`}><Button variant="ghost" type="button"><Icon name="back" size={14} /> استودیو</Button></Link><Button type="button" onClick={() => setOpen(!open)}><Icon name="plus" size={14} /> {open ? "بستن فرم" : "ساختِ تازه"}</Button></>} />
      {err ? <ErrorBox message={err} /> : null}
      {kind === "catalog" && !ov.products.length ? <Alert tone="warn">این فروشگاه هنوز محصولی ندارد؛ اول از بخشِ «محصولات» محصول اضافه کن.</Alert> : null}
      {open || !docs.length ? (kind === "catalog" ? <CatalogForm ov={ov} onCreate={create} busy={busy} /> : kind === "deck" ? <DeckForm ov={ov} onCreate={create} busy={busy} /> : <UiForm ov={ov} onCreate={create} busy={busy} />) : null}
      {docs.map((d) => <DocRow key={d.id} storeId={id} d={d} onDelete={del} />)}
    </div>
  );
}

// ───────────────────────────── راهنمای فایل‌ها (خلاصهٔ راهنمای مالک)

const FILE_TABLE: [string, string, string][] = [
  ["چاپخانه (کاتالوگ، بروشور)", "PDF/X با بلید و رنگ CMYK؛ اگر فایل باز خواستند: بستهٔ سورس", "«بستهٔ چاپخانه» PDF با بلید ۳ میلی‌متر و علامت برش می‌دهد؛ CMYK و PDF/X را چاپخانه می‌سازد."],
  ["مشتری، برای دیدن و تأیید", "PDF؛ یا JPG برای پیش‌نمایشِ سریع", "«بستهٔ مشتری»: PDF کم‌حجم + JPG هر صفحه."],
  ["طراحِ بعدی، برای ویرایش", "سورسِ کامل به‌همراهِ فونت‌ها", "«بستهٔ سورس»: سند (JSON)، PPTX، عکس‌ها، فونت‌ها و مجوزشان."],
  ["سایت", "WebP یا JPG برای عکس؛ PNG یا SVG برای لوگو؛ WOFF2 برای فونت", "«بستهٔ برنامه‌نویس» (UI): SVG/PNG هر فریم + توکن‌های CSS."],
  ["اینستاگرام و شبکه‌ها", "JPG یا PNG رنگ RGB: ۱۰۸۰×۱۰۸۰، ۱۰۸۰×۱۳۵۰، ۱۰۸۰×۱۹۲۰", "«بستهٔ شبکه‌های اجتماعی» هر سه اندازه را برای هر صفحه می‌سازد."],
  ["جلسه و ارائهٔ حضوری", "PPTX با فونت‌های جاسازی‌شده + PDF پشتیبان", "«بستهٔ جلسه»؛ فونت‌ها در بسته است (در PPTX جاسازی نمی‌شود)."],
  ["نمایشگاه یا کیوسک", "PPSX که خودش نمایش می‌دهد، یا ویدیوی MP4", "«بستهٔ نمایشگاه» PPSX می‌دهد؛ MP4 را از «ساختِ ویدیو» بگیر."],
];
const CONCEPTS: [string, string][] = [
  ["وکتور و پیکسلی", "وکتور (AI، SVG، PDF) هر قدر بزرگ شود تیز می‌ماند؛ پیکسلی (JPG، PNG) نه. متنِ PDF و SVG این استودیو منحنی است، عکس‌ها پیکسلی‌اند."],
  ["RGB و CMYK", "RGB رنگِ نور (وب و ارائه)، CMYK رنگِ جوهرِ چاپ. این استودیو RGB می‌دهد؛ تبدیلِ واقعی را چاپخانه انجام می‌دهد."],
  ["بلید و علامت برش", "حاشیهٔ اضافهٔ ۳ میلی‌متری تا بعد از برش نوارِ سفید نماند. «PDF چاپی» همراه با بلید و علامت برش است."],
  ["۳۰۰ dpi", "عکسِ چاپی باید در اندازهٔ واقعیِ چاپ ۳۰۰ dpi باشد؛ چک‌لیست dpi ِ مؤثرِ هر عکس را می‌سنجد."],
  ["فونت‌ها", "فونت‌ها یا جاسازی یا به منحنی تبدیل می‌شوند؛ این استودیو منحنی می‌کند. فونت‌های فارسیِ آماده همه SIL OFL‌اند (وزیرمتن، استعداد، لاله‌زار، شبنم، ساحل، صمیم)."],
  ["قاعدهٔ طلایی", "سورس را نگه دار؛ به دیگران خروجی بده."],
];
const TOOLS: [string, string][] = [
  ["Canva", "ساختِ سریعِ پست و ارائه؛ خروجیِ چاپیِ حرفه‌ای محدود؛ سورس فقط روی سایتِ خودش (در ایران تحریم و مسدود‌شدنِ حساب را در نظر بگیر)."],
  ["Figma", "طراحیِ سایت و اپ (کامپوننت، Auto Layout، متغیر، نمونهٔ کلیک‌پذیر)؛ برای کاتالوگِ چاپی ساخته نشده. «طراحی UI/UX» این استودیو همان ایده‌ها را سبک و پیش از سایت‌ساز می‌دهد."],
  ["PowerPoint", "استانداردِ ارائه؛ PPTXِ این استودیو در آن (و Google Slides، Keynote، LibreOffice) باز می‌شود."],
  ["Adobe / Affinity / CorelDRAW", "برنامه‌های حرفه‌ای چاپ؛ فایلِ باز (INDD، AI، CDR) از این‌جا ساخته نمی‌شود — «بستهٔ سورس» و PDF چاپی را به طراح بده. جایگزینِ رایگان: Affinity، Inkscape، Scribus، LibreOffice."],
];

export function DesignGuidePage() {
  const { id = "" } = useParams<{ id: string }>();
  return (
    <div className="ds-page">
      <PageHeader title="راهنمای فایل‌ها و ابزارهای طراحی" subtitle="خلاصهٔ «راهنمای پسوند فایل‌ها و ابزارهای طراحی» (۱۴۰۵/۰۸/۲۳) و این‌که هر خروجیِ استودیو کجا به کار می‌آید"
        actions={<Link to={`/stores/${id}/design`}><Button variant="ghost" type="button"><Icon name="back" size={14} /> استودیو</Button></Link>} />
      <Card>
        <h2 className="ds-h2">کدام فایل را به چه کسی بدهیم</h2>
        <div className="ds-tablewrap"><table className="ds-table">
          <thead><tr><th>گیرنده</th><th>چه بفرستیم</th><th>در این استودیو</th></tr></thead>
          <tbody>{FILE_TABLE.map((r) => <tr key={r[0]}><td><b>{r[0]}</b></td><td>{r[1]}</td><td>{r[2]}</td></tr>)}</tbody>
        </table></div>
      </Card>
      <Card>
        <h2 className="ds-h2">چند مفهومِ پایه</h2>
        <dl className="ds-dl">{CONCEPTS.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
        <h3 className="ds-sub">چک‌لیستِ فایلِ کاتالوگ برای چاپخانه</h3>
        <ul className="ds-list">
          <li>PDF/X (یا هر نسخه‌ای که چاپخانه خواست) و رنگ CMYK — چاپخانه از PDF ما می‌سازد</li>
          <li>عکس‌ها دست‌کم ۳۰۰ dpi در اندازهٔ واقعیِ چاپ — چک‌لیستِ استودیو می‌سنجد</li>
          <li>بلید ۳ میلی‌متر + علامت برش — در «PDF چاپی»</li>
          <li>فونت‌ها جاسازی یا منحنی — منحنی</li>
          <li>متن‌ها و لوگوهای مهم دست‌کم ۵ میلی‌متر از لبهٔ برش — چک‌لیست می‌سنجد</li>
          <li>صفحه‌ها تکی — بله</li>
          <li>تعدادِ صفحه‌های کاتالوگِ منگنه‌ای مضربِ ۴ — دکمهٔ «تکمیل تا مضرب ۴»</li>
        </ul>
      </Card>
      <Card>
        <h2 className="ds-h2">ابزارها (Canva، Figma، PowerPoint، Adobe و جایگزین‌ها)</h2>
        <dl className="ds-dl">{TOOLS.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
        <p className="ds-muted">متنِ کاملِ راهنما را مالک نوشته است؛ این صفحه فقط خلاصه‌ای است که با خروجی‌های همین استودیو پیوند خورده.</p>
      </Card>
    </div>
  );
}
