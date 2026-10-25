export interface User {
  id: number;
  username: string;
  email: string;
  /** ابزارهای ادمین فقط برای این‌ها کشیده می‌شوند؛ خود اندپوینت‌ها
   *  سمت سرور دوباره چک می‌شوند. */
  is_staff?: boolean;
}

export interface Store {
  id: number;
  name: string;
  slug: string;
  business_type: string;
  description: string;
  target_audience: string;
  logo: string | null;
  is_active: boolean;
  product_count: number;
  created_at: string;
}

export interface StoreProfile {
  brand_voice: string;
  tone: string;
  content_style: string;
  shipping_policy: string;
  return_policy: string;
  refund_policy: string;
  payment_info: string;
  business_rules: string;
  visual_preferences: Record<string, unknown>;
  working_hours: Record<string, unknown>;
  ai_preferences: Record<string, unknown>;
  publishing_preferences: Record<string, unknown>;
}

export interface ProductImage {
  id: number;
  image: string;
  is_main: boolean;
  alt_text: string;
  order: number;
}

export interface ProductAttribute {
  id: number;
  key: string;
  value: string;
}

export interface ProductVariant {
  id: number;
  name: string;
  attributes: Record<string, unknown>;
  price_override: string | null;
  stock_quantity: number;
  reserved_quantity: number;
  available_quantity: number;
  sku: string;
}

export interface Product {
  id: number;
  store: number;
  category: number | null;
  name: string;
  slug: string;
  sku: string;
  description: string;
  short_description: string;
  brand: string;
  price: string;
  compare_at_price: string | null;
  currency: string;
  /** چند تا در انبار هست. فقط فروش تأییدشده کمش می‌کند. */
  stock_quantity: number;
  /** چند تا برای سفارش‌های پرداخت‌نشده کنار گذاشته شده. */
  reserved_quantity: number;
  /** چند تا هنوز قابل فروش است = انبار منهای رزرو. */
  available_quantity: number;
  stock_status: string;
  tags: string[];
  is_available: boolean;
  images: ProductImage[];
  variants: ProductVariant[];
  attributes: ProductAttribute[];
  created_at: string;
}

export type JobState =
  | "QUEUED"
  | "PROCESSING"
  | "PREVIEW"
  | "WAITING_APPROVAL"
  | "APPROVED"
  | "RENDERING"
  | "QC"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED"
  // Old rows still carry this; new generation jobs use PROCESSING.
  | "RUNNING";

/** What the owner is being asked to look at while a job is parked. */
/** What quality control found in the segment a job is parked on. */
export interface PreviewQuality {
  overall?: number | null;
  verdict?: "EXCELLENT" | "GOOD" | "REVIEW" | "REGENERATE" | null;
  vision_checked?: boolean;
  vision_reason?: string;
  problems?: QualityAxis[];
  repaired?: string[];
  plan?: { action: string; reason: string; cost: string; causes?: string[] } | null;
  attempts?: number;
  /** The un-repaired render, when a code repair was applied. */
  original_video?: string | null;
}

export interface JobPreview {
  segment_index?: number;
  segments_done?: number;
  segments_total?: number;
  video?: string | null;
  mode?: string;
  quality?: PreviewQuality;
}

export interface Job {
  id: number;
  type: string;
  state: JobState;
  progress_step: number;
  total_steps: number;
  current_step_label: string;
  /** Persian name of the state — from the server, so one list exists. */
  state_label?: string;
  /** True while nothing will happen until a person answers. */
  awaiting_human?: boolean;
  mode?: "SAFE" | "AUTO";
  preview?: JobPreview;
  cancel_requested?: boolean;
  /** How many times the job has already been retried. */
  retry_count?: number;
  error: string;
  context: Record<string, unknown>;
  result: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface Intelligence {
  id: number;
  product: number;
  summary: string;
  target_audience: string[];
  selling_points: string[];
  weaknesses: string[];
  objections: string[];
  marketing_angles: string[];
  positioning: string;
  recommended_tone: string;
  content_ideas: string[];
  use_cases: string[];
  visual_analysis: unknown[];
  updated_at: string;
}

export interface CompetitorInfo {
  name: string;
  brand: string;
  product: string;
  price: string;
  where_sells: string;
  how_sells: string;
  strengths: string[];
  weaknesses: string[];
  source: string;
}

export interface MarketConclusions {
  competitors?: CompetitorInfo[];
  comparison?: string[];
  competitor_positioning: string[];
  common_messaging: string[];
  content_patterns: string[];
  pricing_observations: string[];
  common_customer_concerns: string[];
  content_gaps: string[];
  differentiation_opportunities: string[];
  strategy_summary: string;
}

export interface WebResearchItem {
  source: string;
  title: string;
  price_toman: number | null;
  url: string;
  shops?: string;
  snippet?: string;
}

export interface MarketResearch {
  id: number;
  product: number;
  research_inputs: string;
  web_results: {
    fetched_at?: string;
    sources?: Array<{ source: string; ok: boolean; count?: number; error?: string }>;
    items?: WebResearchItem[];
  };
  observations: string[];
  conclusions: MarketConclusions;
  confidence: "LOW" | "MEDIUM" | "HIGH";
  created_at: string;
  updated_at: string;
}

export interface Caption {
  id: number;
  product: number;
  platform: string;
  tone: string;
  objective: string;
  short_text: string;
  medium_text: string;
  long_text: string;
  hashtags: string[];
  cta: string;
  about_image: number | null;
  about_video: number | null;
  about_image_url: string | null;
  about_label: string;
  created_at: string;
}

export interface GeneratedImageInfo {
  id: number;
  product: number;
  kind: "POSTER" | "PRODUCT_SHOT" | "ENHANCED";
  concept: string;
  prompt_en: string;
  style: string;
  instructions: string;
  source_image: number | null;
  image: string;
  workflow_version: string;
  /** seed/size plus, for posters, the Persian text that was drawn on by code */
  metadata: {
    seed?: number;
    width?: number;
    height?: number;
    text_overlay?: { headline: string; subline: string; badge: string };
    /** set when drawing the Persian text failed — the poster came out bare */
    text_overlay_error?: string;
  } | null;
  created_at: string;
}

export interface VideoSceneInfo {
  index: number;
  duration: number;
  visual_prompt: string;
  motion_prompt: string;
  narration: string;
  transition: "CONTINUE" | "TRANSITION" | "NEW_SCENE";
  /** The sound chosen for this scene by the script model or by hand.
   *  A missing key means "automatic" — the planner reads the scene's words. */
  sound?: { ambience?: string; effects?: { key: string; at: number }[] };
  /** The person in this scene speaks the narration (lip-sync), instead of a voice-over. */
  speaker_on_camera?: boolean;
  /** What will actually play under this scene, resolved by the backend. */
  sound_plan?: {
    ambience: string | null;
    ambience_label: string | null;
    effects: { key: string; label: string; at: number }[];
  };
}

/** One sound the mixer can place (GET /audio/sounds/). */
export interface SoundOption {
  key: string;
  label: string;
  kind: "bed" | "spot";
  procedural: boolean;
  recordings: number;
  sample_url: string | null;
  available: boolean;
}

/** One engine that would read the narration, in fallback order. */
export interface VoiceSpeaker {
  engine: string;
  voice: string;
  local: boolean;
  processor: string;
  /** False when this engine has no voice of the chosen gender. */
  exact: boolean;
}

export interface VoiceProfileValues {
  gender: "male" | "female";
  rate: number;
  pitch: number;
  volume: number;
  /** A ClonedVoice id: Persian narration in that voice (spoken on a processing node). */
  cloned_voice?: number | null;
}

/** A cloned voice as a narrator choice (GET /stores/{id}/voice/ → cloned_voices). */
export interface ClonedVoiceOption {
  id: number;
  name: string;
  person: string;
  status: string;
  status_label: string;
  usable: boolean;
  license: string;
  commercial: boolean;
}

export interface Pronunciation {
  written: string;
  spoken: string;
}

/** GET/PATCH /stores/{id}/voice/ */
export interface StoreVoice {
  profile: VoiceProfileValues;
  profile_was_invalid: boolean;
  description: string;
  options: {
    voices: { key: "male" | "female"; id: string; label: string; note: string }[];
    sliders: { key: "rate" | "pitch" | "volume"; label: string; min: number; max: number; unit: string; hint: string }[];
    unavailable: { key: string; label: string; why: string }[];
    note: string;
  };
  voices_en: { key: string; id: string; label: string; note: string }[];
  speakers: Record<"fa" | "en", { speakers: VoiceSpeaker[]; error: string }>;
  cloned_voices?: ClonedVoiceOption[];
  local_only: boolean;
  pronunciations: Pronunciation[];
  builtin_pronunciations: Pronunciation[];
  max_pronunciations: number;
}

/** One recording used under a video, and what its licence asks for. */
export interface SoundCredit {
  sound: string;
  title: string;
  engine: string;
  licence: string;
  creator: string;
  source_url: string;
  attribution: string;
}

/** What the voice job laid down: who spoke, and what plays under each scene. */
export interface SoundDesign {
  voice?: {
    engine: string;
    voice: string;
    local: boolean;
    processor: string;
    fallbacks?: string[];
    notes?: string[];
  };
  soundscape?: {
    plan: {
      scene: number;
      ambience: string | null;
      ambience_label: string | null;
      effects: {
        key: string;
        label: string;
        at: number;
        /** The time the script guessed before the video existed. */
        planned_at?: number;
        /** "event": moved onto the frame of the action; "rhythm": one sound
         *  per step seen in the picture; null: no clear event, kept as planned. */
        synced?: "event" | "rhythm" | null;
        steps?: number;
      }[];
    }[];
    credits: SoundCredit[];
    missing: string[];
  } | null;
  /** The narration's audio QC — the worst scene decides. */
  quality?: {
    scored: number;
    silent: number;
    overall: number | null;
    verdict: string;
    weakest_scene?: string;
    retries?: number;
  };
  /** Things the shop should know: words read letter by letter, squeezed scenes… */
  warnings?: string[];
  /** One row per scene marked «گوینده در تصویر». */
  lipsync?: { scene: number; status: "done" | "failed" | "unavailable" | "skipped" | "off"; note: string }[];
  /** Per scene: how far the narration was moved so the product's name is
   *  said when the product appears (0 = left as it was, with the reason). */
  timing?: { scene: number; shift: number; appear: number | null; said: number | null; note: string }[];
}

/** One scored dimension of a segment's quality, with the reason attached. */
export interface QualityAxis {
  name: string;
  score: number;
  note: string;
}

export interface SegmentQuality {
  overall: number;
  verdict: "EXCELLENT" | "GOOD" | "REVIEW" | "REGENERATE";
  /** Only the axes worth mentioning — a list of perfect scores is noise. */
  problems: QualityAxis[];
  /** False means nobody looked, which is not the same as "it passed". */
  vision_checked: boolean;
  /** Why the vision model did not look, when it did not. */
  vision_reason?: string;
  /** Problems already fixed with ffmpeg, without spending GPU. */
  repaired: string[];
  plan?: { action: string; reason: string; cost: string; causes?: string[] } | null;
  /** The render before the code repair, so before and after can sit side by side. */
  original_video?: string | null;
  overall_before_repair?: number | null;
  /** How many renders this segment took. */
  attempts?: number;
}

export interface VideoSegmentInfo {
  index: number;
  status: "PENDING" | "GENERATING" | "DONE" | "FAILED";
  anchor_source: string;
  video: string | null;
  last_frame: string | null;
  retry_count: number;
  error: string;
  quality?: SegmentQuality | null;
  updated_at: string;
}

export interface VideoScriptInfo {
  id: number;
  product: number;
  concept: string;
  objective: string;
  cta: string;
  total_duration: number;
  narration_language: "fa" | "en";
  status: "DRAFT" | "GENERATING" | "READY" | "FAILED";
  final_video: string | null;
  voice_audio: string | null;
  final_video_voiced: string | null;
  /** Voiced cut with the shop's own music under it — the most finished one. */
  final_video_music?: string | null;
  sound_design?: SoundDesign | null;
  finishing?: VideoFinishing | null;
  scenes: VideoSceneInfo[];
  segments: VideoSegmentInfo[];
  created_at: string;
  updated_at: string;
}

/** Shape of a video before/after the finishing pass. */
export interface VideoShape {
  width: number;
  height: number;
  fps: number;
  duration: number;
  has_audio?: boolean;
  bytes?: number;
}

/** What happened after the segments were stitched (VideoScript.finishing). */
export interface VideoFinishing {
  enhance?: {
    ok: boolean;
    applied?: string[];
    seconds?: number;
    before?: VideoShape;
    after?: VideoShape;
    note?: string;
    source?: string;
    source_url?: string | null;
  };
  voice?: {
    started?: boolean;
    done?: boolean;
    job_id?: number;
    auto?: boolean;
    music?: boolean;
    note?: string;
  };
}

export type ApprovalState = "DRAFT" | "APPROVED" | "REJECTED" | "PUBLISHED" | "ARCHIVED";

export interface PublishJobInfo {
  id: number;
  platform: string;
  status: "PENDING" | "SENT" | "FAILED";
  attempts: number;
  last_error: string;
  published_at: string | null;
  created_at: string;
}

export interface CampaignInfo {
  id: number;
  product: number;
  name: string;
  goal: string;
  audience: string;
  notes: string;
  poster: number | null;
  product_image: number | null;
  caption: number | null;
  video_script: number | null;
  poster_detail: GeneratedImageInfo | null;
  product_image_detail: GeneratedImageInfo | null;
  caption_detail: Caption | null;
  video_script_detail: {
    id: number;
    status: string;
    total_duration: number;
    final_video: string | null;
    final_video_voiced: string | null;
  } | null;
  approval_state: ApprovalState;
  publish_jobs: PublishJobInfo[];
  created_at: string;
  updated_at: string;
}

export type ConversationState = "AI" | "HUMAN" | "ESCALATED" | "RESOLVED";

export interface ConversationInfo {
  id: number;
  state: ConversationState;
  customer: { id: number; name: string; phone: string; channel: string; created_at: string } | null;
  last_message: string;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: number;
  role: "CUSTOMER" | "AI" | "HUMAN";
  text: string;
  intent: string;
  grounding: Record<string, unknown>;
  created_at: string;
}

export interface ProductCard {
  id: number;
  name: string;
  price: string;
  currency: string;
  stock_quantity: number;
  image: string | null;
}

export interface OrderItemInfo {
  id: number;
  product: number;
  product_name: string;
  variant: number | null;
  variant_name: string | null;
  quantity: number;
  unit_price: string;
}

export type OrderStatus =
  | "DRAFT"
  | "AWAITING_RECEIPT"
  | "AWAITING_APPROVAL"
  /** پرداخت در محل — مشتری رسیدی نمی‌فرستد و این تصمیمِ فروشنده است. */
  | "COD"
  | "CONFIRMED"
  | "CANCELLED";

export interface ReceiptInfo {
  id: number;
  image: string;
  note: string;
  status: "PENDING" | "APPROVED" | "REJECTED";
  review_note: string;
  reviewed_at: string | null;
  created_at: string;
}

export interface OrderInfo {
  id: number;
  status: OrderStatus;
  total: string;
  items: OrderItemInfo[];
  customer?: { id: number; name: string } | null;
  conversation?: number | null;
  receipts?: ReceiptInfo[];
  /** لحظه‌ای که پول پذیرفته شد — درآمد به این روز تعلق می‌گیرد، نه روز ثبت. */
  confirmed_at?: string | null;
  stock_state?: "NONE" | "RESERVED" | "APPLIED" | "RELEASED";
  /** تا این لحظه کالا برای این سفارش کنار گذاشته شده. */
  reserved_until?: string | null;
  created_at: string;
  updated_at?: string;
}

export interface OpenOrder {
  order_id: number;
  status: OrderStatus;
  total: string;
  items: string[];
}

export interface TicketInfo {
  id: number;
  subject: string;
  description: string;
  status: "OPEN" | "IN_PROGRESS" | "RESOLVED";
  priority: "NORMAL" | "URGENT";
  customer?: { id: number; name: string } | null;
  conversation: number | null;
  resolution_note: string;
  resolved_at: string | null;
  created_at: string;
}

export interface NotificationInfo {
  id: number;
  store: number;
  store_name: string;
  type: "ESCALATION" | "ORDER" | "RECEIPT" | "TICKET" | "AI_ERROR";
  title: string;
  body: string;
  link: string;
  context: Record<string, unknown>;
  is_read: boolean;
  created_at: string;
}

export interface ChatResponse {
  conversation_id: number;
  state: ConversationState;
  message: ChatMessage | null;
  note?: string;
  action?: string;
  products?: ProductCard[];
  order?: OrderInfo | null;
  order_error?: string | null;
  payment_request?: { order_id: number; payment_info: string } | null;
  ticket?: TicketInfo | null;
  open_orders?: OpenOrder[];
}

export interface SalesDayPoint {
  date: string;
  orders: number;
  confirmed_orders: number;
  revenue: string;
}

export interface SalesData {
  days: number;
  orders: { total: number; by_status: Record<string, number> };
  revenue: { confirmed_total: string; confirmed_orders: number; avg_order_value: string };
  conversion: { conversations: number; orders: number; rate_percent: number };
  pending: { receipts: number; awaiting_approval: number; open_tickets: number };
  /** کل عمر فروشگاه — بقیه‌ی اعداد این صفحه فقط همان `days` روز اخیرند. */
  lifetime: { orders: number; confirmed_orders: number; confirmed_total: string };
  series: SalesDayPoint[];
  top_products: { name: string; quantity: number; revenue: string }[];
}

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}
