import { type ReactNode, useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { api, errorMessage } from "../../api/client";
import { faDateTime } from "../../components/fmt";
import { useQueuedAi } from "../../components/QueuedAi";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBox,
  PageHeader,
  SectionTitle,
  Select,
  Spinner,
  fa,
} from "../../components/ui";
import InstagramTrends from "./InstagramTrends";

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

/** From the server: when the tab was last filled, whether a refresh is under way, what failed. */
type Freshness = {
  last_refresh_at: string | null;
  age_hours: number | null;
  stale: boolean;
  refreshing: boolean;
  last_trigger: string;
  problems: string[];
  /** fresh | running | started | recent | queue_off | error — what opening the page did. */
  auto: string;
};

function agoText(hours: number | null): string {
  if (hours === null) return "";
  if (hours < 1) return "کمتر از یک ساعت پیش";
  if (hours < 48) return `${fa(Math.round(hours))} ساعت پیش`;
  return `${fa(Math.round(hours / 24))} روز پیش`;
}

/** A trend row is one sighting per DAY, so its age is a day count, not hours since a fetch. */
function seenText(hours: number): string {
  if (hours < 24) return "امروز";
  if (hours < 48) return "دیروز";
  return `${fa(Math.floor(hours / 24))} روز پیش`;
}

/** «آخرین به‌روزرسانی …» + the automatic-refresh state, so an empty tab explains itself. */
function FreshnessBar({ f }: { f: Freshness | null }) {
  if (!f) return null;
  const waiting = f.refreshing || f.auto === "started" || f.auto === "running";
  return (
    <div
      className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs"
      style={{ color: "var(--text-2)" }}
      data-testid="trends-freshness"
    >
      {waiting ? (
        <span className="inline-flex items-center gap-2" data-testid="trends-refreshing">
          <Spinner size={14} />
          در حال به‌روزرسانیِ خودکارِ ترندها از منبع‌ها… تا چند دقیقهٔ دیگر خودش پر می‌شود.
        </span>
      ) : f.last_refresh_at ? (
        <span>
          آخرین به‌روزرسانی: <b>{agoText(f.age_hours)}</b> ({faDateTime(f.last_refresh_at)})
        </span>
      ) : (
        <span>هنوز ترندی از منبع‌ها خوانده نشده است.</span>
      )}
      {!waiting && f.stale && f.last_refresh_at && <Badge tone="warn">قدیمی</Badge>}
      <span style={{ color: "var(--text-3)" }}>ترندها هر روز دو بار خودکار به‌روز می‌شوند.</span>
      {(f.auto === "queue_off" || f.auto === "error") && (
        <span style={{ color: "var(--warn, var(--text-2))" }}>
          به‌روزرسانیِ خودکار الان کار نمی‌کند؛ دکمهٔ «به‌روزرسانی از منبع» را بزنید.
        </span>
      )}
    </div>
  );
}

/** The shop's categories as chips the owner can correct: detection is a guess, the chips are the truth. */
function GroupChips({
  groups,
  allGroups,
  custom,
  busy,
  error,
  onChange,
  onReset,
}: {
  groups: string[];
  allGroups: string[];
  custom: boolean;
  busy: boolean;
  error: string | null;
  onChange: (next: string[]) => void;
  onReset: () => void;
}) {
  const addable = allGroups.filter((g) => !groups.includes(g));
  return (
    <div className="flex flex-col gap-2" data-testid="trend-groups">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium" style={{ color: "var(--text)" }}>
          دسته‌های فروشگاهِ شما:
        </span>
        {groups.length === 0 && (
          <span className="text-xs" style={{ color: "var(--text-3)" }}>
            هیچ دسته‌ای انتخاب نشده — فقط نامِ محصولات و برچسب‌ها سنجیده می‌شود.
          </span>
        )}
        {groups.map((group) => (
          <span
            key={group}
            data-testid="trend-group-chip"
            className="inline-flex items-center gap-1 rounded-full py-1 pe-1 ps-3 text-xs"
            style={{ background: "var(--brand-soft, var(--surface-2))", color: "var(--text)", border: "1px solid var(--line)" }}
          >
            {group}
            <button
              type="button"
              aria-label={`حذفِ دستهٔ ${group}`}
              disabled={busy}
              onClick={() => onChange(groups.filter((g) => g !== group))}
              className="inline-flex h-6 w-6 items-center justify-center rounded-full text-base leading-none"
              style={{ color: "var(--text-3)" }}
            >
              ×
            </button>
          </span>
        ))}
        {addable.length > 0 && (
          <Select
            aria-label="افزودنِ دسته"
            value=""
            disabled={busy}
            style={{ width: "auto", minWidth: 150 }}
            onChange={(e) => e.target.value && onChange([...groups, e.target.value])}
          >
            <option value="">＋ افزودنِ دسته…</option>
            {addable.map((g) => (
              <option key={g} value={g}>
                {g}
              </option>
            ))}
          </Select>
        )}
        {custom && (
          <Button variant="ghost" size="sm" disabled={busy} onClick={onReset}>
            برگشت به تشخیصِ خودکار
          </Button>
        )}
      </div>
      <div className="text-xs" style={{ color: "var(--text-3)" }}>
        {custom
          ? "این دسته‌ها را خودتان انتخاب کرده‌اید؛ سنجشِ ربطِ ترندها با همین‌ها انجام می‌شود."
          : "این دسته‌ها از نوشته‌های فروشگاهتان تشخیص داده شد؛ اگر درست نیست، با × بردارید یا دسته‌ی دیگری اضافه کنید."}
      </div>
      {error && (
        <div className="text-xs" style={{ color: "var(--bad, #b91c1c)" }} role="alert">
          {error}
        </div>
      )}
    </div>
  );
}

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
function MarketTrends({ tabs }: { tabs: ReactNode }) {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [trends, setTrends] = useState<Trend[]>([]);
  const [ideas, setIdeas] = useState<Idea[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [regions, setRegions] = useState<Region[]>([]);
  const [groups, setGroups] = useState<string[]>([]);
  const [llm, setLlm] = useState<{ available: boolean; note: string } | null>(null);
  const [freshness, setFreshness] = useState<Freshness | null>(null);
  const [allGroups, setAllGroups] = useState<string[]>([]);
  const [groupsCustom, setGroupsCustom] = useState(false);
  const [groupBusy, setGroupBusy] = useState(false);
  const [groupError, setGroupError] = useState<string | null>(null);
  /** Until when to keep re-reading while the page-open refresh runs in the background. */
  const [pollUntil, setPollUntil] = useState(0);
  const [picked, setPicked] = useState<string[]>(["IR"]);
  const [onlyRelevant, setOnlyRelevant] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const qaIdeas = useQueuedAi<{ count: number; note?: string }>("trend-ideas", id ?? "", (res) => {
    setNotice(res.note || `${fa(res.count)} ایده با هوش مصنوعی رسید.`);
    void load();
  });
  const qaRank = useQueuedAi<{ ranked: number }>("trend-rank", id ?? "", (res) => {
    setNotice(`مدلِ زبانی ${fa(res.ranked)} ترند را سنجید.`);
    void load();
  });

  const load = useCallback(async () => {
    try {
      const { data } = await api.get(`/stores/${id}/trends/?regions=${picked.join(",")}`);
      setTrends(data.trends);
      setIdeas(data.ideas);
      setSources(data.sources);
      setRegions(data.regions);
      setGroups(data.store_groups ?? []);
      setAllGroups(data.all_groups ?? []);
      setGroupsCustom(!!data.groups_custom);
      setFreshness(data.freshness ?? null);
      // a refresh queued by opening the page (or started in another tab): keep reading for two minutes
      if (data.freshness?.auto === "started" || data.freshness?.refreshing) {
        setPollUntil((until) => (until > Date.now() ? until : Date.now() + 120_000));
      }
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

  // The tab fills itself: while the refresh queued by opening the page is running, read again every few seconds.
  useEffect(() => {
    if (!freshness || !(freshness.stale || freshness.refreshing) || Date.now() >= pollUntil) return;
    const timer = window.setTimeout(() => void load(), 5000);
    return () => window.clearTimeout(timer);
  }, [freshness, pollUntil, load]);

  async function saveGroups(next: string[] | null) {
    setGroupBusy(true);
    setGroupError(null);
    try {
      const { data } =
        next === null
          ? await api.put(`/stores/${id}/trends/groups/`, { reset: true })
          : await api.put(`/stores/${id}/trends/groups/`, { groups: next });
      setGroups(data.store_groups ?? []);
      setGroupsCustom(!!data.groups_custom);
      await load();
    } catch (err) {
      setGroupError(errorMessage(err));
    } finally {
      setGroupBusy(false);
    }
  }

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
      if (data.queued) qaIdeas.setQueued(data.queued);        // «در صف تا روشن شدنِ سرورِ پردازش»: نسخهٔ هوش مصنوعی خودکار می‌رسد
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
      if (data.queued) {
        qaRank.setQueued(data.queued);
        setNotice(data.note || "رتبه‌بندی «در صف تا روشن شدنِ سرورِ پردازش» ماند و خودکار انجام می‌شود.");
      } else {
        setNotice(`مدلِ زبانی ${fa(data.ranked)} ترند را سنجید.`);
      }
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

  /** «ذخیره در بانکِ ایده»: ایدهٔ ترند به ایده‌های فروشگاه اضافه می‌شود (تکراری نمی‌شود). */
  async function saveToBank(idea: Idea) {
    setBusy(true);
    setError(null);
    try {
      const { data } = await api.post(`/stores/${id}/ideas/from-trend/`, { trend_idea: idea.id });
      setNotice(data.message);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
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
      {tabs}

      <ErrorBox message={error} />
      {qaIdeas.banner}
      {qaRank.banner}
      {notice && (
        <div className="mb-4">
          <Alert tone="ok">{notice}</Alert>
        </div>
      )}
      <FreshnessBar f={freshness} />
      {freshness && freshness.problems.length > 0 && (
        <div className="mb-3" data-testid="trends-source-problems">
          <Alert tone="warn" title="بعضی منبع‌ها جواب ندادند">
            <ul className="list-inside list-disc break-words text-xs leading-6">
              {freshness.problems.slice(0, 6).map((problem, index) => (
                <li key={index}>{problem.length > 160 ? `${problem.slice(0, 160)}…` : problem}</li>
              ))}
            </ul>
            ترندهای بقیهٔ منبع‌ها خوانده شد؛ دفعهٔ بعد دوباره امتحان می‌شود.
          </Alert>
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
          <p>
            عنوانِ ترند و تیترِ خبرهایش با نامِ محصولات، برند، برچسب‌ها و دسته‌های فروشگاه مقایسه
            می‌شود. شکل‌های مختلفِ یک واژه یکی حساب می‌شود (ورزش، ورزشی، ورزشکاران)؛ برای ترندهای
            خارجی، واژه‌های هر دسته به انگلیسی/فرانسوی/آلمانی/ترکی هم دیده می‌شوند. بیشترِ ترندها به
            بیشترِ فروشگاه‌ها ربطی ندارند — این طبیعی است.
          </p>
          <div className="mt-2">
            <GroupChips
              groups={groups}
              allGroups={allGroups}
              custom={groupsCustom}
              busy={groupBusy}
              error={groupError}
              onChange={(next) => void saveGroups(next)}
              onReset={() => void saveGroups(null)}
            />
          </div>
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
                    <Button variant="secondary" onClick={() => saveToBank(idea)} disabled={busy}>
                      ذخیره در بانکِ ایده
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
            title={
              trends.length
                ? "ترندِ مرتبطی نیست"
                : freshness?.refreshing || freshness?.auto === "started"
                  ? "در حال خواندنِ ترندهای امروز…"
                  : "ترند تازه‌ای نداریم"
            }
            description={
              trends.length
                ? "تیکِ «فقط مرتبط‌ها» را بردارید تا همه را ببینید."
                : freshness?.refreshing || freshness?.auto === "started"
                  ? "ترندها خودکار از منبع‌ها خوانده می‌شود و تا چند دقیقهٔ دیگر همین‌جا پر می‌شود؛ لازم نیست کاری بکنید."
                  : "ترندها هر روز خودکار به‌روز می‌شوند. اگر الان لازم دارید، دکمه‌ی «به‌روزرسانی از منبع» را بزنید."
            }
            action={
              trends.length || freshness?.refreshing || freshness?.auto === "started" ? undefined : (
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
        <Badge tone={trend.age_hours > 24 ? "warn" : "ok"}>دیده‌شده {seenText(trend.age_hours)}</Badge>
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

type TrendsTab = "market" | "instagram";

/**
 * The trends page has two sources: the market's daily search trends (above) and what the pages the shop watches are making on
 * Instagram right now (InstagramTrends: read by Abagram on the processing node, or imported from an Abagram file).
 */
export default function TrendsPage() {
  const { id } = useParams<{ id: string }>();
  const [params, setParams] = useSearchParams();
  const [tab, setTab] = useState<TrendsTab>(() => {
    const asked = params.get("tab");
    if (asked === "instagram" || asked === "market") return asked;
    try {
      return localStorage.getItem("trends-tab") === "instagram" ? "instagram" : "market";
    } catch {
      return "market";
    }
  });

  function choose(next: TrendsTab) {
    setTab(next);
    try {
      localStorage.setItem("trends-tab", next);
    } catch {
      /* a private window may refuse storage; the tab still works */
    }
    const nextParams = new URLSearchParams(params);
    nextParams.set("tab", next);
    setParams(nextParams, { replace: true });
  }

  const tabs = (
    <div role="tablist" aria-label="منبعِ ترند" className="mb-4 flex flex-wrap gap-2">
      <Button role="tab" aria-selected={tab === "market"} variant={tab === "market" ? "primary" : "secondary"} onClick={() => choose("market")}>
        ترندهای بازار
      </Button>
      <Button role="tab" aria-selected={tab === "instagram"} variant={tab === "instagram" ? "primary" : "secondary"} onClick={() => choose("instagram")}>
        ترندهای اینستاگرام
      </Button>
    </div>
  );

  if (tab === "instagram") {
    return (
      <>
        <PageHeader
          title="ترندها"
          subtitle="صفحه‌های هم‌حوزه‌ی شما همین حالا چه می‌سازند و چرا کار می‌کند"
          actions={
            <Link to={`/stores/${id}`}>
              <Button variant="secondary">بازگشت</Button>
            </Link>
          }
        />
        {tabs}
        <InstagramTrends storeId={id ?? ""} />
      </>
    );
  }
  return <MarketTrends tabs={tabs} />;
}
