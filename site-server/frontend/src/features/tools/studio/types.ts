/**
 * شکلِ داده‌هایی که APIِ استودیو (`/api/v1/studio/…`) برمی‌گرداند.
 * سریال‌سازی در backend/apps/projects/helpers.py است؛ این فایل آینه‌ی همان است.
 */

export type Pair = [string, string];

export type ProjectStatus = "draft" | "generated" | "error";

export type Project = {
  id: number;
  name: string;
  slug: string;
  description: string;
  status: ProjectStatus;
  status_display: string;
  last_error: string;
  source: "studio" | "imported";
  is_imported: boolean;
  brand_color: string;
  site_title: string;
  generated_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  exists_on_disk: boolean;
  settings_module_name: string;
};

export type ProjectDetail = Project & {
  language_code: string;
  time_zone: string;
  allowed_hosts: string;
  extra_apps: string;
  extra_requirements: string;
  custom_settings: string;
  settings_module: string;
  urls_module: string;
  apps_dir: string;
  path: string;
};

export type ProjectListItem = Project & {
  preview_running: boolean;
  app_count: number;
  page_count: number;
};

export type FieldT = {
  id: number;
  model: number;
  name: string;
  verbose_name_fa: string;
  field_type: string;
  field_type_display: string;
  max_length: number | null;
  max_digits: number | null;
  decimal_places: number | null;
  null: boolean;
  blank: boolean;
  unique: boolean;
  db_index: boolean;
  auto_now: boolean;
  auto_now_add: boolean;
  default: string;
  choices: string;
  help_text_fa: string;
  related_model: number | null;
  related_model_label: string;
  related_ref: string;
  on_delete: string;
  related_name: string;
  raw_code: string;
  order: number;
  is_relational: boolean;
  is_textual: boolean;
  target_label: string;
};

export type RouteRef = { id: number; pattern: string; full_pattern: string; name: string };

export type ViewT = {
  id: number;
  app: number;
  app_name: string;
  name: string;
  label: string;
  kind: string;
  kind_display: string;
  model: number | null;
  model_name: string;
  description: string;
  template_body: string;
  css: string;
  paginate_by: number | null;
  ordering: string;
  form_fields: string;
  field_list: string[];
  login_required: boolean;
  success_url_name: string;
  context_object_name: string;
  custom_code: string;
  managed: boolean;
  order: number;
  class_name: string;
  template_name: string;
  needs_template: boolean;
  routes?: RouteRef[];
};

export type ModelT = {
  id: number;
  app: number;
  app_name: string;
  name: string;
  label: string;
  verbose_name_fa: string;
  verbose_plural_fa: string;
  has_str: boolean;
  str_field: string;
  ordering: string;
  in_admin: boolean;
  admin_list_display: string;
  admin_search_fields: string;
  admin_list_filter: string;
  list_display: string[];
  search_fields: string[];
  list_filter: string[];
  managed: boolean;
  raw_code: string;
  order: number;
  snake: string;
  field_count: number;
  fields?: FieldT[];
  views?: ViewT[];
};

export type RouteT = {
  id: number;
  app: number | null;
  app_name: string;
  pattern: string;
  full_pattern: string;
  name: string;
  view: number | null;
  view_label: string;
  view_text: string;
  managed: boolean;
  order: number;
  target: string;
  code: string;
};

export type AppT = {
  id: number;
  name: string;
  verbose_name_fa: string;
  description: string;
  is_core: boolean;
  managed: boolean;
  path: string;
  url_prefix: string;
  effective_prefix: string;
  dir: string;
  order: number;
  model_count?: number;
  view_count?: number;
  route_count?: number;
  models?: ModelT[];
  views?: ViewT[];
  routes?: RouteT[];
};

export type PageT = {
  id: number;
  title: string;
  slug: string;
  kind: string;
  kind_display: string;
  in_menu: boolean;
  file_path: string;
  order: number;
  is_imported: boolean;
  template_path: string;
  css_name: string;
  view_name: string;
  url_pattern: string;
  body_length: number;
  has_css: boolean;
  body_html?: string;
  has_design?: boolean;
  css?: string;
};

export type SharedKind = "header" | "footer" | "base_css";
export type SharedPart = { kind: SharedKind; kind_display: string; content: string };
/** هدر/فوتر/CSSِ مؤثرِ پروژه — برای پیش‌نمایشِ سمتِ مرورگر */
export type Shared = { base_css: string; header: string; footer: string };

export type BuildT = {
  id: number;
  ok: boolean;
  summary: string;
  detail: string;
  files_written: number;
  created_at: string | null;
};

export type CommitT = { short: string; sha: string; date: string; subject: string; stat: string };
export type CommitDetail = {
  short: string;
  date: string;
  subject: string;
  files: { add: string; del: string; path: string }[];
  diff: string;
  truncated: boolean;
};

export type ProposalStatus = "running" | "pending" | "applied" | "rejected" | "reverted" | "failed";
export type ProposalT = {
  id: number;
  task: string;
  task_display: string;
  title: string;
  prompt_text: string;
  summary: string;
  status: ProposalStatus;
  status_display: string;
  error: string;
  provider_model: string;
  calls: number;
  created_at: string | null;
  applied_at: string | null;
  is_running: boolean;
  can_apply: boolean;
  can_revert: boolean;
  change_count: number;
};

export type ChangeT = {
  id: number;
  target: string;
  target_display: string;
  label: string;
  page: number | null;
  view: number | null;
  old: string;
  new: string;
  diff: string;
  valid: boolean;
  issues: string[];
  order: number;
  is_css: boolean;
  is_html: boolean;
  unchanged: boolean;
};

export type ModelOption = {
  id: number;
  app_id: number;
  app_name: string;
  name: string;
  verbose_name_fa: string;
  label: string;
};
export type ViewOption = {
  id: number;
  app_id: number;
  app_name: string;
  name: string;
  kind_display: string;
  label: string;
};

export type ErField = { name: string; type: string; fa: string; to: number | null; ref: string };
export type ErModel = { id: number; app: string; name: string; fa: string; managed: boolean; fields: ErField[] };

export type RouteRow = {
  pattern: string;
  name: string;
  view: string;
  source: string;
  editable: boolean;
  live: string;
  page_id: number | null;
  route_id: number | null;
  route_view_id: number | null;
  route_managed: boolean | null;
};

/* ---------------------------------------------------------------- پاسخ‌ها */

export type ProjectDetailResp = {
  project: ProjectDetail;
  apps: AppT[];
  pages: PageT[];
  builds: BuildT[];
  model_count: number;
  field_count: number;
  view_count: number;
  route_count: number;
  file_count: number;
  preview_url: string;
  history: CommitT[];
  proposals: ProposalT[];
};

export type SettingsResp = {
  project: ProjectDetail;
  code: string;
  code_path: string;
  languages: Pair[];
  timezones: string[];
};

export type BackendResp = { project: Project; apps: AppT[]; er: ErModel[] };

export type AppDetailResp = {
  project: Project;
  app: AppT;
  models: ModelT[];
  views: ViewT[];
  routes: RouteT[];
  code: Record<string, string>;
  code_keys: string[];
  kinds: Pair[];
  all_models: ModelOption[];
};

export type ModelResp = {
  project: Project;
  model: ModelT;
  fields: FieldT[];
  app: AppT;
  editable: boolean;
  field_types: Pair[];
  on_delete: Pair[];
  all_models: ModelOption[];
  incoming: { id: number; model_id: number; label: string }[];
  code: string;
  views: ViewT[];
};

export type FieldResp = {
  project: Project;
  field: FieldT;
  model: ModelT;
  editable: boolean;
  field_types: Pair[];
  on_delete: Pair[];
  all_models: ModelOption[];
  code: string;
};

export type ViewResp = {
  project: Project;
  view: ViewT;
  app: AppT;
  editable: boolean;
  kinds: Pair[];
  needs_model: string[];
  all_models: ModelOption[];
  model_fields: FieldT[];
  chosen_fields: string[];
  url_names: string[];
  code: string;
  shared: Shared;
};

export type RoutesResp = { project: Project; rows: RouteRow[]; apps: AppT[]; views: ViewOption[] };
export type RouteResp = { project: Project; route: RouteT; apps: AppT[]; views: ViewOption[] };

export type FrontendResp = {
  project: Project;
  pages: PageT[];
  parts: Partial<Record<SharedKind, boolean>>;
  kinds: Pair[];
  view_templates: ViewT[];
};

export type PageResp = { project: Project; page: PageT; drift: boolean; shared: Shared; recent: ProposalT[] };
export type SharedResp = {
  project: Project;
  part: SharedPart;
  default_content: string;
  target_file: string;
  placeholder: string;
  shared: Shared;
};

export type FilesResp = {
  project: Project;
  tree: string[];
  groups: [string, { path: string; name: string }[]][];
  mark: string;
};
export type FileContentResp = { rel: string; content: string; custom_zone: boolean; mark: string };

export type HistoryResp = { project: Project; commits: CommitT[]; git: boolean };

export type PreviewResp = {
  project: Project;
  running: boolean;
  port: number | null;
  pid: number | null;
  url: string;
  log: string;
  admin_user: string;
  admin_password: string;
  own_env: boolean;
  exists_on_disk: boolean;
  ok?: boolean;
  message?: string;
};

export type BuildResp = { ok: boolean; summary?: string; detail: string; message: string; project: ProjectDetail };

export type AiSettingsT = {
  provider: string;
  provider_display: string;
  base_url: string;
  model: string;
  temperature: number;
  max_tokens: number;
  timeout_s: number;
  has_key: boolean;
  masked_key: string;
  is_ready: boolean;
  updated_at: string | null;
};
export type AiSettingsResp = AiSettingsT & {
  providers: Pair[];
  presets: [string, string, string, string][];
  admin_url: string;
};

export type AiHomeResp = {
  project: Project;
  cfg: { provider: string; provider_display: string; model: string; is_ready: boolean };
  pages: PageT[];
  proposals: ProposalT[];
};

export type SpecField = { name: string; verbose: string; type: string; related_model?: string };
export type SpecModel = { name: string; verbose: string; fields: SpecField[] };
export type SpecApp = { name: string; verbose: string; models: SpecModel[] };
export type SampleProduct = {
  name: string;
  description: string;
  category: string;
  price: number | string;
  stock: number | string;
};

export type ProposalResp = {
  project: Project;
  proposal: ProposalT;
  changes: ChangeT[];
  spec: SpecApp[] | null;
  samples: { products?: SampleProduct[] };
  shared: Shared;
  ok?: boolean;
  message?: string;
};

export type ImportReportT = {
  level: number;
  level_display: string;
  warnings: string[];
  unsupported: string[];
  created_at: string | null;
};

export type ImportReportResp = {
  project: ProjectDetail;
  report: ImportReportT;
  data: { settings?: { db_engine?: string; installed_apps?: string[] } };
  apps: AppT[];
  pages: PageT[];
  model_count: number;
  route_count: number;
  deps_status: "" | "running" | "ok" | "failed";
  deps_log: string;
  own_env: boolean;
  preview_running: boolean;
};

export type Message = { ok?: boolean; message: string };
