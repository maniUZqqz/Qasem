"""Vocabulary of the leads module (values are stored, labels are shown to the team)."""
from django.db import models


class LeadStatus(models.TextChoices):
    # The sales-pipeline statuses of the spec. The pipeline board comes later; the field exists now
    # and can be changed by hand.
    NEW = "new", "جدید"
    RESEARCHED = "researched", "بررسی‌شده"
    QUALIFIED = "qualified", "واجد شرایط"
    READY_FOR_OUTREACH = "ready_for_outreach", "آمادهٔ تماس"
    CONTACTED = "contacted", "تماس گرفته‌شده"
    REPLIED = "replied", "پاسخ داده"
    INTERESTED = "interested", "علاقه‌مند"
    DEMO_SCHEDULED = "demo_scheduled", "دمو تنظیم شد"
    NEGOTIATION = "negotiation", "در مذاکره"
    WON = "won", "مشتری شد"
    LOST = "lost", "از دست رفت"
    NOT_INTERESTED = "not_interested", "علاقه‌ای ندارد"


#: statuses from which a "message sent" outcome advances a lead to «تماس گرفته‌شده»
PRE_CONTACT_STATUSES = (
    LeadStatus.NEW.value,
    LeadStatus.RESEARCHED.value,
    LeadStatus.QUALIFIED.value,
    LeadStatus.READY_FOR_OUTREACH.value,
)


class LeadOrigin(models.TextChoices):
    MANUAL = "manual", "ثبت دستی"
    WEBSITE_URL = "website_url", "آدرس وب‌سایت"
    INSTAGRAM_URL = "instagram_url", "پیج اینستاگرام"
    BUSINESS_NAME = "business_name", "نام کسب‌وکار"
    CSV_IMPORT = "csv_import", "فایل CSV"


class BusinessType(models.TextChoices):
    UNKNOWN = "unknown", "نامشخص"
    INSTAGRAM_SHOP = "instagram_shop", "فروشگاه اینستاگرامی"
    ONLINE_STORE = "online_store", "فروشگاه اینترنتی"
    PHYSICAL_STORE = "physical_store", "فروشگاه فیزیکی"
    MARKETPLACE_SELLER = "marketplace_seller", "فروشنده در بازارچهٔ آنلاین"
    SERVICE = "service", "خدماتی"
    OTHER = "other", "سایر"


class ContactKind(models.TextChoices):
    PHONE = "phone", "تلفن"
    EMAIL = "email", "ایمیل"
    WEBSITE = "website", "وب‌سایت"
    INSTAGRAM = "instagram", "اینستاگرام"
    WHATSAPP = "whatsapp", "واتساپ"
    TELEGRAM = "telegram", "تلگرام"
    EITAA = "eitaa", "ایتا"
    BALE = "bale", "بله"
    RUBIKA = "rubika", "روبیکا"
    LINKEDIN = "linkedin", "لینکدین"
    CONTACT_FORM = "contact_form", "فرم تماس / تیکت"
    OTHER = "other", "سایر"


#: Kinds that identify a business: the same value on two leads means the same business.
IDENTIFIER_KINDS = (
    ContactKind.PHONE.value,
    ContactKind.EMAIL.value,
    ContactKind.WEBSITE.value,
    ContactKind.INSTAGRAM.value,
)


class ActivityKind(models.TextChoices):
    CREATED = "created", "ساخته شد"
    UPDATED = "updated", "ویرایش شد"
    STATUS_CHANGED = "status_changed", "وضعیت عوض شد"
    NOTE_ADDED = "note_added", "یادداشت اضافه شد"
    NOTE_EDITED = "note_edited", "یادداشت ویرایش شد"
    NOTE_DELETED = "note_deleted", "یادداشت حذف شد"
    TAG_ADDED = "tag_added", "برچسب اضافه شد"
    TAG_REMOVED = "tag_removed", "برچسب برداشته شد"
    CONTACT_ADDED = "contact_added", "راه تماس اضافه شد"
    CONTACT_UPDATED = "contact_updated", "راه تماس ویرایش شد"
    CONTACT_REMOVED = "contact_removed", "راه تماس حذف شد"
    MERGED = "merged", "با اطلاعاتِ تازه ادغام شد"
    ARCHIVED = "archived", "بایگانی شد"
    UNARCHIVED = "unarchived", "از بایگانی درآمد"
    # written by later modules through leads.services.history.log_activity
    EXTRACTION = "extraction", "استخراجِ اطلاعاتِ تماس"
    QUEUE_OUTCOME = "queue_outcome", "نتیجهٔ صفِ پیام"
    SUPPRESSED = "suppressed", "به فهرستِ «تماس نگیر» رفت"
    UNSUPPRESSED = "unsuppressed", "از فهرستِ «تماس نگیر» برداشته شد"


TAG_COLORS = ("neutral", "brand", "ok", "warn", "bad", "info")
