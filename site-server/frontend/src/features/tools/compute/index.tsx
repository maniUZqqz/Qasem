import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api, errorMessage } from "../../../api/client";
import Icon, { type IconName } from "../../../components/Icon";
import {
  Alert,
  Badge,
  Button,
  Card,
  ErrorBox,
  Field,
  Input,
  Meter,
  PageHeader,
  SectionTitle,
  Select,
  Spinner,
  Table,
  TextArea,
  fa,
} from "../../../components/ui";

/**
 * سرورهای پردازش (GPU، بی‌IP ثابت).
 *
 * این سرورها از بیرون قابلِ دسترس نیستند؛ خودشان با توکن به همین سایت وصل
 * می‌شوند، کار می‌گیرند و خروجی را پس می‌فرستند (apps.compute). اگر دو تا
 * باشند هر کار فقط به یکی می‌رسد و کارِ تکراری دوباره ساخته نمی‌شود.
 *
 * سه چیزی که مالک پای دستگاهِ GPU نمی‌فهمید و این صفحه باید روشن بگوید:
 *   ۱. وصل هست یا نه (وضعیت + آخرین تماس + کدام سرویس‌هایش روشن است)
 *   ۲. تصویر و ویدیو الان کجا ساخته می‌شود و چطور عوضش کند («مسیرِ پردازش»)
 *   ۳. اگر خطا داد، متنِ خطا همین‌جا دیده شود («لاگ» هر سرور)
 */

const SERVICE_KEYS = ["comfyui", "comfy_bridge", "photo", "video", "voice", "ollama", "blender"] as const;
type ServiceKey = (typeof SERVICE_KEYS)[number];
const SERVICE_LABELS: Record<ServiceKey, string> = {
  comfyui: "ComfyUI",
  comfy_bridge: "پلِ ComfyUI",
  photo: "عکس",
  video: "ویدیو",
  voice: "صدا",
  ollama: "Ollama",
  blender: "Blender",
};

/**
 * سرویس‌هایی که عاملِ روی سرور بلد است روشن/خاموش کند (SERVICE_KEYS در apps/compute/api.py).
 * کلیدِ «خواسته» با کلیدِ گزارشِ واقعی یکی نیست: رندرِ سه‌بعدی را عامل با worker3d می‌گیرد
 * ولی حضورش را با blender گزارش می‌کند.
 */
const MANAGED_KEYS = ["ollama", "comfyui", "voice", "photo", "video", "worker3d"] as const;
type ManagedKey = (typeof MANAGED_KEYS)[number];
/** آن‌چه خودِ سرور دربارهٔ هر سرویس می‌گوید: عامل روشنش کرده / کسی بیرون از عامل روشنش کرده / خاموش است */
type ManagedState = "agent" | "external" | "off";
const MANAGED_SERVICES: { key: ManagedKey; actual: ServiceKey; label: string; sub: string }[] = [
  { key: "ollama", actual: "ollama", label: "Ollama", sub: "مدل‌های متن/بینایی" },
  { key: "comfyui", actual: "comfyui", label: "ComfyUI", sub: "تصویر FLUX و ویدیو Wan" },
  { key: "voice", actual: "voice", label: "صدا", sub: "PersianAiKit Voice" },
  { key: "photo", actual: "photo", label: "ویرایشگرِ عکس", sub: "PersianAiKit Photo" },
  { key: "video", actual: "video", label: "ویرایشگرِ ویدیو", sub: "PersianAiKit Video" },
  { key: "worker3d", actual: "blender", label: "رندرِ سه‌بعدی", sub: "Blender" },
];

/** خواستهٔ پنل برای هر سرویس؛ کلیدِ غایب = «دست نزن» (پیش‌فرضِ خودِ سرور) */
type Desired = Partial<Record<ManagedKey, boolean>>;
/** از آخرین heartbeat: حافظهٔ دستگاه و کارتِ گرافیک (مگابایت)؛ هر کدام نباشد، گزارش نشده */
type Resources = { ram_total_mb?: number; ram_free_mb?: number; vram_used_mb?: number; vram_total_mb?: number };

type Node = {
  id: number;
  name: string;
  enabled: boolean;
  online: boolean;
  last_seen: string | null;
  capabilities: Record<string, unknown>;
  stats: Record<string, { seconds: number; n: number }>;
  jobs_done: number;
  token: string;
  notes: string;
  agent: string | null;
  hostname: string | null;
  gpu: string | null;
  /** از آخرین heartbeat؛ وقتی سرور خاموش است، آخرین گزارشِ خودش است */
  services: Partial<Record<ServiceKey, boolean>>;
  /** آخرین خطِ ERROR/CRITICAL که خودِ سرور فرستاده؛ خالی = خطایی نیست */
  last_error: string;
  /** چه سرویس‌هایی روشن/خاموش باشد (POST /compute/nodes/<id>/desired/)؛ عامل در heartbeat بعدی می‌گیرد */
  desired: Desired;
  /** وقتی کاری بیاید که سرویسش روشن نیست، عامل خودش موتورِ دیگر را خالی و سرویسِ لازم را روشن کند */
  auto_switch: boolean;
  /** گزارشِ خودِ سرور: هر سرویس را عامل روشن کرده، چیزی بیرونی، یا خاموش است (کلیدها همان MANAGED_KEYS) */
  managed: Partial<Record<string, ManagedState>>;
  resources: Resources;
};

/** پاسخِ POST …/desired/ همان ردیفِ سرور است ولی بی‌توکن؛ روی ردیفِ موجود merge می‌شود */
type NodeView = Omit<Node, "token">;

type LogLine = { level: string; message: string; ts: string | null };

/** GET/POST /compute/settings/ — مسیرِ تصویر/ویدیو + کلیدِ ثبتِ سرورِ تازه (یک ردیف در بک‌اند) */
type RouteSettings = {
  image_video_node: string;
  updated_at: string | null;
  nodes: string[];
  /** کلیدی که START.bat روی کامپیوترِ گرافیکی می‌خواهد تا خودش را ثبت کند (POST /compute/enroll/) */
  enroll_key: string;
  /** نشانیِ کاملِ همین سایت؛ کامپیوتر به آن وصل می‌شود */
  site: string;
};

/** همان شکلِ /ai/status/ که صفحهٔ «موتورهای هوش مصنوعی» می‌خواند */
type AiCapability = {
  capability: string;
  label: string;
  provider: string;
  kind: string;
  model: string;
  local: boolean | null;
};
type AiStatus = { capabilities: AiCapability[] };

type Output = { name: string; path: string; size: number; media: string; url: string };

type Job = {
  uid: string;
  kind: string;
  state: string;
  state_label: string;
  progress: number;
  message: string;
  error: string;
  node: string | null;
  origin: string;
  attempts: number;
  created: string;
  finished: string | null;
  final: boolean;
  dedupe: boolean;
  outputs: Output[];
};

type Summary = {
  nodes: number;
  online: number;
  capabilities: Record<string, number>;
  queued: number;
  running: number;
};

type Tone = "ok" | "bad" | "warn" | "info" | "neutral";

/** کلیدهایی که جای دیگری نشان داده می‌شوند (زیرِ نام یا در ستونِ سرویس‌ها) و نباید دوباره Badge شوند */
const HIDDEN_CAPS = new Set<string>([
  "hostname", "version", "agent", "platform", "comfy_nodes", "gpu", "slots", "ollama_models", "comfy_profiles",
  // این‌ها در کشوی «سرویس‌ها» و نوارهای حافظه نشان داده می‌شوند
  "managed", "ram_total_mb", "ram_free_mb", "vram_used_mb", "vram_total_mb",
  ...SERVICE_KEYS,
  ...MANAGED_KEYS,
]);

const KINDS: { value: string; label: string; example: string }[] = [
  { value: "echo", label: "echo — فقط آزمونِ اتصال", example: '{"sleep": 2}' },
  {
    value: "comfy.profile",
    label: "comfy.profile — تصویر/ویدیو با پروفایلِ آماده (FLUX / Wan)",
    example: '{"profile": "flux-product-balanced", "prompt": "a red ceramic mug on a wooden table, studio light"}',
  },
  { value: "comfy.graph", label: "comfy.graph — گرافِ خامِ ComfyUI", example: '{"graph": {}}' },
  { value: "photo.edit", label: "photo.edit — ویرایشِ عکس با نسخه (PersianAiKit.Photo)", example: '{"auto": true}' },
  { value: "video.edit", label: "video.edit — ویرایش/خروجیِ ویدیو (PersianAiKit.Video)", example: '{"auto": true}' },
  { value: "voice.tts", label: "voice.tts — متن به گفتار (PersianAiKit.Voice)", example: '{"text": "سلام، این یک آزمایش است."}' },
  { value: "ollama.chat", label: "ollama.chat — متن با Ollama روی GPU", example: '{"model": "qwen2.5:7b", "messages": [{"role": "user", "content": "سلام"}]}' },
];

/** ردیف‌های کارتِ «مسیرِ پردازش» — همان چهار قابلیتِ Provider.Capability در بک‌اند */
const ROUTE_ROWS: { cap: string; label: string; icon: IconName }[] = [
  { cap: "IMAGE", label: "تصویر", icon: "image" },
  { cap: "VIDEO", label: "ویدیو", icon: "film" },
  { cap: "TEXT", label: "متن", icon: "chat" },
  { cap: "VISION", label: "بینایی", icon: "search" },
];

function ago(iso: string | null): string {
  if (!iso) return "هرگز";
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${fa(s)} ثانیه پیش`;
  if (s < 3600) return `${fa(Math.round(s / 60))} دقیقه پیش`;
  return `${fa(Math.round(s / 3600))} ساعت پیش`;
}

function lastSeenText(n: Node): string {
  return n.last_seen ? `آخرین تماس ${ago(n.last_seen)}` : "هنوز تماسی نگرفته";
}

function stateTone(state: string): Tone {
  if (state === "COMPLETED") return "ok";
  if (state === "FAILED") return "bad";
  if (state === "CANCELLED") return "neutral";
  if (state === "QUEUED") return "warn";
  return "info";
}

function levelTone(level: string): Tone {
  const l = (level || "").toUpperCase();
  if (l === "ERROR" || l === "CRITICAL" || l === "FATAL") return "bad";
  if (l === "WARNING" || l === "WARN") return "warn";
  if (l === "DEBUG") return "neutral";
  return "info";
}

/** زمانِ خطِ لاگ: تاریخ و ساعتِ کوتاه با رقمِ فارسی؛ ISO خام در title می‌ماند */
function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("fa-IR", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/** مگابایت ⇐ «۷٫۰» گیگابایت با رقم و ممیزِ فارسی (برای «VRAM ۷٫۰ از ۱۲٫۳ GB») */
function gb(mb: number): string {
  return fa((mb / 1024).toFixed(1)).replace(".", "٫");
}

/**
 * وضعیتِ واقعیِ یک سرویس روی سرور: اول گزارشِ «managed» (عامل روشنش کرده / بیرونی / خاموش)،
 * وگرنه همان پرچمِ ساده‌ی حضور در services.
 */
function actualState(n: Node, s: (typeof MANAGED_SERVICES)[number]): { on: boolean; text: string; tone: Tone; title: string } {
  const m = n.managed?.[s.key] ?? n.managed?.[s.actual];
  if (m === "agent") return { on: true, text: "روشن (عامل)", tone: "ok", title: "عاملِ پردازش خودش این سرویس را روشن کرده و خاموشش هم می‌تواند بکند" };
  if (m === "external")
    return { on: true, text: "روشن (بیرونی)", tone: "info", title: "بیرون از عامل روشن شده (مثلاً دستی)؛ عامل خاموشش نمی‌کند" };
  if (m === "off") return { on: false, text: "خاموش", tone: "neutral", title: "عامل گزارش کرده که خاموش است" };
  const on = Boolean(n.services?.[s.actual]);
  return on
    ? { on: true, text: "روشن", tone: "ok", title: "سرور حضورِ این سرویس را گزارش کرده" }
    : { on: false, text: "خاموش", tone: "neutral", title: "خاموش یا گزارش‌نشده" };
}

/** نشانی‌های خروجی از سرور کامل می‌آیند (/api/v1/…)؛ کلاینت خودش /api/v1 را جلویش می‌گذارد. */
function apiPath(url: string): string {
  return url.replace(/^\/api\/v1/, "");
}

async function downloadBlob(url: string, filename: string) {
  const { data } = await api.get<Blob>(apiPath(url), { responseType: "blob" });
  const href = URL.createObjectURL(data);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // فایرفاکس: آزاد کردنِ URL بلافاصله بعد از click() دانلود را نیمه‌کاره می‌گذارد
  window.setTimeout(() => URL.revokeObjectURL(href), 4000);
}

export default function ComputePage() {
  const [nodes, setNodes] = useState<Node[] | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [shownToken, setShownToken] = useState<number | null>(null);
  /** شناسهٔ سروری که کشوی لاگش باز است (فقط یکی) */
  const [openLog, setOpenLog] = useState<number | null>(null);
  /** شناسهٔ سروری که کشوی «سرویس‌ها»یش باز است (فقط یکی؛ مستقل از لاگ) */
  const [openServices, setOpenServices] = useState<number | null>(null);
  /** یک نسخه از تنظیمات برای هر دو کارت (ثبتِ سرورِ تازه + مسیرِ پردازش)؛ هر ۳۰ ثانیه تازه می‌شود */
  const [settings, setSettings] = useState<RouteSettings | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);

  const loadSettings = useCallback(async () => {
    try {
      const { data } = await api.get<RouteSettings>("/compute/settings/");
      setSettings(data);
      setSettingsError(null);
    } catch (err) {
      setSettingsError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    void loadSettings();
    const t = window.setInterval(() => void loadSettings(), 30000);
    return () => window.clearInterval(t);
  }, [loadSettings]);

  const load = useCallback(async () => {
    try {
      const [n, j] = await Promise.all([
        api.get<Node[]>("/compute/nodes/"),
        api.get<{ summary: Summary; jobs: Job[] }>("/compute/jobs/?limit=40"),
      ]);
      setNodes(n.data);
      setJobs(j.data.jobs);
      setSummary(j.data.summary);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    void load();
    const t = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(t);
  }, [load]);

  const addNode = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) return;
    try {
      await api.post("/compute/nodes/", { name: newName.trim() });
      setNewName("");
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  /** پاسخِ POST …/desired/ بی‌توکن است؛ روی همان ردیف می‌نشیند تا کنترل‌ها بی‌درنگ (پیش از poll بعدی) تازه شوند */
  const patchNode = useCallback((data: NodeView) => {
    setNodes((prev) => (prev ? prev.map((x) => (x.id === data.id ? { ...x, ...data } : x)) : prev));
  }, []);

  const nodeAction = async (node: Node, action: "toggle" | "rotate" | "delete") => {
    if (action === "delete" && !window.confirm(`سرورِ «${node.name}» حذف شود؟`)) return;
    try {
      await api.post(`/compute/nodes/${node.id}/`, { action });
      if (action === "delete" && openLog === node.id) setOpenLog(null);
      if (action === "delete" && openServices === node.id) setOpenServices(null);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const cancelJob = async (job: Job) => {
    try {
      await api.delete(`/compute/jobs/${job.uid}/`);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  if (!nodes) {
    return (
      <div className="py-10 text-center">{error ? <ErrorBox message={error} /> : <Spinner />}</div>
    );
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="سرورهای پردازش"
        subtitle="کامپیوترهای گرافیکی (بی‌IP ثابت) که خودشان به این سایت وصل می‌شوند و تولیدِ تصویر، ویدیو، صدا و متنِ سنگین را انجام می‌دهند."
      />
      <ErrorBox message={error} />

      {summary && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Card>
            <div className="u-num text-2xl font-extrabold" style={{ color: summary.online ? "var(--ok)" : "var(--bad)" }}>
              {fa(summary.online)} / {fa(summary.nodes)}
            </div>
            <div className="mt-1 text-sm" style={{ color: "var(--text-2)" }}>سرورِ آنلاین</div>
          </Card>
          <Card>
            <div className="u-num text-2xl font-extrabold" style={{ color: "var(--text)" }}>{fa(summary.queued)}</div>
            <div className="mt-1 text-sm" style={{ color: "var(--text-2)" }}>در صف</div>
          </Card>
          <Card>
            <div className="u-num text-2xl font-extrabold" style={{ color: "var(--text)" }}>{fa(summary.running)}</div>
            <div className="mt-1 text-sm" style={{ color: "var(--text-2)" }}>در حال پردازش</div>
          </Card>
          <Card>
            <div className="flex flex-wrap gap-1">
              {Object.keys(summary.capabilities).length === 0 && (
                <span className="text-sm" style={{ color: "var(--text-3)" }}>هیچ سرویسی روشن نیست</span>
              )}
              {Object.entries(summary.capabilities).map(([k, v]) => (
                <Badge key={k} tone="brand">
                  {k} ×{fa(v)}
                </Badge>
              ))}
            </div>
            <div className="mt-1 text-sm" style={{ color: "var(--text-2)" }}>توانایی‌های آنلاین</div>
          </Card>
        </div>
      )}

      {summary && summary.online === 0 && (
        <Alert tone="warn" title="هیچ سرورِ پردازشی آنلاین نیست">
          تا وقتی سروری وصل نشود، تولیدِ تصویر و ویدیو انجام نمی‌شود. روی کامپیوترِ گرافیکی پوشهٔ processing را
          بگذارید، START.bat را اجرا کنید و کلیدِ ثبتِ پایین را بدهید؛ اگر قبلاً ثبت شده، فقط START.bat را دوباره اجرا کنید.
        </Alert>
      )}

      <EnrollCard settings={settings} error={settingsError} onChange={setSettings} />

      <Card padded={false}>
        <div className="px-5 pt-5">
          <SectionTitle>سرورها</SectionTitle>
        </div>
        <Table>
          <thead>
            <tr>
              <th>نام</th>
              <th>وضعیت</th>
              <th>سرویس‌ها</th>
              <th>کارهای انجام‌شده</th>
              <th>زمانِ معمولِ هر کار</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {nodes.length === 0 && (
              <tr>
                <td colSpan={6} className="py-6 text-center" style={{ color: "var(--text-3)" }}>
                  هنوز سروری ثبت نشده — یک نام بدهید (مثلاً gpu-1).
                </td>
              </tr>
            )}
            {nodes.map((n) => {
              // توانایی‌هایی که نه زیرِ نام نشان داده می‌شوند نه در ستونِ سرویس‌ها (مثلاً کلیدِ تازه‌ای از عاملِ جدیدتر)
              const extras = Object.entries(n.capabilities || {}).filter(([k, v]) => v && !HIDDEN_CAPS.has(k));
              const introduced = Boolean(n.agent || n.hostname || n.gpu);
              const logOpen = openLog === n.id;
              const toggleLog = () => setOpenLog(logOpen ? null : n.id);
              const servicesOpen = openServices === n.id;
              const toggleServices = () => setOpenServices(servicesOpen ? null : n.id);
              return (
                <Fragment key={n.id}>
                  <tr>
                    <td>
                      <div className="font-bold">{n.name}</div>
                      <div className="mt-0.5 flex flex-wrap gap-x-2 text-xs" style={{ color: "var(--text-3)" }}>
                        {n.agent && (
                          <span title="نسخهٔ عاملِ پردازش روی آن دستگاه">
                            عامل <span dir="ltr">{n.agent}</span>
                          </span>
                        )}
                        {n.hostname && (
                          <span title="نامِ دستگاه">
                            <span dir="ltr">{n.hostname}</span>
                          </span>
                        )}
                        {n.gpu && <span dir="ltr" title="کارتِ گرافیک">{n.gpu}</span>}
                        {!introduced && <span>هنوز خودش را معرفی نکرده</span>}
                      </div>
                    </td>
                    <td>
                      {!n.enabled ? (
                        <Badge>غیرفعال</Badge>
                      ) : n.online ? (
                        <Badge tone="ok">
                          <Icon name="ok" size={12} /> آنلاین
                        </Badge>
                      ) : (
                        <Badge tone="bad">
                          <Icon name="ban" size={12} /> خاموش
                        </Badge>
                      )}
                      <div className="mt-0.5 text-xs" style={{ color: "var(--text-3)" }}>{lastSeenText(n)}</div>
                      <ResourceMeters resources={n.resources} stale={!n.online} />
                      {n.last_error && (
                        <div className="mt-1 flex items-center gap-1 text-xs" style={{ color: "var(--bad)" }}>
                          <Icon name="warn" size={12} />
                          <span className="max-w-[220px] truncate" dir="auto" title={n.last_error}>
                            {n.last_error}
                          </span>
                          <Button size="sm" variant="ghost" onClick={toggleLog}>
                            لاگ
                          </Button>
                        </div>
                      )}
                    </td>
                    <td>
                      <div className="flex max-w-[280px] flex-wrap gap-1">
                        {SERVICE_KEYS.map((k) => {
                          const on = Boolean(n.services?.[k]);
                          return (
                            <span key={k} style={{ opacity: on ? 1 : 0.55 }} title={on ? "روشن" : "خاموش یا گزارش‌نشده"}>
                              <Badge tone={on ? "ok" : "neutral"}>{SERVICE_LABELS[k]}</Badge>
                            </span>
                          );
                        })}
                        {extras.map(([k]) => (
                          <Badge key={k} tone="brand">{k}</Badge>
                        ))}
                      </div>
                      {!n.online && introduced && (
                        <div className="mt-0.5 text-xs" style={{ color: "var(--text-3)" }}>طبق آخرین گزارشِ خودِ سرور</div>
                      )}
                      <div className="mt-1">
                        <Button
                          size="sm"
                          variant={servicesOpen ? "secondary" : "ghost"}
                          onClick={toggleServices}
                          title="کدام سرویس روشن یا خاموش باشد — عامل روی همان کامپیوتر اعمال می‌کند"
                        >
                          <Icon name={servicesOpen ? "up" : "down"} size={12} /> {servicesOpen ? "بستنِ تنظیمِ سرویس‌ها" : "روشن/خاموش کردن"}
                        </Button>
                      </div>
                    </td>
                    <td className="u-num">{fa(n.jobs_done)}</td>
                    <td className="text-xs" style={{ color: "var(--text-2)" }}>
                      {Object.entries(n.stats || {}).length === 0
                        ? "—"
                        : Object.entries(n.stats).map(([k, v]) => (
                            <div key={k}>
                              {k}: {fa(Math.round(v.seconds))} ثانیه ({fa(v.n)})
                            </div>
                          ))}
                    </td>
                    <td>
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Button size="sm" variant={servicesOpen ? "secondary" : "ghost"} onClick={toggleServices}>
                          سرویس‌ها
                        </Button>
                        <Button size="sm" variant={logOpen ? "secondary" : "ghost"} onClick={toggleLog}>
                          لاگ
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setShownToken(shownToken === n.id ? null : n.id)}>
                          توکن
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => void nodeAction(n, "toggle")}>
                          {n.enabled ? "غیرفعال" : "فعال"}
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => void nodeAction(n, "rotate")}>
                          توکنِ تازه
                        </Button>
                        <Button size="sm" variant="danger" onClick={() => void nodeAction(n, "delete")}>
                          حذف
                        </Button>
                      </div>
                      {shownToken === n.id && (
                        <code
                          className="mt-1 block break-all rounded px-2 py-1 text-xs"
                          dir="ltr"
                          style={{ background: "var(--surface-2)", color: "var(--text-2)" }}
                        >
                          {n.token}
                        </code>
                      )}
                    </td>
                  </tr>
                  {servicesOpen && (
                    <tr>
                      <td colSpan={6} style={{ background: "var(--surface-2)" }}>
                        <NodeServices node={n} onClose={() => setOpenServices(null)} onPatched={patchNode} onError={setError} />
                      </td>
                    </tr>
                  )}
                  {logOpen && (
                    <tr>
                      <td colSpan={6} style={{ background: "var(--surface-2)" }}>
                        <NodeLogs node={n} onClose={() => setOpenLog(null)} onCleared={() => void load()} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </Table>
        <form onSubmit={addNode} className="flex flex-wrap items-center gap-2 px-5 pb-5 pt-3">
          <Input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="نامِ سرورِ تازه (مثلاً gpu-1)"
            style={{ maxWidth: 280 }}
          />
          <Button type="submit" variant="secondary">
            <Icon name="plus" size={14} /> افزودن
          </Button>
          <span className="text-xs" style={{ color: "var(--text-3)" }}>
            افزودنِ نام این‌جا اختیاری است — سرورها با «کلیدِ ثبت» خودشان را ثبت می‌کنند؛ فقط اگر می‌خواهید نامی را از پیش رزرو کنید.
          </span>
        </form>
      </Card>

      <RouteCard nodes={nodes} settings={settings} settingsError={settingsError} onSettings={setSettings} onRefresh={loadSettings} />

      <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
        <JobsTable jobs={jobs} onCancel={cancelJob} />
        <SubmitCard onDone={load} />
      </div>
    </div>
  );
}

/** کشوی لاگِ یک سرور: خطاها/هشدارهایی که خودِ عامل فرستاده (POST /compute/log/)، تازه‌ترین بالا. */
function NodeLogs({ node, onClose, onCleared }: { node: Node; onClose: () => void; onCleared: () => void }) {
  const [lines, setLines] = useState<LogLine[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const fetchLogs = useCallback(async () => {
    setBusy(true);
    try {
      const { data } = await api.get<{ node: string; lines: LogLine[] }>(`/compute/nodes/${node.id}/logs/?limit=100`);
      if (!alive.current) return;
      setLines(data.lines);
      setErr(null);
    } catch (e) {
      if (alive.current) setErr(errorMessage(e));
    } finally {
      if (alive.current) setBusy(false);
    }
  }, [node.id]);

  useEffect(() => {
    void fetchLogs();
  }, [fetchLogs]);

  const clear = async () => {
    if (!window.confirm(`لاگِ سرورِ «${node.name}» پاک شود؟`)) return;
    setBusy(true);
    try {
      await api.delete(`/compute/nodes/${node.id}/logs/`);
      if (!alive.current) return;
      setLines([]);
      setErr(null);
      onCleared(); // تا «آخرین خطا»ی ردیفِ بالا هم بی‌درنگ برود
    } catch (e) {
      if (alive.current) setErr(errorMessage(e));
    } finally {
      if (alive.current) setBusy(false);
    }
  };

  return (
    <div className="space-y-2 py-1">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-bold" style={{ color: "var(--text)" }}>لاگِ «{node.name}»</span>
        {lines && lines.length > 0 && (
          <span className="text-xs" style={{ color: "var(--text-3)" }}>
            {fa(lines.length)} خطِ آخر — تازه‌ترین بالا
          </span>
        )}
        <span className="flex-1" />
        <Button size="sm" variant="secondary" disabled={busy} onClick={() => void fetchLogs()}>
          <Icon name="refresh" size={13} /> تازه‌سازی
        </Button>
        <Button size="sm" variant="danger" disabled={busy || !lines || lines.length === 0} onClick={() => void clear()}>
          <Icon name="trash" size={13} /> پاک کردن
        </Button>
        <Button size="sm" variant="ghost" onClick={onClose}>
          <Icon name="x" size={13} /> بستن
        </Button>
      </div>
      <ErrorBox message={err} />
      {!lines ? (
        <Spinner size={16} />
      ) : lines.length === 0 ? (
        <div className="text-xs" style={{ color: "var(--text-3)" }}>
          چیزی ثبت نشده — سرور فقط خطاها و هشدارهایش را می‌فرستد؛ خالی یعنی خبری نبوده.
        </div>
      ) : (
        <div className="max-h-72 overflow-y-auto rounded-lg" style={{ background: "var(--surface)", border: "1px solid var(--line)" }}>
          {lines.map((l, i) => (
            <div
              key={`${l.ts ?? ""}-${i}`}
              className="flex items-start gap-2 px-2 py-1 text-xs"
              style={{ borderBottom: i === lines.length - 1 ? "none" : "1px solid var(--line)" }}
            >
              <span className="shrink-0">
                <Badge tone={levelTone(l.level)}>{l.level || "INFO"}</Badge>
              </span>
              <span className="u-num shrink-0" style={{ color: "var(--text-3)" }} title={l.ts ?? ""}>
                {fmtTime(l.ts)}
              </span>
              <code
                className="min-w-0 flex-1 whitespace-pre-wrap break-words font-mono"
                dir="auto"
                style={{ color: "var(--text-2)" }}
              >
                {l.message}
              </code>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * کشوی «سرویس‌ها»ی یک سرور: برای هر سرویس، «الان» (گزارشِ خودِ سرور) و «بشود» (خواستهٔ پنل).
 * هر تغییر بی‌درنگ POST می‌شود (/compute/nodes/<id>/desired/)؛ عامل روی همان کامپیوتر با heartbeat
 * بعدی می‌گیرد و اعمال می‌کند — پس این‌جا فقط «فرستاده شد» می‌گوییم، نه «اعمال شد».
 * خطاها به ErrorBox ِ بالای صفحه می‌روند (onError) تا جایی که همهٔ خطاها هست دیده شوند.
 */
function NodeServices({
  node,
  onClose,
  onPatched,
  onError,
}: {
  node: Node;
  onClose: () => void;
  onPatched: (n: NodeView) => void;
  onError: (msg: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  /** زمانِ آخرین ارسالِ موفق؛ شمارنده است نه boolean، تا ارسالِ پشتِ‌سرِهم تایمرِ «فرستاده شد» را از نو بیندازد */
  const [sentAt, setSentAt] = useState<number | null>(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  // «فرستاده شد» چند ثانیه می‌ماند؛ با بسته‌شدنِ کشو تایمر پاک می‌شود
  useEffect(() => {
    if (sentAt === null) return;
    const t = window.setTimeout(() => setSentAt(null), 6000);
    return () => window.clearTimeout(t);
  }, [sentAt]);

  const send = async (body: { services?: Partial<Record<ManagedKey, boolean | null>>; auto_switch?: boolean }) => {
    setBusy(true);
    try {
      const { data } = await api.post<NodeView>(`/compute/nodes/${node.id}/desired/`, body);
      onPatched(data); // ردیفِ پدر حتی اگر کشو بسته شده باشد تازه شود
      if (alive.current) setSentAt(Date.now());
    } catch (e) {
      onError(errorMessage(e));
    } finally {
      if (alive.current) setBusy(false);
    }
  };

  return (
    <div className="space-y-3 py-1">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-bold" style={{ color: "var(--text)" }}>سرویس‌های «{node.name}»</span>
        <span className="text-xs" style={{ color: "var(--text-3)" }}>
          «الان» گزارشِ خودِ سرور است؛ «بشود» خواستهٔ شما که عامل روی همان کامپیوتر اجرا می‌کند.
        </span>
        <span className="flex-1" />
        {busy && (
          <span className="flex items-center gap-1 text-xs" style={{ color: "var(--text-3)" }}>
            <Spinner size={12} /> در حال فرستادن…
          </span>
        )}
        {!busy && sentAt !== null && (
          <span className="flex items-center gap-1 text-xs" style={{ color: "var(--ok)" }}>
            <Icon name="ok" size={12} /> فرستاده شد — سرور در چند ثانیه اعمال می‌کند
          </span>
        )}
        <Button size="sm" variant="ghost" onClick={onClose}>
          <Icon name="x" size={13} /> بستن
        </Button>
      </div>

      {!node.enabled ? (
        <div className="flex items-center gap-1 text-xs" style={{ color: "var(--warn)" }}>
          <Icon name="warn" size={12} /> این سرور غیرفعال است؛ تا فعال نشود به سایت وصل نمی‌شود و این انتخاب‌ها اعمال نمی‌شود.
        </div>
      ) : !node.online ? (
        <div className="flex items-center gap-1 text-xs" style={{ color: "var(--warn)" }}>
          <Icon name="warn" size={12} /> سرور الان خاموش است — انتخاب‌ها ذخیره می‌شود و با اولین تماسش اعمال می‌شود؛ ستونِ «الان» آخرین گزارشِ خودش است.
        </div>
      ) : null}

      <div className="grid gap-2 md:grid-cols-2">
        {MANAGED_SERVICES.map((s) => {
          const actual = actualState(node, s);
          const wanted: boolean | null = node.desired?.[s.key] ?? null;
          return (
            <div
              key={s.key}
              className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg px-3 py-2"
              style={{ background: "var(--surface)", border: "1px solid var(--line)" }}
            >
              <div className="min-w-[140px] flex-1">
                <div className="text-sm font-bold" style={{ color: "var(--text)" }}>{s.label}</div>
                <div className="text-xs" dir="auto" style={{ color: "var(--text-3)" }}>{s.sub}</div>
              </div>
              <div className="flex items-center gap-1.5 text-xs" style={{ color: "var(--text-3)" }} title={actual.title}>
                <span>الان:</span>
                <Badge tone={actual.tone}>
                  <Icon name={actual.on ? "ok" : "ban"} size={11} /> {actual.text}
                </Badge>
              </div>
              <div className="flex items-center gap-1.5 text-xs" style={{ color: "var(--text-3)" }}>
                <span>بشود:</span>
                <TriState
                  value={wanted}
                  disabled={busy}
                  label={s.label}
                  onChange={(v) => void send({ services: { [s.key]: v } })}
                />
              </div>
            </div>
          );
        })}
      </div>

      <div className="flex items-start gap-1 text-xs" style={{ color: "var(--text-3)" }}>
        <Icon name="info" size={12} />
        <span>
          ComfyUI هم تصویر (FLUX) و هم ویدیو (Wan) را می‌سازد؛ سرور برای بارکردنِ یکی، مدلِ دیگری را از حافظهٔ گرافیک خالی می‌کند —
          پس برای هر دو همین یک سرویس کافی است. «پیش‌فرض» یعنی به این سرویس دست نزن و همان رفتارِ خودِ سرور بماند.
        </span>
      </div>

      <label className="flex items-start gap-2 text-sm" style={{ color: "var(--text-2)" }}>
        <input
          type="checkbox"
          className="mt-1"
          checked={Boolean(node.auto_switch)}
          disabled={busy}
          onChange={(e) => void send({ auto_switch: e.target.checked })}
        />
        <span>
          <span className="font-bold" style={{ color: "var(--text)" }}>سوئیچِ خودکار</span>{" "}
          <Badge tone={node.auto_switch ? "ok" : "neutral"}>{node.auto_switch ? "روشن" : "خاموش"}</Badge>
          <span className="block text-xs" style={{ color: "var(--text-3)" }}>
            وقتی کاری بیاید که سرویسش روشن نیست (مثلاً Ollama بالاست و ویدیو خواسته شده)، سرور خودش حافظهٔ موتورِ دیگر را آزاد و
            سرویسِ لازم را روشن می‌کند.
          </span>
        </span>
      </label>
    </div>
  );
}

/** کنترلِ سه‌حالتهٔ «بشود»: روشن / خاموش / پیش‌فرض (null = کلید از desired برداشته می‌شود) */
function TriState({
  value,
  disabled,
  label,
  onChange,
}: {
  value: boolean | null;
  disabled: boolean;
  label: string;
  onChange: (v: boolean | null) => void;
}) {
  const opts: { v: boolean | null; text: string; tone: "ok" | "bad" | "brand"; title: string }[] = [
    { v: true, text: "روشن", tone: "ok", title: "عامل این سرویس را روشن می‌کند و روشن نگه می‌دارد" },
    { v: false, text: "خاموش", tone: "bad", title: "عامل این سرویس را خاموش می‌کند تا حافظه‌اش آزاد شود" },
    { v: null, text: "پیش‌فرض", tone: "brand", title: "دست نزن — همان رفتارِ پیش‌فرضِ خودِ سرور" },
  ];
  return (
    <div
      role="radiogroup"
      aria-label={`وضعیتِ خواسته‌شدهٔ ${label}`}
      className="inline-flex overflow-hidden rounded-lg"
      style={{ border: "1px solid var(--line)", background: "var(--surface-2)" }}
    >
      {opts.map((o, i) => {
        const sel = value === o.v;
        const color = o.tone === "brand" ? "var(--brand-strong)" : `var(--${o.tone})`;
        return (
          <button
            key={o.text}
            type="button"
            role="radio"
            aria-checked={sel}
            disabled={disabled}
            title={o.title}
            onClick={() => {
              if (!sel) onChange(o.v); // همان حالت دوباره فرستاده نشود
            }}
            className="px-2.5 py-1 text-xs font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50"
            style={{
              background: sel ? `var(--${o.tone}-soft)` : "transparent",
              color: sel ? color : "var(--text-3)",
              borderInlineStart: i ? "1px solid var(--line)" : "none",
              cursor: disabled ? "not-allowed" : "pointer",
            }}
          >
            {o.text}
          </button>
        );
      })}
    </div>
  );
}

/**
 * نوارهای حافظهٔ یک سرور از آخرین heartbeat: RAM (مصرف = کل − آزاد) و VRAM (مصرف/کل).
 * هر کدام گزارش نشده باشد، نشان داده نمی‌شود؛ هیچ‌کدام نباشد، هیچ.
 */
function ResourceMeters({ resources, stale }: { resources: Resources | undefined; stale: boolean }) {
  const r = resources ?? {};
  const rows: { label: string; used: number; total: number; hint: string }[] = [];
  if (r.ram_total_mb && r.ram_free_mb !== undefined) {
    rows.push({
      label: "RAM",
      used: Math.max(0, r.ram_total_mb - r.ram_free_mb),
      total: r.ram_total_mb,
      hint: "حافظهٔ اصلیِ دستگاه (مصرف = کل − آزاد)",
    });
  }
  if (r.vram_total_mb && r.vram_used_mb !== undefined) {
    rows.push({
      label: "VRAM",
      used: Math.max(0, r.vram_used_mb),
      total: r.vram_total_mb,
      hint: "حافظهٔ کارتِ گرافیک — هر موتور (Ollama، ComfyUI، …) تکه‌ای از آن را می‌گیرد",
    });
  }
  if (rows.length === 0) return null;
  return (
    <div className="mt-1.5 w-[200px] max-w-full space-y-1" style={{ opacity: stale ? 0.55 : 1 }}>
      {rows.map((x) => (
        <div key={x.label} title={stale ? `${x.hint} — طبق آخرین گزارشِ خودِ سرور` : x.hint}>
          <div className="flex items-center justify-between gap-2 text-xs" style={{ color: "var(--text-3)" }}>
            <span dir="ltr">{x.label}</span>
            <span className="u-num">
              {gb(x.used)} از {gb(x.total)} GB
            </span>
          </div>
          <Meter used={x.used} total={x.total} />
        </div>
      ))}
    </div>
  );
}

/**
 * «ثبتِ سرورِ پردازشِ تازه»: دیگر فایلِ راه‌اندازیِ جداگانه برای هر سرور نیست.
 * کامپیوترِ گرافیکی START.bat را اجرا می‌کند، این کلید را می‌گیرد و خودش را با
 * نامِ خودش ثبت می‌کند (POST /compute/enroll/ — پنل آن را صدا نمی‌زند).
 */
function EnrollCard({
  settings,
  error,
  onChange,
}: {
  settings: RouteSettings | null;
  error: string | null;
  onChange: (s: RouteSettings) => void;
}) {
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  // «کپی شد» سه ثانیه می‌ماند
  useEffect(() => {
    if (!copied) return;
    const t = window.setTimeout(() => setCopied(false), 3000);
    return () => window.clearTimeout(t);
  }, [copied]);

  const key = settings?.enroll_key ?? "";

  const copy = async () => {
    if (!key) return;
    try {
      if (!navigator.clipboard) throw new Error("no clipboard");
      await navigator.clipboard.writeText(key);
      if (!alive.current) return;
      setCopied(true);
      setErr(null);
    } catch {
      // http بی‌TLS یا مرورگرِ قدیمی: کلیپ‌بورد در دسترس نیست؛ متن select-all است تا دستی کپی شود
      if (alive.current) setErr("کپیِ خودکار نشد — روی کلید بزنید تا انتخاب شود و با Ctrl+C کپی کنید.");
    }
  };

  const rotate = async () => {
    if (
      !window.confirm(
        "کلیدِ تازه ساخته شود؟\n\nکامپیوترهایی که قبلاً ثبت شده‌اند با توکنِ خودشان کار می‌کنند و چیزشان عوض نمی‌شود؛ فقط ثبتِ کامپیوترهای تازه به کلیدِ جدید نیاز دارد.",
      )
    )
      return;
    setBusy(true);
    try {
      const { data } = await api.post<RouteSettings>("/compute/settings/", { rotate_enroll_key: true });
      if (!alive.current) return;
      onChange(data);
      setCopied(false);
      setErr(null);
    } catch (e) {
      if (alive.current) setErr(errorMessage(e));
    } finally {
      if (alive.current) setBusy(false);
    }
  };

  return (
    <Card>
      <SectionTitle>ثبتِ سرورِ پردازشِ تازه</SectionTitle>
      <ErrorBox message={err ?? error} />
      <div className="grid gap-4 md:grid-cols-2">
        <div className="min-w-0">
          <div className="mb-1.5 text-sm font-medium" style={{ color: "var(--text-2)" }}>کلیدِ ثبت</div>
          <div className="flex flex-wrap items-center gap-2">
            <code
              dir="ltr"
              className="select-all break-all rounded-lg px-3 py-2 font-mono text-sm"
              style={{ background: "var(--surface-2)", color: "var(--text)", border: "1px solid var(--line)" }}
              title="کلیدِ ثبتِ سرورِ تازه"
            >
              {settings ? key || "—" : "…"}
            </code>
            <Button size="sm" variant="secondary" disabled={!key} onClick={() => void copy()}>
              <Icon name={copied ? "ok" : "copy"} size={13} /> {copied ? "کپی شد" : "کپی"}
            </Button>
            <Button size="sm" variant="ghost" disabled={!settings || busy} onClick={() => void rotate()}>
              {busy ? <Spinner size={13} /> : <Icon name="refresh" size={13} />} کلیدِ تازه
            </Button>
          </div>
          <div className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
            نشانیِ سایت که کامپیوتر به آن وصل می‌شود:{" "}
            <span dir="ltr" className="select-all font-mono" style={{ color: "var(--text-2)" }}>
              {settings?.site || "—"}
            </span>
          </div>
          <div className="mt-1 text-xs" style={{ color: "var(--text-3)" }}>
            «کلیدِ تازه» فقط برای ثبت‌های بعدی لازم است؛ کامپیوترهای ثبت‌شده با توکنِ خودشان کار می‌کنند و قطع نمی‌شوند.
          </div>
        </div>
        <ol className="space-y-1.5 text-sm leading-7" style={{ color: "var(--text-2)" }}>
          <li>۱) پوشهٔ processing را از مخزن/زیپ روی کامپیوترِ گرافیکی بگذارید.</li>
          <li>۲) START.bat را اجرا کنید و این کلید را بدهید — کامپیوتر با نامِ خودش ثبت می‌شود.</li>
          <li>۳) ComfyUI را روشن کنید؛ چند ثانیه بعد این‌جا «آنلاین» می‌شود.</li>
        </ol>
      </div>
    </Card>
  );
}

/**
 * «مسیرِ پردازش»: هر نوع کار الان کجا انجام می‌شود.
 * متن/بینایی/تصویر/ویدیو از /ai/status/ (همان تنظیمِ موتورهای هوش مصنوعی)؛
 * برای تصویر و ویدیو، سرورِ پردازشِ مقصد همین‌جا انتخاب می‌شود (/compute/settings/ — نسخهٔ مشترک از پدر).
 */
function RouteCard({
  nodes,
  settings,
  settingsError,
  onSettings,
  onRefresh,
}: {
  nodes: Node[];
  settings: RouteSettings | null;
  settingsError: string | null;
  onSettings: (s: RouteSettings) => void;
  onRefresh: () => Promise<void>;
}) {
  const [status, setStatus] = useState<AiStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const alive = useRef(true);

  const loadStatus = useCallback(async () => {
    try {
      const { data } = await api.get<AiStatus>("/ai/status/");
      if (!alive.current) return;
      setStatus(data);
      setErr(null);
    } catch (e) {
      if (alive.current) setErr(errorMessage(e));
    }
  }, []);

  // موتورها را کسی هر چند ثانیه عوض نمی‌کند؛ ۳۰ ثانیه کافی است (نودها را پدر هر ۵ ثانیه می‌آورد)
  useEffect(() => {
    alive.current = true;
    void loadStatus();
    const t = window.setInterval(() => void loadStatus(), 30000);
    return () => {
      alive.current = false;
      window.clearInterval(t);
    };
  }, [loadStatus]);

  const load = () => Promise.all([loadStatus(), onRefresh()]);

  // پیامِ «ذخیره شد» چند ثانیه بعد خودش می‌رود
  useEffect(() => {
    if (!saved) return;
    const t = window.setTimeout(() => setSaved(null), 6000);
    return () => window.clearTimeout(t);
  }, [saved]);

  const choose = async (name: string) => {
    setSaving(true);
    setSaved(null);
    try {
      const { data } = await api.post<RouteSettings>("/compute/settings/", { image_video_node: name });
      if (!alive.current) return;
      onSettings(data);
      setErr(null);
      setSaved(
        data.image_video_node
          ? `ذخیره شد — تصویر و ویدیو از این پس فقط روی «${data.image_video_node}» ساخته می‌شود`
          : "ذخیره شد — تصویر و ویدیو روی هر سرورِ پردازشی که ComfyUI دارد",
      );
    } catch (e) {
      if (alive.current) setErr(errorMessage(e));
    } finally {
      if (alive.current) setSaving(false);
    }
  };

  const current = settings?.image_video_node ?? "";
  const names = settings ? [...settings.nodes] : nodes.filter((n) => n.enabled).map((n) => n.name);
  if (current && !names.includes(current)) names.push(current); // سرورِ غیرفعال‌شده هم باید در فهرست دیده شود، نه که انتخاب خالی بماند
  const chosen = current ? nodes.find((n) => n.name === current) : undefined;
  const comfyOnline = nodes.filter((n) => n.enabled && n.online && n.services?.comfyui);

  let hint: { tone: Tone; text: string };
  if (current) {
    if (!chosen) hint = { tone: "warn", text: "این سرور دیگر در فهرست نیست — یکی دیگر انتخاب کنید" };
    else if (!chosen.enabled) hint = { tone: "bad", text: "این سرور غیرفعال است؛ تصویر و ویدیو ساخته نمی‌شود" };
    else if (!chosen.online) hint = { tone: "bad", text: "این سرور الان خاموش است؛ کارها تا وصل‌شدنش در صف می‌مانند" };
    else if (!chosen.services?.comfyui) hint = { tone: "warn", text: "این سرور آنلاین است ولی ComfyUI را گزارش نکرده" };
    else hint = { tone: "ok", text: "آنلاین و آماده" };
  } else if (comfyOnline.length) {
    hint = { tone: "ok", text: `الان ${fa(comfyOnline.length)} سرورِ ComfyUI‌دار آنلاین است: ${comfyOnline.map((n) => n.name).join("، ")}` };
  } else {
    hint = { tone: "bad", text: "هیچ سرورِ ComfyUI‌داری آنلاین نیست" };
  }
  const hintColor = hint.tone === "neutral" ? "var(--text-3)" : `var(--${hint.tone})`;

  return (
    <Card padded={false}>
      <div className="px-5 pt-5">
        <SectionTitle
          action={
            <Button size="sm" variant="ghost" onClick={() => void load()}>
              <Icon name="refresh" size={13} /> تازه‌سازی
            </Button>
          }
        >
          مسیرِ پردازش
        </SectionTitle>
        <p className="-mt-1 mb-2 text-xs" style={{ color: "var(--text-3)" }}>
          هر نوع کار الان با کدام موتور و کجا انجام می‌شود. تصویر و ویدیو را همین‌جا می‌توانید به یک سرورِ مشخص ببرید.
        </p>
        <ErrorBox message={err ?? settingsError} />
      </div>
      <Table>
        <thead>
          <tr>
            <th>کار</th>
            <th>موتور</th>
            <th>مدل</th>
            <th>کجا</th>
            <th>سرورِ پردازش</th>
          </tr>
        </thead>
        <tbody>
          {ROUTE_ROWS.map((r) => {
            const c = status?.capabilities.find((x) => x.capability === r.cap);
            return (
              <tr key={r.cap}>
                <td>
                  <span className="inline-flex items-center gap-1.5 font-medium" style={{ color: "var(--text)" }}>
                    <Icon name={r.icon} size={14} /> {r.label}
                  </span>
                </td>
                <td>
                  {!status ? (
                    <Spinner size={14} />
                  ) : c ? (
                    <>
                      {c.provider}
                      <div className="text-xs" dir="ltr" style={{ color: "var(--text-3)", textAlign: "start" }}>{c.kind}</div>
                    </>
                  ) : (
                    <span className="text-xs" style={{ color: "var(--text-3)" }}>موتوری تنظیم نشده</span>
                  )}
                </td>
                <td dir="ltr" className="u-num text-xs" style={{ textAlign: "start" }}>{c?.model || "—"}</td>
                <td>
                  {!c ? (
                    "—"
                  ) : c.local === null ? (
                    <Badge>نامشخص</Badge>
                  ) : (
                    <Badge tone={c.local ? "ok" : "info"}>
                      <Icon name={c.local ? "cpu" : "cloud"} size={12} /> {c.local ? "لوکال" : "API بیرونی"}
                    </Badge>
                  )}
                </td>
                {r.cap === "IMAGE" ? (
                  <td rowSpan={2} style={{ verticalAlign: "top" }}>
                    <Select
                      aria-label="سرورِ تصویر و ویدیو"
                      value={current}
                      disabled={!settings || saving}
                      onChange={(e) => void choose(e.target.value)}
                      style={{ maxWidth: 320 }}
                    >
                      <option value="">هر سرورِ پردازشی که ComfyUI دارد</option>
                      {names.map((nm) => (
                        <option key={nm} value={nm}>{nm}</option>
                      ))}
                    </Select>
                    <div className="mt-1 text-xs" style={{ color: hintColor }}>{hint.text}</div>
                    {saving && (
                      <div className="mt-1 text-xs" style={{ color: "var(--text-3)" }}>در حال ذخیره…</div>
                    )}
                    {saved && (
                      <div className="mt-1 flex items-center gap-1 text-xs" style={{ color: "var(--ok)" }}>
                        <Icon name="ok" size={12} /> {saved}
                      </div>
                    )}
                  </td>
                ) : r.cap === "VIDEO" ? null : (
                  <td className="text-xs" style={{ color: "var(--text-3)" }}>طبق تنظیمِ موتورهای هوش مصنوعی</td>
                )}
              </tr>
            );
          })}
        </tbody>
      </Table>
      <div className="px-5 pb-4 pt-2 text-xs" style={{ color: "var(--text-3)" }}>
        متن و بینایی از تنظیمِ{" "}
        <Link to="/admin/providers" className="underline" style={{ color: "var(--brand)" }}>
          موتورهای هوش مصنوعی
        </Link>{" "}
        می‌آیند؛ انتخابِ سرور در بالا فقط وقتی اثر دارد که موتورِ تصویر/ویدیو «ComfyUI روی سرورِ پردازش» باشد.
      </div>
    </Card>
  );
}

function JobsTable({ jobs, onCancel }: { jobs: Job[]; onCancel: (j: Job) => void }) {
  return (
    <Card padded={false}>
      <div className="px-5 pt-5">
        <SectionTitle>کارها</SectionTitle>
      </div>
      <Table>
        <thead>
          <tr>
            <th>کار</th>
            <th>نوع</th>
            <th>وضعیت</th>
            <th>سرور</th>
            <th>خروجی</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {jobs.length === 0 && (
            <tr>
              <td colSpan={6} className="py-6 text-center" style={{ color: "var(--text-3)" }}>
                هنوز کاری ثبت نشده.
              </td>
            </tr>
          )}
          {jobs.map((j) => (
            <tr key={j.uid}>
              <td>
                <code className="text-xs" dir="ltr">{j.uid.slice(0, 8)}</code>
                <div className="text-xs" style={{ color: "var(--text-3)" }}>
                  {j.origin} · {ago(j.created)}
                </div>
              </td>
              <td className="text-sm">{j.kind}</td>
              <td>
                <Badge tone={stateTone(j.state)}>{j.state_label}</Badge>
                {j.dedupe && <Badge>تکراری</Badge>}
                {!j.final && (
                  <span className="u-num text-xs" style={{ color: "var(--text-2)" }}> {fa(Math.round(j.progress * 100))}٪</span>
                )}
                <div className="max-w-[260px] truncate text-xs" style={{ color: "var(--text-3)" }} title={j.message || j.error}>
                  {j.message || j.error}
                </div>
              </td>
              <td className="text-sm">{j.node || "—"}</td>
              <td>
                <div className="flex flex-wrap gap-1">
                  {j.outputs.map((o) => (
                    <OutputLink key={o.name} output={o} />
                  ))}
                </div>
              </td>
              <td>
                {!j.final && (
                  <Button size="sm" variant="ghost" onClick={() => onCancel(j)}>لغو</Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  );
}

/** خروجی‌ها با JWT محافظت می‌شوند؛ پس تصویرِ بندانگشتی با blob بار می‌شود، نه با <img src>. */
function OutputLink({ output }: { output: Output }) {
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const urlRef = useRef<string | null>(null);
  useEffect(() => {
    let alive = true;
    if (output.media === "image") {
      void api
        .get<Blob>(apiPath(output.url), { responseType: "blob" })
        .then(({ data }) => {
          if (!alive) return;
          urlRef.current = URL.createObjectURL(data);
          setSrc(urlRef.current);
        })
        .catch(() => undefined); // فایلِ خروجی نیست ⇐ فقط دکمهٔ دانلود می‌ماند
    }
    return () => {
      alive = false;
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    };
  }, [output.url, output.media]);
  // خطای دانلود بی‌صاحب نماند؛ دکمه قرمز می‌شود و title علت را می‌گوید
  const open = () => void downloadBlob(output.url, output.name).catch(() => setFailed(true));
  if (output.media === "image" && src) {
    return (
      <button type="button" onClick={open} title={failed ? `دانلود نشد: ${output.name}` : output.name} className="rounded-lg">
        <img src={src} alt={output.name} className="h-12 rounded-lg" />
      </button>
    );
  }
  return (
    <Button size="sm" variant={failed ? "danger" : "ghost"} onClick={open} title={failed ? "دانلود نشد — دوباره بزنید" : undefined}>
      <Icon name="download" size={13} /> {output.name}
    </Button>
  );
}

function SubmitCard({ onDone }: { onDone: () => Promise<void> }) {
  const [kind, setKind] = useState(KINDS[0].value);
  const [payload, setPayload] = useState(KINDS[0].example);
  const [node, setNode] = useState("");
  const [dedupe, setDedupe] = useState(true);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      const form = new FormData();
      form.append("kind", kind);
      form.append("payload", payload);
      form.append("node", node);
      form.append("dedupe", dedupe ? "1" : "0");
      if (file) {
        const field = kind.startsWith("video") ? "video" : kind.startsWith("voice") ? "audio" : "image";
        form.append(field, file);
      }
      const { data } = await api.post<Job>("/compute/submit/", form);
      setMsg(data.state === "COMPLETED" ? `قبلاً انجام شده بود؛ همان خروجی برگشت (${data.uid.slice(0, 8)})` : `ثبت شد: ${data.uid.slice(0, 8)}`);
      await onDone();
    } catch (err) {
      setMsg(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <SectionTitle>آزمایش</SectionTitle>
      <form onSubmit={submit} className="space-y-3">
        <Field label="نوعِ کار">
          <Select
            value={kind}
            onChange={(e) => {
              const k = KINDS.find((x) => x.value === e.target.value) || KINDS[0];
              setKind(k.value);
              setPayload(k.example);
            }}
          >
            {KINDS.map((k) => (
              <option key={k.value} value={k.value}>{k.label}</option>
            ))}
          </Select>
        </Field>
        <Field label="پارامترها (JSON)">
          <TextArea rows={5} dir="ltr" value={payload} onChange={(e) => setPayload(e.target.value)} />
        </Field>
        <Field label="فایلِ ورودی (اختیاری: عکس، ویدیو یا صدا)">
          <Input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </Field>
        <Field label="فقط این سرور (اختیاری)">
          <Input value={node} onChange={(e) => setNode(e.target.value)} placeholder="خالی = هر سرورِ توانا" />
        </Field>
        <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
          <input type="checkbox" checked={dedupe} onChange={(e) => setDedupe(e.target.checked)} />
          اگر عینِ همین کار قبلاً انجام شده، همان خروجی برگردد
        </label>
        <div className="flex items-center gap-3">
          <Button type="submit" disabled={busy}>
            {busy ? <Spinner size={16} /> : <Icon name="play" size={14} />} ثبتِ کار
          </Button>
          {msg && <span className="text-xs" style={{ color: "var(--text-2)" }}>{msg}</span>}
        </div>
      </form>
    </Card>
  );
}
