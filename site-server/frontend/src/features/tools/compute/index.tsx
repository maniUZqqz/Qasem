import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api, errorMessage } from "../../../api/client";
import { NodeAudioSection } from "../../audio/NodeAudioCard";
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
  /** نسخهٔ بستهٔ کدِ پردازش روی همین سایت (GET /compute/update/)؛ null = بسته‌ای نیست */
  agent_latest?: string | null;
  /** روی این سرور کدِ قدیمی‌تر از بستهٔ سایت است (START.bat بعدی یا دکمهٔ «به‌روزرسانی» تازه‌اش می‌کند) */
  update_waiting?: boolean;
  /** عاملِ ۲٫۰ به بالا: به‌روزرسانی از راهِ دور (کارِ node.update) */
  can_remote_update?: boolean;
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
  /** بستهٔ کدِ سرورِ پردازش که گره‌ها خودشان را با آن به‌روز می‌کنند */
  package?: { version?: string; id?: string; size?: number; built?: string };
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

/** فیلدِ فایلی که یک پیش‌تنظیم می‌خواهد. نامِ فیلد همان کلیدی است که بک‌اند (compute/submit) در payload.files می‌گذارد و عامل می‌خواند. */
type PresetFile = { field: "image" | "video" | "audio"; label: string; accept: string; hint: string };

/** پروفایلِ ComfyUI (upmarket_comfyui_flask/profiles.json روی سرورِ پردازش) با کنترل‌های پیش‌فرضش */
type PresetProfile = { id: string; label: string; controls: Record<string, number> };

/**
 * یک «پیش‌تنظیم» از فرمِ آزمایش: نوعِ کار + سرویسی که روی سرور باید روشن باشد + نمونهٔ معتبرِ payload + فایلی که
 * لازم دارد. کلیدهای payload همان‌هایی است که عاملِ سرورِ پردازش (processing-server/agent.py، تابع‌های h_*) می‌خواند؛
 * نامِ فایلِ آپلودشده را خودِ بک‌اند در payload.files.<field> می‌گذارد و عامل از همان‌جا برمی‌دارد.
 */
type Preset = {
  id: string;
  label: string;
  kind: string;
  /** کلیدِ سرویس در services/startable ِ سرور (CAPABILITY_PREFIXES در apps/compute/services.py)؛ null = هر سرورِ آنلاینی */
  service: ServiceKey | null;
  description: string;
  /** نمونهٔ معتبر — با انتخابِ پیش‌تنظیم در textarea می‌نشیند و قابلِ ویرایش است */
  example: Record<string, unknown>;
  file?: PresetFile;
  /** comfy.profile: انتخابِ پروفایل، کلیدهای profile و controls ِ payload را عوض می‌کند */
  profiles?: PresetProfile[];
  /** ollama: مدل از payload.model خوانده و با ollama_models ِ گزارش‌شدهٔ سرور سنجیده می‌شود */
  ollama?: boolean;
  /** مهلتِ کار به ثانیه (پیش‌فرضِ بک‌اند ۱۸۰۰)؛ ویدیو بیشتر می‌خواهد */
  timeout?: number;
  /** یادداشتِ مهم زیرِ توضیح (زمان، حافظه…) */
  note?: string;
};

const FLUX_IMAGE_PROFILES: PresetProfile[] = [
  { id: "flux-product-balanced", label: "متعادل — ۱۰۲۴×۱۰۲۴، ۲۴ گام (پیش‌فرض)", controls: { width: 1024, height: 1024, steps: 24, guidance: 3.5, seed: -1 } },
  { id: "flux-product-portrait", label: "عمودی — ۷۶۸×۱۰۲۴ برای پست و استوری", controls: { width: 768, height: 1024, steps: 24, guidance: 3.5, seed: -1 } },
  { id: "flux-product-fast", label: "سریع — ۷۶۸×۷۶۸، ۲۰ گام برای آزمایشِ پرامپت", controls: { width: 768, height: 768, steps: 20, guidance: 3.5, seed: -1 } },
];
const FLUX_EDIT_PROFILES: PresetProfile[] = [
  { id: "flux-edit-balanced", label: "ویرایشِ متعادل — denoise ۰٫۵۸", controls: { width: 1024, height: 576, steps: 24, denoise: 0.58, guidance: 3.5, seed: -1 } },
  { id: "flux-edit-preserve", label: "حفظِ بیشترِ عکسِ اصلی — denoise ۰٫۴", controls: { width: 1024, height: 576, steps: 24, denoise: 0.4, guidance: 3.0, seed: -1 } },
];
const WAN_PROFILES: PresetProfile[] = [
  { id: "wan22-480p-short", label: "کوتاه — ۱۷ فریم (حدود ۱ ثانیه)، ۸۳۲×۴۸۰", controls: { width: 832, height: 480, length: 17, steps: 8, seed: -1 } },
  { id: "wan22-480p-long", label: "طولانی‌تر — ۳۳ فریم (حدود ۲ ثانیه)، حافظه و زمانِ بیشتر", controls: { width: 832, height: 480, length: 33, steps: 8, seed: -1 } },
];

const IMAGE_FILE = (hint: string): PresetFile => ({ field: "image", label: "عکسِ ورودی (الزامی)", accept: "image/*", hint });

const PRESETS: Preset[] = [
  {
    id: "flux-image",
    label: "تصویر با FLUX",
    kind: "comfy.profile",
    service: "comfyui",
    description:
      "از روی متن (prompt) یک تصویرِ تازه با FLUX روی ComfyUI می‌سازد؛ فایلی لازم نیست. prompt را انگلیسی بنویسید (مدل فارسی را خوب نمی‌فهمد)؛ negative_prompt چیزهایی است که نباشد. خروجی یک PNG است که در جدولِ «کارها» دیده می‌شود.",
    example: {
      profile: "flux-product-balanced",
      prompt: "a red ceramic coffee mug on a wooden table, soft studio light, clean product photo",
      negative_prompt: "blurry, text, watermark",
      controls: { ...FLUX_IMAGE_PROFILES[0].controls },
    },
    profiles: FLUX_IMAGE_PROFILES,
    note: "روی RTX 3060 معمولاً کمتر از یک دقیقه. seed = -1 یعنی هر بار تصادفی.",
  },
  {
    id: "wan-video",
    label: "ویدیو با Wan 2.2",
    kind: "comfy.profile",
    service: "comfyui",
    description:
      "از یک عکسِ مرجع یک ویدیوی کوتاهِ 480p با Wan 2.2 می‌سازد (عکس ⇐ ویدیو). عکس الزامی است؛ prompt حرکتی را توصیف می‌کند که باید اتفاق بیفتد (انگلیسی). length تعدادِ فریم است (۱۶ فریم بر ثانیه).",
    example: {
      profile: "wan22-480p-short",
      prompt: "the mug slowly rotates on the table, gentle camera push-in, soft studio light",
      negative_prompt: "blurry, distorted, text, watermark",
      controls: { ...WAN_PROFILES[0].controls },
    },
    profiles: WAN_PROFILES,
    file: IMAGE_FILE("اولین فریمِ ویدیو همین عکس است. نامش خودکار در payload.files.image می‌رود."),
    timeout: 3600,
    note: "روی RTX 3060 چند دقیقه طول می‌کشد (پروفایلِ طولانی بیشتر). اول «کوتاه» را امتحان کنید؛ اگر حافظهٔ گرافیک کم آمد به همان برگردید. مهلتِ این کار یک ساعت است.",
  },
  {
    id: "flux-edit",
    label: "ویرایشِ تصویر با FLUX",
    kind: "comfy.profile",
    service: "comfyui",
    description:
      "عکسِ مرجع را با FLUX بازسازی می‌کند و تغییرِ خواسته‌شده در prompt را اعمال می‌کند (img2img). عکس الزامی است. denoise کمتر = وفاداریِ بیشتر به عکسِ اصلی، بیشتر = تغییرِ بیشتر.",
    example: {
      profile: "flux-edit-balanced",
      prompt: "the same mug, now matte black, on a marble table, soft studio light",
      negative_prompt: "blurry, text, watermark",
      controls: { ...FLUX_EDIT_PROFILES[0].controls },
    },
    profiles: FLUX_EDIT_PROFILES,
    file: IMAGE_FILE("عکسی که باید ویرایش شود. نامش خودکار در payload.files.image می‌رود."),
  },
  {
    id: "photo-edit",
    label: "ویرایشگرِ عکس (PersianAiKit)",
    kind: "photo.edit",
    service: "photo",
    description:
      "عکس را به ویرایشگرِ عکسِ PersianAiKit (سرویسِ «عکس» روی سرور) می‌دهد. با auto: true نسخهٔ خودکار (نور، رنگ، برش) اعمال می‌شود؛ به‌جایش می‌توانید recipe بدهید. خروجی عکسِ ویرایش‌شده است.",
    example: { auto: true },
    file: IMAGE_FILE("عکسی که باید ویرایش شود. نامش خودکار در payload.files.image می‌رود."),
  },
  {
    id: "photo-analyze",
    label: "تحلیلِ عکس (PersianAiKit)",
    kind: "photo.analyze",
    service: "photo",
    description:
      "عکس را تحلیل می‌کند (سرویسِ «عکس») و نتیجه را به‌صورت JSON برمی‌گرداند (analyze.json). پارامتری ندارد؛ ورودی فقط فایل است.",
    example: {},
    file: IMAGE_FILE("نامش خودکار در payload.files.image می‌رود."),
  },
  {
    id: "video-edit",
    label: "ویرایشگرِ ویدیو (PersianAiKit)",
    kind: "video.edit",
    service: "video",
    description:
      "ویدیو را به ویرایشگرِ ویدیوی PersianAiKit (سرویسِ «ویدیو») می‌دهد؛ با auto: true نسخهٔ خودکار ساخته و خروجیِ MP4 گرفته می‌شود. به‌جای auto می‌توانید recipe بدهید.",
    example: { auto: true },
    file: { field: "video", label: "ویدیوی ورودی (الزامی)", accept: "video/*", hint: "نامش خودکار در payload.files.video می‌رود." },
    timeout: 3600,
    note: "خروجی‌گرفتن طول می‌کشد؛ مهلتِ این کار یک ساعت است.",
  },
  {
    id: "tts",
    label: "متن به گفتار",
    kind: "voice.tts",
    service: "voice",
    description:
      "متنِ فارسی را با سرویسِ «صدا»ی PersianAiKit می‌خواند؛ خروجی speech.wav. فقط text لازم است؛ voice، engine، speed و seed اختیاری‌اند (اگر ننویسید پیش‌فرضِ سرویس).",
    example: { text: "سلام، این یک آزمایش است." },
  },
  {
    id: "asr",
    label: "گفتار به متن",
    kind: "voice.asr",
    service: "voice",
    description:
      "فایلِ صدا را به متن تبدیل می‌کند (asr.json). phrases واژه‌های مورد انتظار است (اختیاری، برای دقتِ بیشتر؛ خالی یعنی هیچ).",
    example: { phrases: [] },
    file: { field: "audio", label: "فایلِ صدا (الزامی)", accept: "audio/*", hint: "wav یا mp3. نامش خودکار در payload.files.audio می‌رود." },
  },
  {
    id: "ollama-chat",
    label: "گفتگو با Ollama",
    kind: "ollama.chat",
    service: "ollama",
    description:
      "یک پرسشِ متنی به مدلِ Ollama روی GPU. بدنه همان /api/chat ِ Ollama است: model و messages. خروجی ollama.json (پاسخ در message.content).",
    example: { model: "qwq:32b", messages: [{ role: "user", content: "سلام! در یک جمله بگو چه کاری از دستت برمی‌آید." }], stream: false },
    ollama: true,
  },
  {
    id: "ollama-vision",
    label: "بیناییِ Ollama (عکس + پرسش)",
    kind: "ollama.chat",
    service: "ollama",
    description:
      "یک عکس را به مدلِ بیناییِ Ollama نشان می‌دهد و درباره‌اش می‌پرسد. در images باید نامِ فایلِ آپلودشده باشد — با انتخابِ فایل خودکار پر می‌شود؛ عامل همان فایل را base64 می‌کند و به Ollama می‌دهد.",
    example: { model: "qwen3-vl:30b", messages: [{ role: "user", content: "این عکس چیست؟ کوتاه و به فارسی.", images: [] }], stream: false },
    file: IMAGE_FILE("با انتخابِ فایل، نامش در messages[…].images می‌نشیند. نامِ فایل بهتر است لاتین باشد."),
    ollama: true,
  },
  {
    id: "comfy-graph",
    label: "گرافِ خامِ ComfyUI",
    kind: "comfy.graph",
    service: "comfyui",
    description:
      "یک گرافِ خامِ ComfyUI (قالبِ API: شناسه ⇐ class_type + inputs) بی‌هیچ پروفایلی. گراف باید یک گرهٔ خروجی مثل SaveImage داشته باشد وگرنه ComfyUI «Prompt has no outputs» می‌دهد. نمونهٔ زیر یک تصویرِ خالیِ ۵۱۲×۵۱۲ می‌سازد و ذخیره می‌کند — برای آزمونِ مسیر کافی است. فایل‌های ورودی (اختیاری) با uploads: [نام‌ها] به ComfyUI داده می‌شوند.",
    example: {
      graph: {
        "1": { class_type: "EmptyImage", inputs: { width: 512, height: 512, batch_size: 1, color: 0 } },
        "2": { class_type: "SaveImage", inputs: { filename_prefix: "nm_test", images: ["1", 0] } },
      },
    },
  },
  {
    id: "echo",
    label: "echo — فقط آزمونِ اتصال",
    kind: "echo",
    service: null,
    description: "هیچ موتوری درگیر نمی‌شود: سرور payload را همان‌طور در echo.json برمی‌گرداند. sleep ثانیه‌های مکث است. برای این‌که ببینید صف و اتصال کار می‌کند.",
    example: { sleep: 2 },
  },
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

  /** «به‌روزرسانی» ِ یک سرور: کارِ node.update در صفِ همان سرور؛ وقتی بی‌کار شد کدِ تازه را می‌گیرد و دوباره روشن می‌شود */
  const [updateAsked, setUpdateAsked] = useState<Record<number, string>>({});
  const updateNode = async (node: Node) => {
    try {
      await api.post(`/compute/nodes/${node.id}/update/`);
      setUpdateAsked((prev) => ({
        ...prev,
        [node.id]: node.online ? "در صف؛ بعد از کارِ جاری به‌روز و دوباره روشن می‌شود" : "در صف؛ وقتی سرور روشن شد",
      }));
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
                        {n.update_waiting && n.agent_latest && (
                          <span
                            className="inline-flex flex-wrap items-center gap-1"
                            title="روی سایت بستهٔ تازه‌تری از کدِ سرورِ پردازش هست. START.bat هر بار خودش به‌روز می‌کند؛ Update.bat یا این دکمه همین حالا."
                          >
                            <Badge tone="warn">
                              نسخهٔ تازه <span dir="ltr">{n.agent_latest}</span>
                            </Badge>
                            {updateAsked[n.id] ? (
                              <span>{updateAsked[n.id]}</span>
                            ) : n.can_remote_update ? (
                              <Button size="sm" variant="ghost" onClick={() => void updateNode(n)}>
                                <Icon name="refresh" size={12} /> به‌روزرسانی
                              </Button>
                            ) : (
                              <span>یک بار بستهٔ تازه را دانلود و START.bat را بزنید</span>
                            )}
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

      {/* مدل‌های صدا: روشن/خاموش، تست، وضعیتِ نصب و دانلودِ هر سرور */}
      <NodeAudioSection nodes={nodes} />

      <RouteCard nodes={nodes} settings={settings} settingsError={settingsError} onSettings={setSettings} onRefresh={loadSettings} />

      <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
        <JobsTable jobs={jobs} onCancel={cancelJob} />
        <SubmitCard nodes={nodes} onDone={load} />
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
  const pkg = settings?.package;
  const [dl, setDl] = useState(false);
  const downloadPackage = async () => {
    setDl(true);
    try {
      await downloadBlob("/api/v1/compute/update/package/", `processing-server-${pkg?.version ?? ""}.zip`);
      if (alive.current) setErr(null);
    } catch (e) {
      if (alive.current) setErr(errorMessage(e));
    } finally {
      if (alive.current) setDl(false);
    }
  };

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
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button size="sm" variant="secondary" disabled={!pkg?.version || dl} onClick={() => void downloadPackage()}>
              {dl ? <Spinner size={13} /> : <Icon name="download" size={13} />} دانلودِ بستهٔ سرورِ پردازش (zip)
            </Button>
            {pkg?.version && (
              <span className="text-xs" style={{ color: "var(--text-3)" }}>
                نسخهٔ <span dir="ltr">{pkg.version}</span>
                {pkg.size ? <> · {fa(Math.round(pkg.size / 1048576))} مگابایت</> : null} — بی GitHub، از همین سایت
              </span>
            )}
          </div>
        </div>
        <ol className="space-y-1.5 text-sm leading-7" style={{ color: "var(--text-2)" }}>
          <li>۱) بستهٔ سرورِ پردازش را (دکمهٔ کنارِ کلید، یا از مخزن) روی کامپیوترِ گرافیکی باز کنید.</li>
          <li>۲) START.bat را اجرا کنید و این کلید را بدهید — کامپیوتر با نامِ خودش ثبت می‌شود.</li>
          <li>۳) ComfyUI را روشن کنید؛ چند ثانیه بعد این‌جا «آنلاین» می‌شود.</li>
          <li>
            ۴) کارِ دیگری لازم نیست: START.bat هر بار همه‌چیز را چک می‌کند (پایتون، git، سایت، ffmpeg، ‎.NET، ComfyUI،
            کارتِ گرافیک، مدل‌ها، دیسک) و مدل‌های پیش‌فرض (گفتار و کلونِ صدا، صدای محیط، موسیقی، موتورِ اصلیِ ویدیو) را اگر
            نباشند خودش در پس‌زمینه دانلود می‌کند؛ فایلی که ComfyUI دارد دوباره دانلود نمی‌شود. پیشرفت، «تست» و روشن/خاموشِ
            هر مدل در «مدل‌های صدا» پایینِ همین صفحه است.
          </li>
          <li>
            ۵) به‌روزرسانی: START.bat هر بار خودش کدِ تازه را از همین سایت می‌گیرد (یا Update.bat، یا دکمهٔ «به‌روزرسانی»
            کنارِ سرور). مدل‌ها، محیط‌های پایتون و شناسنامهٔ سرور در پوشهٔ دادهٔ جدا (NMarketing-data) می‌مانند و با نسخهٔ
            تازه دوباره دانلود نمی‌شوند؛ بارِ اول، پوشهٔ قدیمی را خودش پیدا و منتقل می‌کند.
          </li>
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

function pretty(o: unknown): string {
  return JSON.stringify(o, null, 2);
}

/** payload ِ متنی را به‌عنوان شیء می‌خواند؛ JSON نامعتبر یا غیرِ شیء ⇐ null */
function parsePayload(text: string): Record<string, unknown> | null {
  try {
    const v: unknown = JSON.parse(text);
    return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

/** یک تغییر روی payload ِ متنی؛ اگر متن خراب بود از نمونهٔ پیش‌تنظیم شروع می‌کند */
function patchPayload(
  text: string,
  fallback: Record<string, unknown>,
  fn: (o: Record<string, unknown>) => Record<string, unknown>,
): string {
  return pretty(fn(parsePayload(text) ?? { ...fallback }));
}

/** ollama با عکس: نامِ فایلِ آپلودشده باید در images ِ آخرین پیام باشد (عامل همان نام را base64 می‌کند) */
function withOllamaImage(o: Record<string, unknown>, name: string): Record<string, unknown> {
  const msgs = Array.isArray(o.messages) ? [...(o.messages as unknown[])] : [];
  const last = msgs.length ? msgs[msgs.length - 1] : null;
  if (last && typeof last === "object" && !Array.isArray(last)) {
    msgs[msgs.length - 1] = { ...(last as Record<string, unknown>), images: [name] };
  } else {
    msgs.push({ role: "user", content: "این عکس چیست؟ کوتاه و به فارسی.", images: [name] });
  }
  return { ...o, messages: msgs };
}

/** caps.startable[key] از آخرین heartbeat: عاملِ گره می‌تواند خودش این سرویس را روشن کند */
function startable(n: Node, key: string): boolean {
  const s = n.capabilities?.startable;
  return Boolean(s && typeof s === "object" && (s as Record<string, unknown>)[key]);
}

/** فهرستِ رشته‌ای از capabilities (ollama_models، comfy_profiles)؛ گزارش‌نشده ⇐ خالی */
function listOf(n: Node, key: string): string[] {
  const v = n.capabilities?.[key];
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
}

/**
 * این پیش‌تنظیم الان قابلِ اجراست؟ همان قاعدهٔ بک‌اند (services.enqueue/online_nodes + ComputeNode.has):
 * سرورِ آنلاینی که سرویس را روشن دارد، یا با سوئیچِ خودکار می‌تواند روشنش کند؛ وگرنه ثبت با ۵۰۳ رد می‌شود.
 */
function availability(preset: Preset, nodes: Node[]): { tone: Tone; text: string } {
  const enabled = nodes.filter((n) => n.enabled);
  const online = enabled.filter((n) => n.online);
  const names = (xs: Node[]) => xs.map((n) => n.name).join("، ");
  if (!preset.service) {
    return online.length
      ? { tone: "ok", text: `هر سرورِ آنلاینی انجامش می‌دهد (${names(online)})` }
      : { tone: "bad", text: "هیچ سروری آنلاین نیست — ثبت پذیرفته نمی‌شود تا یکی وصل شود" };
  }
  const key = preset.service;
  const label = SERVICE_LABELS[key];
  const ready = online.filter((n) => n.services?.[key]);
  if (ready.length) return { tone: "ok", text: `${label} روی ${names(ready)} روشن است — آماده` };
  const can = online.filter((n) => startable(n, key));
  const auto = can.filter((n) => n.auto_switch);
  if (auto.length) return { tone: "warn", text: `${label} الان خاموش است؛ ${names(auto)} با سوئیچِ خودکار پیش از کار روشنش می‌کند` };
  if (can.length)
    return { tone: "bad", text: `${label} خاموش است و سوئیچِ خودکارِ ${names(can)} هم خاموش — در کشوی «سرویس‌ها» روشنش کنید` };
  if (online.length) return { tone: "bad", text: `هیچ سرورِ آنلاینی ${label} ندارد — ثبت پذیرفته نمی‌شود` };
  const last = enabled.filter((n) => n.services?.[key] || startable(n, key));
  return last.length
    ? { tone: "bad", text: `هیچ سروری آنلاین نیست — ${names(last)} طبق آخرین گزارشش ${label} را دارد؛ تا وصل نشود ثبت پذیرفته نمی‌شود` }
    : { tone: "bad", text: `هیچ سروری آنلاین نیست و هیچ‌کدام ${label} را گزارش نکرده‌اند` };
}

/**
 * «آزمایش»: فرمِ پیش‌تنظیم‌ها. هر پیش‌تنظیم توضیحِ خودش، payload ِ معتبر و فایلِ لازمش را می‌آورد و می‌گوید
 * کدام سرویس را می‌خواهد و آیا سروری آن را دارد. ثبت همان POST /compute/submit/ (multipart) است:
 * kind + payload (JSON) + timeout + فایل با نامِ فیلدِ خودش (image/video/audio).
 */
function SubmitCard({ nodes, onDone }: { nodes: Node[]; onDone: () => Promise<void> }) {
  const [presetId, setPresetId] = useState(PRESETS[0].id);
  const preset = PRESETS.find((p) => p.id === presetId) ?? PRESETS[0];
  const [payload, setPayload] = useState(() => pretty(PRESETS[0].example));
  const [node, setNode] = useState("");
  const [dedupe, setDedupe] = useState(true);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: Tone; text: string } | null>(null);

  const choosePreset = (id: string) => {
    const p = PRESETS.find((x) => x.id === id) ?? PRESETS[0];
    setPresetId(p.id);
    setPayload(pretty(p.example));
    setFile(null); // ورودیِ فایل با key={preset.id} از نو ساخته می‌شود
    setMsg(null);
  };

  const chooseProfile = (id: string) => {
    const prof = preset.profiles?.find((x) => x.id === id);
    if (!prof) return;
    setPayload((t) => patchPayload(t, preset.example, (o) => ({ ...o, profile: prof.id, controls: { ...prof.controls } })));
  };

  const chooseFile = (f: File | null) => {
    setFile(f);
    if (f && preset.ollama && preset.file?.field === "image") {
      setPayload((t) => patchPayload(t, preset.example, (o) => withOllamaImage(o, f.name)));
    }
  };

  const parsed = parsePayload(payload);
  const currentProfile = typeof parsed?.profile === "string" ? parsed.profile : "";
  const currentModel = typeof parsed?.model === "string" ? parsed.model : "";
  const avail = availability(preset, nodes);
  const enabledNodes = nodes.filter((n) => n.enabled);
  // ollama: مدل‌هایی که سرورها گزارش کرده‌اند (اتحادِ همه)؛ خالی = گزارش نشده، پس چیزی نمی‌گوییم
  const models = preset.ollama ? Array.from(new Set(enabledNodes.flatMap((n) => listOf(n, "ollama_models")))) : [];
  const modelMissing = Boolean(preset.ollama && currentModel && models.length && !models.includes(currentModel));
  const knownProfiles = preset.profiles ? Array.from(new Set(enabledNodes.flatMap((n) => listOf(n, "comfy_profiles")))) : [];
  const profileMissing = Boolean(preset.profiles && currentProfile && knownProfiles.length && !knownProfiles.includes(currentProfile));
  const profileInList = Boolean(preset.profiles?.some((p) => p.id === currentProfile));
  const rows = Math.min(18, Math.max(5, payload.split("\n").length + 1));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setMsg(null);
    if (!parsed) {
      setMsg({ tone: "bad", text: "پارامترها JSON معتبر نیست — باید یک شیء {…} باشد." });
      return;
    }
    if (preset.file && !file) {
      setMsg({ tone: "bad", text: `این پیش‌تنظیم «${preset.file.label}» لازم دارد.` });
      return;
    }
    setBusy(true);
    try {
      const form = new FormData();
      form.append("kind", preset.kind);
      form.append("payload", payload);
      form.append("node", node);
      form.append("dedupe", dedupe ? "1" : "0");
      if (preset.timeout) form.append("timeout", String(preset.timeout));
      if (preset.file && file) form.append(preset.file.field, file);
      const { data } = await api.post<Job>("/compute/submit/", form);
      setMsg(
        data.state === "COMPLETED"
          ? { tone: "ok", text: `قبلاً انجام شده بود؛ همان خروجی برگشت (${data.uid.slice(0, 8)})` }
          : { tone: "ok", text: `ثبت شد: ${data.uid.slice(0, 8)} — در جدولِ «کارها» دنبالش کنید` },
      );
      await onDone();
    } catch (err) {
      setMsg({ tone: "bad", text: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  const availColor = avail.tone === "neutral" ? "var(--text-3)" : `var(--${avail.tone})`;
  const availIcon: IconName = avail.tone === "ok" ? "ok" : avail.tone === "warn" ? "warn" : "ban";

  return (
    <Card>
      <SectionTitle>آزمایش</SectionTitle>
      <p className="-mt-1 mb-3 text-xs" style={{ color: "var(--text-3)" }}>
        یک پیش‌تنظیم انتخاب کنید؛ توضیح، پارامترهای قابلِ ویرایش و فایلِ لازمش همین‌جا می‌آید. نتیجه در جدولِ «کارها» می‌نشیند.
      </p>
      <form onSubmit={submit} className="space-y-3">
        <Field label="چه کاری؟">
          <Select value={preset.id} onChange={(e) => choosePreset(e.target.value)}>
            {PRESETS.map((p) => (
              <option key={p.id} value={p.id}>{p.label}</option>
            ))}
          </Select>
        </Field>

        <div
          className="rounded-lg px-3 py-2 text-sm leading-6"
          style={{ background: "var(--surface-2)", border: "1px solid var(--line)", color: "var(--text-2)" }}
        >
          <div>{preset.description}</div>
          {preset.note && (
            <div className="mt-1 flex items-start gap-1 text-xs" style={{ color: "var(--warn)" }}>
              <Icon name="clock" size={12} /> <span>{preset.note}</span>
            </div>
          )}
          <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs" style={{ color: "var(--text-3)" }}>
            <span>
              نوعِ کار: <code dir="ltr">{preset.kind}</code>
            </span>
            <span>·</span>
            <span className="inline-flex items-center gap-1">
              سرویسِ لازم: {preset.service ? <Badge tone="brand">{SERVICE_LABELS[preset.service]}</Badge> : <Badge>هیچ</Badge>}
            </span>
            {preset.file && (
              <>
                <span>·</span>
                <span>
                  فایل: <code dir="ltr">{preset.file.field}</code>
                </span>
              </>
            )}
          </div>
          <div className="mt-1 flex items-start gap-1 text-xs" style={{ color: availColor }}>
            <span className="mt-0.5 shrink-0"><Icon name={availIcon} size={12} /></span>
            <span>{avail.text}</span>
          </div>
        </div>

        {preset.profiles && (
          <Field
            label="پروفایل"
            hint={
              profileMissing
                ? `سرور پروفایلِ «${currentProfile}» را گزارش نکرده؛ پروفایل‌های سرور: ${knownProfiles.join("، ")}`
                : "انتخاب، کلیدهای profile و controls را در پارامترها عوض می‌کند؛ بعدش هم می‌توانید دستی تغییر دهید."
            }
          >
            <Select value={profileInList ? currentProfile : ""} onChange={(e) => chooseProfile(e.target.value)}>
              {!profileInList && <option value="">— (در پارامترها دستی نوشته شده)</option>}
              {preset.profiles.map((p) => (
                <option key={p.id} value={p.id}>{p.label}</option>
              ))}
            </Select>
          </Field>
        )}

        <Field
          label="پارامترها (JSON) — قابلِ ویرایش"
          hint={
            !parsed
              ? "JSON نامعتبر است — باید یک شیء {…} باشد"
              : modelMissing
                ? `مدلِ «${currentModel}» روی سرور نیست؛ مدل‌های گزارش‌شده: ${models.slice(0, 12).join("، ")}${models.length > 12 ? "، …" : ""}`
                : preset.ollama && models.length
                  ? `مدل‌های روی سرور (${fa(models.length)}): ${models.slice(0, 8).join("، ")}${models.length > 8 ? "، …" : ""}`
                  : undefined
          }
        >
          <TextArea
            rows={rows}
            dir="ltr"
            className="font-mono text-xs"
            value={payload}
            onChange={(e) => setPayload(e.target.value)}
            style={{ borderColor: parsed ? undefined : "var(--bad)" }}
          />
        </Field>

        {preset.file && (
          <Field label={preset.file.label} hint={preset.file.hint}>
            <Input
              key={preset.id}
              type="file"
              accept={preset.file.accept}
              onChange={(e) => chooseFile(e.target.files?.[0] ?? null)}
            />
          </Field>
        )}

        <Field label="فقط این سرور (اختیاری)">
          <Select value={node} onChange={(e) => setNode(e.target.value)}>
            <option value="">هر سرورِ توانا</option>
            {enabledNodes.map((n) => (
              <option key={n.id} value={n.name}>
                {n.name}
                {n.online ? "" : " (خاموش)"}
              </option>
            ))}
          </Select>
        </Field>
        <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
          <input type="checkbox" checked={dedupe} onChange={(e) => setDedupe(e.target.checked)} />
          اگر عینِ همین کار قبلاً انجام شده، همان خروجی برگردد
        </label>
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={busy || !parsed}>
            {busy ? <Spinner size={16} /> : <Icon name="play" size={14} />} ثبتِ کار
          </Button>
          {msg && (
            <span className="text-xs" style={{ color: msg.tone === "bad" ? "var(--bad)" : "var(--ok)" }}>
              {msg.text}
            </span>
          )}
        </div>
      </form>
    </Card>
  );
}
