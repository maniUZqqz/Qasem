<!-- تولیدشده با `python manage.py schemadoc --write` — دستی ویرایش نکن. -->
# نقشه‌ی دیتابیس

این فایل از **خود مدل‌ها** خوانده می‌شود، پس نمی‌تواند از کد جلو یا
عقب بیفتد. بعد از هر مهاجرت یک بار `python manage.py schemadoc --write`
بزنید.

موتور: **SQLite** در توسعه، **PostgreSQL** در production — همان تصمیم D2.
مدل‌ها و مهاجرت‌ها موتور-ناوابسته‌اند، پس جابه‌جایی فقط `DATABASES` را
لمس می‌کند.

> `id`، `created_at` و `updated_at` در جدول‌ها نوشته نشده‌اند چون تقریباً
> همه دارندشان؛ نبودشان استثناست نه بودنشان.

## stores

### Store
Tenant boundary: every business object belongs to a Store.

- `owner` → User
- `name` Char
- `slug` Slug — یکتا، ایندکس
- `business_type` Char
- `description` Text
- `target_audience` Char
- `contact` JSON
- `logo` File — nullable
- `colors` JSON
- `social_links` JSON
- `is_active` Boolean

### StoreProfile
Brand voice, policies and AI preferences for a store.

- `store` → Store — یکتا
- `brand_voice` Char
- `novinhub_token` Char
- `novinhub_account_ids` JSON
- `telegram_bot_token` Char
- `tone` Char
- `content_style` Char
- `visual_preferences` JSON
- `shipping_policy` Text
- `return_policy` Text
- `refund_policy` Text
- `payment_info` Text
- `business_rules` Text
- `working_hours` JSON
- `ai_preferences` JSON
- `publishing_preferences` JSON
- `owner_photo` File — nullable
- `owner_caption` Char
- `voice_profile` JSON
- `subtitles_by_default` Boolean
- `subtitles_burned_by_default` Boolean
- `webhook_secret` Char — ایندکس
- `pronunciations` JSON

### Membership
A person's seat in a store, with a role.

- `store` → Store
- `user` → User
- `role` Char — OWNER | ADMIN | MARKETING | CONTENT | SUPPORT | VIEWER
- `is_active` Boolean
- `invited_by` → User — set_null، nullable
- `removed_at` DateTime — nullable
- **ایندکس:** user، is_active

### SalesAgentSettings
Brand voice and selling rules for one store's agent.

- `store` → Store — یکتا
- `tone` Char — FORMAL | FRIENDLY | PROFESSIONAL | WARM | CUSTOM
- `custom_tone` Text
- `always_say` Text
- `never_say` Text
- `sale_terms` Text
- `limits` Text
- `can_offer_discount` Boolean
- `discount_policy` Text
- `escalate_on_complaint` Boolean

### ContentAutomation
One store's standing instructions for content production.

- `store` → Store — یکتا
- `enabled` Boolean
- `mode` Char — SIMPLE | ADVANCED
- `make_video` Boolean
- `make_image` Boolean
- `make_caption` Boolean
- `image_mode` Char — POSTER | PRODUCT_SHOT
- `video_seconds` PositiveSmallInteger
- `language` Char — fa | en
- `subtitles` Boolean
- `owner_photo_ending` Boolean
- `extra_prompt` Text
- `publish_days` JSON
- `publish_time` Time
- `posts_per_run` PositiveSmallInteger
- `product_ids` JSON
- `approval` Char — AUTO | APPROVE | DRAFT
- `notify` Boolean
- `last_run_at` DateTime — nullable

## products

### Category
Category(id, created_at, updated_at, store, name, parent)

- `store` → Store
- `name` Char
- `parent` → Category — nullable

### Product
Product(id, created_at, updated_at, store, category, name, slug, sku, description, short_description, brand, price, compare_at_price, cost_price, currency, stock_quantity, reserved_quantity, stock_status, tags, shipping_info, marketing_notes, is_available)

- `store` → Store
- `category` → Category — set_null، nullable
- `name` Char
- `slug` Slug — یکتا، ایندکس
- `sku` Char
- `description` Text
- `short_description` Char
- `brand` Char
- `price` Decimal
- `compare_at_price` Decimal — nullable
- `cost_price` Decimal — nullable
- `currency` Char
- `stock_quantity` PositiveInteger
- `reserved_quantity` PositiveInteger
- `stock_status` Char — IN_STOCK | OUT_OF_STOCK | PREORDER
- `tags` JSON
- `shipping_info` JSON
- `marketing_notes` Text
- `is_available` Boolean
- **ایندکس:** store، created_at

### ProductVariant
ProductVariant(id, created_at, updated_at, product, name, attributes, price_override, stock_quantity, reserved_quantity, sku)

- `product` → Product
- `name` Char
- `attributes` JSON
- `price_override` Decimal — nullable
- `stock_quantity` PositiveInteger
- `reserved_quantity` PositiveInteger
- `sku` Char

### ProductAttribute
Key/value specs — port of the legacy `ProductFeature` model.

- `product` → Product
- `key` Char
- `value` Char

### ProductImage
ProductImage(id, product, image, is_main, alt_text, order, created_at)

- `product` → Product
- `image` File
- `is_main` Boolean
- `alt_text` Char
- `order` PositiveInteger

## ai

### AIRequest
Audit record of every call made through the AI orchestration layer.

- `store` → Store
- `job` → Job — set_null، nullable
- `task_type` Char — REASONING | VISION | CODE
- `model` Char
- `prompt_id` Char
- `prompt_version` Char
- `status` Char — OK | TIMEOUT | PROVIDER_ERROR | MALFORMED_OUTPUT | VALIDATION_FAILED
- `attempts` PositiveInteger
- `latency_ms` PositiveInteger — nullable
- `error` Text

### AIResponse
AIResponse(id, request, raw_output, parsed, valid)

- `request` → AIRequest — یکتا
- `raw_output` Text
- `parsed` JSON — nullable
- `valid` Boolean

### ProductIntelligence
Structured AI understanding of a product (replaces legacy free-text ProductAnalysis).

- `product` → Product — یکتا
- `summary` Text
- `target_audience` JSON
- `selling_points` JSON
- `weaknesses` JSON
- `objections` JSON
- `marketing_angles` JSON
- `positioning` Text
- `recommended_tone` Char
- `content_ideas` JSON
- `use_cases` JSON
- `visual_analysis` JSON
- `source_request` → AIRequest — set_null، nullable

### ProductEmbedding
Vector embedding of a product's text, for semantic catalog search.

- `product` → Product — یکتا
- `vector` JSON
- `model` Char
- `source_hash` Char

### MarketResearch
Structured market/competitor analysis for a product.

- `store` → Store
- `product` → Product
- `research_inputs` Text
- `web_results` JSON
- `observations` JSON
- `conclusions` JSON
- `confidence` Char — LOW | MEDIUM | HIGH
- `source_request` → AIRequest — set_null، nullable

### ModelProvider
Where a given AI capability is served from — local hardware or an API.

- `capability` Char — TEXT | VISION | IMAGE | VIDEO
- `kind` Char — OLLAMA | COMFYUI | OPENAI | REPLICATE | HTTP
- `name` Char
- `base_url` Char
- `api_key` Char
- `model_name` Char
- `is_active` Boolean
- `priority` PositiveSmallInteger
- `timeout_s` PositiveInteger
- `options` JSON
- `data_location` Char — ON_PREMISE | IRAN | EU | US | OTHER | UNKNOWN
- `is_approved` Boolean
- `allowed_data` JSON
- `data_retention` Char
- `privacy_policy_url` Char
- `checked_at` DateTime — nullable
- `is_healthy` Boolean — nullable
- `last_error` Text
- **ایندکس:** capability، is_active، priority

### StoreAIPolicy
How much of a store's data is allowed to leave our servers.

- `store` → Store — یکتا
- `mode` Char — LOCAL_ONLY | APPROVED_EXTERNAL | HYBRID
- `allow_customer_data_external` Boolean
- `acknowledged_at` DateTime — nullable
- `acknowledged_by` → User — set_null، nullable

### Competitor
One business this shop competes with.

- `store` → Store
- `name` Char
- `kind` Char — DIRECT | ADJACENT | MARKETPLACE
- `website` Char
- `instagram` Char
- `notes` Text
- `revenue_model` Text
- `positioning` Text
- `strengths` JSON
- `weaknesses` JSON
- `analysed_at` DateTime — nullable
- `is_active` Boolean

### CompetitorProduct
Something a competitor sells, and what it cost on the day we looked.

- `competitor` → Competitor
- `name` Char
- `url` Char
- `price_toman` PositiveBigInteger — nullable
- `observed_at` DateTime — nullable
- `matches` → Product — set_null، nullable
- `source` Char
- `raw` JSON
- **ایندکس:** competitor، matches

### Opportunity
A recommendation the shop can act on. §4.

- `store` → Store
- `product` → Product — nullable
- `kind` Char — PRICING | NEW_PRODUCT | BUNDLE | CHANNEL | CONTENT | INVENTORY
- `title` Char
- `reason` Text
- `action` Char
- `evidence` JSON
- `state` Char — OPEN | DONE | DISMISSED
- `priority` PositiveSmallInteger
- **ایندکس:** store، state، -priority

### Trend
One thing people were searching for, in one country, on one day.

- `title` Char
- `region` Char
- `traffic` Char
- `context` JSON
- `image` Char
- `source` Char
- `seen_at` DateTime
- **ایندکس:** region، -seen_at

### TrendIdea
«با این ترند، برای این محصول، این را بساز». §6.2

- `store` → Store
- `trend` → Trend
- `product` → Product — set_null، nullable
- `kind` Char — VIDEO | POST | STORY | CAPTION
- `idea` Text
- `why` Text
- `hook` Char
- `state` Char — OPEN | USED | DISMISSED
- `job_id` Integer — nullable
- **ایندکس:** store، state

### AudioEngine
One way to make (or clean) a sound, and its place in the queue.

- `role` Char — VOICE | SOUND | DENOISE
- `kind` Char — PIPER | EDGE | AZURE | OPENAI_TTS | ELEVENLABS | GTTS | SOUND_LIBRARY | PROCEDURAL | OP…
- `name` Char
- `is_active` Boolean
- `priority` PositiveSmallInteger
- `base_url` Char
- `api_key` Char
- `model_name` Char
- `voice_fa` Char
- `voice_fa_female` Char
- `voice_en` Char
- `voice_en_female` Char
- `timeout_s` PositiveInteger
- `options` JSON
- `notes` Text
- `checked_at` DateTime — nullable
- `is_healthy` Boolean — nullable
- `last_error` Text

### AudioMix
How loud each layer sits, and which layers are on. One row.

- `voice_lufs` Float
- `polish_voice` Boolean
- `ambience_enabled` Boolean
- `ambience_lufs` Float
- `effects_enabled` Boolean
- `effects_lufs` Float
- `background_lufs` Float
- `background_ceiling_lufs` Float
- `duck_db` Float
- `suggest_denoise` Boolean
- `min_snr_db` Float

### SoundClip
One real recording in the local sound library.

- `category` Char — ایندکس
- `title` Char
- `file` File
- `duration` Float
- `loudness_lufs` Float — nullable
- `origin` Char — OPENVERSE | UPLOAD | ELEVENLABS | PROCEDURAL
- `licence` Char
- `creator` Char
- `source_url` Char
- `attribution` Char
- `is_active` Boolean
- `quality_note` Char

## content

### Caption
Platform-specific caption set for a product (Phase 10).

- `store` → Store
- `product` → Product
- `platform` Char — INSTAGRAM | TELEGRAM | LINKEDIN
- `tone` Char
- `objective` Char
- `short_text` Text
- `medium_text` Text
- `long_text` Text
- `hashtags` JSON
- `cta` Char
- `about_image` → GeneratedImage — set_null، nullable
- `about_video` → VideoScript — set_null، nullable
- `source_request` → AIRequest — set_null، nullable

### GeneratedImage
AI-generated marketing image (Phase 9 — Image Studio).

- `store` → Store
- `product` → Product
- `kind` Char — POSTER | PRODUCT_SHOT | ENHANCED
- `concept` Text
- `prompt_en` Text
- `negative_en` Text
- `style` Char
- `instructions` Text
- `source_image` → ProductImage — set_null، nullable
- `image` File
- `workflow_version` Char
- `source_request` → AIRequest — set_null، nullable
- `metadata` JSON

### VideoScript
Machine-readable advertising video plan (Phase 11).

- `store` → Store
- `product` → Product
- `concept` Text
- `objective` Char
- `cta` Char
- `total_duration` PositiveInteger
- `narration_language` Char
- `status` Char — DRAFT | GENERATING | READY | FAILED
- `final_video` File — nullable
- `voice_audio` File — nullable
- `sound_design` JSON
- `final_video_voiced` File — nullable
- `final_video_real` File — nullable
- `subtitles` File — nullable
- `subtitles_enabled` Boolean — nullable
- `subtitles_burned` Boolean — nullable
- `music` File — nullable
- `music_source` Char
- `music_licence` Char
- `music_attribution` Char
- `music_level_db` Float
- `final_video_music` File — nullable
- `raw` JSON
- `source_request` → AIRequest — set_null، nullable

### VideoScene
VideoScene(id, script, index, duration, visual_prompt, motion_prompt, narration, transition, state, sound, speaker_on_camera)

- `script` → VideoScript
- `index` PositiveInteger
- `duration` PositiveInteger
- `visual_prompt` Text
- `motion_prompt` Text
- `narration` Text
- `transition` Char — CONTINUE | TRANSITION | NEW_SCENE
- `state` JSON
- `sound` JSON
- `speaker_on_camera` Boolean

### VideoCut
One platform-shaped cut of a finished video. `ایده‌ها.md` §10.

- `script` → VideoScript
- `format` Char
- `video` File
- `trimmed` Boolean
- `has_audio` Boolean

### VideoSegment
One generated ~5s clip. Files live under MEDIA and are tracked here (Phase 12).

- `script` → VideoScript
- `index` PositiveInteger
- `status` Char — PENDING | GENERATING | DONE | FAILED
- `anchor_source` Char
- `video` File — nullable
- `last_frame` File — nullable
- `retry_count` PositiveInteger
- `error` Text
- `metadata` JSON
- `scene_state` JSON

### EditDecision
One thing a shop said yes or no to in the editor. §9.

- `store` → Store
- `video` → UploadedVideo — set_null، nullable
- `tool` Char
- `params` JSON
- `accepted` Boolean
- `source` Char — SUGGESTED | MANUAL | DIRECTED | AUTO
- **ایندکس:** store، tool

### UploadedVideo
A video the shop filmed themselves. §8, §10.

- `store` → Store
- `product` → Product — set_null، nullable
- `title` Char
- `video` File
- `edited` File — nullable
- `state` Char — UPLOADED | ANALYZING | READY | EDITED | FAILED
- `duration` Float
- `has_audio` Boolean
- `facts` JSON
- `edit_outcome` JSON
- `transcript` JSON
- `subtitles_enabled` Boolean — nullable
- `subtitles_burned` Boolean — nullable
- `subtitles` File — nullable
- `error` Text

## customers

### Customer
Customer(id, created_at, updated_at, store, name, phone, external_id, channel, metadata)

- `store` → Store
- `name` Char
- `phone` Char
- `external_id` Char
- `channel` Char
- `metadata` JSON

### Conversation
Conversation(id, created_at, updated_at, store, customer, state, channel, external_id, assigned_to, tags, last_customer_at)

- `store` → Store
- `customer` → Customer
- `state` Char — AI | HUMAN | ESCALATED | RESOLVED
- `channel` Char
- `external_id` Char
- `assigned_to` → User — set_null، nullable
- `tags` JSON
- `last_customer_at` DateTime — nullable
- **ایندکس:** store، state، -last_customer_at
- **ایندکس:** store، channel

### Message
Message(id, created_at, updated_at, conversation, role, text, intent, external_id, grounding, ai_request)

- `conversation` → Conversation
- `role` Char — CUSTOMER | AI | HUMAN
- `text` Text
- `intent` Char
- `external_id` Char — ایندکس
- `grounding` JSON
- `ai_request` → AIRequest — set_null، nullable

### Order
Order foundation. Created ONLY from real database data, never AI claims.

- `store` → Store
- `customer` → Customer
- `conversation` → Conversation — set_null، nullable
- `status` Char — DRAFT | AWAITING_RECEIPT | AWAITING_APPROVAL | COD | CONFIRMED | CANCELLED
- `total` Decimal
- `confirmed_at` DateTime — nullable
- `stock_state` Char — NONE | RESERVED | APPLIED | RELEASED
- `reserved_until` DateTime — nullable

### OrderItem
OrderItem(id, order, product, variant, quantity, unit_price)

- `order` → Order
- `product` → Product — protect
- `variant` → ProductVariant — protect، nullable
- `quantity` PositiveInteger
- `unit_price` Decimal

### PaymentReceipt
A payment receipt image the customer sends for an order.

- `order` → Order
- `image` File
- `note` Char
- `status` Char — PENDING | APPROVED | REJECTED
- `review_note` Char
- `reviewed_at` DateTime — nullable

### SupportTicket
A tracked support issue/complaint, usually opened by the AI agent.

- `store` → Store
- `customer` → Customer — set_null، nullable
- `conversation` → Conversation — set_null، nullable
- `subject` Char
- `description` Text
- `status` Char — OPEN | IN_PROGRESS | RESOLVED
- `priority` Char — NORMAL | URGENT
- `resolution_note` Text
- `resolved_at` DateTime — nullable

### Notification
In-app notification for the store owner — fired whenever the AI needs a

- `store` → Store
- `type` Char — ESCALATION | ORDER | RECEIPT | TICKET | AI_ERROR
- `title` Char
- `body` Text
- `link` Char
- `context` JSON
- `is_read` Boolean
- `read_at` DateTime — nullable
- **ایندکس:** store، is_read

### Prospect
A business this shop wants to sell to, and where that stands.

- `store` → Store
- `company` Char
- `website` Char
- `person` Char
- `role` Char
- `phone` Char
- `email` Char
- `social` Char
- `stage` Char — NEW | CONTACTED | INTERESTED | NEGOTIATING | WON | LOST
- `notes` Text
- `last_outcome` Char
- `last_contact_at` DateTime — nullable
- `next_action` Char
- `next_action_at` DateTime — nullable
- **ایندکس:** store، stage، next_action_at

### CallConsent
Permission to record this person, on the record.

- `prospect` → Prospect — یکتا
- `granted` Boolean
- `how` Char — VERBAL | WRITTEN | CONTRACT
- `obtained_how` Char
- `obtained_at` DateTime
- `revoked_at` DateTime — nullable

### Recording
One recorded call, and what came out of it.

- `store` → Store
- `prospect` → Prospect
- `audio` File
- `seconds` PositiveInteger
- `happened_at` DateTime
- `status` Char — STORED | TRANSCRIBED | ANALYSED | FAILED
- `transcript` Text
- `summary` Text
- `sentiment` Char — POSITIVE | NEUTRAL | NEGATIVE
- `objections` JSON
- `commitments` JSON
- `suggested_next` Char
- `error` Char

## campaigns

### Campaign
Groups approved marketing content for one product (Phase 14).

- `store` → Store
- `product` → Product
- `name` Char
- `goal` Char
- `audience` Char
- `notes` Text
- `poster` → GeneratedImage — set_null، nullable
- `product_image` → GeneratedImage — set_null، nullable
- `caption` → Caption — set_null، nullable
- `video_script` → VideoScript — set_null، nullable
- `approval_state` Char — DRAFT | APPROVED | REJECTED | PUBLISHED | ARCHIVED

### PublishJob
One delivery attempt of a campaign package to n8n for one platform.

- `store` → Store
- `campaign` → Campaign
- `platform` Char
- `payload` JSON
- `response` JSON
- `status` Char — PENDING | RUNNING | SENT | FAILED
- `attempts` PositiveInteger
- `last_error` Text
- `published_at` DateTime — nullable
- `scheduled_for` DateTime — nullable
- **ایندکس:** status، scheduled_for

### PostPerformance
How one published post actually did.

- `publish_job` → PublishJob — یکتا
- `store` → Store
- `platform` Char
- `views` PositiveInteger — nullable
- `likes` PositiveInteger — nullable
- `comments` PositiveInteger — nullable
- `saves` PositiveInteger — nullable
- `shares` PositiveInteger — nullable
- `linked_orders` PositiveInteger
- `fetched_at` DateTime — nullable
- `unavailable_reason` Char
- `raw` JSON
- **ایندکس:** store، -created_at

### CampaignTask
One thing that has to happen for this campaign.

- `campaign` → Campaign
- `store` → Store
- `kind` Char — MARKETING | ADVERTISING | CONTENT | SALES | OTHER
- `title` Char
- `detail` Text
- `state` Char — TODO | DOING | BLOCKED | DONE | DROPPED
- `priority` Integer — 1 | 2 | 3
- `assigned_to` → User — set_null، nullable
- `due_at` DateTime — nullable
- `job` → Job — set_null، nullable
- `because` Char
- `order` PositiveInteger
- `done_at` DateTime — nullable
- **ایندکس:** store، state

## billing

### Plan
A sellable package. Mirrors دیتا/1-داده/data.json — keep the two in step.

- `slug` Slug — یکتا، ایندکس
- `name` Char
- `description` Char
- `price_toman` PositiveInteger
- `is_public` Boolean
- `is_trial` Boolean
- `trial_days` PositiveSmallInteger
- `sort_order` PositiveSmallInteger
- `video_seconds` PositiveInteger
- `images` PositiveInteger
- `captions` PositiveInteger
- `max_products` PositiveInteger
- `max_stores` PositiveSmallInteger
- `allows_publishing` Boolean
- `allows_sales_agent` Boolean

### Subscription
One store's current plan and billing period.

- `store` → Store — یکتا
- `plan` → Plan — protect
- `status` Char — TRIALING | ACTIVE | PAST_DUE | CANCELLED | EXPIRED
- `period_start` DateTime
- `period_end` DateTime
- `cancel_at_period_end` Boolean
- `bonus_video_seconds` PositiveInteger
- `bonus_images` PositiveInteger
- `bonus_captions` PositiveInteger
- `note` Char

### Usage
One consumption event, always tied to the period it was spent in.

- `subscription` → Subscription
- `store` → Store
- `metric` Char — VIDEO_SECONDS | IMAGES | CAPTIONS
- `quantity` PositiveInteger
- `state` Char — RESERVED | COMMITTED | RELEASED | REFUNDED
- `period_start` DateTime
- `job` → Job — set_null، nullable
- `detail` Char
- `external` Boolean
- `attempt` PositiveSmallInteger
- `retry_of` → Usage — set_null، nullable
- `quality_reason` Char
- `quality_source` Char — CUSTOMER | AUTO
- **ایندکس:** subscription، metric، period_start، state
- **ایندکس:** store، created_at
- **ایندکس:** job، state

### Payment
One attempt to pay for a plan.

- `store` → Store
- `subscription` → Subscription — set_null، nullable
- `plan` → Plan — protect
- `amount_toman` PositiveInteger
- `provider` Char
- `token` Char — ایندکس
- `reference` Char
- `status` Char — PENDING | PAID | FAILED | ABANDONED | REFUNDED
- `invoice_number` Char — یکتا
- `paid_at` DateTime — nullable
- `refunded_at` DateTime — nullable
- `refund_reason` Char
- `confirmed_by` → User — set_null، nullable
- `gateway_response` JSON
- `error` Char
- **ایندکس:** store، -created_at
- **ایندکس:** status، -created_at

### BillingEvent
Append-only record of everything that changed a subscription.

- `store` → Store
- `kind` Char — SUB_CREATED | PLAN_CHANGED | PAY_STARTED | PAY_PAID | PAY_FAILED | PAY_REFUNDED | ACTIV…
- `summary` Char
- `actor` → User — set_null، nullable
- `payment` → Payment — set_null، nullable
- `context` JSON
- **ایندکس:** store، -created_at

## marketing

### Lead
Someone who filled the contact form on the public site.

- `name` Char
- `email` Char
- `phone` Char
- `business` Char
- `subject` Char — DEMO | PRICING | SUPPORT | PARTNERSHIP | OTHER
- `message` Text
- `status` Char — NEW | CONTACTED | QUALIFIED | CONVERTED | SPAM | CLOSED
- `notes` Text
- `source_path` Char
- `referrer` Char
- `utm` JSON
- `ip` GenericIPAddress — nullable
- `user_agent` Char
- **ایندکس:** status، -created_at
- **ایندکس:** email

### Event
One thing a visitor did on the public site.

- `name` Char — page_view | cta_click | pricing_view | plan_selected | contact_submitted | signup_start…
- `session` Char — ایندکس
- `path` Char
- `locale` Char
- `referrer` Char
- `utm` JSON
- `props` JSON
- **ایندکس:** name، -created_at
- **ایندکس:** session، created_at

### ReferralCode
One shop inviting another. «مشتری، مشتری می‌آورد».

- `owner` → User
- `store` → Store — nullable
- `code` Char — یکتا
- `is_active` Boolean
- `reward_toman` PositiveInteger
- `friend_discount_percent` PositiveSmallInteger
- `note` Char

### Affiliate
A partner who sends shops our way for a cut. Not a customer.

- `user` → User — set_null، nullable
- `name` Char
- `email` Char
- `phone` Char
- `code` Char — یکتا
- `commission_percent` PositiveSmallInteger
- `commission_months` PositiveSmallInteger
- `status` Char — PENDING | ACTIVE | PAUSED | BANNED
- `payout_details` Text
- `note` Text

### DiscountCode
«کد تخفیف». Validated against a moment, never against a flag.

- `code` Char — یکتا
- `kind` Char — PERCENT | AMOUNT
- `value` PositiveInteger
- `is_active` Boolean
- `starts_at` DateTime — nullable
- `ends_at` DateTime — nullable
- `max_uses` PositiveInteger
- `used_count` PositiveInteger
- `once_per_store` Boolean
- `note` Char
- `plans` ↔ Plan

### Redemption
One use of a discount code, by one store.

- `code` → DiscountCode
- `store` → Store
- `plan` → Plan — set_null، nullable
- `price_toman` PositiveInteger
- `discount_toman` PositiveInteger

### Attribution
Where this shop came from. Written once, at signup, and left alone.

- `store` → Store — یکتا
- `channel` Char — DIRECT | REFERRAL | AFFILIATE | SEARCH | SOCIAL | ADS | CONTENT | OTHER
- `campaign` Char
- `source` Char
- `medium` Char
- `landing_path` Char
- `referrer` Char
- `referral` → ReferralCode — set_null، nullable
- `affiliate` → Affiliate — set_null، nullable
- `lead` → Lead — set_null، nullable
- `became_paying_at` DateTime — nullable
- `first_payment_toman` PositiveInteger
- **ایندکس:** channel، -created_at

### Reward
What we owe someone, and whether we have paid it.

- `kind` Char — REFERRAL | COMMISSION
- `state` Char — PENDING | APPROVED | PAID | VOID
- `amount_toman` PositiveInteger
- `user` → User — set_null، nullable
- `affiliate` → Affiliate — set_null، nullable
- `attribution` → Attribution
- `because` Char
- `paid_at` DateTime — nullable
- `paid_by` → User — set_null، nullable
- **ایندکس:** state، -created_at

## api_platform

### APIKey
One credential belonging to one store.

- `store` → Store
- `name` Char
- `prefix` Char — ایندکس
- `key_hash` Char — یکتا
- `scopes` JSON
- `is_active` Boolean
- `is_test` Boolean
- `last_used_at` DateTime — nullable
- `call_count` PositiveInteger
- `expires_at` DateTime — nullable
- `revoked_at` DateTime — nullable
- `created_by` → User — set_null، nullable
- **ایندکس:** store، is_active

### APICall
One request, kept so a shop can debug their own integration.

- `key` → APIKey
- `store` → Store
- `endpoint` Char
- `status_code` PositiveSmallInteger
- `duration_ms` PositiveInteger
- `error` Char
- **ایندکس:** store، -created_at

## cms

### Category
One shelf. An article has exactly one.

- `name` Char — یکتا
- `slug` Slug — یکتا، ایندکس
- `description` Char
- `order` PositiveSmallInteger

### Article
One blog post.

- `title` Char
- `slug` Slug — یکتا، ایندکس
- `description` Char
- `body` Text
- `author` Char
- `category` → Category — protect
- `tags` JSON
- `cover` File — nullable
- `status` Char — DRAFT | PUBLISHED | ARCHIVED
- `published_at` DateTime — nullable
- `display_date` Char
- **ایندکس:** status، -published_at

### Redirect
An old URL that should keep working.

- `old_path` Char — یکتا
- `new_path` Char
- `note` Char

### SiteSettings
The handful of strings that appear on every page.

- `name` Char
- `name_en` Char
- `tagline` Char
- `tagline_en` Char
- `one_liner` Char
- `one_liner_en` Char
- `email` Char
- `instagram` Char
- `telegram` Char
- `phone` Char
- `address` Char
- `keywords` Text
- `keywords_en` Text

### ShowcaseItem
One real output: a product, its poster, its video and its caption.

- `slug` Slug — یکتا، ایندکس
- `category` Char
- `category_en` Char
- `product` Char
- `product_en` Char
- `image` File — nullable
- `video` File — nullable
- `video_poster` File — nullable
- `caption` Text
- `caption_en` Text
- `order` PositiveSmallInteger
- `published` Boolean
- `featured` Boolean

### ShowcaseSegment
A five-second clip, kept because the stitched file is derived from it.

- `item` → ShowcaseItem
- `order` PositiveSmallInteger
- `clip` File

### FaqItem
One question and its answer.

- `group` Char — PRODUCT | AI | PRICING | SECURITY | SALES
- `question` Char
- `answer` Text
- `question_en` Char
- `answer_en` Text
- `order` PositiveSmallInteger
- `published` Boolean
- `on_home` Boolean

### SeoPage
One marketing page, written in the admin.

- `kind` Char — SOLUTION | USE_CASE | FEATURE | COMPARE
- `slug` Slug — ایندکس
- `locale` Char — fa | en
- `icon` Char
- `title` Char
- `lead` Char
- `meta_description` Char
- `intro` Text
- `problem` Text
- `benefit` Text
- `verdict` Text
- `effort` Char
- `example_before` Char
- `example_after` Char
- `published` Boolean
- `order` PositiveSmallInteger

### SeoBullet
One line in one of a page's lists.

- `page` → SeoPage
- `group` Char — PROBLEM | DOES | OUTPUT | FEATURES | WORKFLOW | OUR_WINS | THEIR_WINS | PLANNED
- `order` PositiveSmallInteger
- `text` Char

### SeoStep
A titled paragraph: a step, an answer, a "how".

- `page` → SeoPage
- `order` PositiveSmallInteger
- `title` Char
- `description` Text
- `soon` Boolean

### SeoRow
One line of a comparison table.

- `page` → SeoPage
- `order` PositiveSmallInteger
- `aspect` Char
- `us` Char
- `them` Char

### CustomerLogo
A business that uses the product (§12).

- `name` Char
- `slug` Slug — یکتا، ایندکس
- `description` Char
- `logo` File — nullable
- `website` Char
- `industry` Char
- `consented` Boolean
- `order` PositiveSmallInteger

### CaseStudy
One customer's before and after (§11).

- `customer` → CustomerLogo — set_null، nullable
- `customer_name` Char
- `title` Char
- `slug` Slug — یکتا، ایندکس
- `lead` Char
- `cover` File — nullable
- `problem` Text
- `before` Text
- `solution` Text
- `process` Text
- `outputs` Text
- `results` Text
- `conclusion` Text
- `published` Boolean
- `order` PositiveSmallInteger

### Testimonial
What a customer said (§13), in their words.

- `quote` Text
- `name` Char
- `business` Char
- `role` Char
- `photo` File — nullable
- `outcome` Char
- `case_study` → CaseStudy — set_null، nullable
- `consented` Boolean
- `order` PositiveSmallInteger

### Resource
A guide, template, checklist or e-book (§19).

- `kind` Char — guides | templates | checklists | ebooks
- `title` Char
- `slug` Slug — یکتا، ایندکس
- `description` Char
- `icon` Char
- `file` File — nullable
- `body` Text
- `published` Boolean
- `order` PositiveSmallInteger

## jobs

### Job
Persistent record of every background AI/generation job.

- `store` → Store
- `type` Char — product_analysis | market_analysis | caption_generation | image_generation | video_gene…
- `state` Char — QUEUED | PROCESSING | PREVIEW | WAITING_APPROVAL | APPROVED | RENDERING | QC | COMPLETE…
- `progress_step` PositiveInteger
- `total_steps` PositiveInteger
- `current_step_label` Char
- `retry_count` PositiveInteger
- `error` Text
- `context` JSON
- `result` JSON
- `celery_task_id` Char
- `mode` Char — SAFE | AUTO
- `preview` JSON
- `cancel_requested` Boolean
- **ایندکس:** state
- **ایندکس:** store، created_at

### RenderMetric
One measured unit of generation work.

- `kind` Char — VIDEO_SEGMENT | IMAGE | TEXT | VISION | MODEL_SWAP | AUDIO
- `engine` Char
- `hardware` Char
- `duration_s` Float
- `output_units` Float
- `resolution` Char
- `vram_peak_mb` PositiveInteger — nullable
- `load_s` Float — nullable
- `succeeded` Boolean
- `error_kind` Char
- `retry_count` PositiveSmallInteger
- `job` → Job — set_null، nullable
- `store` → Store — set_null، nullable
- `context` JSON
- **ایندکس:** kind، engine، hardware
- **ایندکس:** -created_at

---

## قواعدی که در شکل جدول‌ها دیده می‌شوند

- **هر جدولِ متعلق به فروشگاه، کلید `store` دارد** و هر کوئری با آن
  فیلتر می‌شود. ایزوله‌سازی مستأجر در لایه‌ی ORM و دسترسی است، نه در
  فرانت.
- **ستون‌های کسب‌وکاری رابطه‌ای‌اند، نه JSON.** JSON فقط برای فراداده‌ی
  مدل و ورک‌فلو است — چیزی که هرگز با آن کوئری نمی‌زنیم.
- **هیچ فایل تولیدشده‌ای بدون ردیف دیتابیس وجود ندارد**، و نام فایل‌ها
  UUID است نه ورودی کاربر.
- **قیمت و موجودی فقط از این جدول‌ها خوانده می‌شود.** مدل زبانی آن‌ها را
  قالب‌بندی می‌کند؛ هرگز نمی‌سازدشان.

<sub>80 مدل در 11 اپ.</sub>
