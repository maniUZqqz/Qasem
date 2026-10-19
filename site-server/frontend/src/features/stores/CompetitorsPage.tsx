import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, errorMessage } from "../../api/client";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBox,
  Field,
  Input,
  PageHeader,
  SectionTitle,
  Select,
  Spinner,
  Table,
  fa,
  toman,
} from "../../components/ui";

type Match = {
  score: number;
  verdict: "same" | "maybe" | "different";
  reason: string;
  our_product_id: number | null;
  our_product_name: string;
  confident: boolean;
  llm?: { relation?: string; same: boolean; substitute: boolean; reason: string; at: string };
};

type CompetitorProduct = {
  id: number;
  name: string;
  url: string;
  link: string;
  image: string;
  price_toman: number | null;
  observed_at: string | null;
  matches: number | null;
  matches_name: string | null;
  our_price: number | null;
  source: string;
  match: Match | null;
  currency_how: string;
};

type Crawl = {
  job_id: number;
  state: string;
  progress: number;
  total: number;
  label: string;
  error: string;
  created_at: string;
  updated_at: string;
  result: {
    crawl?: {
      products_found: number;
      pages_fetched: number;
      candidates: number;
      robots: string;
      robots_blocked: number;
      discovery: string;
      errors: string[];
      skipped_no_product: number;
      stopped: string;
    };
    saved?: { created: number; updated: number };
    verdict?: { label: string; llm: string };
  };
};

type Verdict = {
  status: "confirmed" | "maybe" | "no" | "unknown";
  confirmed: boolean;
  label: string;
  same: number;
  maybe: number;
  checked: number;
};

type Competitor = {
  id: number;
  name: string;
  kind: string;
  website: string;
  instagram: string;
  notes: string;
  revenue_model: string;
  positioning: string;
  strengths: string[];
  weaknesses: string[];
  analysed_at: string | null;
  is_stale: boolean;
  products: CompetitorProduct[];
  product_competitor: Verdict;
  crawl: Crawl | null;
  is_marketplace: boolean;
};

type SuggestionItem = {
  name: string;
  price_toman: number | null;
  url: string;
  our_product_name: string;
  score: number;
  verdict: string;
  reason: string;
  sales_count?: number | null;
};

type Suggestion = {
  key: string;
  name: string;
  platform: string;
  platform_label: string;
  website: string;
  city: string;
  already_added: boolean;
  items: SuggestionItem[];
  our_products: number[];
  why: string;
};

type Discovery = {
  suggestions: Suggestion[];
  sources: { source: string; query: string; ok: boolean; count?: number; error?: string }[];
  note: string;
  products_checked?: string[];
};

const KIND_LABEL: Record<string, string> = {
  DIRECT: "رقیب مستقیم",
  ADJACENT: "رقیب غیرمستقیم",
  MARKETPLACE: "مارکت‌پلیس",
};

const ACTIVE = ["QUEUED", "RUNNING", "PROCESSING"];

const VERDICT_TONE: Record<string, "ok" | "warn" | "neutral" | "bad"> = {
  confirmed: "ok",
  maybe: "warn",
  no: "neutral",
  unknown: "neutral",
};

const MATCH_LABEL: Record<string, string> = {
  same: "همان کالا",
  maybe: "مشابه / جایگزین",
  different: "کالای دیگر",
};

const LLM_RELATION: Record<string, string> = {
  same: "همان کالاست",
  substitute: "جایگزین است (رقیبِ کالایی)",
  complement: "مکمل است، نه رقیب",
  unrelated: "نامرتبط",
};

function percent(score: number) {
  return `${fa(Math.round(score * 100))}٪`;
}

/**
 * Who else sells this, and for how much.
 *
 * Two ways in: by hand (as before), or automatically — «یافتنِ خودکارِ رقبا»
 * proposes sellers of the shop's own products on Digikala/Basalam, and
 * «کرالِ محصولات» reads a competitor's own site. Every competitor product is
 * then checked against the shop's products («رقیب کالایی»), and the badge on
 * each competitor says whether at least one product is confidently the same.
 *
 * Every recorded price still shows **the day it was observed**.
 */
export default function CompetitorsPage() {
  const { id } = useParams<{ id: string }>();
  const [rows, setRows] = useState<Competitor[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [name, setName] = useState("");
  const [kind, setKind] = useState("DIRECT");
  const [website, setWebsite] = useState("");

  const [discovery, setDiscovery] = useState<Discovery | null>(null);
  const [discovering, setDiscovering] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get(`/stores/${id}/competitors/`);
      setRows(data);
    } catch (err) {
      setError(errorMessage(err));
      setRows([]);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  // A crawl runs in the background: poll while one is queued or running.
  const crawling = (rows ?? []).some((c) => c.crawl && ACTIVE.includes(c.crawl.state));
  useEffect(() => {
    if (!crawling) return;
    const timer = window.setTimeout(load, 3000);
    return () => window.clearTimeout(timer);
  }, [crawling, rows, load]);

  async function add(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post(`/stores/${id}/competitors/`, { name, kind, website });
      setName("");
      setWebsite("");
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(competitor: Competitor) {
    setError(null);
    try {
      await api.delete(`/stores/${id}/competitors/${competitor.id}/`);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function discover() {
    setDiscovering(true);
    setError(null);
    setNotice(null);
    try {
      const { data } = await api.post(`/stores/${id}/competitors/discover/`, {});
      setDiscovery(data);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setDiscovering(false);
    }
  }

  async function addSuggestion(suggestion: Suggestion) {
    setError(null);
    try {
      await api.post(`/stores/${id}/competitors/discover/add/`, { suggestion });
      setNotice(`«${suggestion.name}» با ${fa(suggestion.items.length)} کالایش اضافه شد.`);
      setDiscovery((current) =>
        current
          ? {
              ...current,
              suggestions: current.suggestions.map((s) =>
                s.key === suggestion.key ? { ...s, already_added: true } : s,
              ),
            }
          : current,
      );
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  if (rows === null) return <Spinner />;

  return (
    <>
      <PageHeader
        title="رقبا"
        subtitle="چه کسی همین را می‌فروشد، و به چه قیمتی — دستی یا خودکار"
        actions={
          <Link to={`/stores/${id}`}>
            <Button variant="secondary">بازگشت به فروشگاه</Button>
          </Link>
        }
      />

      <ErrorBox message={error} />
      {notice && (
        <div className="mb-4">
          <Alert tone="ok">{notice}</Alert>
        </div>
      )}

      <Card>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <SectionTitle>یافتنِ خودکارِ رقبا</SectionTitle>
            <p className="text-sm leading-7" style={{ color: "var(--text-2)" }}>
              نامِ محصولاتِ شما در دیجی‌کالا و باسلام جست‌وجو می‌شود؛ فروشنده‌هایی که همان کالا
              (یا جایگزینش) را می‌فروشند، با شواهد پیشنهاد می‌شوند. چیزی تا «افزودن» را نزنید
              ذخیره نمی‌شود.
            </p>
          </div>
          <Button onClick={discover} disabled={discovering}>
            {discovering ? "در حال جست‌وجو…" : "یافتنِ خودکارِ رقبا"}
          </Button>
        </div>

        {discovery && (
          <div className="mt-4 flex flex-col gap-3">
            {discovery.note && <Alert tone="info">{discovery.note}</Alert>}
            {discovery.sources.some((s) => !s.ok) && (
              <Alert tone="warn" title="بعضی منابع جواب ندادند">
                {Array.from(
                  new Set(discovery.sources.filter((s) => !s.ok).map((s) => `${s.source}: ${s.error}`)),
                ).join(" · ")}
              </Alert>
            )}
            {discovery.suggestions.length === 0 ? (
              <p className="text-sm" style={{ color: "var(--text-3)" }}>
                فروشنده‌ای با کالای مشابه پیدا نشد
                {discovery.products_checked?.length
                  ? ` (محصولاتِ بررسی‌شده: ${discovery.products_checked.join("، ")})`
                  : ""}
                .
              </p>
            ) : (
              discovery.suggestions.map((s) => (
                <div
                  key={s.key}
                  className="rounded-lg border p-3"
                  style={{ borderColor: "var(--line)" }}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-bold" style={{ color: "var(--text)" }}>
                        {s.name}
                      </span>
                      <Badge tone="info">{s.platform_label}</Badge>
                      {s.city && <Badge tone="neutral">{s.city}</Badge>}
                      {s.website && (
                        <a href={s.website} target="_blank" rel="noreferrer" className="text-xs underline">
                          صفحه‌ی فروشنده
                        </a>
                      )}
                    </div>
                    <Button
                      variant={s.already_added ? "ghost" : "secondary"}
                      disabled={s.already_added}
                      onClick={() => addSuggestion(s)}
                    >
                      {s.already_added ? "اضافه شده" : "افزودن"}
                    </Button>
                  </div>
                  <p className="mt-1 text-sm" style={{ color: "var(--text-2)" }}>
                    {s.why}
                  </p>
                  <ul className="mt-1 list-inside list-disc text-xs leading-6" style={{ color: "var(--text-3)" }}>
                    {s.items.slice(0, 3).map((item) => (
                      <li key={item.url || item.name}>
                        <a href={item.url} target="_blank" rel="noreferrer" className="underline">
                          {item.name}
                        </a>{" "}
                        — {item.price_toman ? toman(item.price_toman) : "بی‌قیمت"} ·{" "}
                        {MATCH_LABEL[item.verdict] ?? item.verdict} ({percent(item.score)}) برای «
                        {item.our_product_name}»
                        {item.sales_count ? ` · ${fa(item.sales_count)} فروش در باسلام` : ""}
                      </li>
                    ))}
                  </ul>
                </div>
              ))
            )}
          </div>
        )}
      </Card>

      <div className="mt-4">
        <Card>
          <SectionTitle>افزودنِ دستیِ رقیب</SectionTitle>
          <form onSubmit={add} className="flex flex-wrap items-end gap-3">
            <div className="min-w-[12rem] flex-1">
              <Field label="نام">
                <Input
                  id="competitor-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="مثلاً نام یک فروشگاه اینترنتی یا اینستاگرامی"
                  required
                />
              </Field>
            </div>
            <Field label="نوع">
              <Select value={kind} onChange={(e) => setKind(e.target.value)}>
                {Object.entries(KIND_LABEL).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </Select>
            </Field>
            <div className="min-w-[12rem] flex-1">
              <Field label="سایت (برای کرالِ خودکار)">
                <Input
                  id="competitor-site"
                  value={website}
                  onChange={(e) => setWebsite(e.target.value)}
                  dir="ltr"
                  placeholder="https://"
                />
              </Field>
            </div>
            <Button type="submit" disabled={busy || !name.trim()}>
              افزودن
            </Button>
          </form>
        </Card>
      </div>

      <div className="mt-6 flex flex-col gap-4">
        {rows.length === 0 && (
          <EmptyState
            icon="search"
            title="هنوز رقیبی ثبت نشده"
            description="«یافتنِ خودکارِ رقبا» را بزنید یا یک رقیب را با سایتش دستی اضافه کنید."
          />
        )}

        {rows.map((competitor) => (
          <CompetitorCard
            key={competitor.id}
            storeId={id!}
            competitor={competitor}
            onChanged={load}
            onError={setError}
            onRemove={() => remove(competitor)}
          />
        ))}
      </div>

      <div className="mt-6 flex flex-col gap-3">
        <Alert tone="info" title="«رقیب کالایی» چطور سنجیده می‌شود">
          نامِ دو کالا یکدست می‌شود (اعداد فارسی، ی/ي، ک/ك، نیم‌فاصله)، واژه‌های مشترک — با وزنِ
          بیشتر برای برند، مدل و اندازه — شمرده می‌شود، اندازه یا مدلِ متفاوت امتیاز را کم می‌کند و
          قیمتِ هم‌رده آن را بالا می‌برد. «همان کالا» یعنی اطمینانِ بالا؛ «مشابه» یعنی مرزی — اگر
          مدلِ زبانی در دسترس باشد از او هم پرسیده می‌شود. هر سطر را می‌توانید خودتان «همین است» یا
          «نیست» کنید و دیگر خودکار عوض نمی‌شود.
        </Alert>
        <Alert tone="neutral" title="این داده کجا استفاده می‌شود">
          قیمتِ کالاهای «همان کالا» مستقیماً در «فرصت‌های فروش» به کار می‌رود — اگر قیمت شما{" "}
          {fa(20)}٪ بالاتر از ارزان‌ترین رقیب باشد، همان‌جا با هر دو عدد گفته می‌شود.
        </Alert>
      </div>
    </>
  );
}

function CompetitorCard({
  storeId,
  competitor,
  onChanged,
  onError,
  onRemove,
}: {
  storeId: string;
  competitor: Competitor;
  onChanged: () => void;
  onError: (message: string | null) => void;
  onRemove: () => void;
}) {
  const [maxPages, setMaxPages] = useState("30");
  const [working, setWorking] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const crawl = competitor.crawl;
  const running = !!crawl && ACTIVE.includes(crawl.state);
  const verdict = competitor.product_competitor;

  const matched = competitor.products.filter(
    (p) => p.matches || (p.match && p.match.verdict !== "different"),
  );

  async function startCrawl() {
    setWorking(true);
    onError(null);
    try {
      await api.post(`/stores/${storeId}/competitors/${competitor.id}/crawl/`, {
        max_pages: Number(maxPages) || 30,
      });
      onChanged();
    } catch (err) {
      onError(errorMessage(err));
    } finally {
      setWorking(false);
    }
  }

  async function rematch() {
    setWorking(true);
    onError(null);
    try {
      await api.post(`/stores/${storeId}/competitors/${competitor.id}/match/`, { use_llm: true });
      onChanged();
    } catch (err) {
      onError(errorMessage(err));
    } finally {
      setWorking(false);
    }
  }

  async function setMatch(product: CompetitorProduct, target: number | null) {
    onError(null);
    try {
      await api.patch(
        `/stores/${storeId}/competitors/${competitor.id}/products/${product.id}/`,
        { matches: target },
      );
      onChanged();
    } catch (err) {
      onError(errorMessage(err));
    }
  }

  const summary = crawl?.result?.crawl;

  return (
    <Card>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <SectionTitle>{competitor.name}</SectionTitle>
          <Badge tone="neutral">{KIND_LABEL[competitor.kind] ?? competitor.kind}</Badge>
          <Badge tone={VERDICT_TONE[verdict.status]}>
            {verdict.confirmed ? "✓ " : ""}
            {verdict.label}
          </Badge>
          {competitor.is_stale && <Badge tone="warn">تحلیل قدیمی است</Badge>}
          {competitor.website && (
            <a
              href={competitor.website}
              target="_blank"
              rel="noreferrer"
              dir="ltr"
              className="text-xs underline"
              style={{ color: "var(--text-3)" }}
            >
              {competitor.website}
            </a>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {competitor.website && !competitor.is_marketplace && (
            <>
              <div className="w-20">
                <Input
                  type="number"
                  min={1}
                  max={120}
                  value={maxPages}
                  onChange={(e) => setMaxPages(e.target.value)}
                  title="حداکثر تعدادِ صفحه‌ی محصول"
                />
              </div>
              <Button onClick={startCrawl} disabled={working || running}>
                {running ? "در حال کرال…" : "کرالِ محصولات"}
              </Button>
            </>
          )}
          <Button
            variant="secondary"
            onClick={rematch}
            disabled={working || competitor.products.length === 0}
          >
            سنجشِ دوباره
          </Button>
          <Button variant="ghost" onClick={onRemove}>
            حذف
          </Button>
        </div>
      </div>

      {!competitor.website && (
        <p className="mb-2 text-xs" style={{ color: "var(--text-3)" }}>
          برای کرالِ خودکار، نشانیِ سایتِ این رقیب را ثبت کنید.
        </p>
      )}

      {crawl && (
        <div className="mb-3">
          {running ? (
            <Alert tone="info" title="در حال خواندنِ سایتِ رقیب">
              {crawl.label || "در صف…"}
              <div
                className="mt-2 h-2 w-full overflow-hidden rounded"
                style={{ background: "var(--surface-2)" }}
              >
                <div
                  className="h-2"
                  style={{
                    width: `${crawl.total ? Math.min(100, (crawl.progress / crawl.total) * 100) : 5}%`,
                    background: "var(--brand)",
                  }}
                />
              </div>
            </Alert>
          ) : crawl.state === "FAILED" ? (
            <Alert tone="bad" title="کرال ناموفق بود">
              {crawl.error}
            </Alert>
          ) : summary ? (
            <Alert
              tone={summary.products_found ? "ok" : "warn"}
              title={`آخرین کرال: ${new Date(crawl.updated_at).toLocaleString("fa-IR")}`}
            >
              {fa(summary.products_found)} محصول از {fa(summary.pages_fetched)} صفحه خوانده شد
              {crawl.result.saved
                ? ` (${fa(crawl.result.saved.created)} تازه، ${fa(crawl.result.saved.updated)} به‌روز)`
                : ""}
              . روشِ یافتن: {summary.discovery || "—"} · robots.txt: {summary.robots}
              {summary.robots_blocked ? ` · ${fa(summary.robots_blocked)} نشانی به‌خاطرِ robots خوانده نشد` : ""}
              {summary.skipped_no_product
                ? ` · ${fa(summary.skipped_no_product)} صفحه نشانه‌ی محصول نداشت`
                : ""}
              {summary.stopped === "no_product_urls" && " · هیچ صفحه‌ی محصولی در نقشه‌ی سایت یا صفحه‌ی اصلی پیدا نشد."}
              {crawl.result.verdict?.llm ? ` · ${crawl.result.verdict.llm}` : ""}
            </Alert>
          ) : null}
        </div>
      )}

      {competitor.positioning && (
        <p className="mb-3 text-sm leading-7" style={{ color: "var(--text-2)" }}>
          {competitor.positioning}
        </p>
      )}

      {matched.length > 0 && (
        <>
          <div className="mb-1 text-sm font-bold" style={{ color: "var(--text)" }}>
            کالاهای مشترک با شما
          </div>
          <Table>
            <thead>
              <tr>
                <th>کالای شما</th>
                <th>کالای آن‌ها</th>
                <th>قیمتِ آن‌ها</th>
                <th>اختلاف با شما</th>
                <th>اطمینان</th>
                <th>دلیل</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {matched.map((product) => {
                const m = product.match;
                const ours = product.matches_name ?? m?.our_product_name ?? "—";
                const ourPrice = product.our_price;
                const diff =
                  ourPrice && product.price_toman
                    ? Math.round(((product.price_toman - ourPrice) / ourPrice) * 100)
                    : null;
                return (
                  <tr key={product.id}>
                    <td>{ours}</td>
                    <td>
                      {product.link ? (
                        <a href={product.link} target="_blank" rel="noreferrer" className="underline">
                          {product.name}
                        </a>
                      ) : (
                        product.name
                      )}
                    </td>
                    <td className="u-num">
                      {product.price_toman ? toman(product.price_toman) : "—"}
                      {product.currency_how === "currency_guess" && (
                        <div className="text-xs" style={{ color: "var(--warn)" }}>
                          واحد اعلام نشده
                        </div>
                      )}
                    </td>
                    <td className="u-num">
                      {diff === null ? (
                        product.matches ? "—" : "تأییدنشده"
                      ) : (
                        <span style={{ color: diff < 0 ? "var(--bad)" : "var(--ok)" }}>
                          {diff > 0 ? "+" : ""}
                          {fa(diff)}٪
                        </span>
                      )}
                    </td>
                    <td>
                      {m ? (
                        <Badge tone={m.verdict === "same" ? "ok" : "warn"}>
                          {MATCH_LABEL[m.verdict]} {percent(m.score)}
                        </Badge>
                      ) : (
                        <Badge tone="neutral">دستی</Badge>
                      )}
                    </td>
                    <td className="text-xs leading-6" style={{ color: "var(--text-3)" }}>
                      {m?.reason}
                      {m?.llm && (
                        <div>
                          مدلِ زبانی: {LLM_RELATION[m.llm.relation ?? ""] ??
                            (m.llm.same ? "همان کالاست" : m.llm.substitute ? "جایگزین است" : "نه")}{" "}
                          —{" "}
                          {m.llm.reason}
                        </div>
                      )}
                    </td>
                    <td>
                      <div className="flex gap-1">
                        {!product.matches && m?.our_product_id && (
                          <Button variant="secondary" onClick={() => setMatch(product, m.our_product_id)}>
                            همین است
                          </Button>
                        )}
                        {(product.matches || m?.verdict === "maybe") && (
                          <Button variant="ghost" onClick={() => setMatch(product, null)}>
                            نیست
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
          <p className="mt-1 text-xs" style={{ color: "var(--text-3)" }}>
            اختلافِ منفی (قرمز) یعنی رقیب ارزان‌تر از شماست.
          </p>
        </>
      )}

      {competitor.products.length === 0 ? (
        <p className="text-sm" style={{ color: "var(--text-3)" }}>
          هنوز محصولی از این رقیب ثبت نشده.
        </p>
      ) : (
        <div className="mt-3">
          <Button variant="ghost" onClick={() => setShowAll((v) => !v)}>
            {showAll ? "بستن" : `همه‌ی محصولاتِ این رقیب (${fa(competitor.products.length)})`}
          </Button>
          {showAll && (
            <Table>
              <thead>
                <tr>
                  <th>محصول</th>
                  <th>قیمت</th>
                  <th>دیده‌شده در</th>
                  <th>منبع</th>
                  <th>رقیب کالایی؟</th>
                </tr>
              </thead>
              <tbody>
                {competitor.products.map((product) => (
                  <tr key={product.id}>
                    <td>
                      {product.link ? (
                        <a href={product.link} target="_blank" rel="noreferrer" className="underline">
                          {product.name}
                        </a>
                      ) : (
                        product.name
                      )}
                    </td>
                    <td className="u-num">
                      {product.price_toman ? toman(product.price_toman) : "—"}
                    </td>
                    {/* The date is not decoration: it is what separates a
                        fact from a claim. */}
                    <td className="u-num" style={{ color: "var(--text-3)" }}>
                      {product.observed_at
                        ? new Date(product.observed_at).toLocaleDateString("fa-IR")
                        : "نامشخص"}
                    </td>
                    <td style={{ color: "var(--text-3)" }}>{product.source || "—"}</td>
                    <td>
                      {product.match ? (
                        <Badge
                          tone={
                            product.matches ? "ok" : product.match.verdict === "maybe" ? "warn" : "neutral"
                          }
                        >
                          {product.matches ? "همان کالا" : MATCH_LABEL[product.match.verdict]}
                        </Badge>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </div>
      )}

      <AddCompetitorProduct storeId={storeId} competitorId={competitor.id} onAdded={onChanged} />
    </Card>
  );
}

function AddCompetitorProduct({
  storeId,
  competitorId,
  onAdded,
}: {
  storeId: string;
  competitorId: number;
  onAdded: () => void;
}) {
  const [name, setName] = useState("");
  const [price, setPrice] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post(`/stores/${storeId}/competitors/${competitorId}/products/`, {
        name,
        price_toman: price ? Number(price) : null,
        source: "دستی",
      });
      setName("");
      setPrice("");
      onAdded();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="mt-3 flex flex-wrap items-end gap-2 border-t pt-3"
      style={{ borderColor: "var(--line)" }}
    >
      <div className="min-w-[10rem] flex-1">
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="نام محصول رقیب (دستی)"
        />
      </div>
      <div className="w-40">
        <Input
          type="number"
          value={price}
          onChange={(e) => setPrice(e.target.value)}
          placeholder="قیمت (تومان)"
        />
      </div>
      <Button type="submit" variant="secondary" disabled={busy || !name.trim()}>
        ثبت قیمت
      </Button>
      {error && <Alert tone="bad">{error}</Alert>}
    </form>
  );
}
