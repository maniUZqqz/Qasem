import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, errorMessage } from "../../api/client";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBox,
  PageHeader,
  SectionTitle,
  Spinner,
  fa,
} from "../../components/ui";

type News = {
  title: string;
  url: string;
  source: string;
  published?: string;
  hashtags?: string[];
};

type Relevance = {
  key: "high" | "maybe" | "none";
  label: string;
  score: number;
  reason: string;
  words: string[];
  llm?: { relevance: number; reason: string };
};

type Trend = {
  id: number;
  title: string;
  region: string;
  region_title: string;
  traffic: string;
  news: News[];
  image: string;
  source: string;
  is_stale: boolean;
  age_hours: number;
  relevance: Relevance | null;
  also_in: string[];
};

type Idea = {
  id: number;
  trend: number;
  trend_title: string;
  product: number | null;
  product_name: string | null;
  kind: string;
  kind_label: string;
  idea: string;
  hook: string;
  why: string;
  state: string;
  expired: boolean;
  job_id: number | null;
};

type Source = { key: string; title: string; live: boolean; note: string };
type Region = { key: string; title: string };

const REL_TONE: Record<string, "ok" | "warn" | "neutral"> = {
  high: "ok",
  maybe: "warn",
  none: "neutral",
};
const LLM_LABEL = ["نامرتبط (به نظرِ مدل)", "ربطِ ضعیف (به نظرِ مدل)", "مرتبط (به نظرِ مدل)"];

/**
 * What people are talking about, and what this shop should make about it. §6.
 *
 * - Google's daily search trends for Iran, the US, Europe (FR/GB/DE), Turkey
 *   and the UAE, each with **the news headlines that explain why** it trends.
 * - «جهانی»: the same story across countries, most widespread first.
 * - Instagram: there is no public trending data, so this is an indirect source
 *   — dated headlines *about* what trends on Instagram/Reels, labelled as such.
 * - Each trend is labelled by relevance to this shop's products (shared words,
 *   across languages through a small category lexicon; the model's opinion is
 *   added when asked and reachable).
 */
export default function TrendsPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [trends, setTrends] = useState<Trend[]>([]);
  const [ideas, setIdeas] = useState<Idea[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [regions, setRegions] = useState<Region[]>([]);
  const [groups, setGroups] = useState<string[]>([]);
  const [llm, setLlm] = useState<{ available: boolean; note: string } | null>(null);
  const [picked, setPicked] = useState<string[]>(["IR"]);
  const [onlyRelevant, setOnlyRelevant] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get(`/stores/${id}/trends/?regions=${picked.join(",")}`);
      setTrends(data.trends);
      setIdeas(data.ideas);
      setSources(data.sources);
      setRegions(data.regions);
      setGroups(data.store_groups ?? []);
      setLlm(data.llm ?? null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [id, picked]);

  useEffect(() => {
    load();
  }, [load]);

  function toggle(key: string) {
    setPicked((current) => {
      if (key === "ALL") return current.includes("ALL") ? ["IR"] : ["ALL"];
      const base = current.filter((r) => r !== "ALL");
      const next = base.includes(key) ? base.filter((r) => r !== key) : [...base, key];
      return next.length ? next : ["IR"];
    });
  }

  async function refresh() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const { data } = await api.post(`/stores/${id}/trends/`, { regions: picked });
      setNotice(`${fa(data.fetched)} ترند خوانده شد، ${fa(data.new)} تای تازه.`);
      if (data.problems?.length) setError(data.problems.join(" · "));
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function askForIdeas(trendId?: number) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const { data } = await api.post(`/stores/${id}/trends/ideas/`, {
        regions: picked,
        ...(trendId ? { trend_id: trendId } : {}),
      });
      setIdeas(data.ideas);
      setNotice(data.note || `${fa(data.ideas.length)} ایده آماده شد.`);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function rankWithModel() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const { data } = await api.post(`/stores/${id}/trends/relevance/`, { regions: picked });
      setNotice(`مدلِ زبانی ${fa(data.ranked)} ترند را سنجید.`);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  /** کدام تب صفحه‌ی تولید محتوا به این نوع پیشنهاد می‌خورد. */
  const TAB: Record<string, string> = {
    VIDEO: "video",
    POST: "image",
    STORY: "image",
    CAPTION: "caption",
  };

  /** «بساز» یعنی برو بساز — مستقیم به صفحه‌ی تولید محتوا. */
  async function use(idea: Idea) {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/stores/${id}/trends/ideas/${idea.id}/use/`);
      const tab = TAB[idea.kind] ?? "video";
      navigate(`/stores/${id}/studio?tab=${tab}&product=${idea.product}`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  async function dismiss(idea: Idea) {
    try {
      await api.post(`/stores/${id}/trends/ideas/${idea.id}/dismiss/`);
      setIdeas((current) => current.filter((i) => i.id !== idea.id));
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  if (loading) return <Spinner />;

  const dark = sources.filter((s) => !s.live);
  const indirect = sources.find((s) => s.key === "instagram_news");
  const shown = onlyRelevant
    ? trends.filter(
        (t) => (t.relevance && t.relevance.key !== "none") || (t.relevance?.llm?.relevance ?? 0) > 0,
      )
    : trends;
  const relevantCount = trends.filter((t) => t.relevance && t.relevance.key !== "none").length;

  return (
    <>
      <PageHeader
        title="ترندها"
        subtitle="چه چیزی الان سر زبان‌هاست، چرا، و به کارِ فروشگاهِ شما می‌آید یا نه"
        actions={
          <Link to={`/stores/${id}`}>
            <Button variant="secondary">بازگشت</Button>
          </Link>
        }
      />

      <ErrorBox message={error} />
      {notice && (
        <div className="mb-4">
          <Alert tone="ok">{notice}</Alert>
        </div>
      )}

      <div className="mb-3 flex flex-wrap items-center gap-2">
        {regions.map((region) => {
          const on = picked.includes(region.key);
          return (
            <Button
              key={region.key}
              variant={on ? "primary" : "secondary"}
              onClick={() => toggle(region.key)}
            >
              {region.title}
            </Button>
          );
        })}
      </div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Button variant="secondary" onClick={refresh} disabled={busy}>
          {busy ? "…" : "به‌روزرسانی از منبع"}
        </Button>
        <Button onClick={() => askForIdeas()} disabled={busy || trends.length === 0}>
          چه بسازم؟ (همه‌ی ترندها)
        </Button>
        {llm?.available && (
          <Button variant="secondary" onClick={rankWithModel} disabled={busy || trends.length === 0}>
            سنجشِ ربط با هوش مصنوعی
          </Button>
        )}
        <label className="flex items-center gap-1 text-sm" style={{ color: "var(--text-2)" }}>
          <input
            type="checkbox"
            checked={onlyRelevant}
            onChange={(e) => setOnlyRelevant(e.target.checked)}
          />
          فقط مرتبط‌ها ({fa(relevantCount)})
        </label>
      </div>

      <div className="mb-4 flex flex-col gap-2">
        <Alert tone="info" title="ربط به فروشگاه چطور سنجیده می‌شود">
          عنوانِ ترند و تیترِ خبرهایش با نامِ محصولات، برند، برچسب‌ها و دسته‌ی فروشگاه مقایسه
          می‌شود؛ برای ترندهای خارجی، واژه‌های هر دسته به انگلیسی/فرانسوی/آلمانی/ترکی هم دیده
          می‌شوند
          {groups.length ? ` (دسته‌های فروشگاهِ شما: ${groups.join("، ")})` : ""}. بیشترِ ترندها به
          بیشترِ فروشگاه‌ها ربطی ندارند — این طبیعی است.
        </Alert>
        {picked.includes("IG") && indirect && (
          <Alert tone="warn" title="اینستاگرام — منبعِ غیرمستقیم">
            {indirect.note}
          </Alert>
        )}
        {dark.length > 0 && (
          <Alert tone="neutral" title="این‌ها را نداریم">
            <ul className="list-inside list-disc">
              {dark.map((s) => (
                <li key={s.key}>
                  <b>{s.title}</b> — {s.note}
                </li>
              ))}
            </ul>
          </Alert>
        )}
      </div>

      {ideas.length > 0 && (
        <div className="mb-8">
          <SectionTitle>ایده‌های محتوا برای شما</SectionTitle>
          <div className="flex flex-col gap-2">
            {ideas.map((idea) => (
              <Card key={idea.id}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="mb-1 flex flex-wrap items-center gap-2">
                      <Badge tone="brand">{idea.kind_label}</Badge>
                      <Badge tone="neutral">{idea.trend_title}</Badge>
                      {idea.product_name && <Badge tone="info">{idea.product_name}</Badge>}
                      {idea.expired && <Badge tone="warn">ترندش گذشته</Badge>}
                    </div>
                    {idea.hook && (
                      <p className="font-bold" style={{ color: "var(--text)" }}>
                        «{idea.hook}»
                      </p>
                    )}
                    <p className="text-sm leading-7" style={{ color: "var(--text-2)" }}>
                      {idea.idea}
                    </p>
                    <p className="mt-1 text-xs" style={{ color: "var(--text-3)" }}>
                      چرا شما: {idea.why}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <Button onClick={() => use(idea)} disabled={busy || idea.expired || !idea.product}>
                      بساز
                    </Button>
                    <Button variant="ghost" onClick={() => dismiss(idea)}>
                      نه
                    </Button>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        </div>
      )}

      <SectionTitle>
        {picked.includes("ALL") ? "ترندهای جهانی (پرتکرارترین در کشورها اول)" : "ترندهای الان"}
      </SectionTitle>
      {shown.length === 0 ? (
        <Card>
          <EmptyState
            icon="trending"
            title={trends.length ? "ترندِ مرتبطی نیست" : "ترند تازه‌ای نداریم"}
            description={
              trends.length
                ? "تیکِ «فقط مرتبط‌ها» را بردارید تا همه را ببینید."
                : "دکمه‌ی «به‌روزرسانی از منبع» را بزنید تا ترندهای امروز خوانده شود."
            }
            action={
              trends.length ? undefined : (
                <Button onClick={refresh} disabled={busy}>
                  به‌روزرسانی
                </Button>
              )
            }
          />
        </Card>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2">
          {shown.map((trend) => (
            <TrendCard
              key={trend.id}
              trend={trend}
              busy={busy}
              onIdea={() => askForIdeas(trend.id)}
            />
          ))}
        </div>
      )}
    </>
  );
}

function TrendCard({ trend, busy, onIdea }: { trend: Trend; busy: boolean; onIdea: () => void }) {
  const rel = trend.relevance;
  const instagram = trend.region === "IG";
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-bold" style={{ color: "var(--text)" }}>
          {trend.title}
        </span>
        <Badge tone="neutral">{trend.region_title}</Badge>
        {trend.traffic && <Badge tone="info">{trend.traffic} جست‌وجو</Badge>}
        <Badge tone={trend.age_hours > 24 ? "warn" : "ok"}>دیده‌شده {fa(trend.age_hours)} ساعت پیش</Badge>
        {trend.also_in.length > 0 && <Badge tone="brand">هم‌زمان در {trend.also_in.join("، ")}</Badge>}
      </div>

      {rel && (
        <div className="mt-2 text-xs leading-6">
          <Badge tone={REL_TONE[rel.key]}>{rel.label}</Badge>{" "}
          <span style={{ color: "var(--text-3)" }}>{rel.reason}</span>
          {rel.llm && (
            <div style={{ color: "var(--text-3)" }}>
              <Badge tone={rel.llm.relevance === 2 ? "ok" : rel.llm.relevance === 1 ? "warn" : "neutral"}>
                {LLM_LABEL[rel.llm.relevance] ?? ""}
              </Badge>{" "}
              {rel.llm.reason}
            </div>
          )}
        </div>
      )}

      {trend.news.length > 0 && (
        <div className="mt-2">
          <div className="text-xs font-medium" style={{ color: "var(--text-2)" }}>
            {instagram ? "منبع:" : "چرا ترند شده (تیترِ خبرها):"}
          </div>
          <ul className="list-inside list-disc text-xs leading-6" style={{ color: "var(--text-3)" }}>
            {trend.news.map((item, index) => (
              <li key={`${item.url}-${index}`}>
                {item.url ? (
                  <a href={item.url} target="_blank" rel="noreferrer" className="underline">
                    {item.title}
                  </a>
                ) : (
                  item.title
                )}
                {item.source ? ` — ${item.source}` : ""}
                {item.published ? ` · ${new Date(item.published).toLocaleDateString("fa-IR")}` : ""}
                {item.hashtags && item.hashtags.length > 0 && (
                  <span> · {item.hashtags.map((h) => `#${h}`).join(" ")}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-2">
        <Button variant="secondary" onClick={onIdea} disabled={busy}>
          ایده‌ی محتوا از این ترند
        </Button>
      </div>
    </Card>
  );
}
