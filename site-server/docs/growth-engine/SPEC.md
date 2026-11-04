
UPmarket Growth Engine

Master Implementation Specification

You are acting as a Senior Software Architect, Lead Backend Engineer, AI Engineer, and Frontend Engineer.

Your task is to implement an internal customer acquisition and sales intelligence engine for the existing UpMarket platform.

This is an internal growth tool, not a standalone SaaS and not a generic CRM.

The system must discover potential customers, understand their businesses, identify opportunities for UpMarket, generate personalized sales proposals, and manage human-approved outreach.

---

1. PRODUCT CONTEXT

UpMarket is an AI-powered marketing and content production platform for small businesses, online shops, and Instagram sellers.

Its value proposition is helping small sellers access AI-powered marketing capabilities without hiring a complete marketing team.

Target customers:

- Instagram shops
- Online stores
- Clothing stores
- Cosmetics shops
- Accessories shops
- Small product-based businesses
- Other businesses that need regular marketing content

The Growth Engine must find businesses that could genuinely benefit from UpMarket.

Primary market: Iran.

The architecture must allow expansion to other countries and languages.

The system supports two discovery methods:

1. Automatic discovery through permitted search APIs, directories, and other authorized sources.
2. Manual discovery through website URLs, Instagram profile URLs, manual entries, and CSV imports.

Outreach mode: Human approval is mandatory before every outbound communication.

2. FIRST TASK: REPOSITORY AUDIT

Before writing code, inspect the existing UpMarket repository.

Identify:

- Existing Django applications
- Existing React application
- Existing authentication system
- Existing database configuration
- Existing AI integrations
- Existing API architecture
- Existing shared components
- Existing design system
- Existing background task infrastructure

Do not replace existing infrastructure unnecessarily.

Do not create duplicate authentication, AI services, or database configurations.

The public Next.js marketing website must remain independent and unaffected.

Integrate the Growth Engine into the existing authenticated application wherever practical.

After auditing, provide:

1. Current architecture.
2. Proposed integration architecture.
3. Folder structure.
4. Database schema.
5. API endpoint specification.
6. Development milestones.
7. Existing code that can be reused.
8. Potential technical risks.

Wait for approval before making architectural changes.

3. ARCHITECTURE

Use a modular monolith architecture.

Backend:

- Django
- Django REST Framework
- PostgreSQL
- Celery
- Redis

Frontend:

- Existing React application
- TypeScript
- Existing UI component system
- Recharts for analytics where appropriate

Data collection:

- httpx
- BeautifulSoup
- Playwright when browser rendering is necessary
- Official APIs
- Authorized business directories

AI:

- Existing UpMarket AI gateway if available
- OpenAI-compatible API interface
- Configurable models
- Structured JSON outputs
- Configurable prompts

Do not introduce new infrastructure without a clear reason.

4. BACKEND MODULES

Create an independent Django application namespace:

apps/growth_engine/

Organize responsibilities into:

- core
- sources
- discovery
- extraction
- leads
- enrichment
- qualification
- intelligence
- campaigns
- ai_writer
- outreach
- compliance
- analytics
- integrations

Each module must have its own models, serializers, services, views, URLs, tasks, and tests where applicable.

Use service classes for business logic.

Avoid large views, giant service files, duplicated code, and circular dependencies.

5. DISCOVERY ENGINE

Implement a provider-based discovery architecture.

Create a shared interface for discovery providers.

Supported discovery modes:

A. Search-based discovery:

- Search by business category.
- Search by city and country.
- Search by keywords.
- Search by business type.
- Search by domain.
- Search by product category.

B. Manual discovery:

> Manora:
- Website URL.
- Instagram profile URL.
- Business name.
- CSV upload.
- Manual business information.

C. API integrations:

- Official search APIs.
- Authorized business directories.
- Other providers that permit the intended commercial use.

Each provider must be independently replaceable.

Every discovery result must contain:

- Business name
- Website URL
- Social profile URLs when provided or lawfully available
- Source provider
- Source URL
- Discovery timestamp
- Country
- City
- Business category

Implement duplicate detection using normalized URLs, domains, and other reliable identifiers.

Support discovery jobs with:

- Queued
- Running
- Completed
- Failed
- Cancelled

Provide progress tracking and error reporting.

Do not bypass authentication, CAPTCHA, access restrictions, anti-bot controls, or platform terms.

Instagram data collection must use user-provided information, permitted public sources, or authorized APIs. Do not automate unauthorized profile scraping or messaging.

6. BUSINESS DATA EXTRACTION

Create an extraction engine.

For permitted websites, extract:

- Business name
- Description
- Product categories
- Product names
- Publicly available product information
- Public contact page
- Public business email
- Public business phone
- Website language
- Public social links
- Business location when available

Build a modular extractor.

Use BeautifulSoup for normal HTML pages.

Use Playwright only when JavaScript rendering is necessary and permitted.

Implement:

- Request timeouts
- Retry handling
- Rate limits
- Robots and website policy checks
- Extraction logs
- Source attribution
- Field-level provenance
- Extraction confidence

Never fabricate missing information.

7. LEAD MANAGEMENT

Implement a complete Lead management system.

Lead fields:

- Business name
- Website
- Instagram URL
- Business category
- Description
- Country
- City
- Lead status
- Discovery source
- Created timestamp
- Updated timestamp

Create separate models for:

- ContactPoint
- LeadSource
- BusinessProfile
- LeadTag
- LeadNote
- LeadActivity

Support:

- Search
- Filters
- Sorting
- Pagination
- Bulk selection
- CSV import
- CSV export
- Duplicate detection
- Manual editing
- Lead history

8. BUSINESS INTELLIGENCE

Build a dedicated business research engine.

Its purpose is to understand whether a business could benefit from UpMarket.

Analyze available evidence:

- Product types
- Business model
- Online presence
- Marketing activity
- Public content quality
- Product presentation
- Available promotional material
- Content publishing patterns where evidence is available
- Potential marketing opportunities

Generate a structured research report:

{
"business_summary": "",
"business_category": "",
"target_audience": [],
"products": [],
"online_presence": {},
"observed_marketing_activity": [],
"potential_opportunities": [],
"evidence": [],
"missing_information": [],
"confidence": 0
}

All claims must be grounded in collected evidence.

Clearly distinguish facts from hypotheses.

Do not claim that a business lacks a marketing team or has a specific problem without evidence.

9. LEAD QUALIFICATION

Build a configurable scoring engine.

Initial scoring weights:

- Business compatibility: 25
- AI content production opportunity: 20
- Online presence: 15
- Product and market compatibility: 15
- Commercial potential: 15
- Information completeness: 10

Total: 100.

Scoring must be configurable from the admin interface.

Store:

- Score
- Individual criterion scores
- Explanation
- Evidence
- Confidence
- Scoring timestamp

Qualification statuses:

- High Priority
- Medium Priority
- Low Priority
- Needs Review
- Disqualified

Never use lead score as a substitute for permission to contact.

10. AI SALES RESEARCHER

Create a dedicated AI service.

For every qualified lead, generate:

1. Business summary.
2. Potential customer needs.
3. UpMarket product opportunities.
4. Recommended value proposition.
5. Suggested sales angle.
6. Suggested demonstration.
7. Possible objections.
8. Suggested response to objections.

> Manora:
The AI must understand UpMarket's actual capabilities.

Do not promise unavailable features.

Create a configurable UpMarket product knowledge base containing:

- Product description
- Features
- Pricing
- Benefits
- Limitations
- Target customer profiles
- Demonstration URLs
- Current offers

Use this knowledge base as the source of truth for sales generation.

11. AI MESSAGE GENERATOR

Generate personalized messages using:

- Business research
- Lead information
- UpMarket knowledge base
- Campaign objective
- Communication channel
- Language
- Tone

Output structured data:

{
"subject": "",
"message": "",
"personalization_reason": "",
"value_proposition": "",
"evidence_references": [],
"warnings": []
}

Support Persian and English initially.

Provide:

- Formal tone
- Friendly business tone
- Concise tone
- Professional sales tone

Users must be able to:

- Generate
- Regenerate
- Edit
- Save
- Compare message versions
- Approve
- Reject

Do not invent facts, relationships, previous conversations, testimonials, or business-specific observations.

12. CAMPAIGN MANAGEMENT

Users must be able to create campaigns.

Campaign fields:

- Campaign name
- Target business categories
- Country
- City
- Target criteria
- Selected leads
- Objective
- Message template
- Language
- Communication channel
- Campaign status

Campaign statuses:

- Draft
- Discovering
- Researching
- Ready for Review
- Active
- Paused
- Completed
- Cancelled

A campaign must be able to run discovery, qualification, and research as separate background jobs.

Allow users to inspect campaign results before approving any outreach.

13. COMPLIANCE AND HUMAN APPROVAL

This is a mandatory architectural requirement.

Every outbound communication must pass:

1. Contact eligibility validation.
2. Channel-specific permission validation.
3. Suppression-list validation.
4. Duplicate communication validation.
5. Campaign status validation.
6. Human approval validation.

Create an immutable approval history.

Approval must be bound to the exact message version and recipient.

If the message or recipient changes after approval, approval must become invalid.

Do not treat a publicly visible email address, Instagram profile, or contact form as automatic marketing consent.

Implement:

- Consent and lawful-basis records where applicable.
- Contact permission tracking.
- Source and purpose records.
- Unsubscribe management.
- Suppression lists.
- Audit logs.
- Configurable sending limits.
- Campaign pause.
- Emergency stop.

Contact forms must not be used for automated unsolicited mass submissions.

Never implement spam-filter evasion, CAPTCHA bypass, unauthorized bulk messaging, or platform restriction bypass.

14. OUTREACH PROVIDER ARCHITECTURE

Build a provider-based communication system.

Common provider methods:

- validate()
- send()
- get_status()
- handle_webhook()

Initial channels:

1. Email through authorized providers.
2. WhatsApp Business through authorized integrations.
3. Instagram through supported official integrations or manual contact workflows.
4. Manual phone-call tasks.
5. Manual follow-up tasks.

Provider integrations must be optional and independently replaceable.

No channel may send without explicit approval and valid eligibility.

Implement:

- Idempotency keys
- Delivery status
- Retry policies
- Failure handling
- Provider rate limits
- Delivery logs
- Cancellation
- Webhook processing

Never retry blocked or opted-out contacts.

15. SALES PIPELINE

Build an internal sales pipeline.

Statuses:

- New
- Researched
- Qualified
- Ready for Outreach
- Contacted
- Replied
- Interested
- Demo Scheduled
- Negotiation
- Won
- Lost
- Not Interested

Allow manual status updates.

Record:

- Notes
- Contact history
- Meetings
- Next actions
- Objections
- Sales outcomes
- Lost reasons

The purpose is to help the UpMarket team manage real opportunities, not to become a generic CRM.

16. FRONTEND PAGES

Create the following pages inside the existing application:

> Manora:
1. Growth Dashboard
2. Lead Discovery
3. Discovery Job Details
4. Lead Database
5. Lead Details
6. Business Intelligence
7. AI Sales Research
8. Campaign Management
9. Campaign Details
10. AI Message Editor
11. Approval Queue
12. Outreach History
13. Sales Pipeline
14. Analytics
15. Provider Integrations
16. Growth Settings

UI requirements:

- Persian RTL support
- Responsive layout
- Reusable components
- Consistent design system
- Search and filters
- Data tables
- Charts
- Progress indicators
- Loading states
- Empty states
- Error states
- Confirmation dialogs

Keep components small and modular.

Do not duplicate components already available in the existing application.

17. ANALYTICS

Track:

- Total discovered businesses
- Unique leads
- Qualified leads
- High-priority leads
- Research completion rate
- Generated messages
- Approved messages
- Outreach attempts
- Delivered messages
- Responses
- Interested leads
- Demos scheduled
- Won opportunities
- Conversion rates

Provide filtering by:

- Campaign
- Date
- Business category
- Country
- City
- Communication channel

Do not confuse delivery rate with response rate or conversion rate.

18. SECURITY AND PERFORMANCE

Implement:

- Authentication using existing UpMarket infrastructure.
- Role-based permissions.
- Environment-based secrets.
- Input validation.
- Secure file uploads.
- API rate limits.
- Structured logging.
- Database indexes.
- Background processing.
- Transaction-safe operations.
- Error monitoring.

Do not expose API keys or provider credentials to the frontend.

Avoid N+1 database queries.

Avoid synchronous execution of long-running discovery or extraction tasks.

19. TESTING

Create tests for:

- Discovery providers
- URL normalization
- Lead deduplication
- Extraction
- Data provenance
- Qualification scoring
- AI structured output
- Research evidence validation
- Contact eligibility
- Suppression lists
- Approval invalidation
- Duplicate-send prevention
- Campaign execution
- Provider failures
- Celery retries
- API permissions

Use mocked external APIs in automated tests.

Do not send real messages during tests.

20. IMPLEMENTATION MILESTONES

Implement in the following order:

Milestone 0:
Repository audit and architecture approval.

Milestone 1:
Core models, API structure, navigation and Growth Dashboard.

Milestone 2:
Manual discovery, CSV import and Lead management.

Milestone 3:
Automatic discovery provider framework.

Milestone 4:
Website extraction and enrichment.

Milestone 5:
Business Intelligence and lead scoring.

Milestone 6:
AI Sales Researcher and product knowledge base.

Milestone 7:
AI Message Generator and Campaign Management.

Milestone 8:
Compliance, approval and outreach provider framework.

Milestone 9:
Sales Pipeline and Analytics.

Milestone 10:
Integration testing, optimization and deployment documentation.

Complete and test each milestone before proceeding.

21. IMPORTANT DEVELOPMENT RULES

- Do not implement everything in one enormous file.
- Do not generate the whole project in one response.
- Do not overwrite working application code.
- Do not introduce unnecessary dependencies.
- Reuse existing services and components.
- Keep business logic independent of API views.
- Keep AI providers replaceable.
- Keep discovery sources replaceable.
- Keep communication providers replaceable.
- Add documentation for every module.
- Add tests for every critical business rule.
- Maintain backward compatibility.
- Never assume a feature exists without inspecting the repository.

At the end of each milestone, report:

1. Implemented features.
2. Created files.
3. Modified files.
4. Database migrations.
5. API endpoints.
6. Tests executed and results.
7. Known issues.
8. Manual verification instructions.
9. Next milestone.

Do not mark incomplete functionality as completed.

FINAL OBJECTIVE

Deliver a reliable internal AI-powered growth engine for UpMarket.

The system should help the team:


Discover relevant businesses → Understand their business → Identify marketing opportunities → Qualify leads → Generate personalized sales proposals → Approve outreach → Manage conversations → Convert prospects into UpMarket customers.

Start with the repository audit and wait for architectural approval.
