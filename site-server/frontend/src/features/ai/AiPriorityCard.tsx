import { useCallback, useEffect, useMemo, useState } from "react";
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
 * وضعِ زنده فقط از دیتابیس خوانده می‌شود (بی‌درخواست به متیس یا گره)؛ دکمهٔ «آزمون» یک درخواستِ کوچکِ واقعی می‌فرستد.
 */

type Order = "local_first" | "metis_first";
type Kind = "text" | "code" | "vision";
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
  ready: boolean;
  reason: string;
  metis_model: string;
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
  recent: Recent[];
  message?: string;
};

type TestResult = { ok: boolean; provider: "local" | "metis"; kind: string; message: string };

const KINDS: Kind[] = ["text", "code", "vision"];
const KIND_HINT: Record<Kind, string> = {
  text: "کپشن، تحلیل، پژوهش، چتِ فروش، سناریو، کارگردانیِ ادیتورِ ویدیو و کارگردانِ سه‌بعدی",
  code: "سایت‌ساز و ساختِ قالب و کد",
  vision: "خواندنِ عکس: تحلیلِ محصول، کنترلِ کیفیتِ فیلم‌برداری و ویرایشِ هوشمندِ عکس",
};
const VISION_HINTS = ["-vl", "vl:", "vision", "llava", "gemma3", "minicpm-v", "moondream"];

function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("fa-IR", { dateStyle: "short", timeStyle: "short" });
  } catch {
    return "—";
  }
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
  const isVision = VISION_HINTS.some((h) => low.includes(h));
  if (kind === "vision") return isVision;
  if (kind === "code") return low.includes("coder") || low.includes("code");
  return !isVision && !low.includes("coder") && !low.includes("embed") && !low.includes("bge");
}

function Tick({ installed, online }: { installed: boolean | null; online: boolean }) {
  if (installed === true) return <Badge tone="ok">{online ? "نصب است" : "نصب بوده"}</Badge>;
  if (installed === false) return <Badge tone="bad">نصب نیست</Badge>;
  return <Badge>نامعلوم</Badge>;
}

export default function AiPriorityCard() {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<"save" | "local" | "metis" | "reset" | null>(null);
  const [dirty, setDirty] = useState(false);
  const [priority, setPriority] = useState<Order>("local_first");
  const [overrides, setOverrides] = useState<Record<Kind, "" | Order>>({ text: "", code: "", vision: "" });
  const [models, setModels] = useState<Record<Kind, string>>({ text: "", code: "", vision: "" });
  const [minutes, setMinutes] = useState("5");
  const [testKind, setTestKind] = useState<Kind>("text");
  const [results, setResults] = useState<{ local?: TestResult; metis?: TestResult }>({});

  const fill = useCallback((s: Snapshot) => {
    setSnap(s);
    setPriority(s.priority);
    setOverrides({ text: s.kinds.text.override, code: s.kinds.code.override, vision: s.kinds.vision.override });
    setModels({ text: s.kinds.text.selected_model, code: s.kinds.code.selected_model, vision: s.kinds.vision.selected_model });
    setMinutes(String(s.breaker_minutes));
    setDirty(false);
  }, []);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<Snapshot>("/ai/priority/");
      fill(data);
      setError(null);
    } catch (err) {
      setError(problem(err));
    }
  }, [fill]);

  useEffect(() => {
    void load();
  }, [load]);

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
        priority_code: overrides.code,
        priority_vision: overrides.vision,
        model_text: models.text,
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
      // وضعِ زنده تازه شد؛ پیش‌نویسِ ذخیره‌نشده را خراب نکن
      if (!dirty) fill(data.status);
      else setSnap(data.status);
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
      if (!dirty) fill(data);
      else setSnap(data);
      setNotice(data.message ?? null);
    } catch (err) {
      setError(problem(err));
    } finally {
      setBusy(null);
    }
  }

  const { local, metis } = snap;
  const metisBad = metis.last_error && ["no_credit", "bad_key", "rate_limit"].includes(metis.last_error.kind);
  const anyCircuit = local.circuit_minutes_left > 0 || metis.circuit_minutes_left > 0;

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
          <div className="rounded-xl p-4" style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }} data-testid="status-local">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <b style={{ color: "var(--text)" }}>لوکال — سرورِ پردازش</b>
              {local.online ? <Badge tone="ok">آنلاین{local.node ? ` · ${local.node}` : ""}</Badge> : <Badge tone="warn">خاموش</Badge>}
            </div>
            {!local.online && local.reason && (
              <p className="mt-2 text-sm" style={{ color: "var(--text-2)" }}>
                {local.reason}
              </p>
            )}
            <ul className="mt-3 space-y-1.5 text-sm" style={{ color: "var(--text-2)" }}>
              {KINDS.map((k) => (
                <li key={k} className="flex flex-wrap items-center justify-between gap-2">
                  <span>
                    {snap.kinds[k].label}: <b dir="ltr">{snap.kinds[k].model}</b>
                  </span>
                  <Tick installed={snap.kinds[k].installed} online={local.online} />
                </li>
              ))}
            </ul>
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

          <div className="rounded-xl p-4" style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }} data-testid="status-metis">
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
              const picked = models[k];
              const orphan = picked && !known.includes(picked);
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
                  {r.fell_back && r.reason && <span style={{ color: "var(--warn)" }}> · چون {r.reason}</span>}
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
