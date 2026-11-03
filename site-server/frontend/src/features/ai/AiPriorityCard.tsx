import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";

import { api, errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import { Alert, Badge, Button, Card, ErrorBox, Select, Spinner, fa } from "../../components/ui";

/**
 * اولویتِ هوش مصنوعی: لوکال یا متیس — تنظیمِ واحدِ همهٔ کارهای هوش مصنوعیِ NM.
 *
 * هر کار (سایت‌ساز، متن و بازاریابی، چتِ فروش، پژوهش، کارگردانِ سه‌بعدی، ادیتورِ عکس/ویدیو، فیلم‌برداریِ هدایت‌شده، …)
 * هم با لوکال (Ollama روی سرورِ پردازش) و هم با متیس (API) می‌تواند انجام شود. این کارت می‌گوید کدام اول باشد؛ اگر اولی
 * در دسترس نبود (گره خاموش، مدل نصب نیست، مهلت، اعتبار تمام (۴۰۲)، ۴۰۱/۴۰۳، ۵xx، قطعِ اتصال) خودکار دومی جواب می‌دهد.
 *
 * چهار نوعِ کار، هرکدام مدلِ لوکالِ خودش: متنِ روزمره (سریع)، پژوهش و استدلالِ عمیق (کند و دقیق)، کد، بینایی. اگر مدلِ انتخابی روی
 * سرورِ پردازش نصب نبود، اولین مدلِ مناسبِ نصب‌شده جواب می‌دهد (پیش از رفتن به متیس) و همین‌جا نوشته می‌شود؛ کنارِ هر مدلِ نصب‌نشده
 * دکمهٔ «دانلود مدل» است (کارِ ollama.pull در صفِ سرورِ پردازش، با درصد و سرعت؛ گرهٔ خاموش هم در صف می‌گذارد).
 *
 * وضعِ زنده فقط از دیتابیس خوانده می‌شود (بی‌درخواست به متیس یا گره)؛ دکمهٔ «آزمون» یک درخواستِ کوچکِ واقعی می‌فرستد.
 */

type Order = "local_first" | "metis_first";
type Kind = "text" | "research" | "code" | "vision";
type LastError = { kind: string; message: string; at: string | null; from_history?: boolean };

type KindInfo = {
  label: string;
  override: "" | Order;
  first: "local" | "metis";
  order: ("local" | "metis")[];
  selected_model: string;
  default_model: string;
  model: string;
  installed: boolean | null;
  effective_model: string;
  substitute: string;
  chain: string[];
  usable: boolean | null;
  ready: boolean;
  reason: string;
  metis_model: string;
  pullable: boolean;
  size_mb: number;
};

type ModelRow = { tag: string; label: string; size_mb: number; purpose: string; vision: boolean; installed: boolean | null };

type Pull = {
  uid: string;
  tag: string;
  label: string;
  state: string;
  final: boolean;
  percent: number;
  done_mb: number | null;
  total_mb: number | null;
  speed_mbs: number | null;
  phase: string;
  node: string;
  node_online: boolean;
  waiting_for_node: boolean;
  text: string;
  error: string;
};

type Recent = {
  id: number;
  at: string;
  prompt_id: string;
  status: string;
  label: string;
  via: string;
  model: string;
  fell_back: boolean;
  reason: string;
  error: string;
};

type Snapshot = {
  priority: Order;
  breaker_minutes: number;
  orders: { value: Order; label: string }[];
  kinds: Record<Kind, KindInfo>;
  local: {
    online: boolean;
    node: string;
    nodes: { name: string; online: boolean }[];
    known_models: string[];
    models_reported_at: string | null;
    models_stale: boolean;
    pull_nodes: { id: number; name: string; online: boolean; agent: string; pull_ready: boolean }[];
    reason: string;
    last_ok_at: string | null;
    last_error: LastError | null;
    circuit_minutes_left: number;
  };
  metis: {
    configured: boolean;
    host: string;
    model_text: string;
    model_vision: string;
    last_ok_at: string | null;
    last_error: LastError | null;
    circuit_minutes_left: number;
  };
  models: ModelRow[];
  pulls: Pull[];
  recent: Recent[];
  message?: string;
};

type TestResult = { ok: boolean; provider: "local" | "metis"; kind: string; message: string };

const KINDS: Kind[] = ["text", "research", "code", "vision"];
const KIND_HINT: Record<Kind, string> = {
  text: "محتوا، کپشن، چتِ فروش، متنِ تبلیغ، سناریو، کارگردانیِ ادیتورِ ویدیو و کارگردانِ سه‌بعدی — باید سریع باشد",
  research: "پژوهشِ بازار و رقبا، ترندها، تحلیلِ تماس و تحلیلِ محصول — هرچه عمیق‌تر فکر کند بهتر است، کندی مهم نیست",
  code: "سایت‌ساز و ساختِ قالب و کد",
  vision: "خواندنِ عکس: تحلیلِ محصول، کنترلِ کیفیتِ فیلم‌برداری و ویرایشِ هوشمندِ عکس",
};
const VISION_ONLY = ["-vl", "vl:", "llava", "minicpm-v", "moondream"];

function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("fa-IR", { dateStyle: "short", timeStyle: "short" });
  } catch {
    return "—";
  }
}

/** ۸۱۶۴ ⇒ «۸٫۲» (گیگابایتِ ده‌دهی، همان‌طور که Ollama نشان می‌دهد) */
function gb(mb: number): string {
  return fa((mb / 1000).toFixed(1).replace(".", "٫"));
}

function problem(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const data = err.response?.data as { error?: unknown } | undefined;
    if (data && typeof data.error === "string") return data.error;
  }
  return errorMessage(err);
}

function suggested(kind: Kind, name: string): boolean {
  const low = name.toLowerCase();
  const isCoder = low.includes("coder") || low.includes("code");
  if (kind === "vision") return VISION_ONLY.some((h) => low.includes(h)) || low.includes("gemma3");
  if (kind === "code") return isCoder;
  return !VISION_ONLY.some((h) => low.includes(h)) && !isCoder && !low.includes("embed") && !low.includes("bge");
}

function Tick({ installed, online }: { installed: boolean | null; online: boolean }) {
  if (installed === true) return <Badge tone="ok">{online ? "نصب است" : "نصب بوده"}</Badge>;
  if (installed === false) return <Badge tone="bad">نصب نیست</Badge>;
  return <Badge>نامعلوم</Badge>;
}

function PullBar({ pull, onCancel, busy }: { pull: Pull; onCancel: (uid: string) => void; busy: boolean }) {
  const failed = pull.state === "FAILED";
  const done = pull.state === "COMPLETED";
  const tone = failed ? "var(--bad)" : done ? "var(--ok)" : pull.waiting_for_node ? "var(--warn)" : "var(--brand)";
  return (
    <li className="rounded-lg p-3" style={{ background: "var(--surface)", border: "1px solid var(--line)" }} data-testid={`pull-job-${pull.uid}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <b dir="ltr" style={{ color: "var(--text)" }}>
          {pull.tag}
        </b>
        <span className="flex items-center gap-2">
          {failed ? <Badge tone="bad">ناموفق</Badge> : done ? <Badge tone="ok">نصب شد</Badge> : pull.state === "CANCELLED" ? <Badge>لغو شد</Badge> : pull.state === "QUEUED" ? <Badge tone="warn">در صف</Badge> : pull.waiting_for_node ? <Badge tone="warn">متوقف (سرور خاموش)</Badge> : <Badge tone="brand">در حال دانلود</Badge>}
          {!pull.final && (
            <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => onCancel(pull.uid)} data-testid={`pull-cancel-${pull.uid}`}>
              لغو
            </Button>
          )}
        </span>
      </div>
      {!pull.final && (
        <div className="mt-2" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pull.percent)} aria-label={`دانلودِ ${pull.tag}`}>
          <div className="u-meter">
            <span style={{ width: `${Math.max(2, Math.min(100, pull.percent))}%`, background: tone, transition: "width .6s ease" }} />
          </div>
        </div>
      )}
      <p className="mt-2 text-sm leading-7" style={{ color: failed ? "var(--bad)" : pull.waiting_for_node ? "var(--warn)" : "var(--text-2)" }} data-testid={`pull-text-${pull.uid}`}>
        {pull.text}
      </p>
    </li>
  );
}

export default function AiPriorityCard() {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const dirtyRef = useRef(false);
  const [priority, setPriority] = useState<Order>("local_first");
  const [overrides, setOverrides] = useState<Record<Kind, "" | Order>>({ text: "", research: "", code: "", vision: "" });
  const [models, setModels] = useState<Record<Kind, string>>({ text: "", research: "", code: "", vision: "" });
  const [minutes, setMinutes] = useState("5");
  const [testKind, setTestKind] = useState<Kind>("text");
  const [results, setResults] = useState<{ local?: TestResult; metis?: TestResult }>({});

  const fill = useCallback((s: Snapshot) => {
    setSnap(s);
    setPriority(s.priority);
    setOverrides({ text: s.kinds.text.override, research: s.kinds.research.override, code: s.kinds.code.override, vision: s.kinds.vision.override });
    setModels({ text: s.kinds.text.selected_model, research: s.kinds.research.selected_model, code: s.kinds.code.selected_model, vision: s.kinds.vision.selected_model });
    setMinutes(String(s.breaker_minutes));
    setDirty(false);
    dirtyRef.current = false;
  }, []);

  /** وضعِ زنده را تازه می‌کند؛ پیش‌نویسِ ذخیره‌نشده را خراب نمی‌کند */
  const accept = useCallback(
    (s: Snapshot) => {
      if (dirtyRef.current) setSnap(s);
      else fill(s);
    },
    [fill],
  );

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<Snapshot>("/ai/priority/");
      accept(data);
      setError(null);
    } catch (err) {
      setError(problem(err));
    }
  }, [accept]);

  useEffect(() => {
    void load();
  }, [load]);

  // تا وقتی دانلودی در جریان است هر چند ثانیه درصد را تازه کن
  const activePulls = useMemo(() => (snap?.pulls ?? []).filter((p) => !p.final), [snap]);
  const hasActive = activePulls.length > 0;
  useEffect(() => {
    if (!hasActive) return undefined;
    const timer = window.setInterval(() => void load(), 4000);
    return () => window.clearInterval(timer);
  }, [hasActive, load]);

  const known = useMemo(() => snap?.local.known_models ?? [], [snap]);

  if (!snap) {
    return (
      <Card>
        <div className="py-8 text-center">{error ? <ErrorBox message={error} /> : <Spinner />}</div>
      </Card>
    );
  }

  const touch = () => {
    setDirty(true);
    dirtyRef.current = true;
    setNotice(null);
  };

  async function save() {
    setBusy("save");
    setError(null);
    setNotice(null);
    try {
      const { data } = await api.post<Snapshot>("/ai/priority/", {
        priority,
        priority_text: overrides.text,
        priority_research: overrides.research,
        priority_code: overrides.code,
        priority_vision: overrides.vision,
        model_text: models.text,
        model_research: models.research,
        model_code: models.code,
        model_vision: models.vision,
        breaker_minutes: Number(minutes),
      });
      fill(data);
      setNotice(data.message ?? "ذخیره شد.");
    } catch (err) {
      setError(problem(err));
    } finally {
      setBusy(null);
    }
  }

  async function test(provider: "local" | "metis") {
    setBusy(provider);
    setError(null);
    try {
      const { data } = await api.post<TestResult & { status: Snapshot }>("/ai/priority/test/", {
        provider,
        kind: provider === "local" ? testKind : "text",
      });
      setResults((r) => ({ ...r, [provider]: data }));
      accept(data.status);
    } catch (err) {
      setError(problem(err));
    } finally {
      setBusy(null);
    }
  }

  async function reset() {
    setBusy("reset");
    setError(null);
    try {
      const { data } = await api.post<Snapshot>("/ai/priority/reset/", {});
      accept(data);
      setNotice(data.message ?? null);
    } catch (err) {
      setError(problem(err));
    } finally {
      setBusy(null);
    }
  }

  async function startPull(tag: string, sizeMb: number) {
    const queued = !snap?.local.online;
    const ask =
      `مدلِ ${tag} حدود ${gb(sizeMb)} گیگابایت است و روی سرورِ پردازشِ شما دانلود می‌شود.` +
      (queued ? "\nسرورِ پردازش الان خاموش است؛ دانلود در صف می‌ماند و همین که کامپیوتر روشن شد خودکار شروع می‌شود." : "") +
      "\nشروع شود؟";
    if (!window.confirm(ask)) return;
    setBusy(`pull:${tag}`);
    setError(null);
    setNotice(null);
    try {
      const { data } = await api.post<Snapshot>("/ai/models/pull/", { tag });
      accept(data);
      setNotice(data.message ?? "دانلود در صف گذاشته شد.");
    } catch (err) {
      setError(problem(err));
    } finally {
      setBusy(null);
    }
  }

  async function cancelPull(uid: string) {
    setBusy(`cancel:${uid}`);
    setError(null);
    try {
      const { data } = await api.post<Snapshot>("/ai/models/pull/cancel/", { uid });
      accept(data);
      setNotice(data.message ?? "لغو شد.");
    } catch (err) {
      setError(problem(err));
    } finally {
      setBusy(null);
    }
  }

  const { local, metis } = snap;
  const metisBad = metis.last_error && ["no_credit", "bad_key", "rate_limit"].includes(metis.last_error.kind);
  const anyCircuit = local.circuit_minutes_left > 0 || metis.circuit_minutes_left > 0;
  const pullNodes = local.pull_nodes ?? [];
  const noPullNode = pullNodes.length === 0;
  const oldAgent = pullNodes.length > 0 && pullNodes.every((n) => !n.pull_ready);
  const oldAgentNode = oldAgent ? pullNodes[0] : null;
  const activeFor = (tag: string) => activePulls.find((p) => p.tag === tag);
  const catalog = snap.models ?? [];
  const missingCatalog = catalog.filter((m) => m.installed === false);

  /** دکمهٔ «دانلود مدل» (یا وضعِ دانلودِ جاری) برای یک برچسب */
  const pullControl = (tag: string, sizeMb: number, testId: string, pullable: boolean, installed: boolean | null) => {
    if (installed === true || !pullable) return null;
    const active = activeFor(tag);
    if (active) {
      return (
        <span className="text-xs" style={{ color: active.waiting_for_node ? "var(--warn)" : "var(--brand)" }} data-testid={`${testId}-active`}>
          {active.state === "QUEUED" ? "در صفِ دانلود" : active.waiting_for_node ? "دانلود متوقف (سرور خاموش)" : `در حال دانلود ${fa(Math.round(active.percent))}٪`}
        </span>
      );
    }
    const blocked = noPullNode || oldAgent;
    return (
      <Button
        type="button"
        variant="secondary"
        size="sm"
        disabled={busy !== null || blocked}
        title={noPullNode ? "هیچ سرورِ پردازشی ثبت نشده" : oldAgent ? "عاملِ سرورِ پردازش قدیمی است؛ Update.bat را روی آن کامپیوتر بزنید" : undefined}
        onClick={() => void startPull(tag, sizeMb)}
        data-testid={testId}
      >
        <Icon name="download" size={14} />
        {busy === `pull:${tag}` ? "…" : `${local.online ? "دانلود مدل" : "دانلود مدل (در صف)"} · ${gb(sizeMb)} گیگابایت`}
      </Button>
    );
  };

  return (
    <Card>
      <div className="space-y-5" data-testid="ai-priority">
        <div>
          <h2 className="text-lg font-bold" style={{ color: "var(--text)" }}>
            اولویتِ هوش مصنوعی: لوکال یا متیس
          </h2>
          <p className="mt-1 text-sm leading-7" style={{ color: "var(--text-3)" }}>
            هر کارِ هوش مصنوعی در NM می‌تواند هم روی <b>سرورِ پردازشِ خودتان (لوکال)</b> و هم با <b>متیس (API)</b> انجام شود.
            اینجا می‌گویید کدام اول باشد؛ اگر اولی در دسترس نبود (سرور خاموش، مدل نصب نیست، مهلت، اعتبار تمام، قطعِ اتصال) همان
            لحظه خودکار دومی جواب می‌دهد.
          </p>
        </div>

        <ErrorBox message={error} />
        {notice && <Alert tone="ok">{notice}</Alert>}

        {/* ── اولویت */}
        <div role="radiogroup" aria-label="اولویتِ هوش مصنوعی" className="grid gap-3 sm:grid-cols-2">
          {snap.orders.map((o) => {
            const on = priority === o.value;
            return (
              <label
                key={o.value}
                className="flex cursor-pointer items-start gap-3 rounded-xl p-4"
                style={{
                  background: on ? "var(--brand-soft)" : "var(--surface-2)",
                  border: `1.5px solid ${on ? "var(--brand)" : "var(--line)"}`,
                }}
              >
                <input
                  type="radio"
                  name="ai-priority"
                  className="mt-1.5"
                  checked={on}
                  data-testid={`prio-${o.value}`}
                  onChange={() => {
                    setPriority(o.value);
                    touch();
                  }}
                />
                <span>
                  <b style={{ color: "var(--text)" }}>{o.value === "local_first" ? "اول لوکال" : "اول متیس"}</b>
                  <span className="block text-sm leading-6" style={{ color: "var(--text-3)" }}>
                    {o.value === "local_first"
                      ? "روی سرورِ پردازشِ خودتان (بی‌هزینه، داده بیرون نمی‌رود)؛ نشد ⇒ متیس."
                      : "با متیس (سریع‌تر، هزینه دارد)؛ نشد ⇒ سرورِ پردازشِ خودتان."}
                  </span>
                </span>
              </label>
            );
          })}
        </div>

        {/* ── وضعِ زندهٔ هر مسیر */}
        <div className="grid gap-3 md:grid-cols-2">
          <div className="min-w-0 rounded-xl p-4" style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }} data-testid="status-local">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <b style={{ color: "var(--text)" }}>لوکال — سرورِ پردازش</b>
              {local.online ? <Badge tone="ok">آنلاین{local.node ? ` · ${local.node}` : ""}</Badge> : <Badge tone="warn">خاموش</Badge>}
            </div>
            {!local.online && (
              <div className="mt-2 space-y-1" data-testid="local-offline">
                <p className="text-sm leading-7" style={{ color: "var(--warn)" }}>
                  {local.reason || "سرورِ پردازش خاموش است."}
                </p>
                {local.known_models.length > 0 && (
                  <p className="text-xs leading-6" style={{ color: "var(--text-3)" }}>
                    فهرستِ مدل‌های زیر مالِ آخرین باری است که سرور روشن بود{local.models_reported_at ? ` (${when(local.models_reported_at)})` : ""}؛ ممکن
                    است عوض شده باشد. دانلود را می‌توانید همین حالا در صف بگذارید — همین که کامپیوتر روشن شد خودکار شروع می‌شود.
                  </p>
                )}
              </div>
            )}
            {local.online && local.models_stale && (
              <p className="mt-2 text-xs leading-6" style={{ color: "var(--text-3)" }}>
                فهرستِ مدل‌ها از آخرین باری است که Ollama روشن بود.
              </p>
            )}
            {oldAgent && oldAgentNode && (
              <div className="mt-3" data-testid="old-agent">
                <Alert tone="warn" title="عاملِ سرورِ پردازش قدیمی است">
                  دکمهٔ دانلودِ مدل کار نمی‌کند تا عامل به‌روز شود (نسخهٔ فعلی: <span dir="ltr">{oldAgentNode.agent || "نامعلوم"}</span>). روی کامپیوترِ سرورِ پردازش فایلِ{" "}
                  <b dir="ltr">Update.bat</b> را اجرا کنید (یا وقتی روشن شد، در «سرورهای پردازش» دکمهٔ «به‌روزرسانی» را بزنید)؛ بعد همین‌جا دانلود را بزنید.
                </Alert>
              </div>
            )}
            {noPullNode && (
              <p className="mt-2 text-sm" style={{ color: "var(--warn)" }}>
                هیچ سرورِ پردازشی با Ollama ثبت نشده؛ دانلودِ مدل ممکن نیست.
              </p>
            )}
            <ul className="mt-3 space-y-3 text-sm" style={{ color: "var(--text-2)" }}>
              {KINDS.map((k) => {
                const info = snap.kinds[k];
                return (
                  <li key={k} className="min-w-0" data-testid={`live-${k}`}>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="min-w-0">
                        {info.label}: <b dir="ltr">{info.model}</b>
                      </span>
                      <Tick installed={info.installed} online={local.online} />
                    </div>
                    {info.installed === false && info.substitute && (
                      <p className="mt-1 text-xs leading-6" style={{ color: "var(--warn)" }} data-testid={`substitute-${k}`}>
                        نصب نیست؛ فعلاً <b dir="ltr">{info.substitute}</b> جواب می‌دهد{info.substitute !== info.model ? " (جایگزینِ نصب‌شده)" : ""} — پیش از رفتن به متیس.
                      </p>
                    )}
                    {info.installed === false && !info.substitute && info.usable === false && (
                      <p className="mt-1 text-xs leading-6" style={{ color: "var(--bad)" }}>
                        هیچ مدلِ مناسبی برای این کار نصب نیست؛ کارها مستقیم به متیس می‌روند.
                      </p>
                    )}
                    {info.installed !== true && info.pullable && (
                      <div className="mt-1.5 flex flex-wrap items-center gap-2">{pullControl(info.model, info.size_mb, `pull-${k}`, info.pullable, info.installed)}</div>
                    )}
                  </li>
                );
              })}
            </ul>

            {(snap.pulls ?? []).length > 0 && (
              <div className="mt-4">
                <h4 className="mb-2 text-sm font-bold" style={{ color: "var(--text)" }}>
                  دانلودِ مدل
                </h4>
                <ul className="space-y-2" data-testid="pulls">
                  {(snap.pulls ?? []).map((p) => (
                    <PullBar key={p.uid} pull={p} onCancel={(uid) => void cancelPull(uid)} busy={busy !== null} />
                  ))}
                </ul>
              </div>
            )}

            {local.circuit_minutes_left > 0 && (
              <p className="mt-2 text-xs" style={{ color: "var(--warn)" }}>
                چند لحظه پیش خطا داد؛ {fa(local.circuit_minutes_left)} دقیقهٔ دیگر کنار گذاشته است.
              </p>
            )}
            {local.last_error && (
              <p className="mt-2 text-xs leading-6" style={{ color: "var(--text-3)" }}>
                آخرین خطا ({when(local.last_error.at)}): {local.last_error.message}
              </p>
            )}
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Select value={testKind} onChange={(e) => setTestKind(e.target.value as Kind)} aria-label="نوعِ آزمونِ لوکال" style={{ width: "auto", minWidth: 0 }}>
                {KINDS.map((k) => (
                  <option key={k} value={k}>
                    {snap.kinds[k].label}
                  </option>
                ))}
              </Select>
              <Button type="button" variant="secondary" size="sm" disabled={busy !== null} onClick={() => void test("local")} data-testid="test-local">
                <Icon name="refresh" size={14} />
                {busy === "local" ? "در حال آزمون…" : "آزمونِ لوکال"}
              </Button>
            </div>
            {results.local && (
              <div className="mt-3" data-testid="result-local">
                <Alert tone={results.local.ok ? "ok" : "bad"}>{results.local.message}</Alert>
              </div>
            )}
          </div>

          <div className="min-w-0 rounded-xl p-4" style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }} data-testid="status-metis">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <b style={{ color: "var(--text)" }}>متیس — API</b>
              {!metis.configured ? (
                <Badge tone="bad">تنظیم نشده</Badge>
              ) : metisBad ? (
                <Badge tone="bad">{metis.last_error!.kind === "no_credit" ? "اعتبار تمام شده (۴۰۲)" : metis.last_error!.kind === "bad_key" ? "کلید نامعتبر (۴۰۱/۴۰۳)" : "سهمیه تمام (۴۲۹)"}</Badge>
              ) : metis.last_error ? (
                <Badge tone="warn">آخرین درخواست خطا داد</Badge>
              ) : metis.last_ok_at ? (
                <Badge tone="ok">آماده</Badge>
              ) : (
                <Badge>تنظیم شده · آزمایش نشده</Badge>
              )}
            </div>
            <p className="mt-2 text-sm" style={{ color: "var(--text-2)" }}>
              سرویس: <span dir="ltr">{metis.host || "—"}</span>
            </p>
            <p className="text-sm" style={{ color: "var(--text-2)" }}>
              مدل: متن <b dir="ltr">{metis.model_text || "—"}</b> · بینایی <b dir="ltr">{metis.model_vision || "—"}</b>
            </p>
            {metis.last_ok_at && (
              <p className="mt-1 text-xs" style={{ color: "var(--text-3)" }}>
                آخرین جوابِ موفق: {when(metis.last_ok_at)}
              </p>
            )}
            {metis.last_error && (
              <p className="mt-2 text-sm leading-6" style={{ color: metisBad ? "var(--bad)" : "var(--warn)" }} data-testid="metis-last-error">
                آخرین خطا{metis.last_error.at ? ` (${when(metis.last_error.at)})` : ""}: {metis.last_error.message}
                {metis.last_error.from_history && <span className="text-xs" style={{ color: "var(--text-3)" }}> — از دفترِ درخواست‌ها</span>}
              </p>
            )}
            {metis.circuit_minutes_left > 0 && (
              <p className="mt-1 text-xs" style={{ color: "var(--warn)" }}>
                تا {fa(metis.circuit_minutes_left)} دقیقهٔ دیگر کنار گذاشته است (کارها مستقیم سراغِ لوکال می‌روند).
              </p>
            )}
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Button type="button" variant="secondary" size="sm" disabled={busy !== null || !metis.configured} onClick={() => void test("metis")} data-testid="test-metis">
                <Icon name="refresh" size={14} />
                {busy === "metis" ? "در حال آزمون…" : "آزمونِ متیس"}
              </Button>
              <span className="text-xs" style={{ color: "var(--text-3)" }}>
                فقط با زدنِ این دکمه یک درخواستِ بسیار کوچک (۴ توکن) به متیس می‌رود.
              </span>
            </div>
            {results.metis && (
              <div className="mt-3" data-testid="result-metis">
                <Alert tone={results.metis.ok ? "ok" : "bad"}>{results.metis.message}</Alert>
              </div>
            )}
          </div>
        </div>

        {/* ── مدل و اولویتِ هر نوعِ کار */}
        <div>
          <h3 className="mb-2 text-base font-bold" style={{ color: "var(--text)" }}>
            مدلِ لوکال و اولویتِ هر نوعِ کار
          </h3>
          <div className="space-y-3">
            {KINDS.map((k) => {
              const info = snap.kinds[k];
              const mine = known.filter((m) => suggested(k, m));
              const others = known.filter((m) => !suggested(k, m));
              const downloadable = missingCatalog.filter((m) => suggested(k, m.tag) && !known.includes(m.tag));
              const picked = models[k];
              const orphan = picked && !known.includes(picked) && !downloadable.some((m) => m.tag === picked);
              const effectiveFirst = overrides[k] ? (overrides[k] === "metis_first" ? "metis" : "local") : priority === "metis_first" ? "metis" : "local";
              return (
                <div key={k} className="rounded-xl p-4" style={{ border: "1px solid var(--line)" }} data-testid={`kind-${k}`}>
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <b style={{ color: "var(--text)" }}>{info.label}</b>
                    <span className="text-xs" style={{ color: "var(--text-3)" }}>
                      ترتیب: {effectiveFirst === "local" ? "لوکال ← متیس" : "متیس ← لوکال"}
                    </span>
                  </div>
                  <p className="mt-0.5 text-xs leading-6" style={{ color: "var(--text-3)" }}>
                    {KIND_HINT[k]}
                  </p>
                  <div className="mt-3 grid gap-3 sm:grid-cols-2">
                    <label className="block">
                      <span className="mb-1 block text-xs font-medium" style={{ color: "var(--text-2)" }}>
                        مدلِ لوکال
                      </span>
                      <Select
                        dir="ltr"
                        value={picked}
                        data-testid={`model-${k}`}
                        onChange={(e) => {
                          setModels((m) => ({ ...m, [k]: e.target.value }));
                          touch();
                        }}
                      >
                        <option value="">{`پیش‌فرض (${info.default_model})`}</option>
                        {orphan && <option value={picked}>{`${picked} (روی سرور گزارش نشده)`}</option>}
                        {mine.length > 0 && (
                          <optgroup label="پیشنهادی برای این کار">
                            {mine.map((m) => (
                              <option key={m} value={m}>
                                {m}
                              </option>
                            ))}
                          </optgroup>
                        )}
                        {others.length > 0 && (
                          <optgroup label="بقیهٔ مدل‌های سرور">
                            {others.map((m) => (
                              <option key={m} value={m}>
                                {m}
                              </option>
                            ))}
                          </optgroup>
                        )}
                        {downloadable.length > 0 && (
                          <optgroup label="نصب نیست — قابل دانلود">
                            {downloadable.map((m) => (
                              <option key={m.tag} value={m.tag}>
                                {`${m.tag} — ${gb(m.size_mb)} GB`}
                              </option>
                            ))}
                          </optgroup>
                        )}
                      </Select>
                    </label>
                    <label className="block">
                      <span className="mb-1 block text-xs font-medium" style={{ color: "var(--text-2)" }}>
                        اولویتِ این نوع
                      </span>
                      <Select
                        value={overrides[k]}
                        data-testid={`override-${k}`}
                        onChange={(e) => {
                          setOverrides((o) => ({ ...o, [k]: e.target.value as "" | Order }));
                          touch();
                        }}
                      >
                        <option value="">مثلِ تنظیمِ کلی</option>
                        <option value="local_first">اول لوکال</option>
                        <option value="metis_first">اول متیس</option>
                      </Select>
                    </label>
                  </div>
                  {known.length === 0 && (
                    <p className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
                      هنوز هیچ سرورِ پردازشی فهرستِ مدل‌هایش را نفرستاده؛ وقتی روشن شد فهرست اینجا پر می‌شود.
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        <details>
          <summary className="cursor-pointer text-sm" style={{ color: "var(--text-2)" }}>
            پیشرفته: مدتِ کنار گذاشتنِ مسیرِ خراب
          </summary>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
              <input
                type="number"
                min={1}
                max={120}
                value={minutes}
                className="u-input"
                style={{ width: 90 }}
                dir="ltr"
                onChange={(e) => {
                  setMinutes(e.target.value);
                  touch();
                }}
              />
              دقیقه
            </label>
            <span className="text-xs leading-6" style={{ color: "var(--text-3)" }}>
              مسیری که تازه خطا داده (مهلت، ۴۰۲، ۴۰۱، ۵xx، قطعِ اتصال) این‌قدر کنار می‌ماند تا هر درخواست منتظرِ مهلتش نماند.
            </span>
          </div>
        </details>

        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" disabled={busy !== null || !dirty} onClick={() => void save()} data-testid="save-priority">
            {busy === "save" ? "…" : "ذخیره"}
          </Button>
          {anyCircuit && (
            <Button type="button" variant="ghost" size="sm" disabled={busy !== null} onClick={() => void reset()}>
              آزاد کردنِ مسیرهای کنارگذاشته
            </Button>
          )}
          {dirty && (
            <span className="text-xs" style={{ color: "var(--warn)" }}>
              تغییرها هنوز ذخیره نشده است.
            </span>
          )}
        </div>

        {/* ── آخرین پاسخ‌ها */}
        {snap.recent.length > 0 && (
          <details>
            <summary className="cursor-pointer text-sm" style={{ color: "var(--text-2)" }}>
              آخرین پاسخ‌ها را چه کسی داد؟
            </summary>
            <ul className="mt-2 space-y-1.5 text-xs leading-6" data-testid="ai-recent" style={{ color: "var(--text-2)" }}>
              {snap.recent.map((r) => (
                <li key={r.id}>
                  {when(r.at)} · <span dir="ltr">{r.prompt_id}</span> · <b>{r.label || (r.status === "OK" ? "—" : "شکست")}</b>
                  {r.reason && <span style={{ color: "var(--warn)" }}> · {r.fell_back ? "چون " : ""}{r.reason}</span>}
                  {r.status !== "OK" && r.error && <span style={{ color: "var(--bad)" }}> · {r.error}</span>}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </Card>
  );
}
