/**
 * Types of the Growth Engine API (`/api/v1/growth/`). They mirror the serializers in
 * `backend/apps/growth_engine/*`; the vocabulary (statuses, kinds, countries) is fetched from
 * `GET /growth/meta/` so it has one source of truth.
 */

export type Choice = { value: string; label: string };

export type Meta = {
  statuses: Choice[];
  origins: Choice[];
  contact_kinds: Choice[];
  business_types: Choice[];
  activity_kinds: Choice[];
  countries: { code: string; name: string }[];
  csv: {
    max_bytes: number;
    max_rows: number;
    targets: { key: string; label: string; multi: boolean }[];
    default_country: string;
  };
  limits: { bulk_max_ids: number; export_max_rows: number };
};

export type Paged<T> = { count: number; next: string | null; previous: string | null; results: T[] };

export type FieldError = { field: string; code: string; message: string };

export type Tag = { id: number; name: string; color: string };

export type LeadRow = {
  id: number;
  display_name: string;
  business_name: string;
  website: string;
  instagram_url: string;
  category: string;
  city: string;
  country: string;
  country_name: string;
  status: string;
  status_label: string;
  origin: string;
  origin_label: string;
  is_archived: boolean;
  tags: Tag[];
  phone: string;
  email: string;
  created_at: string;
  updated_at: string;
  /** set once the compliance module is installed */
  do_not_contact?: boolean;
  /** rule-based reachability score (0-100) with its reasons; no AI */
  reach?: { value: number; level: "high" | "medium" | "low"; label: string; reasons: { text: string; points: number }[] };
};

/** where a value came from: `manual`, a CSV row, or a website extraction run */
export type SourceInfo = {
  kind: "manual" | "csv" | "extract" | "osm" | "search" | "other";
  file?: string;
  row?: number | null;
  run?: number | null;
  ref?: string;
  object?: string;
  url?: string;
  provider?: string;
  host?: string;
};

export type Provenance = Record<string, { source: string; at: string; by: number | null }>;

export type Contact = {
  id: number;
  kind: string;
  kind_label: string;
  value: string;
  label: string;
  is_primary: boolean;
  source_ref: string;
  source: SourceInfo;
  source_url: string;
  evidence: string;
  confidence: number | null;
  created_at: string;
};

export type Profile = {
  language: string;
  business_type: string;
  business_type_label: string;
  product_categories: string[];
  product_names: string[];
  address: string;
  provenance: Provenance;
};

export type LeadSourceRow = {
  id: number;
  provider: string;
  provider_label: string;
  source_ref: string;
  source: SourceInfo;
  source_url: string;
  discovered_at: string;
  job_id: number | null;
  created_by: string;
};

export type LeadDetail = LeadRow & {
  description: string;
  provenance: Provenance;
  profile: Profile;
  contacts: Contact[];
  sources: LeadSourceRow[];
  created_by_name: string;
  notes_count: number;
};

export type Note = { id: number; body: string; author: number | null; author_name: string; created_at: string; updated_at: string };

export type Activity = {
  id: number;
  kind: string;
  kind_label: string;
  actor: number | null;
  actor_name: string;
  summary: string;
  data: Record<string, unknown>;
  source_ref: string;
  source: SourceInfo | null;
  created_at: string;
};

export type TagWithCount = Tag & { lead_count: number };

// ------------------------------------------------------------------ duplicates / merge

export type MergePreview = {
  fields: { field: string; label: string; existing: string; incoming: string; state: "fill" | "same" | "conflict" }[];
  contacts_new: { kind: string; value: string }[];
  contacts_known: { kind: string; value: string }[];
  contacts_elsewhere: { kind: string; value: string; lead_id: number }[];
  tags_new: string[];
};

export type DuplicateItem = {
  lead: LeadRow;
  matched_on: { kind: string; value: string; normalized: string }[];
  merge_preview?: MergePreview;
};

// ------------------------------------------------------------------ discovery

export type ManualMode = "website_url" | "instagram_url" | "business_name" | "manual";

export type ManualInput = {
  mode: ManualMode;
  business_name?: string;
  website?: string;
  instagram?: string;
  phone?: string;
  email?: string;
  whatsapp?: string;
  telegram?: string;
  category?: string;
  description?: string;
  country?: string;
  city?: string;
  note?: string;
  tags?: string[];
  address?: string;
  resolution?: { action: "merge" | "skip"; target_lead?: number; overwrite_fields?: string[] };
};

export type ManualCheck = { valid: boolean; errors: FieldError[]; duplicates: DuplicateItem[]; similar: LeadRow[] };

export type CsvUpload = {
  upload_id: string;
  file_name: string;
  size: number;
  encoding: string;
  delimiter: string;
  total_rows: number;
  headers: string[];
  sample_rows: { row: number; cells: string[] }[];
  suggested_mapping: Record<string, string>;
  targets: { key: string; label: string; multi: boolean }[];
};

export type CsvCheck = {
  total_rows: number;
  valid_rows: number;
  error_rows: number;
  errors: { row: number; errors: FieldError[] }[];
  sample: {
    row: number;
    ok: boolean;
    errors: FieldError[];
    summary: {
      business_name: string;
      website: string;
      instagram: string;
      phones: string[];
      emails: string[];
      city: string;
      country: string;
      category: string;
      tags: string[];
    };
  }[];
  mapping: Record<string, string>;
};

export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export type DiscoveryJob = {
  id: number;
  kind: string;
  kind_label: string;
  status: JobStatus;
  status_label: string;
  file_name: string;
  encoding: string;
  total_items: number;
  processed_items: number;
  progress: number;
  created_count: number;
  merged_count: number;
  skipped_count: number;
  duplicate_count: number;
  error_count: number;
  error: string;
  stalled: boolean;
  can_resume: boolean;
  cancel_requested: boolean;
  attempts: number;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  created_by_name: string;
  /** the licence / source line of a provider search (e.g. "© OpenStreetMap contributors (ODbL)") */
  attribution?: string;
  params: {
    mapping?: Record<string, string>;
    default_country?: string;
    default_city?: string;
    tags?: string[];
    extract_after?: boolean;
    provider?: string;
    category?: string;
    category_label?: string;
    city?: string;
    country?: string;
    max_results?: number;
    require_contact?: boolean;
    attribution?: string;
    attribution_url?: string;
    empty_note?: string;
  };
};

export type JobRow = {
  id: number;
  row_number: number;
  status: "error" | "duplicate" | "merged" | "skipped" | "created";
  status_label: string;
  raw: Record<string, string>;
  errors: FieldError[];
  matches: { lead_id: number; name: string; matched_on: { kind: string; value: string }[] }[];
  matched_lead_id: number | null;
  resolved_at: string | null;
  merge_preview?: MergePreview;
};

// ------------------------------------------------------------------ dashboard

export type Dashboard = {
  generated_at: string;
  totals: {
    leads: number;
    new_7d: number;
    with_website: number;
    with_instagram: number;
    archived: number;
    with_phone: number;
    with_email: number;
    with_contact_form: number;
  };
  by_status: { status: string; label: string; count: number }[];
  by_origin: { origin: string; label: string; count: number }[];
  top_cities: { city: string; count: number }[];
  daily: { date: string; value: number }[];
  pending_duplicates: number;
  recent_jobs: {
    id: number;
    file_name: string;
    status: JobStatus;
    status_label: string;
    progress: number;
    created_count: number;
    duplicate_count: number;
    error_count: number;
    total_items: number;
    queued_at: string;
    created_by_name: string;
  }[];
  recent_activity: { id: number; lead_id: number; lead_name: string; kind: string; kind_label: string; summary: string; actor_name: string; created_at: string }[];
  /** blocks contributed by other modules (extraction, outreach ...): see their own types */
  extra: Record<string, Record<string, unknown>>;
  coming_soon: { key: string; title: string; milestone: string }[];
};

// ------------------------------------------------------------------ extraction (shape fixed in docs/growth-engine/DESIGN-EXT.md)

export type ExtractionFinding = {
  field: string;
  value: string;
  source_url: string;
  evidence: string;
  confidence: number | null;
  applied: boolean;
  reason: string;
};

export type ExtractionPage = {
  url: string;
  kind: string;
  status: number;
  outcome: string;
  outcome_label: string;
  elapsed_ms: number;
  bytes: number;
  note: string;
};

export type ExtractionRunInfo = {
  id: number;
  job_id: number | null;
  status: "queued" | "running" | "done" | "failed" | "skipped";
  status_label: string;
  reason: string;
  reason_label: string;
  started_at: string | null;
  finished_at: string | null;
  pages_fetched: number;
  robots_state: string;
  contacts_added: number;
  findings: ExtractionFinding[];
  pages: ExtractionPage[];
};

export type ExtractionJobInfo = {
  id: number;
  status: JobStatus;
  status_label: string;
  scope: "single" | "selected" | "csv_import";
  progress: number;
  total_items: number;
  processed_items: number;
  runs_done: number;
  runs_failed: number;
  runs_skipped: number;
  pages_fetched: number;
  contacts_added: number;
  error: string;
  stalled: boolean;
  can_resume: boolean;
  queued_at: string;
  finished_at: string | null;
  created_by_name: string;
};

// ------------------------------------------------------------------ extraction: the job with its runs, and the lead's runs

export type ExtractionRunBrief = {
  id: number;
  lead_id: number;
  lead_name: string;
  status: string;
  status_label: string;
  reason: string;
  reason_label: string;
  pages_fetched: number;
  contacts_added: number;
};

export type ExtractionJobDetail = ExtractionJobInfo & { runs?: ExtractionRunBrief[] };

export type ExtractionLeadRuns = { runs: ExtractionRunInfo[] };

/** compliance: why a lead goes on the do-not-contact list */
export type DncReason = "opt_out" | "asked_not_to_contact" | "complaint" | "invalid_contact" | "other";

/** result of POST /growth/discovery/manual/ */
export type ManualResult =
  | { result: "created"; lead: LeadRow }
  | {
      result: "merged";
      lead: LeadRow;
      filled: string[];
      overwritten: string[];
      conflicts: { field: string; label: string; existing: string; incoming: string }[];
      contacts_added: { kind: string; value: string }[];
      contacts_skipped: { kind: string; value: string; reason: string; lead_id?: number }[];
    }
  | { result: "skipped" };

/** result of POST /growth/discovery/jobs/<id>/resolve/ */
export type ResolveResult = { resolved: number; merged: number; skipped: number; created: number; remaining: number };

// ------------------------------------------------------------------ automatic discovery (M3)

export type ProviderSetting = { name: string; label: string; type: "lines" | "url" | "int" | "text"; default?: unknown; help?: string };

export type DiscoveryProvider = {
  key: string;
  label: string;
  description: string;
  kind: "map" | "search";
  needs_key: boolean;
  enabled: boolean;
  ready: boolean;
  not_ready_reason: string;
  attribution: string;
  attribution_url: string;
  license_note: string;
  max_results_limit: number;
  categories: { key: string; label: string; tags: string[] }[];
  settings_schema: ProviderSetting[];
  settings: Record<string, unknown>;
  /** which secrets are SET; their values never come to the browser */
  secrets: Record<string, { label: string; is_set: boolean }>;
  source_provider: string;
  usage_today?: number;
  daily_cap?: number;
};

export type SearchCheck = {
  ok: boolean;
  summary: string;
  attribution: string;
  place: { name: string; cached: boolean; osm_url: string } | null;
  notes: string[];
};
