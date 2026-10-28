import { useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import { Alert, Badge, Button, Card, EmptyState, PageHeader, Spinner } from "../../components/ui";
import CaptureFlow from "./CaptureFlow";
import OutputsPanel from "./OutputsPanel";
import PlanEditor from "./PlanEditor";
import { Overview, Session, fa, liveSupport, shootApi } from "./api";

/**
 * «فیلم‌برداریِ هدایت‌شده» (پنل › محتوا): محصول ⇐ تحلیل ⇐ برنامهٔ ویرایش‌پذیر ⇐ عکاسی و فیلم‌برداری با راهنما ⇐
 * تدوینِ خودکار ⇐ ویدیو و پوسترِ تبلیغاتی. هر جلسه ذخیره است؛ از هر گوشی‌ای ادامه پیدا می‌کند.
 */

type Step = "plan" | "capture" | "edit";
const STEPS: { key: Step; label: string }[] = [
  { key: "plan", label: "برنامه" },
  { key: "capture", label: "عکس و فیلم" },
  { key: "edit", label: "تدوین" },
];

export default function GuidedShootPage() {
  const { id = "" } = useParams<{ id: string }>();
  const [params, setParams] = useSearchParams();
  const [overview, setOverview] = useState<Overview | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [step, setStep] = useState<Step>("plan");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [analyze, setAnalyze] = useState(true);
  const sessionId = Number(params.get("session") || 0);
  const live = liveSupport();

  const loadOverview = useCallback(async () => {
    try {
      setOverview(await shootApi.overview(id));
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [id]);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

  useEffect(() => {
    if (!sessionId) {
      setSession(null);
      return;
    }
    if (session?.id === sessionId) return;
    shootApi
      .get(id, sessionId)
      .then((s) => {
        setSession(s);
        setStep(s.takes.some((t) => t.accepted) ? (s.outputs.length ? "edit" : "capture") : "plan");
      })
      .catch((err) => setError(errorMessage(err)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, sessionId]);

  // تازه‌سازی تا وقتی چیزی در جریان است (تحلیل، صدای راهنما، ساختِ خروجی)
  const busyServer =
    !!session &&
    (session.state === "ANALYZING" ||
      session.voice?.state === "RUNNING" ||
      session.outputs.some((o) => o.state === "QUEUED" || o.state === "RUNNING"));
  useEffect(() => {
    if (!busyServer || !session) return;
    const t = window.setInterval(() => {
      shootApi
        .get(id, session.id)
        .then(setSession)
        .catch(() => undefined);
    }, 2500);
    return () => window.clearInterval(t);
  }, [busyServer, id, session?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const open = (s: Session) => {
    setSession(s);
    setStep("plan");
    setParams({ session: String(s.id) });
  };

  const start = async (productId: number) => {
    setBusy(true);
    setError(null);
    try {
      open(await shootApi.create(id, { product: productId, purpose: "ad", analyze }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const removeSession = async (s: Session) => {
    if (!window.confirm(`جلسهٔ «${s.product.name}» و همهٔ عکس‌ها و فیلم‌هایش پاک شود؟`)) return;
    try {
      await shootApi.remove(id, s.id);
      await loadOverview();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const makeVoice = async () => {
    if (!session) return;
    try {
      setSession(await shootApi.action(id, session.id, "voice"));
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  if (!overview) {
    return <div className="py-10 text-center">{error ? <Alert tone="bad">{error}</Alert> : <Spinner />}</div>;
  }

  // ───────────────────────── شروع: انتخابِ محصول
  if (!session) {
    return (
      <div className="u-rise mx-auto max-w-3xl space-y-4" data-testid="shoot-start">
        <PageHeader
          title="فیلم‌برداریِ هدایت‌شده"
          subtitle="محصول را انتخاب کن؛ می‌گوییم از چه زاویه‌هایی عکس و فیلم بگیری، بعد خودکار تدوین می‌کنیم و پوستر و ویدیوی تبلیغاتی می‌سازیم."
        />
        {error && <Alert tone="bad">{error}</Alert>}
        <Alert tone={live.ok ? "ok" : "info"} title={live.ok ? "دوربینِ زنده در دسترس است" : "حالتِ «دوربینِ گوشی (گام‌به‌گام)»"}>
          {live.ok ? "راهنما روی تصویرِ دوربین و حینِ ضبط نشان داده و گفته می‌شود." : live.reason}
        </Alert>
        <label className="flex items-center gap-2 text-sm" style={{ minHeight: 44 }}>
          <input type="checkbox" checked={analyze} onChange={(e) => setAnalyze(e.target.checked)} />
          تحلیلِ محصول با هوش مصنوعی (عکس + توضیح) — بی‌آن، الگوی آمادهٔ همان دسته
        </label>
        {overview.products.length === 0 ? (
          <Card>
            <EmptyState icon="box" title="هنوز محصولی نیست" action={<Link to={`/stores/${id}`}>افزودنِ محصول</Link>} />
          </Card>
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {overview.products.map((p) => (
              <button
                key={p.id}
                disabled={busy}
                onClick={() => void start(p.id)}
                className="u-card u-card-hover overflow-hidden p-0 text-right disabled:opacity-60"
                data-testid={`product-${p.id}`}
              >
                {p.thumb ? (
                  <img src={p.thumb} alt="" className="h-28 w-full object-cover" />
                ) : (
                  <div className="grid h-28 place-items-center" style={{ background: "var(--surface-2)", color: "var(--text-3)" }}>
                    <Icon name="image" size={22} />
                  </div>
                )}
                <div className="p-3">
                  <div className="truncate font-bold" style={{ color: "var(--text)" }}>
                    {p.name}
                  </div>
                  <div className="text-xs" style={{ color: "var(--text-3)" }}>
                    {p.images ? `${fa(p.images)} عکس` : "بی‌عکس (تحلیل فقط از متن)"}
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}
        {busy && (
          <div className="flex items-center gap-2 text-sm">
            <Spinner size={16} /> ساختِ جلسه…
          </div>
        )}
        {overview.sessions.length > 0 && (
          <Card>
            <div className="mb-2 font-bold" style={{ color: "var(--text)" }}>
              جلسه‌های قبلی
            </div>
            <div className="space-y-2">
              {overview.sessions.map((s) => (
                <div key={s.id} className="flex items-center justify-between gap-2 rounded-xl p-2" style={{ border: "1px solid var(--line)" }}>
                  <button className="min-w-0 flex-1 text-right" style={{ minHeight: 44 }} onClick={() => setParams({ session: String(s.id) })}>
                    <div className="truncate font-semibold" style={{ color: "var(--text)" }}>
                      {s.product.name}
                    </div>
                    <div className="text-xs" style={{ color: "var(--text-3)" }}>
                      {s.purpose === "photos" ? "عکس‌های محصول" : "تبلیغ"} — {fa(s.counts?.accepted_shots ?? 0)} از {fa(s.counts?.shots ?? 0)} زاویه/نما ·{" "}
                      {fa(s.counts?.outputs ?? 0)} خروجی
                    </div>
                  </button>
                  <Button variant="ghost" size="sm" onClick={() => void removeSession(s)} aria-label="حذف">
                    <Icon name="trash" size={15} />
                  </Button>
                </div>
              ))}
            </div>
          </Card>
        )}
      </div>
    );
  }

  // ───────────────────────── جلسه
  const shotsTotal = session.plan.photos.length + (session.purpose === "ad" ? session.plan.video.length : 0);
  const shotsDone = new Set(session.takes.filter((t) => t.accepted).map((t) => t.shot)).size;
  return (
    <div className="u-rise mx-auto max-w-3xl space-y-4" data-testid="shoot-session">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <button className="u-back" onClick={() => setParams({})}>
            <Icon name="back" size={15} />
            همهٔ جلسه‌ها
          </button>
          <h1 className="truncate text-xl font-extrabold" style={{ color: "var(--text)" }}>
            {session.product.name}
          </h1>
          <div className="text-xs" style={{ color: "var(--text-3)" }}>
            {fa(shotsDone)} از {fa(shotsTotal)} زاویه/نما قبول شده
          </div>
        </div>
        {session.state === "ANALYZING" && <Badge tone="info">در حالِ تحلیل…</Badge>}
      </div>

      <nav className="grid grid-cols-3 gap-2">
        {STEPS.map((s, i) => (
          <button
            key={s.key}
            onClick={() => setStep(s.key)}
            className="rounded-xl px-2 py-2 text-sm font-bold"
            style={{
              minHeight: 48,
              background: step === s.key ? "var(--brand)" : "var(--surface-2)",
              color: step === s.key ? "#fff" : "var(--text-2)",
              border: "1px solid var(--line)",
            }}
            data-testid={`step-${s.key}`}
          >
            {fa(i + 1)}. {s.label}
          </button>
        ))}
      </nav>

      {error && <Alert tone="bad">{error}</Alert>}

      {step === "plan" && (
        <PlanEditor storeId={id} session={session} overview={overview} onSession={setSession} onStart={() => setStep("capture")} />
      )}

      {step === "capture" && (
        <>
          <Card>
            <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span style={{ color: "var(--text-2)" }}>
                صدای راهنما:{" "}
                {session.voice?.state === "READY"
                  ? `آماده (${session.voice.engine || "موتورِ گفتارِ سایت"})`
                  : session.voice?.state === "RUNNING"
                    ? "در حالِ ساخت…"
                    : session.voice?.state === "FAILED"
                      ? `نشد (${session.voice.error || ""}) — نوشته‌ها و لرزش کار می‌کنند`
                      : "ساخته نشده (فقط نوشته، یا صدای فارسیِ خودِ مرورگر اگر دارد)"}
              </span>
              {session.voice?.state !== "RUNNING" && (
                <Button variant="secondary" size="sm" onClick={() => void makeVoice()} data-testid="make-voice">
                  <Icon name="mic" size={14} />
                  {session.voice?.state === "READY" ? "ساختِ دوباره" : "ساختِ صدای راهنما"}
                </Button>
              )}
            </div>
          </Card>
          <CaptureFlow
            storeId={id}
            session={session}
            onSession={setSession}
            kinds={session.purpose === "ad" ? ["photo", "video"] : ["photo"]}
            footer={
              <Card>
                <div className="mb-2 font-bold" style={{ color: "var(--ok)" }}>
                  ✓ همهٔ زاویه‌ها و نماها قبول شد
                </div>
                <Button className="w-full" style={{ minHeight: 54 }} onClick={() => setStep("edit")} data-testid="go-edit">
                  تدوینِ خودکار و ساختِ پوستر و ویدیو
                  <Icon name="next" size={16} />
                </Button>
              </Card>
            }
          />
        </>
      )}

      {step === "edit" && <OutputsPanel storeId={id} session={session} overview={overview} onSession={setSession} />}
    </div>
  );
}
