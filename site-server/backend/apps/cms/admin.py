"""Writing an article. This is the whole point of the app — it replaces a
git commit and a deploy with a form.
"""
from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html

from .forms import ArticleForm
from .models import (
    Article,
    CaseStudy,
    Category,
    CustomerLogo,
    FaqItem,
    Resource,
    Redirect,
    SeoBullet,
    SeoPage,
    SeoRow,
    SeoStep,
    ShowcaseItem,
    ShowcaseSegment,
    SiteSettings,
    Testimonial,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    name_en = "Blog categories"
    description = (
        "قفسه‌های وبلاگ. هر مقاله دقیقاً در یکی می‌نشیند، و همین دسته است "
        "که در نشانی /blog/category/… دیده می‌شود."
    )
    list_display = ["name", "slug", "live_count", "order"]
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ["name"]


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    name_en = "Blog articles"
    description = (
        "پست‌های وبلاگ سایت عمومی. چیزی که اینجا ذخیره می‌شود، همان است که در "
        "nmarketing.ir/blog دیده می‌شود."
    )
    # The only reason this form exists: `tags` is a JSONField, and Django
    # renders those as a box that demands valid JSON. See forms.py.
    form = ArticleForm
    list_display = ["title", "category", "state", "display_date", "reading_minutes"]
    list_filter = ["status", "category"]
    search_fields = ["title", "description", "body"]
    readonly_fields = ["reading_minutes", "created_at", "updated_at"]
    fieldsets = [
        (None, {"fields": ["title", "slug", "description", "category", "tags"]}),
        ("متن", {"fields": ["body", "cover"]}),
        ("انتشار", {
            "fields": ["status", "published_at", "display_date", "author"],
            "description": (
                "تاریخ در آینده یعنی زمان‌بندی‌شده — خودش سر وقت منتشر می‌شود. "
                "لازم نیست کاری بکنید."
            ),
        }),
        ("اطلاعات", {"fields": ["reading_minutes", "created_at", "updated_at"]}),
    ]

    @admin.display(description="وضعیت")
    def state(self, obj):
        if obj.is_scheduled:
            return format_html(
                '<span style="color:#b26b00">زمان‌بندی‌شده — {}</span>',
                obj.published_at.strftime("%Y-%m-%d %H:%M"),
            )
        if obj.is_live:
            return format_html('<span style="color:#0a7">منتشر شده</span>')
        return obj.get_status_display()

    def save_model(self, request, obj, form, change):
        """Keep old links working when somebody edits a slug.

        Editing a slug is a reasonable thing to want and a quiet catastrophe:
        every link anyone shared, and every result Google indexed, 404s — and
        the person who fixed the typo has no idea they did it.
        """
        if change and "slug" in form.changed_data:
            old = form.initial.get("slug")
            if old and old != obj.slug:
                Redirect.objects.get_or_create(
                    old_path=f"/blog/{old}",
                    defaults={
                        "new_path": f"/blog/{obj.slug}",
                        "note": f"آدرس مقاله در {timezone.now():%Y-%m-%d} عوض شد",
                    },
                )
        super().save_model(request, obj, form, change)


@admin.register(Redirect)
class RedirectAdmin(admin.ModelAdmin):
    name_en = "Redirects"
    description = (
        "آدرس‌های قدیمی که باید کار کنند. وقتی نشانی یک مقاله عوض می‌شود خودکار ساخته "
        "می‌شود — بدون این، هر لینکی که کسی به اشتراک گذاشته (و هرچه گوگل ایندکس کرده) "
        "بی‌صدا ۴۰۴ می‌شود."
    )
    list_display = ["old_path", "new_path", "note", "created_at"]
    search_fields = ["old_path", "new_path"]


# ---------------------------------------------------------------------------
#  The public site's own content. Every one of these used to be a TypeScript
#  constant that needed a deploy to change.
# ---------------------------------------------------------------------------


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    name_en = "Site settings"
    description = (
        "همان چند رشته‌ای که در تمام صفحه‌های سایت عمومی تکرار می‌شوند: نام، "
        "شعار، راه تماس. فقط یک ردیف دارد و همان یکی را ویرایش کنید."
    )
    fieldsets = [
        ("نام و شعار", {"fields": ["name", "name_en", "tagline", "tagline_en"]}),
        ("یک جمله‌ای", {
            "fields": ["one_liner", "one_liner_en"],
            "description": "همین جمله زیر تیتر صفحه‌ی اصلی می‌آید.",
        }),
        ("راه‌های ارتباط", {"fields": ["email", "phone", "instagram", "telegram", "address"]}),
        ("سئو", {"fields": ["keywords", "keywords_en"]}),
    ]

    def has_add_permission(self, request):
        # One row. The link in the sidebar goes straight to editing it.
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        # Deleting it would leave every page of the site without a name.
        return False


class ShowcaseSegmentInline(admin.TabularInline):
    model = ShowcaseSegment
    extra = 0
    fields = ["order", "clip"]


@admin.register(ShowcaseItem)
class ShowcaseItemAdmin(admin.ModelAdmin):
    name_en = "Showcase"
    description = (
        "نمونه‌کارهای واقعی: یک محصول با پوستر و ویدیو و کپشنش. همان چیزی که در صفحه‌ی "
        "نمونه‌کارها به بازدیدکننده نشان داده می‌شود."
    )
    list_display = ["product", "category", "has_video", "segment_count", "featured", "published", "order"]
    list_filter = ["published", "featured", "category"]
    list_editable = ["featured", "published", "order"]
    search_fields = ["product", "category", "caption"]
    prepopulated_fields = {"slug": ("product",)}
    inlines = [ShowcaseSegmentInline]
    fieldsets = [
        (None, {"fields": ["slug", "category", "category_en", "product", "product_en"]}),
        ("پوستر", {"fields": ["image"]}),
        ("ویدیو", {
            "fields": ["video", "video_poster"],
            "description": (
                "یک ویدیوی کامل آپلود کنید، <b>یا</b> قطعه‌های ۵ ثانیه‌ای را پایین "
                "اضافه کنید و بعد دستور <code>python manage.py stitch_showcase</code> "
                "را بزنید تا به هم بچسبند و همین‌جا بنشینند. سایت همیشه "
                "<b>یک</b> ویدیو نشان می‌دهد، نه قطعه‌های جدا."
            ),
        }),
        ("کپشن", {"fields": ["caption", "caption_en"]}),
        ("نمایش", {"fields": ["featured", "published", "order"]}),
    ]

    @admin.display(description="ویدیو", boolean=True)
    def has_video(self, obj):
        return bool(obj.video)

    @admin.display(description="قطعه‌ها")
    def segment_count(self, obj):
        return obj.segments.count()


@admin.register(FaqItem)
class FaqItemAdmin(admin.ModelAdmin):
    name_en = "FAQ"
    description = (
        "پرسش‌های متداول سایت، گروه‌بندی‌شده (محصول، قیمت، امنیت…) چون صفحه‌ی /faq "
        "بخش‌بخش رندر می‌شود."
    )
    list_display = ["question", "group", "on_home", "published", "order"]
    list_filter = ["group", "published", "on_home"]
    list_editable = ["on_home", "published", "order"]
    search_fields = ["question", "answer"]
    fieldsets = [
        (None, {"fields": ["group", "question", "answer"]}),
        ("English", {"fields": ["question_en", "answer_en"], "classes": ["collapse"]}),
        ("نمایش", {"fields": ["on_home", "published", "order"]}),
    ]


# ---------------------------------------------------------------------------
#  SEO pages. Four kinds, one form — they share a shape, and four admin pages
#  that look identical is four places to fix the same typo.
# ---------------------------------------------------------------------------


class SeoBulletInline(admin.TabularInline):
    model = SeoBullet
    extra = 0
    fields = ["group", "order", "text"]


class SeoStepInline(admin.TabularInline):
    model = SeoStep
    extra = 0
    fields = ["order", "title", "description", "soon"]


class SeoRowInline(admin.TabularInline):
    model = SeoRow
    extra = 0
    fields = ["order", "aspect", "us", "them"]
    verbose_name_plural = "ردیف‌های جدول مقایسه — فقط برای صفحه‌های «مقایسه»"


@admin.register(SeoPage)
class SeoPageAdmin(admin.ModelAdmin):
    name_en = "SEO pages"
    description = (
        "صفحه‌های بازاریابی سایت که متنشان از همین‌جا نوشته می‌شود — بدون دست‌زدن به "
        "کد."
    )
    list_display = ["title", "kind", "slug", "locale", "published", "order"]
    list_filter = ["kind", "locale", "published"]
    list_editable = ["published", "order"]
    search_fields = ["title", "slug", "lead", "intro"]
    prepopulated_fields = {"slug": ("title",)}
    inlines = [SeoBulletInline, SeoStepInline, SeoRowInline]
    fieldsets = [
        (None, {
            "fields": ["kind", "slug", "locale", "icon", "title", "lead"],
            "description": (
                "اگر <b>slug</b> با یکی از صفحه‌های موجود یکی باشد، این ردیف "
                "جای آن را می‌گیرد. اگر تازه باشد، یک صفحه‌ی تازه ساخته می‌شود — "
                "بدون دیپلوی."
            ),
        }),
        ("متن", {"fields": ["intro", "problem", "benefit", "verdict", "effort"]}),
        ("قبل و بعد", {"fields": ["example_before", "example_after"]}),
        ("سئو", {"fields": ["meta_description"]}),
        ("نمایش", {"fields": ["published", "order"]}),
    ]


# ---------------------------------------------------------------------------
#  Proof and resources. Each of these pages 404s while its table is empty, on
#  purpose — see the models. The `consented` checkboxes are the other half of
#  that: a logo or a quote is a public claim about somebody else's business.
# ---------------------------------------------------------------------------


@admin.register(CustomerLogo)
class CustomerLogoAdmin(admin.ModelAdmin):
    name_en = "Customer logos"
    description = (
        "کسب‌وکارهایی که از محصول استفاده می‌کنند. ستون «رضایت» تزئینی نیست: لوگوی کسی "
        "روی صفحه‌ی بازاریابی، ادعایی عمومی درباره‌ی کسب‌وکار اوست."
    )
    list_display = ["name", "industry", "consented", "order"]
    list_filter = ["consented", "industry"]
    list_editable = ["consented", "order"]
    search_fields = ["name", "description"]
    prepopulated_fields = {"slug": ("name",)}


class TestimonialInline(admin.StackedInline):
    model = Testimonial
    extra = 0
    fields = ["quote", "name", "business", "role", "outcome", "consented", "order"]


@admin.register(CaseStudy)
class CaseStudyAdmin(admin.ModelAdmin):
    name_en = "Case studies"
    description = (
        "قبل و بعدِ یک مشتری. ترتیب فیلدها عمدی است — مشکل، وضع قبل، راه‌حل، نتیجه — "
        "چون همان ترتیب است که صفحه را به یک روایت تبدیل می‌کند نه فهرست قابلیت."
    )
    list_display = ["title", "who", "published", "order"]
    list_filter = ["published"]
    list_editable = ["published", "order"]
    search_fields = ["title", "problem", "results"]
    prepopulated_fields = {"slug": ("title",)}
    inlines = [TestimonialInline]
    fieldsets = [
        (None, {
            "fields": ["title", "slug", "customer", "customer_name", "lead", "cover"],
            "description": (
                "تا وقتی «منتشر شده» تیک نخورد، صفحه‌ی مطالعات موردی این را "
                "نشان نمی‌دهد — و اگر هیچ مطالعه‌ای منتشر نشده باشد، خودِ صفحه "
                "۴۰۴ می‌دهد و در sitemap نمی‌آید."
            ),
        }),
        ("داستان", {
            "fields": ["problem", "before", "solution", "process", "outputs",
                       "results", "conclusion"],
        }),
        ("نمایش", {"fields": ["published", "order"]}),
    ]

    @admin.display(description="مشتری")
    def who(self, obj):
        return obj.who or "—"


@admin.register(Testimonial)
class TestimonialAdmin(admin.ModelAdmin):
    name_en = "Testimonials"
    description = (
        "آنچه مشتری گفته، با کلمات خودش."
    )
    list_display = ["name", "business", "outcome", "consented", "order"]
    list_filter = ["consented"]
    list_editable = ["consented", "order"]
    search_fields = ["name", "business", "quote"]


@admin.register(Resource)
class ResourceAdmin(admin.ModelAdmin):
    name_en = "Resources"
    description = (
        "راهنما، قالب، چک‌لیست و کتابچه‌ی قابل دانلود. ابزار جذب سرنخ است، پس باید "
        "واقعاً به کار بیاید."
    )
    list_display = ["title", "kind", "has_file", "published", "order"]
    list_filter = ["kind", "published"]
    list_editable = ["published", "order"]
    search_fields = ["title", "description"]
    prepopulated_fields = {"slug": ("title",)}
    fieldsets = [
        (None, {"fields": ["kind", "title", "slug", "icon", "description"]}),
        ("محتوا", {
            "fields": ["file", "body"],
            "description": "یا یک فایل برای دانلود بگذار، یا متن مارک‌داون بنویس.",
        }),
        ("نمایش", {"fields": ["published", "order"]}),
    ]

    @admin.display(description="فایل", boolean=True)
    def has_file(self, obj):
        return bool(obj.file)
