import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { errorMessage } from "../../../api/client";
import Icon from "../../../components/Icon";
import { useQueuedAi } from "../../../components/QueuedAi";
import { useFlags } from "../../panel/FlagsContext";
import { Alert, Badge, Button, Card, EmptyState, ErrorBox, Field, Input, PageHeader, Select, Spinner, TextArea, fa } from "../../../components/ui";
import { GenerateResult, Idea, IdeaDraft, Overview, faDigits, ideasApi, jalaliText, matches } from "./api";
import "./ideas.css";

/**
 * بانکِ ایده — «این هفته چه پستی بگذارم؟»
 *
 * ایده‌های آمادهٔ فارسی در ۸ دسته، با جای‌گیرهایی که از پروفایلِ فروشگاه پر می‌شوند؛ ستاره و پنهان‌کردن (برای هر فروشگاه جدا)؛
 * «ایده بساز» که با هوش مصنوعی (اگر در دسترس باشد) یا فرمول‌های آمادهٔ فارسی ایدهٔ تازه می‌نویسد و تکراری نمی‌سازد؛
 * و «از این ایده شروع کن»: استودیوی تولید محتوا، تقویمِ انتشار یا تامنیل‌ساز با فرم‌هایی که از قبل پر شده‌اند.
 * هیچ قیمت، آمار یا نظرِ مشتریِ ساختگی در ایده‌ها نیست؛ جاهای خالیِ «[...]» را خودِ فروشگاه با دادهٔ واقعی پر می‌کند.
 */

const FORMAT_ICON: Record<string, "film" | "image" | "camera" | "clock"> = { reel: "film", carousel: "image", photo: "camera", story: "clock" };
const ORIGIN_FA: Record<string, string> = { user: "نوشتهٔ شما", duplicate: "کپی از ایدهٔ آماده", generated: "ساخته‌شده با «ایده بساز»", trend: "از ترندها", imported: "واردشده" };
const VIA_FA: Record<string, string> = { ai: "هوش مصنوعی", mixed: "هوش مصنوعی + فرمول", formula: "فرمول‌های آماده" };
const EMPTY_DRAFT: IdeaDraft = { category: "tips", format: "photo", channel: "instagram", title: "", logline: "", hook: "", shoot: "", cta: "", tags: "" };

function tomorrowISO(): string {
  const d = new Date(Date.now() + 86_400_000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function safeGet(key: string): string {
  try {
    return localStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}
function safeSet(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* حالتِ خصوصی: مهم نیست */
  }
}

export default function IdeasPage() {
  const { id = "" } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { featureEnabled } = useFlags();            // «ideas.generate» و «ideas.start» را ادمین می‌تواند جدا خاموش کند
  const canGenerate = featureEnabled("ideas.generate");
  const canStart = featureEnabled("ideas.start");
  const [ov, setOv] = useState<Overview | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [product, setProduct] = useState<number | null>(null);
  // فیلترها
  const [text, setText] = useState("");
  const [category, setCategory] = useState("");
  const [fmt, setFmt] = useState("");
  const [channel, setChannel] = useState("");
  const [tag, setTag] = useState("");
  const [onlyFav, setOnlyFav] = useState(false);
  const [onlyMine, setOnlyMine] = useState(false);
  const [onlyData, setOnlyData] = useState(false);
  const [showHidden, setShowHidden] = useState(false);
  // کارت‌ها
  const [open, setOpen] = useState<string | null>(null);
  const [startFor, setStartFor] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ key: string | null; draft: IdeaDraft } | null>(null);
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);
  const [genOpen, setGenOpen] = useState(false);
  const [gen, setGen] = useState<GenerateResult | null>(null);
  // «در صف تا روشن شدنِ سرورِ پردازش»: ایده‌های هوشمند که با روشن شدنِ گره خودکار ساخته و ذخیره می‌شوند
  const qa = useQueuedAi<GenerateResult>("ideas", id, (r) => {
    setGen(r);
    setFresh(new Set((r.ideas ?? []).map((x) => x.key)));
    setNotice("ایده‌های هوشمندِ صف‌دار رسید و ذخیره شد.");
    void load();
  });
  const topRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try {
      setOv(await ideasApi.overview(id, product));
      setLoadError(null);
    } catch (e) {
      setLoadError(errorMessage(e));
    }
  }, [id, product]);

  useEffect(() => {
    void load();
  }, [load]);

  const list = useMemo(
    () =>
      (ov?.ideas ?? []).filter(
        (i) =>
          (showHidden || !i.hidden) &&
          (!category || i.category === category) &&
          (!fmt || i.format === fmt) &&
          (!channel || i.channel === channel || i.channel === "both") &&
          (!tag || i.tags.includes(tag)) &&
          (!onlyFav || i.favorite) &&
          (!onlyMine || !i.builtin) &&
          (!onlyData || i.needs_data) &&
          matches(i, text),
      ),
    [ov, showHidden, category, fmt, channel, tag, onlyFav, onlyMine, onlyData, text],
  );
  const filtered = !!(text || category || fmt || channel || tag || onlyFav || onlyMine || onlyData);
  const clearAll = () => {
    setText("");
    setCategory("");
    setFmt("");
    setChannel("");
    setTag("");
    setOnlyFav(false);
    setOnlyMine(false);
    setOnlyData(false);
  };

  async function run<T>(key: string, job: () => Promise<T>): Promise<T | undefined> {
    setBusy(key);
    setError(null);
    try {
      return await job();
    } catch (e) {
      setError(errorMessage(e));
      return undefined;
    } finally {
      setBusy(null);
    }
  }

  const mark = (i: Idea, patch: { favorite?: boolean; hidden?: boolean }) =>
    run(`mark-${i.key}`, async () => {
      await ideasApi.mark(id, i.key, patch);
      await load();
    });

  const surprise = () => {
    if (!list.length) return;
    const pick = list[Math.floor(Math.random() * list.length)];
    setOpen(pick.key);
    window.setTimeout(() => document.getElementById(`idea-${pick.key}`)?.scrollIntoView({ block: "center", behavior: "smooth" }), 60);
  };

  const duplicate = (i: Idea) =>
    run(`dup-${i.key}`, async () => {
      const made = await ideasApi.duplicate(id, i.key);
      await load();
      setNotice("کپی ساخته شد؛ حالا می‌توانید ویرایشش کنید.");
      setEditing({ key: made.key, draft: draftOf(made) });
      topRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });

  const remove = (i: Idea) =>
    run(`del-${i.key}`, async () => {
      if (!window.confirm(`«${i.filled.title}» پاک شود؟`)) return;
      await ideasApi.remove(id, i.key);
      await load();
    });

  const saveDraft = () =>
    run("save", async () => {
      if (!editing) return;
      if (editing.key) await ideasApi.update(id, editing.key, editing.draft);
      else await ideasApi.create(id, editing.draft);
      setEditing(null);
      setNotice("ایده ذخیره شد.");
      await load();
    });

  async function goStudio(i: Idea, tab: string) {
    const r = await run(`studio-${i.key}`, () => ideasApi.startStudio(id, i.key, product));
    if (!r) return;
    const q = new URLSearchParams({ tab });
    if (r.product_id) q.set("product", String(r.product_id));
    q.set("brief", tab === "image" ? r.detail : r.brief);
    navigate(`/stores/${id}/studio?${q.toString()}`);
  }

  async function goThumbnail(i: Idea) {
    const r = await run(`thumb-${i.key}`, () => ideasApi.startThumbnail(id, i.key));
    if (!r) return;
    const q = new URLSearchParams({ format: r.format, title: r.title, subtitle: r.subtitle, kicker: r.kicker });
    navigate(`/stores/${id}/thumbnails?${q.toString()}`);
  }

  if (loadError) return <ErrorBox message={loadError} />;
  if (!ov) return <Spinner />;

  const st = ov.store;
  const missing = [!st.known["مخاطب"] && "مخاطبِ فروشگاه", !st.known["حوزه"] && "نوعِ کسب‌وکار"].filter(Boolean) as string[];

  return (
    <div className="ib-root" ref={topRef}>
      <PageHeader
        title="بانکِ ایده"
        subtitle="«این هفته چه پستی بگذارم؟» — ایده‌های آمادهٔ فارسی برای فروشگاه شما؛ همیشه جواب دارد، حتی وقتی هوش مصنوعی خاموش است."
        actions={
          <>
            <Button onClick={() => setEditing({ key: null, draft: { ...EMPTY_DRAFT, category: category || "tips" } })}>
              <Icon name="plus" /> ایدهٔ تازه
            </Button>
            {canGenerate && (
              <Button variant="secondary" onClick={() => setGenOpen((v) => !v)} aria-expanded={genOpen}>
                <Icon name="sparkle" /> ایده بساز
              </Button>
            )}
            <Button variant="ghost" onClick={surprise} disabled={!list.length}>
              <Icon name="refresh" /> غافلگیرم کن
            </Button>
          </>
        }
      />
      <ErrorBox message={error} />
      {notice && <Alert tone="ok" action={<Button size="sm" variant="ghost" onClick={() => setNotice(null)}>بستن</Button>}>{notice}</Alert>}

      {/* ── پروفایلِ فروشگاه و محصول */}
      <Card className="ib-profile">
        <div className="ib-profile-row">
          <div className="ib-chips">
            <Badge tone="brand">{st.name}</Badge>
            {st.known["مخاطب"] && <Badge tone="neutral">مخاطب: {st.values["مخاطب"]}</Badge>}
            {st.tone && <Badge tone="neutral">لحن: {st.tone}</Badge>}
            <Badge tone={ov.ai.ok ? "ok" : "neutral"}>{ov.ai.ok ? "هوش مصنوعی آماده است" : "هوش مصنوعی الان در دسترس نیست"}</Badge>
          </div>
          <div className="ib-product">
            <Field label="محصول یا خدمتِ این ایده‌ها" hint="جای‌گیرِ «{محصول}» در همهٔ ایده‌ها با همین پر می‌شود">
              <Select value={product ?? ""} onChange={(e) => setProduct(e.target.value ? Number(e.target.value) : null)}>
                <option value="">بدونِ انتخاب (واژهٔ «محصول»)</option>
                {ov.products.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </Select>
            </Field>
          </div>
        </div>
        {!ov.ai.ok && (
          <p className="ib-hint">
            {ov.ai.why ? `${ov.ai.why.replace(/[.؛\s]+$/, "")}. ` : ""}ایده‌های آماده و «ایده بساز» (با فرمول‌های فارسی) همچنان کار می‌کنند؛ با برگشتنِ هوش مصنوعی همان دکمه ایده‌های هوشمند می‌دهد.
          </p>
        )}
        {missing.length > 0 && (
          <p className="ib-hint">
            برای ایده‌های دقیق‌تر {missing.join(" و ")} را در <Link to={`/stores/${id}/brand`}>پروفایل برند</Link> بنویسید؛ تا آن موقع واژهٔ عمومی («مشتری‌ها») می‌آید.
          </p>
        )}
      </Card>

      {qa.banner}

      {/* ── ایده بساز */}
      {genOpen && canGenerate && (
        <Generator
          storeId={id}
          ov={ov}
          product={product}
          defaultCategory={category}
          busy={busy === "gen"}
          result={gen}
          onRun={async (body) => {
            const r = await run("gen", () => ideasApi.generate(id, { ...body, product }));
            if (!r) return;
            setGen(r);
            qa.setQueued(r.queued);
            setFresh(new Set(r.ideas.map((x) => x.key)));
            clearAll();
            setOnlyMine(true);
            await load();
          }}
        />
      )}

      {/* ── ویرایشگر */}
      {editing && (
        <Card className="ib-editor">
          <h2 className="ib-h2">{editing.key ? "ویرایشِ ایده" : "ایدهٔ تازه"}</h2>
          <p className="ib-hint">می‌توانید از {"{محصول} {فروشگاه} {مخاطب} {حوزه}"} استفاده کنید تا از پروفایلِ فروشگاه پر شود، و جای خالیِ «[...]» برای دادهٔ واقعی بگذارید.</p>
          <div className="ib-form">
            <Field label="عنوان">
              <Input value={editing.draft.title ?? ""} maxLength={120} onChange={(e) => setEditing({ ...editing, draft: { ...editing.draft, title: e.target.value } })} />
            </Field>
            <Field label="دسته">
              <Select value={editing.draft.category} onChange={(e) => setEditing({ ...editing, draft: { ...editing.draft, category: e.target.value } })}>
                {ov.categories.map((c) => (<option key={c.key} value={c.key}>{c.fa}</option>))}
              </Select>
            </Field>
            <Field label="قالب">
              <Select value={editing.draft.format} onChange={(e) => setEditing({ ...editing, draft: { ...editing.draft, format: e.target.value } })}>
                {ov.formats.map((c) => (<option key={c.key} value={c.key}>{c.fa}</option>))}
              </Select>
            </Field>
            <Field label="کانال">
              <Select value={editing.draft.channel} onChange={(e) => setEditing({ ...editing, draft: { ...editing.draft, channel: e.target.value } })}>
                <option value="instagram">اینستاگرام</option>
                <option value="telegram">تلگرام</option>
                <option value="both">اینستاگرام و تلگرام</option>
              </Select>
            </Field>
            <div className="ib-wide">
              <Field label="یک‌جمله‌ای (این پست چیست؟)">
                <TextArea rows={2} value={editing.draft.logline ?? ""} maxLength={600} onChange={(e) => setEditing({ ...editing, draft: { ...editing.draft, logline: e.target.value } })} />
              </Field>
            </div>
            <div className="ib-wide">
              <Field label="قلاب (جملهٔ اولِ محتوا)">
                <Input value={editing.draft.hook ?? ""} maxLength={300} onChange={(e) => setEditing({ ...editing, draft: { ...editing.draft, hook: e.target.value } })} />
              </Field>
            </div>
            <div className="ib-wide">
              <Field label="چه چیزی فیلم یا عکس بگیریم؟">
                <TextArea rows={2} value={editing.draft.shoot ?? ""} maxLength={600} onChange={(e) => setEditing({ ...editing, draft: { ...editing.draft, shoot: e.target.value } })} />
              </Field>
            </div>
            <Field label="دعوت به اقدام">
              <Input value={editing.draft.cta ?? ""} maxLength={80} onChange={(e) => setEditing({ ...editing, draft: { ...editing.draft, cta: e.target.value } })} />
            </Field>
            <Field label="برچسب‌ها (با ویرگول)">
              <Input value={editing.draft.tags ?? ""} onChange={(e) => setEditing({ ...editing, draft: { ...editing.draft, tags: e.target.value } })} />
            </Field>
          </div>
          <div className="ib-actions">
            <Button onClick={() => void saveDraft()} disabled={busy === "save" || !(editing.draft.title ?? "").trim() || !(editing.draft.logline ?? "").trim()}>
              {busy === "save" ? "…" : "ذخیره"}
            </Button>
            <Button variant="ghost" onClick={() => setEditing(null)}>انصراف</Button>
          </div>
        </Card>
      )}

      {/* ── جست‌وجو و فیلتر */}
      <div className="ib-filters">
        <Input type="search" value={text} onChange={(e) => setText(e.target.value)} placeholder="جست‌وجو در عنوان، متن، برچسب و مناسبت…" aria-label="جست‌وجو" />
        <div className="ib-cats" role="group" aria-label="دسته‌ها">
          <button type="button" className={`ib-chip${category === "" ? " on" : ""}`} aria-pressed={category === ""} onClick={() => setCategory("")}>
            همه <span>({fa(ov.total)})</span>
          </button>
          {ov.categories.map((c) => (
            <button key={c.key} type="button" className={`ib-chip${category === c.key ? " on" : ""}`} aria-pressed={category === c.key} onClick={() => setCategory(category === c.key ? "" : c.key)}>
              {c.fa} <span>({fa(c.count)})</span>
            </button>
          ))}
        </div>
        <div className="ib-row">
          <Select value={fmt} onChange={(e) => setFmt(e.target.value)} aria-label="قالب">
            <option value="">همهٔ قالب‌ها</option>
            {ov.formats.map((f) => (<option key={f.key} value={f.key}>{f.fa} ({fa(f.count)})</option>))}
          </Select>
          <Select value={channel} onChange={(e) => setChannel(e.target.value)} aria-label="کانال">
            <option value="">همهٔ کانال‌ها</option>
            {ov.channels.map((f) => (<option key={f.key} value={f.key}>{f.fa} ({fa(f.count)})</option>))}
          </Select>
          <Select value={tag} onChange={(e) => setTag(e.target.value)} aria-label="برچسب">
            <option value="">همهٔ برچسب‌ها</option>
            {ov.tags.map((t) => (<option key={t.tag} value={t.tag}>{t.tag} ({fa(t.count)})</option>))}
          </Select>
          <label className="ib-check"><input type="checkbox" checked={onlyFav} onChange={(e) => setOnlyFav(e.target.checked)} /> فقط ستاره‌دارها</label>
          <label className="ib-check"><input type="checkbox" checked={onlyMine} onChange={(e) => setOnlyMine(e.target.checked)} /> ایده‌های من</label>
          <label className="ib-check"><input type="checkbox" checked={onlyData} onChange={(e) => setOnlyData(e.target.checked)} /> نیازمندِ دادهٔ واقعی ({fa(ov.needs_data)})</label>
          <label className="ib-check"><input type="checkbox" checked={showHidden} onChange={(e) => setShowHidden(e.target.checked)} /> پنهان‌ها</label>
          {filtered && <Button variant="ghost" size="sm" onClick={clearAll}>پاک‌کردنِ فیلترها</Button>}
        </div>
        <div className="ib-count" aria-live="polite">{fa(list.length)} ایده نشان داده می‌شود</div>
      </div>

      {/* ── کارت‌ها */}
      {list.length === 0 ? (
        <Card>
          <EmptyState
            icon="bulb"
            title="ایده‌ای با این فیلتر پیدا نشد"
            description="فیلترها را کم کنید، یا با «ایده بساز» ایده‌های تازه بگیرید."
            action={filtered ? <Button variant="secondary" onClick={clearAll}>پاک‌کردنِ فیلترها</Button> : undefined}
          />
        </Card>
      ) : (
        <div className="ib-grid">
          {list.map((i) => (
            <IdeaCard
              key={i.key}
              idea={i}
              isOpen={open === i.key}
              isFresh={fresh.has(i.key)}
              starting={startFor === i.key}
              busy={busy}
              ov={ov}
              storeId={id}
              product={product}
              canStart={canStart}
              onToggle={() => setOpen(open === i.key ? null : i.key)}
              onFav={() => void mark(i, { favorite: !i.favorite })}
              onHide={() => void mark(i, { hidden: !i.hidden })}
              onCopy={() => void duplicate(i)}
              onEdit={() => {
                setEditing({ key: i.key, draft: draftOf(i) });
                topRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
              }}
              onDelete={() => void remove(i)}
              onStart={() => setStartFor(startFor === i.key ? null : i.key)}
              onStudio={(tab) => void goStudio(i, tab)}
              onThumbnail={() => void goThumbnail(i)}
              onPlanned={async (body) => {
                const r = await run(`plan-${i.key}`, () => ideasApi.startCalendar(id, i.key, body));
                if (r) {
                  setNotice(`به «${r.campaign}» اضافه شد (کارِ محتوا با تاریخِ پیشنهادی). چیزی منتشر یا زمان‌بندی نشد.`);
                  await load();
                }
                return !!r;
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function draftOf(i: Idea): IdeaDraft {
  return { category: i.category, format: i.format, channel: i.channel, title: i.title, logline: i.logline, hook: i.hook, shoot: i.shoot, cta: i.cta, tags: i.tags.join("، ") };
}

/* ───────────────────────────────────────────── ایده بساز */

function Generator({
  storeId, ov, product, defaultCategory, busy, result, onRun,
}: {
  storeId: string;
  ov: Overview;
  product: number | null;
  defaultCategory: string;
  busy: boolean;
  result: GenerateResult | null;
  onRun: (body: { category: string; count: number; topic: string; instruction: string; facts: string[]; ai: boolean; variation: number }) => Promise<void>;
}) {
  const factsKey = `ideabank-facts-${storeId}`;
  const [category, setCategory] = useState(defaultCategory);
  const [count, setCount] = useState(5);
  const [topic, setTopic] = useState("");
  const [instruction, setInstruction] = useState("");
  const [facts, setFacts] = useState(() => safeGet(factsKey));
  const [useAi, setUseAi] = useState(true);
  const [variation, setVariation] = useState(0);
  const productName = ov.products.find((p) => p.id === product)?.name;
  return (
    <Card className="ib-gen">
      <h2 className="ib-h2"><Icon name="sparkle" /> ایده بساز</h2>
      <p className="ib-hint">
        ایده‌های تازه می‌نویسد و به «ایده‌های من» اضافه می‌کند؛ تکراری نمی‌سازد و از ایده‌های ستاره‌دارتان یاد می‌گیرد.
        {ov.ai.ok ? " هوش مصنوعی آماده است." : " هوش مصنوعی الان در دسترس نیست؛ از فرمول‌های آمادهٔ فارسی استفاده می‌شود."}
      </p>
      <div className="ib-form">
        <Field label="دسته">
          <Select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">ترکیبی از همهٔ دسته‌ها</option>
            {ov.categories.map((c) => (<option key={c.key} value={c.key}>{c.fa}</option>))}
          </Select>
        </Field>
        <Field label="چند ایده؟">
          <Select value={count} onChange={(e) => setCount(Number(e.target.value))}>
            {[3, 5, 8].map((n) => (<option key={n} value={n}>{faDigits(n)} ایده</option>))}
          </Select>
        </Field>
        <div className="ib-wide">
          <Field label="موضوع (اختیاری)" hint={productName ? `بدونِ موضوع از «${productName}» استفاده می‌شود` : "بدونِ موضوع از محصولِ انتخاب‌شده یا حوزهٔ فروشگاه استفاده می‌شود"}>
            <Input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="مثلاً: برنامهٔ ورزشی برای مبتدی‌ها" onKeyDown={(e) => e.key === "Enter" && void onRun({ category, count, topic, instruction, facts: facts.split("\n"), ai: useAi, variation })} />
          </Field>
        </div>
        <div className="ib-wide">
          <Field label="توضیحِ بیشتر برای هوش مصنوعی (اختیاری)">
            <Input value={instruction} onChange={(e) => setInstruction(e.target.value)} placeholder="مثلاً: لحنِ صمیمی؛ برای نوروز" />
          </Field>
        </div>
        <div className="ib-wide">
          <Field label="واقعیت‌های برند (اختیاری؛ هر خط یک جمله)" hint="فقط جمله‌هایی که خودتان تأیید کرده‌اید؛ ایده‌ها آن‌ها را عیناً به کار می‌برند و هیچ عدد، قیمت یا آماری از خودشان نمی‌سازند.">
            <TextArea rows={3} value={facts} onChange={(e) => { setFacts(e.target.value); safeSet(factsKey, e.target.value); }} placeholder="مثلاً: شعارِ ما «…» است" />
          </Field>
        </div>
      </div>
      <div className="ib-actions">
        <label className="ib-check"><input type="checkbox" checked={useAi} onChange={(e) => setUseAi(e.target.checked)} /> با هوش مصنوعی (اگر در دسترس بود)</label>
        <Button
          disabled={busy}
          onClick={() => {
            setVariation((v) => v + 1);
            void onRun({ category, count, topic, instruction, facts: facts.split("\n"), ai: useAi, variation });
          }}
        >
          {busy ? "در حال نوشتن…" : "ایده بساز"}
        </Button>
      </div>
      {result && (
        <Alert tone={result.via === "formula" && result.ai.tried ? "info" : "ok"} title={`${fa(result.saved ?? result.ideas.length)} ایدهٔ تازه — ${VIA_FA[result.via] ?? result.via}`}>
          {result.message}
          {result.skipped ? ` (${fa(result.skipped)} ایدهٔ تکراری رد شد.)` : ""}
        </Alert>
      )}
    </Card>
  );
}

/* ───────────────────────────────────────────── یک کارت */

function IdeaCard(props: {
  idea: Idea;
  isOpen: boolean;
  isFresh: boolean;
  starting: boolean;
  busy: string | null;
  ov: Overview;
  storeId: string;
  product: number | null;
  canStart: boolean;
  onToggle: () => void;
  onFav: () => void;
  onHide: () => void;
  onCopy: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onStart: () => void;
  onStudio: (tab: string) => void;
  onThumbnail: () => void;
  onPlanned: (body: { campaign?: number; product?: number; due?: string }) => Promise<boolean>;
}) {
  const { idea: i, isOpen, starting, ov } = props;
  const cat = ov.categories.find((c) => c.key === i.category)?.fa ?? i.category;
  const fmtLabel = ov.formats.find((c) => c.key === i.format)?.fa ?? i.format;
  const chan = ov.channels.find((c) => c.key === i.channel)?.fa ?? "اینستاگرام و تلگرام";
  const f = i.filled;
  return (
    <article id={`idea-${i.key}`} className={`ib-card${i.hidden ? " is-hidden" : ""}${props.isFresh ? " is-fresh" : ""}${isOpen ? " is-open" : ""}`}>
      <header className="ib-card-head">
        <div className="ib-badges">
          <Badge tone="brand">{cat}</Badge>
          <Badge tone="neutral"><Icon name={FORMAT_ICON[i.format] ?? "file"} size={12} /> {fmtLabel}</Badge>
          <Badge tone="neutral">{chan}</Badge>
          {i.occasion_next && <Badge tone="info">{i.occasion_next.label}{i.occasion_next.days === 0 ? " — امروز" : i.occasion_next.days <= 45 ? " — به‌زودی" : ""}</Badge>}
          {i.needs_data && <Badge tone="warn">نیازمندِ دادهٔ واقعی</Badge>}
          {!i.builtin && <Badge tone="ok">{ORIGIN_FA[i.origin] ?? "ایدهٔ من"}</Badge>}
          {i.hidden && <Badge tone="neutral">پنهان</Badge>}
          {i.uses > 0 && <Badge tone="neutral">{faDigits(i.uses)} بار استفاده</Badge>}
        </div>
        <button type="button" className={`ib-star${i.favorite ? " on" : ""}`} aria-pressed={i.favorite} title={i.favorite ? "برداشتنِ ستاره" : "ستاره بده"} onClick={props.onFav}>
          {i.favorite ? "★" : "☆"}
        </button>
      </header>

      <h3 className="ib-title">{f.title}</h3>
      <p className="ib-logline">{f.logline}</p>
      {f.hook && <p className="ib-hook">«{f.hook}»</p>}

      {isOpen && (
        <div className="ib-more">
          {f.shoot && (<p><b>چه چیزی بگیریم؟</b> {f.shoot}</p>)}
          {f.cta && (<p><b>دعوت به اقدام:</b> {f.cta}</p>)}
          {i.tags.length > 0 && <div className="ib-tags">{i.tags.map((t) => (<span key={t}>{t}</span>))}</div>}
          {i.slots.length > 0 && (
            <Alert tone="warn" title="جاهای خالی">
              این ایده را فقط با دادهٔ واقعیِ فروشگاه پر کنید: {i.slots.join("، ")}. هیچ چیزی از خودمان نساخته‌ایم.
            </Alert>
          )}
          {i.occasion_next && <p className="ib-hint">تاریخِ ثابتِ شمسی: {i.occasion_next.label}؛ نزدیک‌ترین بار {faDigits(i.occasion_next.days)} روز دیگر.</p>}
        </div>
      )}

      <div className="ib-actions">
        {props.canStart && <Button size="sm" onClick={props.onStart} aria-expanded={starting}><Icon name="rocket" size={14} /> از این ایده شروع کن</Button>}
        <Button size="sm" variant="ghost" onClick={props.onToggle}>{isOpen ? "کمتر" : "جزئیات"}</Button>
        {i.builtin ? (
          <Button size="sm" variant="ghost" onClick={props.onCopy} title="برای ویرایش، یک کپی از ایده بسازید">کپی برای ویرایش</Button>
        ) : (
          <>
            <Button size="sm" variant="ghost" onClick={props.onEdit}><Icon name="edit" size={13} /> ویرایش</Button>
            <Button size="sm" variant="ghost" onClick={props.onDelete}><Icon name="trash" size={13} /> حذف</Button>
          </>
        )}
        <Button size="sm" variant="ghost" onClick={props.onHide} title={i.hidden ? "دوباره نشان بده" : "از فهرست پنهان کن"}>{i.hidden ? "نشان بده" : "پنهان کن"}</Button>
      </div>

      {starting && props.canStart && <StartPanel {...props} />}
    </article>
  );
}

function StartPanel({ idea: i, ov, storeId, product, busy, onStudio, onThumbnail, onPlanned }: Parameters<typeof IdeaCard>[0]) {
  const [campaign, setCampaign] = useState<string>(ov.campaigns[0] ? String(ov.campaigns[0].id) : "");
  const [planProduct, setPlanProduct] = useState<string>(product ? String(product) : ov.products[0] ? String(ov.products[0].id) : "");
  const [due, setDue] = useState<string>(i.occasion_next?.date ?? tomorrowISO());
  const [done, setDone] = useState(false);
  const studioDefault = i.format === "reel" ? "video" : "image";
  const tabs = [
    { key: "video", label: "ویدیو" },
    { key: "image", label: "عکس و پوستر" },
    { key: "caption", label: "کپشن" },
  ];
  return (
    <div className="ib-start" role="group" aria-label="شروع از این ایده">
      <section>
        <h4><Icon name="sparkle" size={14} /> تولید محتوا</h4>
        <p className="ib-hint">استودیو با خلاصهٔ ایده در کادرِ «هدف» باز می‌شود؛ پیشنهادِ این ایده: {tabs.find((t) => t.key === studioDefault)?.label}.</p>
        <div className="ib-actions">
          {tabs.map((t) => (
            <Button key={t.key} size="sm" variant={t.key === studioDefault ? "primary" : "secondary"} disabled={busy === `studio-${i.key}`} onClick={() => onStudio(t.key)}>
              {t.label}
            </Button>
          ))}
        </div>
      </section>
      <section>
        <h4><Icon name="clock" size={14} /> تقویمِ انتشار</h4>
        <p className="ib-hint">یک «کارِ محتوا» با تاریخِ پیشنهادی در تختهٔ کمپین ساخته می‌شود؛ چیزی منتشر یا زمان‌بندی نمی‌شود.</p>
        <div className="ib-form ib-form-sm">
          {ov.campaigns.length > 0 && (
            <Field label="کمپین">
              <Select value={campaign} onChange={(e) => setCampaign(e.target.value)}>
                {ov.campaigns.map((c) => (<option key={c.id} value={c.id}>{c.name}</option>))}
                <option value="">— «برنامهٔ محتوا» برای یک محصول بساز —</option>
              </Select>
            </Field>
          )}
          {(!campaign || ov.campaigns.length === 0) && (
            <Field label="محصولِ کمپین">
              <Select value={planProduct} onChange={(e) => setPlanProduct(e.target.value)}>
                {ov.products.length === 0 && <option value="">اول یک محصول اضافه کنید</option>}
                {ov.products.map((p) => (<option key={p.id} value={p.id}>{p.name}</option>))}
              </Select>
            </Field>
          )}
          <Field label="تاریخ" hint={jalaliText(due) ? `تاریخِ شمسی: ${jalaliText(due)}` : undefined}>
            <Input type="date" value={due} onChange={(e) => setDue(e.target.value)} />
          </Field>
        </div>
        <div className="ib-actions">
          <Button
            size="sm"
            disabled={busy === `plan-${i.key}` || (!campaign && !planProduct) || !due}
            onClick={async () => setDone(await onPlanned(campaign ? { campaign: Number(campaign), due } : { product: Number(planProduct), due }))}
          >
            {busy === `plan-${i.key}` ? "…" : "افزودن به تقویم"}
          </Button>
          {done && <Link className="ib-link" to={`/stores/${storeId}/campaigns/calendar`}>دیدن در تقویم انتشار</Link>}
        </div>
      </section>
      <section>
        <h4><Icon name="image" size={14} /> تامنیل‌ساز</h4>
        <p className="ib-hint">قالب و عنوانِ هماهنگ با ایده پر می‌شود (پیش از ساخت می‌توانید همه‌چیز را عوض کنید).</p>
        <Button size="sm" variant="secondary" disabled={busy === `thumb-${i.key}`} onClick={onThumbnail}>باز کردنِ تامنیل‌ساز</Button>
      </section>
    </div>
  );
}
