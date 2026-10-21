/**
 * شکلِ داده‌های «ویدیوی سه‌بعدی» — همان JSON ای که backend/apps/up3d/{api,panel}.py می‌فرستد.
 *
 * سندِ صحنه (`SceneDoc`) قراردادِ مشترکِ AI، SDK و ویرایشگر است (up3d.scene/1)؛
 * شش شیارِ خطِ زمان همه یک شکلِ «قطعه» (`Item`) دارند و فقط فیلدهای معنادارشان فرق می‌کند.
 */

export type Level = "error" | "warning" | "info";

export type Issue = { level: Level; code: string; path: string; message: string };

export type Report = {
  ok: boolean;
  errors: number;
  warnings: number;
  issues: Issue[];
  timeline?: unknown[];
  changes?: string[];
};

/** مشخصاتِ یک پارامتر در manifest ِ دارایی (params). */
export type ParamSpec = {
  type?: "number" | "int" | "bool" | "enum" | "color" | "text" | "file" | "product_ref" | "surface_ref" | string;
  default?: unknown;
  values?: (string | number)[];
  min?: number;
  max?: number;
  label?: string;
  required?: boolean;
};

export type Asset = {
  id: string;
  kind: string;
  label: string;
  name?: { fa?: string; en?: string };
  description?: { fa?: string; en?: string };
  has_thumbnail: boolean;
  has_preview: boolean;
  default?: boolean;
  order?: number;
  license?: string;
  params?: Record<string, ParamSpec>;
  /** شناسهٔ بستهٔ دارایی (data/asset-packs/<pack>) — دارایی‌های خودِ موتور null */
  pack?: string | null;
};

export type Motion = Asset & {
  category: string;
  duration: { min: number; default: number; max: number };
  layer?: boolean;
  product?: { requires?: string; effect?: string; param?: string };
  hands?: { uses?: string; param?: string; requires_free?: boolean };
};

export type Environment = Asset & {
  marks: Record<string, unknown>;
  surfaces: Record<string, unknown>;
  default_lighting?: string;
};

export type Shot = Asset & {
  framing: { height: number; lens: number; fstop: number };
  moves: string[];
  subject: string;
};

export type ProductAsset = Asset & { dimensions: number[]; grasp: { height: number } };

export type Character = Asset & { gender: string; provider: string };

export type RenderProfile = Asset & {
  engine: string;
  resolution: { long: number };
  samples?: number;
  recommended: "cpu" | "gpu";
  frame_step?: number;
  denoise?: boolean;
  motion_blur?: boolean;
  adaptive_threshold?: number;
  bounces?: Record<string, number>;
  est_sec_per_frame_cpu?: number;
  quality?: Record<string, unknown>;
};

/** تنظیمِ دستیِ کیفیت روی یک پروفایل (بخشِ «کیفیت و رندر» ⇐ تنظیماتِ پیشرفته) — همان کلیدهای compiler.clean_quality */
export type QualityOverride = {
  resolution?: number;
  samples?: number;
  frame_step?: number;
  denoise?: boolean;
  motion_blur?: boolean;
};

/** چرا کار هنوز کارگر ندارد (api.job_json ⇐ services.waiting_info) */
export type Waiting = {
  needs_gpu: boolean;
  allow_cpu: boolean;
  online: string[];
  eligible: string[];
  /** کارگرهای GPU ِ آنلاین (اولویت با آن‌هاست) */
  gpu_online?: string[];
  /** سرورهای پردازشِ دارای GPU و آمادگیِ رندرِ سه‌بعدی‌شان */
  gpu_nodes?: GpuNode[];
};

/** سرورِ پردازشِ دارای GPU (apps.compute) از نگاهِ بخشِ سه‌بعدی — services.gpu_nodes() */
export type GpuNode = {
  id: number;
  name: string;
  online: boolean;
  gpu: string | string[] | null;
  agent?: string | null;
  /** Blender روی آن گره پیدا شده؟ (اگر نه، worker-3d.bat یک بار دانلودش می‌کند) */
  blender: boolean;
  worker3d_running: boolean;
  managed?: "agent" | "external" | "off" | null;
  startable: boolean;
  /** خواستهٔ پنل برای «رندرِ سه‌بعدی»: true/false یا undefined = پیش‌فرض (خودکار وقتی کارِ سه‌بعدی منتظر است) */
  desired?: boolean | null;
  auto_switch: boolean;
  worker_online: boolean;
  worker_gpu: boolean;
  worker_blender?: string | null;
  /** نسخهٔ up3d ِ کارگرِ آن گره؛ کمتر از 1.1 ⇐ پوشهٔ processing قدیمی است و کار نمی‌گیرد */
  worker_version?: string | null;
  worker_capable?: boolean;
  /** دادهٔ کاراکترهای MPFB روی آن گره هست؟ */
  worker_mpfb?: boolean | null;
};

// ───────────────────────── بسته‌های دارایی

export type PackAssetRow = { kind: string; id: string; name?: { fa?: string; en?: string } | null; active?: boolean };

export type AssetPack = {
  id: string;
  name: string;
  description?: string;
  enabled: boolean;
  installed?: string;
  source?: string;
  size?: number;
  assets: PackAssetRow[];
  problems?: { file: string; error: string }[];
};

export type PackReportAsset = { kind: string; id: string | null; label?: string; folder: string; errors: string[]; warnings: string[] };

export type PackReport = {
  ok: boolean;
  pack: string | null;
  name: string | null;
  assets: PackReportAsset[];
  errors: string[];
  warnings: string[];
  dry_run: boolean;
  size?: number;
  message?: string;
};

export type Voice = Asset & { gender: string; provider: string; voice?: string };

export type Catalog = {
  character: Character[];
  motion: Motion[];
  environment: Environment[];
  product: ProductAsset[];
  lighting: Asset[];
  shot: Shot[];
  render_profile: RenderProfile[];
  voice: Voice[];
  overlay_style: Asset[];
  music: Asset[];
  template: Asset[];
};

export type CatalogKind = keyof Catalog;

// ───────────────────────── سندِ صحنه

export type Track = "actions" | "speech" | "expressions" | "gaze" | "shots" | "overlays";

export type Item = {
  id?: string;
  start: number;
  duration?: number;
  /** actions/speech/expressions/gaze */
  actor?: string | null;
  motion?: string;
  text?: string;
  voice?: string;
  style?: string;
  shot?: string;
  subject?: string;
  move?: string;
  expression?: string;
  intensity?: number;
  target?: string;
  type?: string;
  position?: string;
  params?: Record<string, unknown>;
};

export type Actor = { id: string; character: string; mark: string; params?: Record<string, unknown> };

export type ProductRef = {
  id: string;
  asset: string;
  name?: string;
  surface?: string;
  params?: Record<string, unknown>;
};

export type SceneDoc = {
  format: string;
  meta: { title?: string; language?: string; source?: string; brief?: Record<string, unknown>; [k: string]: unknown };
  output: { aspect: string; fps: number; duration: number };
  environment: { id: string; params: Record<string, unknown> };
  lighting: { id: string; params: Record<string, unknown> };
  actors: Actor[];
  products: ProductRef[];
  actions: Item[];
  speech: Item[];
  expressions: Item[];
  gaze: Item[];
  shots: Item[];
  overlays: Item[];
  audio: { music?: string | null; music_volume?: number; subtitles?: boolean; voice_volume?: number };
};

// ───────────────────────── کارها و پروژه‌ها

export type JobState =
  | "PENDING"
  | "PLANNING"
  | "PLANNED"
  | "SCENE_BUILDING"
  | "RENDERING"
  | "QUALITY_CHECK"
  | "ASSEMBLING"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED";

export type JobKind = "plan" | "render" | "export" | "contact" | "thumbnail";

export type QCCheck = { level: "pass" | "warn" | "fail"; message: string };

export type QC = { result?: "pass" | "warn" | "fail"; checks?: QCCheck[] };

export type Job = {
  id: number;
  uid: string;
  kind: JobKind;
  kind_label: string;
  profile: string;
  state: JobState;
  state_label: string;
  progress: number;
  frames_done: number;
  frames_total: number;
  sec_per_frame: number | null;
  message: string;
  error: string;
  worker: string | null;
  estimate_seconds: number | null;
  created: string;
  started: string | null;
  finished: string | null;
  final: boolean;
  project: number | null;
  project_title: string | null;
  version: number | null;
  files: Record<string, string>;
  cancel_requested: boolean;
  eta_seconds?: number;
  /** فقط وقتی کار آمادهٔ کارگر است ولی هنوز کارگری نگرفته */
  waiting?: Waiting | null;
  quality?: QualityOverride | null;
  /** فقط در جزئیاتِ کار (light=false) */
  log?: string;
  qc?: QC;
  report?: { engine?: Record<string, unknown>; director?: Record<string, unknown> };
  params?: Record<string, unknown>;
};

export type ProjectResult = {
  video: string;
  poster: string;
  job: number;
  profile: string;
  qc: string | null;
};

export type ProjectLite = {
  id: number;
  uid: string;
  title: string;
  brief: Record<string, unknown>;
  created: string;
  updated: string;
  poster: string;
  version: number | null;
  valid: boolean;
  result: ProjectResult | null;
};

export type Version = { number: number; source: string; note: string; valid: boolean; created: string };

export type Project = ProjectLite & {
  document: SceneDoc | null;
  report: Report | null;
  jobs: Job[];
  versions: Version[];
};

export type Worker = {
  id: number;
  name: string;
  enabled: boolean;
  online: boolean;
  has_gpu: boolean;
  profiles: string[];
  capabilities: {
    gpu?: string[] | string | null;
    cpu_count?: number;
    os?: string;
    blender_version?: string;
    [k: string]: unknown;
  };
  stats: Record<string, { sec_per_frame: number; n: number }>;
  last_seen: string | null;
  jobs_done: number;
  created: string;
  token: string;
};

export type WorkersResponse = { workers: Worker[]; server: string; gpu_nodes?: GpuNode[]; blender_zip?: string };

export type AiInfo = {
  ready: boolean;
  enabled: boolean;
  model: string;
  tts_model: string;
  tts_enabled: boolean;
  base_url: string;
};

export type Dashboard = {
  projects: ProjectLite[];
  jobs: Job[];
  workers: Worker[];
  ai: AiInfo;
  counts: Record<string, number>;
  files_url: string;
  active_jobs: number;
  workers_online: number;
  server: string;
};

export type Status = {
  active_jobs: number;
  workers_online: number;
  ai_ready: boolean;
  server: string;
  worker_server: string;
  files_url: string;
};

export type Estimate = {
  frames: number;
  seconds: number;
  worker: string | null;
  sec_per_frame: number;
  available: boolean;
  needs_gpu?: boolean;
  cpu_seconds?: number | null;
  cpu_worker?: string | null;
};

export type Template = { id: string; fa: string; en: string };

export type UploadResult = { id: string; path: string; url: string; kind: string; name: string; size: number };

export type SceneResponse = { version: number; valid: boolean; report: Report; document: SceneDoc };

export type EditResponse = SceneResponse & { diff: string[]; repairs: string[] };

export type TokenInfo = { token: string; server: string; worker_server: string; username: string };
