import { useCallback, useEffect, useState } from "react";

import { api, errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import { Alert, Badge, Button, Card, ErrorBox, Meter, SectionTitle, Spinner, fa } from "../../components/ui";
import { useAuthAudio } from "./useAuthAudio";

/**
 * «مدل‌های صدا» of one processing node: on / off, «تست», installed / downloading / missing, «دانلود» — no command line.
 * Off = the site never sends that kind of job to the node, the node stops the engine at once and never starts it.
 */

type Test = {
  id: number;
  model: string;
  label: string;
  status: "QUEUED" | "RUNNING" | "DONE" | "FAILED";
  status_label: string;
  result: {
    load_s?: number; gen_s?: number; audio_s?: number; rtf?: number; vram_peak_mb?: number; vram_base_mb?: number;
    vram_total_mb?: number; ram_peak_used_mb?: number; ram_total_mb?: number; gpu_util_peak?: number;
    gpu_util_avg?: number; cold?: boolean;
  };
  verdict: "" | "light" | "medium" | "heavy";
  verdict_label: string;
  meaning: string;
  error: string;
  waiting: string;
  progress: number | null;
  message: string;
  has_audio: boolean;
  audio: string | null;
  finished_at: string | null;
};

type Row = {
  key: "speech" | "clone" | "sfx" | "music";
  label: string;
  what: string;
  seconds: string;
  engine_label: string;
  license: string;
  package: string;
  enabled: boolean;
  installed: boolean | null;
  missing_mb: number | null;
  total_mb: number | null;
  downloading: boolean;
  running: boolean;
  last_test: Test | null;
};

type Pkg = { package: string; title: string; installed: boolean; optional: boolean; missing_mb: number; total_mb: number;
  in_comfyui: number };

type CardData = {
  node: { id: number; name: string; online: boolean; agent: string; agent_ok: boolean; gpu: string };
  settings: Record<"speech" | "clone" | "sfx" | "music", boolean> & { idle_min: number };
  rows: Row[];
  packages: Pkg[];
  download: { running: boolean; percent: number | null; error: string; queued: string[];
    progress: { current?: string; items_done?: number; items_total?: number } | null };
  preflight: { key: string; ok: boolean | null; detail: string }[];
};

const VERDICT_TONE = { light: "ok", medium: "warn", heavy: "bad" } as const;

function gbText(mb: number | null | undefined) {
  if (!mb) return "—";
  return mb >= 1024 ? `${fa((mb / 1024).toFixed(1))} گیگ` : `${fa(Math.round(mb))} مگ`;
}

function TestLine({ t }: { t: Test }) {
  const r = t.result || {};
  if (t.status === "QUEUED" || t.status === "RUNNING") {
    return (
      <div className="flex items-center gap-2 text-xs" style={{ color: "var(--text-3)" }}>
        <Spinner size={14} /> {t.status === "QUEUED" ? t.waiting : t.message || "در حالِ تست…"}
      </div>
    );
  }
  if (t.status === "FAILED") return <div className="text-xs" style={{ color: "var(--bad)" }}>{t.error}</div>;
  return (
    <div className="flex flex-col gap-1 text-xs" style={{ color: "var(--text-2)" }} data-testid="bench-result">
      <div className="flex flex-wrap items-center gap-2">
        {t.verdict && <Badge tone={VERDICT_TONE[t.verdict]}>{t.verdict_label}</Badge>}
        <span>بالا آمدنِ مدل: {fa(Math.round(r.load_s ?? 0))} ث{r.cold === false ? " (گرم)" : ""}</span>
        <span>ساخت: {fa((r.gen_s ?? 0).toFixed(1))} ث برای {fa((r.audio_s ?? 0).toFixed(1))} ث صدا</span>
        <span dir="ltr">RTF {r.rtf ?? "—"}</span>
        <span>VRAM: {r.vram_peak_mb ? `${fa(Math.round(r.vram_peak_mb / 102.4) / 10)} از ${fa(Math.round((r.vram_total_mb ?? 0) / 1024))} گیگ` : "—"}</span>
        <span>RAM: {r.ram_peak_used_mb ? `${fa(Math.round(r.ram_peak_used_mb / 102.4) / 10)} گیگ` : "—"}</span>
        <span>GPU: {r.gpu_util_peak != null ? `${fa(Math.round(r.gpu_util_peak))}٪` : "—"}</span>
      </div>
      {t.meaning && <div style={{ color: "var(--text-3)" }}>{t.meaning}</div>}
    </div>
  );
}

export default function NodeAudioCard({ nodeId }: { nodeId: number }) {
  const [data, setData] = useState<CardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [src, setSrc] = useState<Record<string, string>>({});
  const audio = useAuthAudio();
  const url = `/compute/nodes/${nodeId}/audio/`;

  const load = useCallback(async () => {
    try {
      const { data: d } = await api.get<CardData>(url);
      setData(d);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [url]);

  useEffect(() => {
    void load();
  }, [load]);

  // while a test runs or a download goes on, keep the card fresh
  const live = Boolean(
    data && (data.download.running || data.download.queued.length || data.rows.some((r) => r.last_test && ["QUEUED", "RUNNING"].includes(r.last_test.status))),
  );
  useEffect(() => {
    if (!live) return;
    const id = window.setInterval(() => void load(), 4000);
    return () => window.clearInterval(id);
  }, [live, load]);

  const patch = async (body: Record<string, unknown>, tag: string) => {
    setBusy(tag);
    setError(null);
    try {
      const { data: d } = await api.patch<CardData>(url, body);
      setData(d);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const test = async (model: string) => {
    setBusy(`test-${model}`);
    setError(null);
    try {
      await api.post(`${url}test/`, { model });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const download = async (packages: string[]) => {
    setBusy(`dl-${packages.join(",")}`);
    setError(null);
    try {
      const { data: d } = await api.post<CardData>(`/compute/nodes/${nodeId}/models/download/`, { packages });
      setData(d);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const listen = async (t: Test) => {
    if (!t.audio) return;
    try {
      const u = await audio.load(t.audio.replace(/^\/api\/v1/, ""));
      setSrc((s) => ({ ...s, [t.id]: u }));
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  if (!data) {
    return (
      <Card>
        <SectionTitle>مدل‌های صدا</SectionTitle>
        <ErrorBox message={error} />
        {!error && <Spinner />}
      </Card>
    );
  }

  const optional = data.packages.filter((p) => p.optional || !p.installed);
  const queued = new Set(data.download.queued);
  // an agent older than 1.8 cannot run «تست» / «دانلود»: the warning above says what to do, the buttons wait for it
  const old = !data.node.agent_ok && Boolean(data.node.agent);

  return (
    <Card>
      <SectionTitle>
        <span className="flex flex-wrap items-center gap-2" data-testid="node-audio-card">
          <Icon name="mic" size={16} /> مدل‌های صدا — {data.node.name}
          <Badge tone={data.node.online ? "ok" : "neutral"}>{data.node.online ? "آنلاین" : "خاموش"}</Badge>
        </span>
      </SectionTitle>
      <ErrorBox message={error} />
      {!data.node.agent_ok && data.node.agent && (
        <Alert tone="warn">
          عاملِ این سرور نسخهٔ {data.node.agent} است؛ این بخش از نسخهٔ ۱٫۸ کار می‌کند. روی آن کامپیوتر پوشهٔ پردازش را به‌روز
          کنید (git pull) و START.bat را دوباره باز کنید.
        </Alert>
      )}
      {data.download.running && (
        <div className="mb-3 flex flex-col gap-1 text-sm" style={{ color: "var(--text-2)" }} data-testid="download-progress">
          <span className="flex items-center gap-2">
            <Spinner size={14} /> در حالِ دانلودِ مدل‌ها روی سرور
            {data.download.percent != null && ` — ${fa(Math.round(data.download.percent))}٪`}
            {data.download.progress?.current && <span dir="ltr" className="text-xs">{data.download.progress.current}</span>}
          </span>
          <Meter used={Math.round(data.download.percent ?? 0)} total={100} />
        </div>
      )}
      {data.download.error && <Alert tone="warn">{data.download.error}</Alert>}

      <div className="flex flex-col gap-3">
        {data.rows.map((r) => {
          const state = r.installed === null ? "نامعلوم" : r.installed ? "نصب است" : r.downloading ? "در حالِ دانلود" : "نصب نیست";
          const tone = r.installed ? "ok" : r.downloading ? "info" : "warn";
          return (
            <div key={r.key} className="flex flex-col gap-2 rounded-xl p-3" style={{ border: "1px solid var(--line)" }}
              data-testid={`audio-row-${r.key}`}>
              <div className="flex flex-wrap items-center gap-2">
                <label className="flex items-center gap-2 font-bold" style={{ color: "var(--text)" }}>
                  <input type="checkbox" checked={r.enabled} disabled={busy !== null}
                    onChange={(e) => void patch({ [r.key]: e.target.checked }, r.key)} aria-label={`${r.label} فعال`} />
                  {r.label}
                </label>
                <Badge tone={r.enabled ? "ok" : "neutral"}>{r.enabled ? "فعال" : "غیرفعال"}</Badge>
                <Badge tone={tone}>{state}</Badge>
                {r.running && <Badge tone="brand">الان بالاست</Badge>}
                <span className="text-xs" style={{ color: "var(--text-3)" }}>
                  {r.what} · {r.license}{r.total_mb ? ` · ${gbText(r.total_mb)}` : ""}
                </span>
                <span className="flex-1" />
                {r.installed === false && !r.downloading && (
                  <Button size="sm" variant="secondary" disabled={busy !== null || old || queued.has(r.package)}
                    onClick={() => void download([r.package])}>
                    <Icon name="download" size={13} /> {queued.has(r.package) ? "در صفِ دانلود" : `دانلود (${gbText(r.missing_mb)})`}
                  </Button>
                )}
                <Button size="sm" disabled={busy !== null || old || !r.enabled || r.installed === false}
                  onClick={() => void test(r.key)} title={`کارِ استاندارد: ${r.seconds}`}>
                  <Icon name="cpu" size={13} /> {busy === `test-${r.key}` ? "…" : "تست"}
                </Button>
              </div>
              {!r.enabled && (
                <div className="text-xs" style={{ color: "var(--text-3)" }}>
                  خاموش: سایت این نوع کار را به این سرور نمی‌فرستد و مدل حافظه نمی‌گیرد.
                  {r.key === "speech" && " نریشن با گویندهٔ بعدیِ فهرست (Edge یا Piper) خوانده می‌شود."}
                  {r.key === "sfx" && " صدای محیطِ ویدیوها از کتابخانه و صدای ساخته‌شده با کد می‌آید."}
                  {r.key === "music" && " موسیقی فقط از کتابخانه یا فایلِ خودِ فروشگاه."}
                  {r.key === "clone" && " صدای کلون‌شده نه ساخته می‌شود نه می‌خواند (پیامِ روشن به کاربر)."}
                </div>
              )}
              {r.last_test && (
                <div className="flex flex-col gap-1">
                  <TestLine t={r.last_test} />
                  {r.last_test.has_audio && (src[r.last_test.id] ? (
                    <audio controls src={src[r.last_test.id]} className="h-9 w-full max-w-md" />
                  ) : (
                    <Button size="sm" variant="ghost" onClick={() => void listen(r.last_test as Test)}>
                      <Icon name="play" size={13} /> شنیدنِ خروجیِ تست
                    </Button>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
        <span>خالی کردنِ حافظهٔ کارتِ گرافیک بعد از</span>
        <select className="u-input w-28" value={data.settings.idle_min} aria-label="خالی کردن بعد از"
          onChange={(e) => void patch({ idle_min: Number(e.target.value) }, "idle")}>
          {[5, 10, 15, 30, 60].map((m) => <option key={m} value={m}>{fa(m)} دقیقه</option>)}
        </select>
        <span className="text-xs" style={{ color: "var(--text-3)" }}>بیکاری (پیش‌فرض ۱۵).</span>
      </div>

      {optional.length > 0 && (
        <div className="mt-4">
          <div className="mb-1 text-sm font-bold" style={{ color: "var(--text)" }}>بسته‌های دیگر</div>
          <div className="flex flex-col gap-1">
            {optional.map((p) => (
              <div key={p.package} className="flex flex-wrap items-center gap-2 text-sm" data-testid={`pkg-${p.package}`}>
                <code dir="ltr">{p.package}</code>
                <Badge tone={p.installed ? "ok" : "neutral"}>{p.installed ? "دارد" : `دانلود می‌شود: ${gbText(p.missing_mb)}`}</Badge>
                {p.optional && <Badge tone="info">اختیاری</Badge>}
                {p.in_comfyui > 0 && <Badge tone="ok">{fa(p.in_comfyui)} فایل در ComfyUI بود</Badge>}
                <span className="text-xs" style={{ color: "var(--text-3)" }}>{p.title}</span>
                {!p.installed && (
                  <Button size="sm" variant="secondary" disabled={busy !== null || old || queued.has(p.package) || data.download.running}
                    onClick={() => void download([p.package])}>
                    <Icon name="download" size={13} /> {queued.has(p.package) ? "در صف" : "دانلود"}
                  </Button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {data.preflight.length > 0 && (
        <details className="mt-4 text-xs" style={{ color: "var(--text-3)" }}>
          <summary className="cursor-pointer">چک‌لیستِ آخرین روشن شدن (START.bat)</summary>
          <ul className="mt-1 flex flex-col gap-0.5" dir="ltr">
            {data.preflight.map((p) => (
              <li key={p.key}>
                {p.ok === true ? "✓" : p.ok === false ? "✗" : "…"} {p.key}: {p.detail}
              </li>
            ))}
          </ul>
        </details>
      )}
    </Card>
  );
}

/** Every node's «مدل‌های صدا» on the processing-servers page (anchor #voice-models for links from «صدا»). */
export function NodeAudioSection({ nodes }: { nodes: { id: number; enabled: boolean }[] }) {
  const shown = nodes.filter((n) => n.enabled);
  const count = shown.length;
  useEffect(() => {
    if (count && window.location.hash === "#voice-models") {
      window.setTimeout(() => document.getElementById("voice-models")?.scrollIntoView({ behavior: "smooth" }), 300);
    }
  }, [count]);
  if (!shown.length) return null;
  return (
    <div id="voice-models" className="flex flex-col gap-4">
      {shown.map((n) => <NodeAudioCard key={n.id} nodeId={n.id} />)}
    </div>
  );
}
