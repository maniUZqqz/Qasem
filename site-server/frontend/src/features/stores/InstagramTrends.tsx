import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api, errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBox,
  Input,
  SectionTitle,
  Select,
  Spinner,
  fa,
} from "../../components/ui";

/* ────────────────────────────── types (what GET /stores/:id/igtrends/ returns) */

type Post = {
  id: number;
  account: string;
  url: string;
  fmt: string;
  fmt_label: string;
  hook: string;
  hook_type: string;
  hashtags: string[];
  likes: number | null;
  comments: number | null;
  views: number | null;
  likes_hidden: boolean;
  score: number;
  ratio: number;
  age_h: number;
  music: string;
  why: string;
};

type Brief = {
  source: "ai" | "template";
  format: string;
  kind: string;
  hook: string;
  idea: string;
  why: string;
  outline: string[];
  caption: string;
  hashtags: string[];
  needs_edit: boolean;
  product_id: number | null;
  product_name: string | null;
  note?: string;
};

type Cluster = {
  id: number;
  label: string;
  kind: string;
  fmt: string;
  fmt_label: string;
  score: number;
  size: number;
  accounts_count: number;
  accounts: string[];
  why: string[];
  hooks: { text: string; type: string; account: string }[];
  audio: { title: string; artist: string; uses: number }[];
  hashtags: string[];
  formats: Record<string, number>;
  in_niche: boolean;
  examples?: Post[];
  brief: Brief | null;
};

type Seed = {
  id: number;
  kind: "account" | "hashtag" | "keyword";
  kind_label: string;
  value: string;
  note: string;
  enabled: boolean;
  scrape: boolean;
  source: string;
  last_status: string;
  fail_count: number;
  last_read_at: string | null;
};

type Run = {
  id: number;
  state: string;
  state_label: string;
  source: string;
  source_label: string;
  message: string;
  stop_code: string;
  accounts_read: number;
  posts_new: number;
  created_at: string;
};

type Overview = {
  node: {
    ready: boolean;
    problem: string | null;
    message: string;
    can_queue: boolean;
    open_with: string;
    address: string;
    node: { name: string; online: boolean; last_seen: string | null } | null;
    service: { signed_in?: boolean; account?: string; proxy?: string; step?: string } | null;
  };
  config: { auto_scan: boolean; interval_h: number; max_accounts: number; min_reread_h: number };
  seeds: Seed[];
  clusters: Cluster[];
  dismissed_count: number;
  top_posts: Post[];
  hashtags: { tag: string; posts: number; accounts: number; score: number; recent_posts: number }[];
  audio: { title: string; artist: string; reels: number; accounts: number; score: number; total_views: number }[];
  runs: Run[];
  totals: { pages: number; posts: number; last_read_at: string | null };
  can_edit: boolean;
};

const TAB: Record<string, string> = { VIDEO: "video", POST: "image", STORY: "image", CAPTION: "caption" };
const RUN_TONE: Record<string, "ok" | "warn" | "bad" | "info" | "neutral"> = {
  ok: "ok",
  stopped: "warn",
  failed: "bad",
  queued: "info",
  running: "info",
};
const SEED_STATUS: Record<string, string> = { ok: "خوانده شد", not_found: "پیدا نشد", private: "خصوصی", failed: "خطا در خواندن" };

/* ────────────────────────────── small helpers */

function compact(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (n >= 1_000_000) return `${fa((n / 1_000_000).toFixed(1).replace(/\.0$/, "").replace(".", "٫"))} میلیون`;
  if (n >= 1_000) return `${fa((n / 1_000).toFixed(1).replace(/\.0$/, "").replace(".", "٫"))} هزار`;
  return fa(n);
}

function ageText(hours: number): string {
  if (hours < 1) return "کمتر از یک ساعت پیش";
  if (hours < 48) return `${fa(Math.round(hours))} ساعت پیش`;
  return `${fa(Math.round(hours / 24))} روز پیش`;
}

function whenText(iso: string | null): string {
  if (!iso) return "هنوز نه";
  const hours = (Date.now() - new Date(iso).getTime()) / 3_600_000;
  return hours < 0 ? "همین حالا" : ageText(hours);
}

function scoreTone(score: number): "ok" | "warn" | "neutral" {
  return score >= 55 ? "ok" : score >= 30 ? "warn" : "neutral";
}

/* ────────────────────────────── the tab */

export default function InstagramTrends({ storeId }: { storeId: string }) {
  const navigate = useNavigate();
  const [data, setData] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [briefs, setBriefs] = useState<Record<number, { brief: Brief; idea_id: number }>>({});
  const [showSeeds, setShowSeeds] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const base = `/stores/${storeId}/igtrends`;

  const load = useCallback(
    async (quiet = false) => {
      try {
        const { data: d } = await api.get<Overview>(`${base}/`);
        setData(d);
        if (!quiet) setError(null);
      } catch (err) {
        if (!quiet) setError(errorMessage(err));
      } finally {
        setLoading(false);
      }
    },
    [base],
  );

  useEffect(() => {
    load();
  }, [load]);

  // while a scan waits or runs, look again every few seconds
  const waiting = data?.runs.some((r) => r.state === "queued" || r.state === "running") ?? false;
  useEffect(() => {
    if (!waiting) return;
    const timer = window.setInterval(() => load(true), 8000);
    return () => window.clearInterval(timer);
  }, [waiting, load]);

  async function run<T>(key: string, job: () => Promise<T>): Promise<T | undefined> {
    setBusy(key);
    setError(null);
    setNotice(null);
    try {
      return await job();
    } catch (err) {
      setError(errorMessage(err));
      return undefined;
    } finally {
      setBusy(null);
    }
  }

  const scan = () =>
    run("scan", async () => {
      await api.post(`${base}/scan/`, {});
      setNotice("خواندن در صفِ سرورِ پردازش گذاشته شد؛ نتیجه خودکار اینجا می‌آید.");
      await load(true);
    });

  const importFiles = (files: FileList | null) => {
    if (!files || files.length === 0) return;
    return run("import", async () => {
      const form = new FormData();
      Array.from(files).forEach((f) => form.append("files", f));
      const { data: r } = await api.post(`${base}/import/`, form);
      setProblems(r.problems ?? []);
      setNotice(`${fa(r.result.accounts)} صفحه و ${fa(r.result.posts)} پست وارد شد (${fa(r.result.new)} تازه).`);
      if (fileInput.current) fileInput.current.value = "";
      await load(true);
    });
  };

  const makeIdea = (c: Cluster) =>
    run(`idea-${c.id}`, async () => {
      const { data: r } = await api.post(`${base}/clusters/${c.id}/brief/`, {});
      setBriefs((prev) => ({ ...prev, [c.id]: { brief: r.brief, idea_id: r.idea_id } }));
      setNotice(r.note || (r.source === "ai" ? "ایده با هوش مصنوعی ساخته شد." : "ایده‌ی قالبی ساخته شد."));
    });

  const build = (clusterId: number) => {
    const pack = briefs[clusterId];
    if (!pack) return;
    return run(`use-${clusterId}`, async () => {
      await api.post(`/stores/${storeId}/trends/ideas/${pack.idea_id}/use/`);
      navigate(`/stores/${storeId}/studio?tab=${TAB[pack.brief.kind] ?? "video"}&product=${pack.brief.product_id}`);
    });
  };

  const dismiss = (c: Cluster) =>
    run(`dismiss-${c.id}`, async () => {
      await api.post(`${base}/clusters/${c.id}/dismiss/`, { dismissed: true });
      await load(true);
    });

  if (loading) return <Spinner />;
  if (!data) return <ErrorBox message={error ?? "داده خوانده نشد."} />;
  const { node } = data;
  const lastRun = data.runs[0];

  return (
    <div className="flex flex-col gap-4" data-testid="ig-trends">
      <ErrorBox message={error} />
      {notice && <Alert tone="ok">{notice}</Alert>}
      {problems.length > 0 && (
        <Alert tone="warn" title="بعضی فایل‌ها وارد نشد">
          <ul className="list-inside list-disc">
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </Alert>
      )}

      {/* ── connection + actions ───────────────────────────────────────────── */}
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="mb-1 flex flex-wrap items-center gap-2">
              <span className="font-bold" style={{ color: "var(--text)" }}>
                خواندنِ اینستاگرام با آباگرام
              </span>
              <Badge tone={node.ready ? "ok" : node.problem === "node_offline" ? "neutral" : "warn"}>
                {node.ready ? "آماده" : node.problem === "node_offline" ? "سرورِ پردازش خاموش" : "نیازمندِ اقدام"}
              </Badge>
              {node.node && <Badge tone="neutral">{node.node.name}</Badge>}
              {node.service?.account && <Badge tone="info">@{node.service.account}</Badge>}
            </div>
            <p className="text-sm leading-7" style={{ color: "var(--text-3)" }}>
              آباگرام روی سرورِ پردازش (کامپیوترِ گرافیکی) اجرا می‌شود و هر چند ساعت یک بار فقط چند صفحه را با فاصله‌ی تصادفی و بودجه‌ی کوچک می‌خواند؛
              با اولین علامتِ مشکل (تأییدِ انسان، «صبر کن»، سقف) خودش می‌ایستد. {data.totals.pages ? `${fa(data.totals.pages)} صفحه زیرِ نظر است و ${fa(data.totals.posts)} پستِ دو هفتهٔ اخیر ذخیره شده.` : ""}
            </p>
          </div>
          {data.can_edit && (
            <div className="flex flex-wrap gap-2">
              <Button onClick={scan} disabled={busy !== null || !node.can_queue || waiting}>
                <span className="inline-flex items-center gap-1.5">
                  <Icon name="refresh" size={15} />
                  {busy === "scan" ? "…" : waiting ? "در حالِ خواندن" : "همین حالا بخوان"}
                </span>
              </Button>
              <Button variant="secondary" onClick={() => fileInput.current?.click()} disabled={busy !== null}>
                <span className="inline-flex items-center gap-1.5">
                  <Icon name="upload" size={15} />
                  {busy === "import" ? "در حالِ وارد کردن…" : "واردکردنِ فایلِ آباگرام"}
                </span>
              </Button>
              <input
                ref={fileInput}
                type="file"
                accept=".json,application/json"
                multiple
                hidden
                onChange={(e) => importFiles(e.target.files)}
                data-testid="ig-import-input"
              />
            </div>
          )}
        </div>

        {!node.ready && node.message && (
          <div className="mt-3">
            <Alert tone={node.problem === "node_offline" || node.problem === "installing" || node.problem === "cooldown" ? "info" : "warn"} title="چه باید کرد">
              {node.message}
            </Alert>
          </div>
        )}

        {lastRun && (
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs" style={{ color: "var(--text-3)" }}>
            <Badge tone={RUN_TONE[lastRun.state] ?? "neutral"}>{lastRun.state_label}</Badge>
            <span>{lastRun.source_label}</span>
            <span>·</span>
            <span>{whenText(lastRun.created_at)}</span>
            {lastRun.message && (
              <>
                <span>·</span>
                <span>{lastRun.message}</span>
              </>
            )}
          </div>
        )}
        {data.runs.length > 1 && (
          <details className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
            <summary className="cursor-pointer">خواندن‌های قبلی</summary>
            <ul className="mt-1 list-inside list-disc leading-6">
              {data.runs.slice(1).map((r) => (
                <li key={r.id}>
                  {r.state_label} — {r.source_label} — {whenText(r.created_at)}
                  {r.message ? ` — ${r.message}` : ""}
                </li>
              ))}
            </ul>
          </details>
        )}
      </Card>

      {/* ── topics ─────────────────────────────────────────────────────────── */}
      <div>
        <SectionTitle
          action={
            data.dismissed_count > 0 ? (
              <span className="text-xs" style={{ color: "var(--text-3)" }}>
                {fa(data.dismissed_count)} موضوعِ ردشده پنهان است
              </span>
            ) : undefined
          }
        >
          موضوع‌هایی که همین حالا در حوزه‌ی شما ترند است
        </SectionTitle>
        {data.clusters.length === 0 ? (
          <Card>
            <EmptyState
              icon="trending"
              title="هنوز موضوعی پیدا نشده"
              description={
                data.totals.posts
                  ? "پست‌های ذخیره‌شده هنوز موضوعِ مشترکی بین چند پست نساخته‌اند؛ بعد از خواندنِ بیشترِ صفحه‌ها دوباره نگاه کنید."
                  : "یا منتظرِ اولین خواندنِ آباگرام بمانید، یا خروجیِ JSON آباگرام را وارد کنید تا همین حالا ترندها ساخته شود."
              }
            />
          </Card>
        ) : (
          <div className="grid gap-3 lg:grid-cols-2">
            {data.clusters.map((c) => (
              <ClusterCard
                key={c.id}
                cluster={c}
                pack={briefs[c.id]}
                busy={busy}
                canEdit={data.can_edit}
                onIdea={() => makeIdea(c)}
                onBuild={() => build(c.id)}
                onDismiss={() => dismiss(c)}
              />
            ))}
          </div>
        )}
      </div>

      {/* ── best posts ─────────────────────────────────────────────────────── */}
      {data.top_posts.length > 0 && (
        <div>
          <SectionTitle>بهترین پست‌های دو هفتهٔ اخیر (نسبت به حدِ معمولِ هر صفحه)</SectionTitle>
          <div className="grid gap-2 md:grid-cols-2">
            {data.top_posts.slice(0, 8).map((p) => (
              <PostRow key={p.id} post={p} />
            ))}
          </div>
        </div>
      )}

      {/* ── hashtags and sounds ────────────────────────────────────────────── */}
      {(data.hashtags.length > 0 || data.audio.length > 0) && (
        <div className="grid gap-3 md:grid-cols-2">
          {data.hashtags.length > 0 && (
            <Card>
              <div className="mb-2 flex items-center gap-2 font-bold" style={{ color: "var(--text)" }}>
                <Icon name="tag" size={16} /> هشتگ‌های داغ
              </div>
              <div className="flex flex-wrap gap-1.5">
                {data.hashtags.map((h) => (
                  <Badge key={h.tag} tone={scoreTone(h.score)}>
                    #{h.tag.replace(/_/g, " ")} · {fa(h.posts)} پست
                  </Badge>
                ))}
              </div>
            </Card>
          )}
          {data.audio.length > 0 && (
            <Card>
              <div className="mb-2 flex items-center gap-2 font-bold" style={{ color: "var(--text)" }}>
                <Icon name="music" size={16} /> آهنگ‌های پرکاربرد در ریلز
              </div>
              <ul className="flex flex-col gap-1 text-sm" style={{ color: "var(--text-2)" }}>
                {data.audio.map((a) => (
                  <li key={`${a.title}-${a.artist}`}>
                    «{a.title}»{a.artist ? ` — ${a.artist}` : ""}{" "}
                    <span className="text-xs" style={{ color: "var(--text-3)" }}>
                      · {fa(a.reels)} ریلز از {fa(a.accounts)} صفحه · {compact(a.total_views)} بازدید
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      )}

      {/* ── seeds ──────────────────────────────────────────────────────────── */}
      <Card>
        <button type="button" className="flex w-full items-center justify-between text-start" onClick={() => setShowSeeds((v) => !v)} aria-expanded={showSeeds}>
          <span className="flex items-center gap-2 font-bold" style={{ color: "var(--text)" }}>
            <Icon name="settings" size={16} /> صفحه‌ها و هشتگ‌های دیده‌بانی ({fa(data.seeds.length)})
          </span>
          <span className="text-xs" style={{ color: "var(--text-3)" }}>
            {showSeeds ? "بستن" : "ویرایش"}
          </span>
        </button>
        {showSeeds && <SeedsPanel base={base} data={data} onChange={() => load(true)} />}
      </Card>
    </div>
  );
}

/* ────────────────────────────── pieces */

function PostRow({ post }: { post: Post }) {
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2">
        <a href={post.url} target="_blank" rel="noreferrer" className="font-bold underline" style={{ color: "var(--text)" }}>
          @{post.account}
        </a>
        <Badge tone="neutral">{post.fmt_label}</Badge>
        <Badge tone={scoreTone(post.score)}>امتیاز {fa(Math.round(post.score))}</Badge>
        <span className="text-xs" style={{ color: "var(--text-3)" }}>
          {ageText(post.age_h)}
        </span>
      </div>
      {post.hook && (
        <p className="mt-1 text-sm leading-7" style={{ color: "var(--text-2)" }} dir="auto">
          «{post.hook}»
        </p>
      )}
      <div className="mt-1 flex flex-wrap gap-3 text-xs" style={{ color: "var(--text-3)" }}>
        <span>{post.likes_hidden ? "لایک پنهان" : `${compact(post.likes)} لایک`}</span>
        <span>{compact(post.comments)} کامنت</span>
        {post.views !== null && <span>{compact(post.views)} بازدید</span>}
      </div>
      {post.why && (
        <p className="mt-1 text-xs" style={{ color: "var(--text-3)" }}>
          {post.why}
        </p>
      )}
    </Card>
  );
}

function ClusterCard({
  cluster: c,
  pack,
  busy,
  canEdit,
  onIdea,
  onBuild,
  onDismiss,
}: {
  cluster: Cluster;
  pack?: { brief: Brief; idea_id: number };
  busy: string | null;
  canEdit: boolean;
  onIdea: () => void;
  onBuild: () => void;
  onDismiss: () => void;
}) {
  const brief = pack?.brief ?? c.brief;
  const [open, setOpen] = useState(false);
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-base font-extrabold" style={{ color: "var(--text)" }}>
          {c.label}
        </span>
        <Badge tone={scoreTone(c.score)}>امتیاز {fa(Math.round(c.score))}</Badge>
        <Badge tone="neutral">{c.fmt_label}</Badge>
        {c.kind === "breakout" && <Badge tone="brand">پستِ پرفروغ</Badge>}
        {c.in_niche && <Badge tone="info">هم‌خوان با واژه‌های شما</Badge>}
      </div>

      <ul className="mt-2 list-inside list-disc text-sm leading-7" style={{ color: "var(--text-2)" }}>
        {c.why.slice(0, 4).map((w) => (
          <li key={w}>{w}</li>
        ))}
      </ul>

      {c.hashtags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {c.hashtags.slice(0, 6).map((h) => (
            <Badge key={h} tone="neutral">
              #{h.replace(/_/g, " ")}
            </Badge>
          ))}
        </div>
      )}

      {c.examples && c.examples.length > 0 && (
        <div className="mt-3">
          <button type="button" className="text-xs underline" style={{ color: "var(--text-3)" }} onClick={() => setOpen((v) => !v)} aria-expanded={open}>
            {open ? "پنهان‌کردنِ نمونه‌ها" : `دیدنِ ${fa(c.examples.length)} نمونه از پست‌ها`}
          </button>
          {open && (
            <div className="mt-2 flex flex-col gap-2">
              {c.examples.map((p) => (
                <PostRow key={p.id} post={p} />
              ))}
            </div>
          )}
        </div>
      )}

      {c.hooks.length > 0 && (
        <p className="mt-2 text-xs leading-6" style={{ color: "var(--text-3)" }}>
          قلاب‌های رایج: {Array.from(new Set(c.hooks.map((h) => HOOK_FA[h.type] ?? h.type))).join("، ")}
        </p>
      )}

      {brief && <BriefView brief={brief} />}

      {canEdit && (
        <div className="mt-3 flex flex-wrap gap-2">
          <Button onClick={onIdea} disabled={busy !== null}>
            <span className="inline-flex items-center gap-1.5">
              <Icon name="bulb" size={15} />
              {busy === `idea-${c.id}` ? "…" : brief ? "ایده‌ی تازه بساز" : "ایده بساز"}
            </span>
          </Button>
          {pack && (
            <Button variant="secondary" onClick={onBuild} disabled={busy !== null || !pack.brief.product_id}>
              بساز
            </Button>
          )}
          <Button variant="ghost" onClick={onDismiss} disabled={busy !== null} title="این موضوع به کارم نمی‌آید؛ از فهرست پنهان شود" aria-label="این موضوع به کارم نمی‌آید؛ پنهانش کن">
            نه
          </Button>
        </div>
      )}
      {pack && !pack.brief.product_id && (
        <p className="mt-1 text-xs" style={{ color: "var(--text-3)" }}>
          برای ساختن، اول در «محصولات» یک محصول اضافه کنید تا ایده به آن وصل شود.
        </p>
      )}
    </Card>
  );
}

const HOOK_FA: Record<string, string> = {
  question: "پرسش",
  number: "فهرستِ عددی",
  contrarian: "هشدار / باورِ غلط",
  story: "تجربه / داستان",
  cta: "دعوت به اقدام",
  claim: "وعدهٔ نتیجه",
  statement: "جملهٔ خبری",
};

function BriefView({ brief }: { brief: Brief }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(brief.caption);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard may be blocked; the text is selectable anyway */
    }
  }
  return (
    <div className="mt-3 rounded-xl p-3" style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }}>
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <Badge tone={brief.source === "ai" ? "brand" : "neutral"}>{brief.source === "ai" ? "با هوش مصنوعی" : "قالبِ ساده"}</Badge>
        {brief.product_name && <Badge tone="info">{brief.product_name}</Badge>}
        {brief.needs_edit && <Badge tone="warn">جاهای [ ] را خودتان پر کنید</Badge>}
      </div>
      <p className="font-bold leading-7" style={{ color: "var(--text)" }}>
        «{brief.hook}»
      </p>
      <p className="text-sm leading-7" style={{ color: "var(--text-2)" }}>
        {brief.idea}
      </p>
      {brief.outline.length > 0 && (
        <ol className="mt-1 list-inside list-decimal text-sm leading-7" style={{ color: "var(--text-2)" }}>
          {brief.outline.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ol>
      )}
      {brief.caption && (
        <div className="mt-2">
          <div className="mb-1 flex items-center justify-between text-xs" style={{ color: "var(--text-3)" }}>
            <span>پیش‌نویسِ کپشن</span>
            <button type="button" className="underline" onClick={copy}>
              {copied ? "کپی شد" : "کپی"}
            </button>
          </div>
          <pre className="whitespace-pre-wrap text-sm leading-7" style={{ color: "var(--text-2)", fontFamily: "inherit" }}>
            {brief.caption}
          </pre>
        </div>
      )}
      <p className="mt-1 text-xs" style={{ color: "var(--text-3)" }}>
        چرا شما: {brief.why}
      </p>
      {brief.note && (
        <p className="mt-1 text-xs" style={{ color: "var(--text-3)" }}>
          {brief.note}
        </p>
      )}
    </div>
  );
}

function SeedsPanel({ base, data, onChange }: { base: string; data: Overview; onChange: () => void }) {
  const [kind, setKind] = useState<Seed["kind"]>("account");
  const [value, setValue] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function act(job: () => Promise<unknown>) {
    setSaving(true);
    setErr(null);
    try {
      await job();
      onChange();
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  const groups: [Seed["kind"], string][] = [
    ["account", "صفحه‌ها (خوانده می‌شوند)"],
    ["hashtag", "هشتگ‌ها (برای تشخیصِ حوزه)"],
    ["keyword", "واژه‌ها (برای تشخیصِ حوزه)"],
  ];

  return (
    <div className="mt-4 flex flex-col gap-4">
      <ErrorBox message={err} />
      {groups.map(([k, title]) => {
        const rows = data.seeds.filter((s) => s.kind === k);
        return (
          <div key={k}>
            <div className="mb-1 text-sm font-medium" style={{ color: "var(--text-2)" }}>
              {title}
            </div>
            {rows.length === 0 ? (
              <p className="text-xs" style={{ color: "var(--text-3)" }}>
                چیزی اضافه نشده.
              </p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {rows.map((s) => (
                  <span
                    key={s.id}
                    className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs"
                    style={{ background: "var(--surface-2)", border: "1px solid var(--line)", color: s.enabled ? "var(--text-2)" : "var(--text-3)", opacity: s.enabled ? 1 : 0.6 }}
                    title={s.note || undefined}
                  >
                    <button type="button" aria-label={s.enabled ? "خاموش‌کردن" : "روشن‌کردن"} onClick={() => act(() => api.patch(`${base}/seeds/${s.id}/`, { enabled: !s.enabled }))}>
                      <Icon name={s.enabled ? "check" : "pause"} size={12} />
                    </button>
                    <span dir="ltr">{s.kind === "account" ? `@${s.value}` : `#${s.value.replace(/_/g, " ")}`}</span>
                    {s.kind === "account" && s.last_status && s.last_status !== "ok" && <Badge tone="warn">{SEED_STATUS[s.last_status] ?? s.last_status}</Badge>}
                    {s.kind === "account" && !s.scrape && s.last_status !== "private" && <Badge tone="neutral">فقط از فایل</Badge>}
                    <button type="button" aria-label="حذف" onClick={() => act(() => api.delete(`${base}/seeds/${s.id}/`))}>
                      <Icon name="x" size={12} />
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>
        );
      })}

      {data.can_edit && (
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (!value.trim()) return;
            act(async () => {
              await api.post(`${base}/seeds/`, { kind, value });
              setValue("");
            });
          }}
        >
          <Select value={kind} onChange={(e) => setKind(e.target.value as Seed["kind"])} aria-label="نوع" style={{ maxWidth: 140 }}>
            <option value="account">صفحه</option>
            <option value="hashtag">هشتگ</option>
            <option value="keyword">واژه</option>
          </Select>
          <Input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder={kind === "account" ? "نامِ کاربری یا لینکِ صفحه (چند تا با ویرگول)" : "مثلاً تمرین_در_خانه"}
            aria-label="مقدار"
            style={{ minWidth: 220 }}
          />
          <Button type="submit" disabled={saving || !value.trim()}>
            <span className="inline-flex items-center gap-1">
              <Icon name="plus" size={14} /> افزودن
            </span>
          </Button>
          <Button type="button" variant="ghost" disabled={saving} onClick={() => act(() => api.post(`${base}/seeds/reset/`, {}))}>
            بازگرداندنِ پیشنهادهای اولیه
          </Button>
        </form>
      )}

      {data.can_edit && (
        <label className="flex flex-wrap items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
          <input
            type="checkbox"
            checked={data.config.auto_scan}
            onChange={(e) => act(() => api.post(`${base}/config/`, { auto_scan: e.target.checked }))}
          />
          خواندنِ خودکار (حداکثر هر {fa(data.config.interval_h)} ساعت، {fa(data.config.max_accounts)} صفحه، فقط وقتی آباگرام آماده است)
        </label>
      )}
      <p className="text-xs leading-6" style={{ color: "var(--text-3)" }}>
        پیشنهادهای اولیه فقط نقطهٔ شروع‌اند: صفحه‌هایی که خودتان در حوزه‌ی فارسی دنبال می‌کنید را اضافه کنید. صفحه‌ای که پیدا نشود بعد از دو بار خودش خاموش می‌شود.
        هشتگ و واژه‌ها صفحه‌ای را نمی‌خوانند؛ فقط می‌گویند حوزه‌ی شما چیست تا موضوع‌های هم‌خوان بالاتر بیایند.
      </p>
    </div>
  );
}
