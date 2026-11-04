"""Growth Engine settings, with safe defaults.

Read from ``settings.GROWTH_ENGINE`` (a dict) so every limit can be tuned from the
environment without touching code; a missing key falls back to the default here.
"""
from django.conf import settings

DEFAULTS = {
    # --- CSV import ---------------------------------------------------------------------------
    "CSV_MAX_BYTES": 5 * 1024 * 1024,
    "CSV_MAX_ROWS": 10_000,
    "CSV_PREVIEW_ROWS": 8,
    "UPLOAD_TTL_SECONDS": 24 * 3600,
    "JOB_STALL_SECONDS": 180,
    "DEFAULT_COUNTRY": "IR",
    # --- bulk operations ----------------------------------------------------------------------
    "BULK_MAX_IDS": 500,
    "EXPORT_MAX_ROWS": 50_000,
    # --- outbound HTTP (integrations/safe_http.py) -----------------------------------------------
    "HTTP_USER_AGENT": "NMarketingBot/1.0 (+https://nmarketing.ir/bot; business contact lookup)",
    "HTTP_ROBOTS_TOKEN": "NMarketingBot",
    "HTTP_CONNECT_TIMEOUT": 5.0,
    "HTTP_READ_TIMEOUT": 12.0,
    "HTTP_MAX_BYTES": 1_500_000,
    "HTTP_MAX_REDIRECTS": 3,
    "HTTP_DOMAIN_DELAY": 2.0,  # seconds between two requests to the same host
    "HTTP_RETRIES": 2,  # GET only; a POST is never repeated
    "HTTP_ALLOWED_PORTS": (80, 443, 8080, 8443),
    "HTTP_ALLOW_PRIVATE": False,  # tests / a deliberately internal target only
    # --- contact extraction ------------------------------------------------------------------------
    "EXTRACT_MAX_PAGES": 5,
    "EXTRACT_RECENT_DAYS": 30,
    "EXTRACT_MAX_LEADS_PER_JOB": 500,
    # --- outreach (the values an operator edits live in Growth Settings, not here) -------------
    "SEND_MAX_ITEMS_PER_CAMPAIGN": 500,
    "SEND_SNIPPET_CHARS": 500,
}


def get(key: str):
    return {**DEFAULTS, **getattr(settings, "GROWTH_ENGINE", {})}[key]
