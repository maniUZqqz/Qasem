import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { errorMessage } from "../../../api/client";
import Icon from "../../../components/Icon";
import { Alert, Badge, Button, Card, EmptyState, ErrorBox, Field, PageHeader, SectionTitle, Select, Spinner, fa } from "../../../components/ui";
import { useAuth } from "../../auth/AuthContext";
import {
  ANGLE_COLORS,
  ImageSource,
  MoveBody,
  NodeRow,
  NodeStatus,
  Overview,
  Presets,
  Run,
  VideoSource,
  VirtualBody,
  cutBar,
  mmss,
  multiangleApi,
  readiness,
} from "./api";

type Tab = "virtual" | "move25d" | "real";

const TABS: { key: Tab; label: string; hint: string }[] = [
  { key: "virtual", label: "زاویه‌های مجازی", hint: "از یک فیلم چند زاویه و فیلمِ مولتی‌کمِ خودکار" },
  { key: "move25d", label: "حرکتِ دوربینِ ۲٫۵بعدی", hint: "از یک نما، دوربین به جلو، کنار، بالا یا دورِ سوژه می‌چرخد" },
  { key: "real", label: "چند دوربینِ واقعی", hint: "چند فیلم از یک رویداد؛ هم‌گام با صدا و برشِ خودکار" },
];

const POLL_ACTIVE_MS = 3000;
const POLL_IDLE_MS = 15000;

/**
 * «چندزاویه» — از یک فیلمِ تک‌دوربین چند زاویه با حرکتِ طبیعیِ دوربین و برشِ خودکار، و حرکتِ دوربینِ ۲٫۵بعدی از یک نما.
 * کارِ سنگین روی سرورِ پردازش (کارتِ گرافیک) انجام می‌شود؛ اگر خاموش باشد کار در صف می‌ماند و با روشن شدنش خودکار اجرا می‌شود.
 * محیط و مدل‌ها را خودِ سرورِ پردازش نصب می‌کند و خودش را آزمایش می‌کند؛ این صفحه فقط وضعیتش را نشان می‌دهد.
 */
export default function MultiAnglePage() {
  const { id: storeId = "" } = useParams<{ id: string }>();
  const [data, setData] = useState<Overview | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [status, setStatus] = useState<NodeStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("virtual");
  const [open, setOpen] = useState<number | null>(null);

  const load = useCallback(() => {
    multiangleApi
      .overview(storeId)
      .then((d) => {
        setData(d);
        setRuns(d.runs);
        setStatus(d.status);
        setError(null);
      })
      .catch((e) => setError(errorMessage(e)));
  }, [storeId]);
  useEffect(load, [load]);

  const anyActive = runs.some((r) => r.active);
  useEffect(() => {
    // اجراهای در جریان هر ۳ ثانیه؛ وضعیتِ سرورِ پردازش (نصبِ خودکار) آهسته‌تر
    const timer = window.setInterval(
      () => {
        if (document.hidden) return;
        if (anyActive) {
          runs
            .filter((r) => r.active)
            .forEach((r) =>
              multiangleApi
                .run(storeId, r.id)
                .then((fresh) => setRuns((cur) => cur.map((x) => (x.id === fresh.id ? { ...x, ...fresh } : x))))
                .catch(() => undefined),
            );
        }
        multiangleApi.status(storeId).then(setStatus).catch(() => undefined);
      },
      anyActive ? POLL_ACTIVE_MS : POLL_IDLE_MS,
    );
    return () => window.clearInterval(timer);
  }, [anyActive, runs, storeId]);

  function created(run: Run) {
    setRuns((cur) => [run, ...cur.filter((r) => r.id !== run.id)]);
    setOpen(run.id);
  }

  async function removeRun(run: Run) {
    if (!window.confirm(`«${run.title}» و فایل‌هایش (زاویه‌های ساخته‌شده در رسانهٔ ادیتور) پاک شود؟`)) return;
    try {
      await multiangleApi.remove(storeId, run.id);
      setRuns((cur) => cur.filter((r) => r.id !== run.id));
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  if (!data && !error) {
    return (
      <Card>
        <Spinner />
      </Card>
    );
  }

  return (
    <div className="space-y-5" data-testid="multiangle-page">
      <PageHeader
        title="چندزاویه"
        subtitle="یک فیلم را با یک دوربین بگیرید؛ نمای باز، متوسط و نزدیک با حرکتِ طبیعیِ دوربین و برشِ خودکار می‌گیرید. یا از یک نما، حرکتِ دوربینِ سینمایی بسازید."
      />
      <ErrorBox message={error} />
      <NodeCard storeId={storeId} status={status} onChange={setStatus} />

      <div className="flex flex-wrap gap-2" role="tablist" aria-label="نوعِ کار">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => setTab(t.key)}
            data-testid={`tab-${t.key}`}
            className={`u-btn ${tab === t.key ? "u-btn-primary" : "u-btn-secondary"}`}
            title={t.hint}
          >
            {t.label}
          </button>
        ))}
      </div>

      {data && tab === "virtual" && <VirtualForm storeId={storeId} presets={data.presets} videos={data.sources.videos} status={status} onCreated={created} />}
      {data && tab === "move25d" && <MoveForm storeId={storeId} presets={data.presets} videos={data.sources.videos} images={data.sources.images} status={status} onCreated={created} />}
      {data && tab === "real" && <RealForm storeId={storeId} presets={data.presets} videos={data.sources.videos} />}

      <div>
        <SectionTitle>ساخته‌شده‌ها</SectionTitle>
        {runs.length === 0 ? (
          <EmptyState title="هنوز چیزی نساخته‌اید" description="یک فیلم انتخاب کنید و «بساز» را بزنید؛ نتیجه همین‌جا می‌آید و زاویه‌ها در «ادیتور ویدیو» هم هستند." />
        ) : (
          <div className="space-y-3">
            {runs.map((r) => (
              <RunCard
                key={r.id}
                storeId={storeId}
                run={r}
                expanded={open === r.id}
                onToggle={() => setOpen(open === r.id ? null : r.id)}
                onChange={(fresh) => setRuns((cur) => cur.map((x) => (x.id === fresh.id ? { ...x, ...fresh } : x)))}
                onRemove={() => void removeRun(r)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ───────────────────────────── وضعیتِ سرورِ پردازش

function NodeCard({ storeId, status, onChange }: { storeId: string; status: NodeStatus | null; onChange: (s: NodeStatus) => void }) {
  const { user } = useAuth();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [showMore, setShowMore] = useState(false);

  if (!status) return null;
  const ready = status.ready.virtual && status.ready.move && status.online;
  const tone = ready ? "ok" : status.needs_update.length ? "warn" : status.online ? "info" : "warn";

  async function prepare() {
    setBusy(true);
    setNote(null);
    try {
      const r = await multiangleApi.prepare(storeId);
      onChange(r.status);
      setNote("درخواستِ نصب به سرورِ پردازش فرستاده شد؛ بقیه خودکار است.");
    } catch (e) {
      setNote(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function selftest() {
    setBusy(true);
    setNote(null);
    try {
      const r = await multiangleApi.selftest(storeId);
      onChange(r.status);
      setNote(r.runs.length ? "آزمونِ خودکار در صفِ سرورِ پردازش است." : "سرورِ پردازشِ روشنی برای آزمون نیست.");
    } catch (e) {
      setNote(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Alert
      tone={tone}
      title={ready ? "سرورِ پردازش آماده است" : "سرورِ پردازش"}
      action={
        <div className="flex shrink-0 flex-col gap-2">
          {!ready && status.nodes.length > 0 && (
            <Button variant="secondary" size="sm" disabled={busy} onClick={() => void prepare()}>
              <Icon name="download" size={14} /> آماده‌سازی
            </Button>
          )}
          {status.nodes.length > 0 && (
            <Button variant="ghost" size="sm" onClick={() => setShowMore((v) => !v)}>
              {showMore ? "بستن" : "جزئیات"}
            </Button>
          )}
        </div>
      }
    >
      <div data-testid="node-message">{status.needs_update.length ? status.update_text : status.message}</div>
      {note && <div className="mt-1 text-xs">{note}</div>}
      {showMore && (
        <div className="mt-3 space-y-3">
          {status.nodes.map((n) => (
            <NodeDetails key={n.name} node={n} staff={!!user?.is_staff} busy={busy} onTest={() => void selftest()} />
          ))}
        </div>
      )}
    </Alert>
  );
}

function NodeDetails({ node, staff, busy, onTest }: { node: NodeRow; staff: boolean; busy: boolean; onTest: () => void }) {
  const device = node.runtime.gpu ? `کارتِ گرافیک (${node.runtime.providers.filter((p) => p !== "CPU").join("، ") || "GPU"})` : "پردازنده";
  return (
    <div className="rounded-xl p-3" style={{ background: "var(--surface-2)" }}>
      <div className="flex flex-wrap items-center gap-2 text-sm font-bold">
        <Icon name="cpu" size={15} /> {node.name}
        <Badge tone={node.online ? "ok" : "warn"}>{node.online ? "روشن" : "خاموش"}</Badge>
        {node.gpu && <Badge tone="info">{node.gpu}</Badge>}
        {node.runtime.ok && <Badge tone={node.runtime.gpu ? "ok" : "neutral"}>اجرا روی {device}</Badge>}
      </div>
      <ul className="mt-2 grid gap-1 text-xs sm:grid-cols-3">
        {node.models.map((m) => (
          <li key={m.key} className="flex items-center gap-2">
            <Badge tone={m.state === "installed" ? "ok" : m.state === "failed" ? "bad" : "info"}>{m.state_label}</Badge>
            <span>
              {m.label}
              {m.state === "downloading" && m.progress != null ? ` — ${fa(Math.round(m.progress * 100))}٪` : ""}
            </span>
          </li>
        ))}
      </ul>
      {node.runtime.ok === false && node.runtime.message && <div className="mt-1 text-xs">{node.runtime.message}</div>}
      <div className="mt-3 text-xs font-bold">آزمونِ خودکار</div>
      {node.selftest ? (
        <div className="mt-1 space-y-1 text-xs" data-testid="selftest-result">
          <Badge tone={node.selftest.ok ? "ok" : node.selftest.state === "FAILED" ? "bad" : "info"}>
            {node.selftest.ok ? "گذشت" : node.selftest.state === "FAILED" ? "رد شد" : "در حالِ اجرا"}
          </Badge>
          {node.selftest.checks.map((c) => (
            <div key={c.name} className="flex gap-2">
              <span style={{ color: c.ok ? "var(--ok)" : "var(--bad)" }}>{c.ok ? "✓" : "✗"}</span>
              <span>{c.label}</span>
              {!c.ok && c.detail && <span style={{ color: "var(--text-3)" }}>— {c.detail}</span>}
            </div>
          ))}
        </div>
      ) : (
        <div className="mt-1 text-xs" style={{ color: "var(--text-3)" }}>
          پس از آماده شدن، خودکار اجرا می‌شود.
        </div>
      )}
      {staff && node.online && (
        <div className="mt-2">
          <Button variant="secondary" size="sm" disabled={busy} onClick={onTest}>
            <Icon name="refresh" size={14} /> اجرای دوبارهٔ آزمون
          </Button>
        </div>
      )}
    </div>
  );
}

// ───────────────────────────── فرم‌ها

function SourceList({ items, value, onPick, empty }: { items: { ref: string; title: string; meta: string; url: string | null }[]; value: string; onPick: (ref: string) => void; empty: string }) {
  if (items.length === 0) return <div className="text-sm" style={{ color: "var(--text-3)" }}>{empty}</div>;
  return (
    <div className="max-h-64 space-y-1 overflow-y-auto rounded-xl p-1" style={{ background: "var(--surface-2)" }} role="radiogroup" data-testid="source-list">
      {items.map((v) => (
        <label
          key={v.ref}
          className="flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm"
          style={{ background: value === v.ref ? "var(--brand-soft, var(--surface))" : "transparent" }}
        >
          <input type="radio" name="source" checked={value === v.ref} onChange={() => onPick(v.ref)} />
          <span className="min-w-0 flex-1 truncate font-medium">{v.title}</span>
          <span className="shrink-0 text-xs" style={{ color: "var(--text-3)" }}>
            {v.meta}
          </span>
        </label>
      ))}
    </div>
  );
}

const videoMeta = (v: VideoSource) => `${mmss(v.duration)} · ${fa(v.width)}×${fa(v.height)}${v.has_audio ? "" : " · بی‌صدا"}`;

function Preview({ items, value }: { items: { ref: string; url: string | null }[]; value: string }) {
  const url = items.find((i) => i.ref === value)?.url;
  if (!url) return null;
  const isImage = /\.(jpe?g|png|webp|gif)(\?|$)/i.test(url);
  return isImage ? (
    <img src={url} alt="" className="max-h-56 rounded-xl" />
  ) : (
    <video src={url} controls preload="metadata" className="max-h-56 rounded-xl" />
  );
}

function VirtualForm({ storeId, presets, videos, status, onCreated }: { storeId: string; presets: Presets; videos: VideoSource[]; status: NodeStatus | null; onCreated: (r: Run) => void }) {
  const [source, setSource] = useState("");
  const [angles, setAngles] = useState<string[]>(presets.angles.filter((a) => a.default).map((a) => a.key));
  const [format, setFormat] = useState(presets.defaults.format);
  const [pace, setPace] = useState(presets.defaults.pace);
  const [rhythm, setRhythm] = useState(presets.defaults.rhythm);
  const [handheld, setHandheld] = useState(presets.defaults.handheld);
  const [multicam, setMulticam] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ready = readiness(status, "virtual");
  const chosen = videos.find((v) => v.ref === source);
  const tooLong = !!chosen && chosen.duration > presets.limits.max_seconds;

  function toggle(key: string) {
    setAngles((cur) => (cur.includes(key) ? cur.filter((k) => k !== key) : [...cur, key]));
  }

  async function submit() {
    setBusy(true);
    setError(null);
    const body: VirtualBody = { mode: "virtual", source, angles, format, pace, handheld, rhythm, multicam };
    try {
      onCreated(await multiangleApi.create(storeId, body));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <div className="space-y-4" data-testid="virtual-form">
        <Field label="فیلم" hint={`تا ${fa(presets.limits.max_seconds)} ثانیه؛ بیشترِ فیلم‌های ایستاده (ریلز) و افقی جواب می‌دهد.`}>
          <SourceList
            items={videos.map((v) => ({ ref: v.ref, title: v.title, meta: videoMeta(v), url: v.url }))}
            value={source}
            onPick={setSource}
            empty="فیلمی در فروشگاه نیست؛ از «ادیتور ویدیو» یک فیلم بارگذاری کنید."
          />
        </Field>
        <Preview items={videos} value={source} />
        {tooLong && <Alert tone="info">فیلم از {fa(presets.limits.max_seconds)} ثانیه بلندتر است؛ فقط همین‌قدرِ اولش پردازش می‌شود.</Alert>}

        <div>
          <div className="mb-1.5 text-sm font-medium" style={{ color: "var(--text-2)" }}>
            زاویه‌ها
          </div>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {presets.angles.map((a) => (
              <label key={a.key} className="flex cursor-pointer items-start gap-2 rounded-xl p-3 text-sm" style={{ background: "var(--surface-2)" }}>
                <input type="checkbox" checked={angles.includes(a.key)} onChange={() => toggle(a.key)} data-testid={`angle-${a.key}`} />
                <span>
                  <span className="flex items-center gap-2 font-bold">
                    <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: ANGLE_COLORS[a.key] }} />
                    {a.label}
                  </span>
                  <span className="block text-xs" style={{ color: "var(--text-3)" }}>
                    {a.hint}
                  </span>
                </span>
              </label>
            ))}
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="شکلِ خروجی">
            <Select value={format} onChange={(e) => setFormat(e.target.value)}>
              {presets.formats.map((f) => (
                <option key={f.key} value={f.key}>
                  {f.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="ریتمِ برش‌ها">
            <Select value={pace} onChange={(e) => setPace(e.target.value)}>
              {presets.paces.map((f) => (
                <option key={f.key} value={f.key}>
                  {f.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="برش روی چه چیزی بیفتد؟" hint="مکثِ گفتار یا پایانِ جمله؛ با موسیقی روی ضرب">
            <Select value={rhythm} onChange={(e) => setRhythm(e.target.value)}>
              {presets.rhythms.map((f) => (
                <option key={f.key} value={f.key}>
                  {f.label}
                </option>
              ))}
            </Select>
          </Field>
        </div>

        <Field label={`لرزشِ دست: ${handheld === 0 ? "ثابت (سه‌پایه)" : handheld < 0.5 ? "خفیف" : "دست‌گرفته"}`} hint="تکانِ ملایمِ دوربینِ روی دست؛ برای حالتِ طبیعی‌تر. صفر = کاملاً ثابت.">
          <input type="range" min={0} max={1} step={0.05} value={handheld} onChange={(e) => setHandheld(Number(e.target.value))} className="w-full" />
        </Field>

        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={multicam} onChange={(e) => setMulticam(e.target.checked)} /> فیلمِ مولتی‌کمِ خودکار هم ساخته شود (برش‌ها روی مکثِ گفتار و ضرب)
        </label>

        <ErrorBox message={error} />
        {!ready.ok && <Alert tone={ready.tone === "ok" ? "info" : ready.tone}>{ready.text} کار ثبت می‌شود و در صف می‌ماند تا سرورِ پردازش آماده شود.</Alert>}
        <div className="flex justify-end">
          <Button disabled={busy || !source || angles.length < 2} onClick={() => void submit()} data-testid="create-virtual">
            {busy ? <Spinner size={14} /> : <Icon name="film" size={15} />} بساز
          </Button>
        </div>
        {angles.length < 2 && <div className="text-xs" style={{ color: "var(--text-3)" }}>دست‌کم دو زاویه انتخاب کنید.</div>}
      </div>
    </Card>
  );
}

function MoveForm({
  storeId,
  presets,
  videos,
  images,
  status,
  onCreated,
}: {
  storeId: string;
  presets: Presets;
  videos: VideoSource[];
  images: ImageSource[];
  status: NodeStatus | null;
  onCreated: (r: Run) => void;
}) {
  const [source, setSource] = useState("");
  const [move, setMove] = useState("dolly_in");
  const [amount, setAmount] = useState(presets.defaults.amount);
  const [duration, setDuration] = useState(presets.defaults.duration);
  const [format, setFormat] = useState(presets.defaults.format);
  const [ease, setEase] = useState("inout");
  const [relief, setRelief] = useState(1);
  const [inpaint, setInpaint] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ready = readiness(status, "move25d");
  const all = useMemo(
    () => [
      ...images.map((i) => ({ ref: i.ref, title: i.title, meta: `عکس · ${fa(i.width)}×${fa(i.height)}`, url: i.url })),
      ...videos.map((v) => ({ ref: v.ref, title: v.title, meta: `فیلم · ${videoMeta(v)}`, url: v.url })),
    ],
    [images, videos],
  );
  const isVideo = source.startsWith("video:") || source.startsWith("edited:") || source.startsWith("script:");

  async function submit() {
    setBusy(true);
    setError(null);
    const body: MoveBody = { mode: "move25d", source, move, amount, duration, format, ease, relief, inpaint };
    try {
      onCreated(await multiangleApi.create(storeId, body));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <div className="space-y-4" data-testid="move-form">
        <Field label="عکس یا فیلم" hint="از فیلم، چند ثانیهٔ اول (تا ۱۲ ثانیه) استفاده می‌شود.">
          <SourceList items={all} value={source} onPick={setSource} empty="عکس یا فیلمی در فروشگاه نیست." />
        </Field>
        <Preview items={all} value={source} />

        <div>
          <div className="mb-1.5 text-sm font-medium" style={{ color: "var(--text-2)" }}>
            حرکتِ دوربین
          </div>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {presets.moves.map((m) => (
              <button
                key={m.key}
                type="button"
                onClick={() => setMove(m.key)}
                data-testid={`move-${m.key}`}
                className="rounded-xl p-3 text-start text-sm"
                style={{
                  background: move === m.key ? "var(--brand-soft, var(--surface-2))" : "var(--surface-2)",
                  border: `1px solid ${move === m.key ? "var(--brand)" : "transparent"}`,
                }}
              >
                <span className="block font-bold">{m.label}</span>
                <span className="block text-xs" style={{ color: "var(--text-3)" }}>
                  {m.hint}
                </span>
              </button>
            ))}
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={`مقدارِ حرکت: ${fa(Math.round(amount * 100))}٪`} hint="بیشتر = پارالاکسِ قوی‌تر؛ زیادش لبه‌های سوژه را می‌کشد.">
            <input type="range" min={0.1} max={1} step={0.05} value={amount} onChange={(e) => setAmount(Number(e.target.value))} className="w-full" />
          </Field>
          <Field label={`عمقِ صحنه: ${fa(Math.round(relief * 100))}٪`} hint="فاصلهٔ جلو و عقب را بیشتر یا کمتر نشان می‌دهد.">
            <input type="range" min={0.5} max={2} step={0.1} value={relief} onChange={(e) => setRelief(Number(e.target.value))} className="w-full" />
          </Field>
          {!isVideo && (
            <Field label={`مدت: ${fa(duration)} ثانیه`}>
              <input type="range" min={2} max={presets.limits.max_move_seconds} step={0.5} value={duration} onChange={(e) => setDuration(Number(e.target.value))} className="w-full" />
            </Field>
          )}
          <Field label="شکلِ خروجی">
            <Select value={format} onChange={(e) => setFormat(e.target.value)}>
              {presets.formats.map((f) => (
                <option key={f.key} value={f.key}>
                  {f.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="شتابِ حرکت">
            <Select value={ease} onChange={(e) => setEase(e.target.value)}>
              <option value="inout">نرمِ ابتدا و انتها</option>
              <option value="sine">سینوسی (نرم‌تر)</option>
              <option value="out">تند شروع، نرم پایان</option>
              <option value="linear">یکنواخت</option>
            </Select>
          </Field>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={inpaint} onChange={(e) => setInpaint(e.target.checked)} /> ترمیمِ بخش‌هایی که پشتِ سوژه بود و دیده می‌شود (کندتر، تمیزتر)
        </label>

        <ErrorBox message={error} />
        {!ready.ok && <Alert tone={ready.tone === "ok" ? "info" : ready.tone}>{ready.text} کار ثبت می‌شود و در صف می‌ماند تا سرورِ پردازش آماده شود.</Alert>}
        <div className="flex justify-end">
          <Button disabled={busy || !source} onClick={() => void submit()} data-testid="create-move">
            {busy ? <Spinner size={14} /> : <Icon name="camera" size={15} />} بساز
          </Button>
        </div>
      </div>
    </Card>
  );
}

function RealForm({ storeId, presets, videos }: { storeId: string; presets: Presets; videos: VideoSource[] }) {
  const navigate = useNavigate();
  const [picked, setPicked] = useState<string[]>([]);
  const [pace, setPace] = useState(presets.defaults.pace);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const withAudio = videos.filter((v) => v.has_audio);

  function toggle(ref: string) {
    setPicked((cur) => (cur.includes(ref) ? cur.filter((r) => r !== ref) : cur.length >= 4 ? cur : [...cur, ref]));
  }

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const r = await multiangleApi.real(storeId, picked, pace);
      navigate(`/stores/${storeId}/editor?project=${r.project_id}`);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <div className="space-y-4" data-testid="real-form">
        <p className="text-sm leading-7" style={{ color: "var(--text-2)" }}>
          اگر یک رویداد را با چند دوربین (یا چند گوشی) ضبط کرده‌اید، فیلم‌ها را انتخاب کنید: با صدا هم‌گام می‌شوند و برش‌ها روی مکثِ گفتار می‌افتند. نتیجه یک گروهِ مولتی‌کم در «ادیتور ویدیو» است که هر برش را می‌توانید جابه‌جا کنید. این کار روی خودِ سایت انجام می‌شود و به سرورِ پردازش نیاز ندارد.
        </p>
        <Field label="۲ تا ۴ فیلم از یک رویداد (باید صدا داشته باشند)">
          {withAudio.length === 0 ? (
            <div className="text-sm" style={{ color: "var(--text-3)" }}>
              فیلمِ صدادار نیست.
            </div>
          ) : (
            <div className="max-h-64 space-y-1 overflow-y-auto rounded-xl p-1" style={{ background: "var(--surface-2)" }}>
              {withAudio.map((v) => (
                <label key={v.ref} className="flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm">
                  <input type="checkbox" checked={picked.includes(v.ref)} onChange={() => toggle(v.ref)} />
                  <span className="min-w-0 flex-1 truncate font-medium">{v.title}</span>
                  <span className="shrink-0 text-xs" style={{ color: "var(--text-3)" }}>
                    {videoMeta(v)}
                  </span>
                </label>
              ))}
            </div>
          )}
        </Field>
        <Field label="ریتمِ برش‌ها">
          <Select value={pace} onChange={(e) => setPace(e.target.value)}>
            {presets.paces.map((f) => (
              <option key={f.key} value={f.key}>
                {f.label}
              </option>
            ))}
          </Select>
        </Field>
        <ErrorBox message={error} />
        <div className="flex justify-end">
          <Button disabled={busy || picked.length < 2} onClick={() => void submit()} data-testid="create-real">
            {busy ? <Spinner size={14} /> : <Icon name="link" size={15} />} هم‌گام کن و برش بزن
          </Button>
        </div>
      </div>
    </Card>
  );
}

// ───────────────────────────── یک اجرا

function ProgressBar({ value }: { value: number }) {
  return (
    <div className="h-2 w-full overflow-hidden rounded-full" style={{ background: "var(--surface-2)" }} role="progressbar" aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100}>
      <div className="h-full rounded-full" style={{ width: `${Math.max(3, Math.round(value * 100))}%`, background: "var(--brand)", transition: "width .4s" }} />
    </div>
  );
}

function RunCard({ storeId, run, expanded, onToggle, onChange, onRemove }: { storeId: string; run: Run; expanded: boolean; onToggle: () => void; onChange: (r: Run) => void; onRemove: () => void }) {
  const [detail, setDetail] = useState<Run | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const tone = run.state === "READY" ? "ok" : run.state === "FAILED" ? "bad" : run.state === "CANCELLED" ? "neutral" : "info";

  useEffect(() => {
    if (!expanded || run.state !== "READY") return;
    let off = false;
    multiangleApi
      .run(storeId, run.id)
      .then((r) => !off && setDetail(r))
      .catch((e) => !off && setError(errorMessage(e)));
    return () => {
      off = true;
    };
  }, [expanded, run.id, run.state, storeId]);

  async function cancel() {
    setBusy(true);
    try {
      onChange(await multiangleApi.cancel(storeId, run.id));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function toEditor() {
    setBusy(true);
    setError(null);
    try {
      const r = await multiangleApi.toEditor(storeId, run.id);
      navigate(`/stores/${storeId}/editor?project=${r.project_id}`);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <div className="flex flex-wrap items-center gap-3" data-testid={`run-${run.id}`}>
        {run.thumb && <img src={run.thumb} alt="" className="h-14 w-10 rounded-lg object-cover" />}
        <button type="button" onClick={onToggle} className="min-w-0 flex-1 text-start">
          <div className="truncate font-bold">{run.title}</div>
          <div className="text-xs" style={{ color: "var(--text-3)" }}>
            {run.mode_label}
          </div>
        </button>
        <Badge tone={tone}>{run.state_label}</Badge>
        {run.active && (
          <Button variant="ghost" size="sm" disabled={busy} onClick={() => void cancel()}>
            <Icon name="x" size={14} /> لغو
          </Button>
        )}
        <Button variant="ghost" size="sm" onClick={onRemove} aria-label="حذف">
          <Icon name="trash" size={14} />
        </Button>
      </div>
      {run.active && (
        <div className="mt-3 space-y-1">
          <ProgressBar value={run.progress} />
          <div className="text-xs" style={{ color: "var(--text-3)" }}>
            {run.message}
          </div>
        </div>
      )}
      {run.state === "FAILED" && <div className="mt-3"><ErrorBox message={run.error || "ساخت ناموفق بود."} /></div>}
      <ErrorBox message={error} />
      {expanded && run.state === "READY" && (
        <div className="mt-4">
          {!detail ? (
            <Spinner />
          ) : (
            <RunDetail run={detail} busy={busy} onEditor={() => void toEditor()} storeId={storeId} />
          )}
        </div>
      )}
    </Card>
  );
}

function RunDetail({ run, busy, onEditor, storeId }: { run: Run; busy: boolean; onEditor: () => void; storeId: string }) {
  const refs = useRef<HTMLVideoElement[]>([]);
  const [playing, setPlaying] = useState(false);
  const bar = useMemo(() => cutBar(run.cuts ?? []), [run.cuts]);

  function playAll() {
    const vids = refs.current.filter(Boolean);
    const t0 = vids[0]?.currentTime ?? 0;
    vids.forEach((v) => {
      v.muted = true;
      v.currentTime = t0;
      void v.play();
    });
    setPlaying(true);
  }
  function pauseAll() {
    refs.current.filter(Boolean).forEach((v) => v.pause());
    setPlaying(false);
  }
  function seekAll(t: number) {
    refs.current.filter(Boolean).forEach((v) => (v.currentTime = t));
  }

  if (run.mode === "move25d" && run.move) {
    return (
      <div className="space-y-3" data-testid="move-result">
        <div className="grid gap-3 sm:grid-cols-2">
          {run.move.url && <video src={run.move.url} poster={run.move.preview ?? undefined} controls loop preload="metadata" className="w-full rounded-xl" />}
          {run.move.depth && (
            <div>
              <img src={run.move.depth} alt="نقشهٔ عمق" className="w-full rounded-xl" />
              <div className="mt-1 text-xs" style={{ color: "var(--text-3)" }}>
                نقشهٔ عمق (روشن = نزدیک): پارالاکس از روی همین ساخته شد.
              </div>
            </div>
          )}
        </div>
        <Warnings items={run.warnings} />
        <div className="text-xs" style={{ color: "var(--text-3)" }}>
          {run.move.label}
          {run.output ? ` · ${fa(run.output.width)}×${fa(run.output.height)} · ${fa(run.output.fps)} فریم‌بر‌ثانیه` : ""}. فیلم در سطلِ رسانهٔ «ادیتور ویدیو» هم هست.
        </div>
        <a className="u-btn u-btn-secondary" href={`/stores/${storeId}/editor`}>
          <Icon name="film" size={15} /> رفتن به ادیتور ویدیو
        </a>
      </div>
    );
  }

  const angles = run.angles ?? [];
  return (
    <div className="space-y-4" data-testid="virtual-result">
      <div className="flex flex-wrap items-center gap-2">
        {playing ? (
          <Button variant="secondary" size="sm" onClick={pauseAll}>
            ⏸ توقفِ همهٔ زاویه‌ها
          </Button>
        ) : (
          <Button variant="secondary" size="sm" onClick={playAll}>
            <Icon name="play" size={14} /> پخشِ هم‌زمانِ زاویه‌ها
          </Button>
        )}
        <Button variant="secondary" size="sm" disabled={busy || angles.length < 2} onClick={onEditor} data-testid="open-editor">
          <Icon name="film" size={14} /> باز کردن در ادیتور (مولتی‌کم)
        </Button>
        {run.subject && <Badge tone="info">سوژه: {run.subject}</Badge>}
        {run.output && <Badge tone="neutral">{`${fa(run.output.width)}×${fa(run.output.height)} · ${fa(Math.round(run.output.duration))} ثانیه`}</Badge>}
        {run.node?.encoder && <Badge tone="neutral">{run.node.encoder === "nvenc" ? "رمزگذاری با کارتِ گرافیک" : "رمزگذاری با پردازنده"}</Badge>}
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {angles.map((a, i) => (
          <div key={a.key} className="rounded-xl p-2" style={{ background: "var(--surface-2)" }}>
            <video
              ref={(el) => {
                if (el) refs.current[i] = el;
              }}
              src={a.url ?? undefined}
              poster={a.preview ?? undefined}
              controls
              preload="metadata"
              className="w-full rounded-lg"
              onSeeked={(e) => {
                if (i === 0 && !playing) seekAll(e.currentTarget.currentTime);
              }}
            />
            <div className="mt-2 flex items-center gap-2 text-sm font-bold">
              <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: ANGLE_COLORS[a.key] }} />
              {a.label}
              {a.upscale != null && a.upscale > 1.35 && <Badge tone="warn">کمی نرم ({fa(a.upscale.toFixed(1))}×)</Badge>}
            </div>
          </div>
        ))}
        {run.multicam_url && (
          <div className="rounded-xl p-2" style={{ background: "var(--surface-2)" }}>
            <video src={run.multicam_url} controls preload="metadata" className="w-full rounded-lg" />
            <div className="mt-2 text-sm font-bold">مولتی‌کمِ خودکار</div>
          </div>
        )}
      </div>

      {bar.length > 0 && (
        <div data-testid="cut-bar">
          <div className="mb-1 text-sm font-bold">برش‌ها</div>
          <div className="relative flex h-8 w-full overflow-hidden rounded-lg" dir="ltr">
            {bar.map((c, i) => (
              <div
                key={`${c.t}-${i}`}
                title={`${c.label} — ${mmss(c.t)} تا ${mmss(c.end)} — ${c.reason}`}
                style={{ width: `${c.width}%`, background: ANGLE_COLORS[c.angle] ?? "#888", borderInlineEnd: "2px solid var(--surface)" }}
                className="flex items-center justify-center overflow-hidden text-[10px] font-bold text-white"
              >
                {c.width > 9 ? c.label : ""}
              </div>
            ))}
          </div>
          <ul className="mt-2 grid gap-1 text-xs sm:grid-cols-2">
            {(run.cuts ?? []).map((c, i) => (
              <li key={i} style={{ color: "var(--text-2)" }}>
                {fa(mmss(c.t))} — {c.label} <span style={{ color: "var(--text-3)" }}>({c.reason_label})</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <Warnings items={run.warnings} />
      {(run.skipped?.length ?? 0) > 0 && <div className="text-xs" style={{ color: "var(--text-3)" }}>ساخته نشد: {run.skipped!.map((s) => s.label).join("، ")}</div>}
    </div>
  );
}

function Warnings({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <Alert tone="warn" title="نکته‌ها">
      <ul className="list-disc space-y-1 pe-5">
        {items.map((w, i) => (
          <li key={i}>{w}</li>
        ))}
      </ul>
    </Alert>
  );
}
