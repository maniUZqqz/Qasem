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

type Trend = {
  id: number;
  title: string;
  region: string;
  region_title: string;
  traffic: string;
  context: string[];
  image: string;
  is_stale: boolean;
  age_hours: number;
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

/**
 * What people are talking about, and what this shop should make about it. §6.
 *
 * Two things the page has to be honest about, because the alternative is a
 * customer making decisions on numbers we invented:
 *
 * - **Sources we could not reach are listed, not hidden.** A shop that sees no
 *   Instagram trends should know we never had access, rather than concluding
 *   nothing is happening there.
 * - **Every idea shows its `why`.** The backend throws away any suggestion
 *   whose connection to the shop it cannot justify; showing the survivors'
 *   reasoning is what lets a shop disagree with one.
 */
export default function TrendsPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [trends, setTrends] = useState<Trend[]>([]);
  const [ideas, setIdeas] = useState<Idea[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [regions, setRegions] = useState<Region[]>([]);
  const [picked, setPicked] = useState<string[]>(["IR"]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get(
        `/stores/${id}/trends/?regions=${picked.join(",")}`,
      );
      setTrends(data.trends);
      setIdeas(data.ideas);
      setSources(data.sources);
      setRegions(data.regions);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [id, picked]);

  useEffect(() => {
    load();
  }, [load]);

  async function refresh() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const { data } = await api.post(`/stores/${id}/trends/`, { regions: picked });
      setNotice(
        `${fa(data.fetched)} ترند خوانده شد، ${fa(data.new)} تای تازه.`,
      );
      if (data.problems?.length) setError(data.problems.join(" · "));
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function askForIdeas() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const { data } = await api.post(`/stores/${id}/trends/ideas/`, {
        regions: picked,
      });
      setIdeas(data.ideas);
      setNotice(data.note || `${fa(data.ideas.length)} ایده آماده شد.`);
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

  /**
   * «بساز» یعنی برو بساز.
   *
   * سند (صفحه ۲، بند ۲) می‌گوید از همین‌جا باید **مستقیم وارد صفحه‌ی تولید
   * محتوا** شد. قبلاً این دکمه کار را شروع می‌کرد و همین‌جا می‌ماند، با
   * جمله‌ای که می‌گفت «در صفحه‌ی محصول دنبالش کنید» — یعنی کاربر باید خودش
   * می‌رفت آن صفحه را پیدا می‌کرد. مقصد تا امروز وجود نداشت؛ حالا دارد.
   */
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

  return (
    <>
      <PageHeader
        title="ترندها"
        subtitle="چه چیزی الان سر زبان‌هاست — و شما چه بسازید"
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

      <div className="mb-4 flex flex-wrap items-center gap-2">
        {regions.map((region) => {
          const on = picked.includes(region.key);
          return (
            <Button
              key={region.key}
              variant={on ? "primary" : "secondary"}
              onClick={() =>
                setPicked((current) =>
                  on
                    ? current.filter((r) => r !== region.key) || ["IR"]
                    : [...current, region.key],
                )
              }
            >
              {region.title}
            </Button>
          );
        })}
        <Button variant="secondary" onClick={refresh} disabled={busy}>
          {busy ? "…" : "به‌روزرسانی"}
        </Button>
        <Button onClick={askForIdeas} disabled={busy || trends.length === 0}>
          چه بسازم؟
        </Button>
      </div>

      {dark.length > 0 && (
        <div className="mb-4">
          <Alert tone="neutral" title="این‌ها را نداریم">
            <ul className="list-inside list-disc">
              {dark.map((s) => (
                <li key={s.key}>
                  <b>{s.title}</b> — {s.note}
                </li>
              ))}
            </ul>
          </Alert>
        </div>
      )}

      {ideas.length > 0 && (
        <div className="mb-8">
          <SectionTitle>برای شما</SectionTitle>
          <div className="flex flex-col gap-2">
            {ideas.map((idea) => (
              <Card key={idea.id}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="mb-1 flex flex-wrap items-center gap-2">
                      <Badge tone="brand">{idea.kind_label}</Badge>
                      <Badge tone="neutral">{idea.trend_title}</Badge>
                      {idea.product_name && (
                        <Badge tone="info">{idea.product_name}</Badge>
                      )}
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
                    <Button
                      onClick={() => use(idea)}
                      disabled={busy || idea.expired || !idea.product}
                    >
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

      <SectionTitle>ترندهای الان</SectionTitle>
      {trends.length === 0 ? (
        <Card>
          <EmptyState
            icon="trending"
            title="ترند تازه‌ای نداریم"
            description="دکمه‌ی به‌روزرسانی را بزنید تا ترندهای امروز خوانده شود."
            action={
              <Button onClick={refresh} disabled={busy}>
                به‌روزرسانی
              </Button>
            }
          />
        </Card>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2">
          {trends.map((trend) => (
            <Card key={trend.id}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-bold" style={{ color: "var(--text)" }}>
                  {trend.title}
                </span>
                <Badge tone="neutral">{trend.region_title}</Badge>
                {trend.traffic && <Badge tone="info">{trend.traffic}</Badge>}
                <Badge tone={trend.age_hours > 24 ? "warn" : "ok"}>
                  {fa(trend.age_hours)} ساعت پیش
                </Badge>
              </div>
              {trend.context.length > 0 && (
                <ul
                  className="mt-2 list-inside list-disc text-xs"
                  style={{ color: "var(--text-3)" }}
                >
                  {trend.context.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              )}
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
