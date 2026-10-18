"""Articles, written in the admin instead of in a git commit.

Markdown files were right for seven articles: versioned with the code,
reviewable in a pull request, no admin needed. They stop being right at the
cadence this is going to: an article every other day means a deploy every other
day, and a deploy to publish a blog post is a deploy nobody wants to do at
eleven at night — so the post waits, and the cadence quietly dies.

Four decisions worth reading.

**Publishing is a date, not a button.** `published_at` in the future means
scheduled; in the past means live. One field, no state machine, and "publish
this on Saturday morning" costs nothing extra.

**The slug never changes by itself.** It is set once from the title and then
left alone, because a slug that follows the title breaks every link to the
article the moment somebody fixes a typo in the headline — and the person
fixing the typo has no idea they did it.

**A category is a shelf; tags are labels.** One category per article, many tags.
That is what makes a category page a navigable section rather than a second tag
list, and it matches what the site already renders.

**Markdown stays the input format.** It is what the existing articles are
written in, what the existing renderer expects, and what a writer can paste from
anywhere. Storing HTML would mean trusting whatever a browser editor produced.
"""
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from apps.common.models import TimeStampedModel

#: Persian reads slower than English in most measurements. Only ever shown as a
#: rough hint, so the exact number matters less than it being honest.
WORDS_PER_MINUTE = 200


class Category(TimeStampedModel):
    """One shelf. An article has exactly one."""

    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=100, unique=True, allow_unicode=True, blank=True)
    description = models.CharField(max_length=300, blank=True)
    order = models.PositiveSmallIntegerField(default=100)

    class Meta:
        ordering = ["order", "name"]
        verbose_name = "دسته"
        verbose_name_plural = "دسته‌ها"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name, allow_unicode=True)
        super().save(*args, **kwargs)

    @property
    def live_count(self) -> int:
        return self.articles.filter(
            status=Article.Status.PUBLISHED, published_at__lte=timezone.now(),
        ).count()


class Article(TimeStampedModel):
    """One blog post."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "پیش‌نویس"
        PUBLISHED = "PUBLISHED", "منتشرشده"
        ARCHIVED = "ARCHIVED", "بایگانی"

    title = models.CharField(max_length=200)
    #: Set once, from the title, and then left alone. See the module docstring.
    slug = models.SlugField(max_length=220, unique=True, allow_unicode=True, blank=True)
    description = models.CharField(
        max_length=300,
        help_text="یک جمله — همین در گوگل و زیر عنوان نشان داده می‌شود",
    )
    body = models.TextField(help_text="مارک‌داون")
    author = models.CharField(max_length=120, default="تیم آپ‌مارکت")
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="articles",
    )
    tags = models.JSONField(default=list, blank=True)
    cover = models.ImageField(upload_to="blog/covers/", null=True, blank=True)

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.DRAFT,
    )
    #: The future means scheduled, the past means live. One field instead of a
    #: state machine, so "publish this on Saturday morning" costs nothing.
    published_at = models.DateTimeField(null=True, blank=True)

    #: Persian dates are written by hand because converting them properly needs
    #: a calendar library, and a wrong date on an article is worse than one the
    #: author typed.
    display_date = models.CharField(
        max_length=40, blank=True, help_text="مثلاً ۱۴۰۴/۰۶/۱۵ — اگر خالی بماند نمایش داده نمی‌شود",
    )

    class Meta:
        ordering = ["-published_at", "-created_at"]
        indexes = [models.Index(fields=["status", "-published_at"])]
        verbose_name = "مقاله"
        verbose_name_plural = "مقاله‌ها"

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._unique_slug()
        # Publishing without a date would leave the article invisible on a page
        # that filters by date — which looks exactly like a bug to whoever just
        # pressed publish.
        if self.status == self.Status.PUBLISHED and self.published_at is None:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)

    def _unique_slug(self) -> str:
        base = slugify(self.title, allow_unicode=True)[:200] or "article"
        slug, suffix = base, 2
        while Article.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug = f"{base}-{suffix}"
            suffix += 1
        return slug

    @property
    def is_live(self) -> bool:
        return (
            self.status == self.Status.PUBLISHED
            and self.published_at is not None
            and self.published_at <= timezone.now()
        )

    @property
    def is_scheduled(self) -> bool:
        return (
            self.status == self.Status.PUBLISHED
            and self.published_at is not None
            and self.published_at > timezone.now()
        )

    @property
    def reading_minutes(self) -> int:
        words = len(self.body.split())
        return max(1, round(words / WORDS_PER_MINUTE))

    @property
    def clean_tags(self) -> list[str]:
        out = []
        for tag in (self.tags or [])[:12]:
            text = str(tag).strip()[:40]
            if text and text not in out:
                out.append(text)
        return out


class Redirect(TimeStampedModel):
    """An old URL that should keep working.

    Created automatically when a slug is changed by hand in the admin. Without
    it, editing a slug silently 404s every link anyone ever shared — including
    the ones Google has indexed, which is the traffic the article was for.
    """

    old_path = models.CharField(max_length=300, unique=True)
    new_path = models.CharField(max_length=300)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "ریدایرکت"
        verbose_name_plural = "ریدایرکت‌ها"

    def __str__(self):
        return f"{self.old_path} → {self.new_path}"


# ---------------------------------------------------------------------------
#  Everything below this line is the public site's own content.
#
#  It used to live in `website/lib/*.ts` and `website/content/*.json`, which
#  meant that changing the tagline, adding a question to the FAQ or swapping a
#  sample video was a code edit, a build and a deploy. That is the same trap the
#  articles were in before this app existed, and it has the same answer: put it
#  behind the admin, keep the files as the fallback.
# ---------------------------------------------------------------------------


class SiteSettings(TimeStampedModel):
    """The handful of strings that appear on every page.

    A single row. `load()` returns it and creates it on first call, so nothing
    downstream has to cope with an empty table — a site whose name renders as
    blank because nobody opened the admin yet is worse than one with a default.
    """

    name = models.CharField(max_length=80, default="آپ‌مارکت")
    name_en = models.CharField(max_length=80, default="UpMarket")
    tagline = models.CharField(max_length=200, blank=True)
    tagline_en = models.CharField(max_length=200, blank=True)
    one_liner = models.CharField(max_length=300, blank=True)
    one_liner_en = models.CharField(max_length=300, blank=True)
    email = models.EmailField(blank=True)
    instagram = models.URLField(blank=True)
    telegram = models.URLField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    address = models.CharField(max_length=300, blank=True)
    #: Comma-separated, not JSON: whoever edits this is writing keywords, not
    #: data, and a mistyped bracket should not be able to break the page.
    keywords = models.TextField(
        blank=True, help_text="با ویرگول جدا کنید — برای متادیتای سئو",
    )
    keywords_en = models.TextField(blank=True, help_text="با ویرگول جدا کنید")

    class Meta:
        verbose_name = "تنظیمات سایت"
        verbose_name_plural = "تنظیمات سایت"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # One row, always. Without this a second row is one misclick away, and
        # then which one the site reads is down to primary-key order.
        self.pk = 1
        # `objects.create()` passes force_insert, which turns "save over row 1"
        # into a UNIQUE violation — a crash where the point was that there is
        # only ever one row.
        kwargs.pop("force_insert", None)
        # …and that turns the second create into an UPDATE, where `auto_now_add`
        # contributes nothing, so `created_at` would go in as NULL. Keep the
        # row's real birthday.
        if self.created_at is None:
            self.created_at = (
                type(self).objects.filter(pk=1)
                .values_list("created_at", flat=True).first()
                or timezone.now()
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):  # pragma: no cover - blocked in admin too
        pass

    @classmethod
    def load(cls) -> "SiteSettings":
        row, _ = cls.objects.get_or_create(pk=1)
        return row

    @staticmethod
    def split(text: str) -> list[str]:
        return [part.strip() for part in (text or "").split("،" if "،" in (text or "") else ",") if part.strip()]


class ShowcaseItem(TimeStampedModel):
    """One real output: a product, its poster, its video and its caption.

    **One video, not five.** The pipeline renders in five-second segments and
    the site used to show them as five tiles playing at once, which is a
    description of our rendering architecture, not a sample of our work. The
    segments belong stitched, and stitching them is `stitch_showcase`'s job —
    this model stores the finished file.
    """

    slug = models.SlugField(max_length=60, unique=True, allow_unicode=True)
    category = models.CharField(max_length=60, help_text="مثلاً پوشاک، دکوراسیون")
    category_en = models.CharField(max_length=60, blank=True)
    product = models.CharField(max_length=120)
    product_en = models.CharField(max_length=120, blank=True)

    image = models.ImageField(upload_to="showcase/", null=True, blank=True)
    #: The stitched result. `segments` below is only ever the raw material.
    video = models.FileField(upload_to="showcase/", null=True, blank=True)
    #: A still to show before the video is played. Without one the browser
    #: shows a black rectangle until the first frame decodes.
    video_poster = models.ImageField(upload_to="showcase/", null=True, blank=True)
    caption = models.TextField(blank=True)
    caption_en = models.TextField(blank=True)

    order = models.PositiveSmallIntegerField(default=100)
    published = models.BooleanField(default=True)
    #: Shown on the home page as the "one product, three outputs" sample.
    #: Exactly one item should have it; `save` enforces that.
    featured = models.BooleanField(
        default=False, help_text="نمونه‌ای که در صفحه‌ی اصلی نشان داده می‌شود",
    )

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "نمونه‌کار"
        verbose_name_plural = "نمونه‌کارها"

    def __str__(self):
        return f"{self.category} — {self.product}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.featured:
            # Two featured samples means the home page picks one by id, which
            # looks like the admin ignoring the checkbox that was just ticked.
            ShowcaseItem.objects.filter(featured=True).exclude(pk=self.pk).update(
                featured=False,
            )


class ShowcaseSegment(TimeStampedModel):
    """A five-second clip, kept because the stitched file is derived from it.

    Uploading the segments and letting `stitch_showcase` join them is the
    supported path; uploading a finished video straight onto `ShowcaseItem`
    also works and skips this table entirely.
    """

    item = models.ForeignKey(
        ShowcaseItem, on_delete=models.CASCADE, related_name="segments",
    )
    order = models.PositiveSmallIntegerField(default=1)
    clip = models.FileField(upload_to="showcase/segments/")

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "قطعه‌ی ویدیو"
        verbose_name_plural = "قطعه‌های ویدیو"

    def __str__(self):
        return f"{self.item.product} — قطعه {self.order}"


class FaqItem(TimeStampedModel):
    """One question and its answer.

    Grouped rather than flat, because `/faq` renders sections (محصول، قیمت،
    امنیت…) and a flat list would have to guess them back from the text.
    """

    class Group(models.TextChoices):
        PRODUCT = "PRODUCT", "محصول"
        AI = "AI", "هوش مصنوعی"
        PRICING = "PRICING", "قیمت"
        SECURITY = "SECURITY", "امنیت"
        SALES = "SALES", "فروش"

    group = models.CharField(
        max_length=10, choices=Group.choices, default=Group.PRODUCT,
    )
    question = models.CharField(max_length=300)
    answer = models.TextField()
    question_en = models.CharField(max_length=300, blank=True)
    answer_en = models.TextField(blank=True)
    order = models.PositiveSmallIntegerField(default=100)
    published = models.BooleanField(default=True)
    #: On the home page only the first few are shown, and they are the ones
    #: that decide whether somebody keeps reading.
    on_home = models.BooleanField(default=False, verbose_name="در صفحه‌ی اصلی")

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "سؤال متداول"
        verbose_name_plural = "سؤالات متداول"

    def __str__(self):
        return self.question


# ---------------------------------------------------------------------------
#  SEO pages: solutions, use cases, features, comparisons.
#
#  `سایت عمومی.md` §2 asks for an architecture that can grow to «۱۰۰ تا ۵۰۰+
#  صفحه» without touching the front-end, and §34 forbids the obvious shortcut —
#  no near-identical pages generated for keywords. Both point the same way: a
#  page is a row somebody wrote, not a template with a noun swapped.
#
#  The TypeScript files stay as the shipped set. These rows **add to and
#  override** them by slug, so an editor can publish a new industry page or fix
#  a sentence on an existing one without a deploy, and a build that cannot
#  reach the backend still renders every page that shipped.
#
#  Four kinds share one model because they share one shape: an intro, some
#  bullets, some titled steps, a before/after, and — for comparisons — a table.
#  Giving each its own model would be four admin pages that look identical.
# ---------------------------------------------------------------------------


class SeoPage(TimeStampedModel):
    """One marketing page, written in the admin."""

    class Kind(models.TextChoices):
        SOLUTION = "SOLUTION", "راه‌حل (صنعت)"
        USE_CASE = "USE_CASE", "مورد استفاده"
        FEATURE = "FEATURE", "قابلیت"
        COMPARE = "COMPARE", "مقایسه"

    kind = models.CharField(max_length=10, choices=Kind.choices)
    slug = models.SlugField(max_length=120, allow_unicode=True)
    locale = models.CharField(
        max_length=2, choices=[("fa", "فارسی"), ("en", "انگلیسی")], default="fa",
    )

    icon = models.CharField(max_length=8, blank=True, help_text="یک ایموجی")
    title = models.CharField(max_length=200)
    lead = models.CharField(
        max_length=300, blank=True, help_text="یک جمله — روی کارت‌ها و زیر تیتر",
    )
    meta_description = models.CharField(
        max_length=300, blank=True, help_text="اگر خالی بماند، از «یک جمله» ساخته می‌شود",
    )

    #: The long prose. Which of these a page uses depends on its kind, and the
    #: admin only shows the ones that kind renders.
    intro = models.TextField(blank=True, verbose_name="مقدمه")
    problem = models.TextField(blank=True, verbose_name="مسئله")
    benefit = models.TextField(blank=True, verbose_name="چرا مهم است")
    verdict = models.TextField(
        blank=True, verbose_name="نتیجه‌گیری",
        help_text="فقط برای مقایسه — «کدام برای چه کسی».",
    )
    effort = models.CharField(
        max_length=120, blank=True, verbose_name="چقدر طول می‌کشد",
    )

    example_before = models.CharField(max_length=300, blank=True, verbose_name="قبل")
    example_after = models.CharField(max_length=300, blank=True, verbose_name="بعد")

    published = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=100)

    class Meta:
        ordering = ["order", "id"]
        # One page per slug per language per kind. Without this, two rows for
        # the same URL are one paste away and which one wins is arbitrary.
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "slug", "locale"], name="unique_seo_page",
            ),
        ]
        verbose_name = "صفحه‌ی سئو"
        verbose_name_plural = "صفحه‌های سئو"

    def __str__(self):
        return f"{self.get_kind_display()} — {self.title}"


class SeoBullet(TimeStampedModel):
    """One line in one of a page's lists."""

    class Group(models.TextChoices):
        PROBLEM = "PROBLEM", "مشکل‌ها"
        DOES = "DOES", "چه کار می‌کند"
        OUTPUT = "OUTPUT", "خروجی"
        FEATURES = "FEATURES", "قابلیت‌های مرتبط"
        WORKFLOW = "WORKFLOW", "روند کار"
        OUR_WINS = "OUR_WINS", "کجا ما بهتریم"
        THEIR_WINS = "THEIR_WINS", "کجا رقیب بهتر است"
        PLANNED = "PLANNED", "هنوز ساخته نشده"

    page = models.ForeignKey(SeoPage, on_delete=models.CASCADE, related_name="bullets")
    group = models.CharField(max_length=12, choices=Group.choices)
    order = models.PositiveSmallIntegerField(default=1)
    text = models.CharField(max_length=300)

    class Meta:
        ordering = ["group", "order", "id"]
        verbose_name = "خط فهرست"
        verbose_name_plural = "خط‌های فهرست"

    def __str__(self):
        return self.text


class SeoStep(TimeStampedModel):
    """A titled paragraph: a step, an answer, a "how"."""

    page = models.ForeignKey(SeoPage, on_delete=models.CASCADE, related_name="steps")
    order = models.PositiveSmallIntegerField(default=1)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    #: §34 forbids claiming what is not built. A step that depends on something
    #: unfinished is labelled rather than quietly listed.
    soon = models.BooleanField(default=False, verbose_name="هنوز ساخته نشده")

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "گام"
        verbose_name_plural = "گام‌ها"

    def __str__(self):
        return self.title


class SeoRow(TimeStampedModel):
    """One line of a comparison table."""

    page = models.ForeignKey(SeoPage, on_delete=models.CASCADE, related_name="rows")
    order = models.PositiveSmallIntegerField(default=1)
    aspect = models.CharField(max_length=120, verbose_name="از نظر")
    us = models.CharField(max_length=300, verbose_name="آپ‌مارکت")
    them = models.CharField(max_length=300, verbose_name="رقیب")

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "ردیف مقایسه"
        verbose_name_plural = "ردیف‌های مقایسه"

    def __str__(self):
        return self.aspect


# ---------------------------------------------------------------------------
#  Proof: case studies, customers, testimonials — and the resource library.
#
#  These four pages are in `سایت عمومی.md` (§11, §12, §13, §19) and were never
#  built, for a reason that was right and an inference from it that was wrong.
#
#  The reason: §34 forbids showing invented work as a real customer's. That
#  still stands, and nothing here softens it.
#
#  The wrong inference: that the *page* therefore could not exist. It could —
#  what could not exist was fake content on it. The difference only became
#  workable once there was an admin to put real content in, which is now.
#
#  So each of these renders exactly what somebody entered, and **404s while it
#  is empty**, staying out of the sitemap and out of the footer. §18's rule
#  about thin pages is the same rule: a page that answers 200 with nothing on
#  it gets indexed once and then embarrasses you for a year.
# ---------------------------------------------------------------------------


class CustomerLogo(TimeStampedModel):
    """A business that uses the product (§12).

    `consented` is not decoration. A logo on a marketing page is a public claim
    about somebody else's business, and the honest default for "did they say we
    could?" is no.
    """

    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180, unique=True, allow_unicode=True, blank=True)
    description = models.CharField(max_length=300, blank=True)
    logo = models.ImageField(upload_to="customers/", null=True, blank=True)
    website = models.URLField(blank=True)
    industry = models.CharField(max_length=80, blank=True)
    consented = models.BooleanField(
        default=False,
        verbose_name="اجازه‌ی نمایش دارد",
        help_text="تا وقتی تیک نخورد، هیچ‌جای سایت نشان داده نمی‌شود.",
    )
    order = models.PositiveSmallIntegerField(default=100)

    class Meta:
        ordering = ["order", "name"]
        verbose_name = "مشتری"
        verbose_name_plural = "مشتری‌ها"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name, allow_unicode=True) or "customer"
        super().save(*args, **kwargs)


class CaseStudy(TimeStampedModel):
    """One customer's before and after (§11).

    The fields are the spec's own section order — customer, problem, before,
    solution, process, outputs, results, conclusion — because that order is
    what makes the page read as a story rather than a feature list with a name
    on it.
    """

    customer = models.ForeignKey(
        CustomerLogo, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="case_studies",
    )
    customer_name = models.CharField(
        max_length=160, blank=True,
        help_text="اگر مشتری در فهرست مشتری‌ها نیست، اسمش را اینجا بنویس.",
    )
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, allow_unicode=True, blank=True)
    lead = models.CharField(max_length=300, blank=True)
    cover = models.ImageField(upload_to="case-studies/", null=True, blank=True)

    problem = models.TextField(verbose_name="مسئله‌ی کسب‌وکار")
    before = models.TextField(blank=True, verbose_name="قبل")
    solution = models.TextField(blank=True, verbose_name="کاری که آپ‌مارکت کرد")
    process = models.TextField(blank=True, verbose_name="روند")
    outputs = models.TextField(blank=True, verbose_name="خروجی‌های تولیدشده")
    #: §34: «ادعاهای غیرقابل اثبات درباره افزایش فروش» — so results are the
    #: customer's own words or a measured number, and the help text says so.
    results = models.TextField(
        blank=True, verbose_name="نتیجه",
        help_text="فقط عددی که قابل اثبات است یا جمله‌ای که خودِ مشتری گفته.",
    )
    conclusion = models.TextField(blank=True, verbose_name="جمع‌بندی")

    published = models.BooleanField(default=False)
    order = models.PositiveSmallIntegerField(default=100)

    class Meta:
        ordering = ["order", "-created_at"]
        verbose_name = "مطالعه‌ی موردی"
        verbose_name_plural = "مطالعات موردی"

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title, allow_unicode=True)[:200] or "case"
            slug, n = base, 2
            while CaseStudy.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f"{base}-{n}", n + 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def who(self) -> str:
        return self.customer.name if self.customer else self.customer_name


class Testimonial(TimeStampedModel):
    """What a customer said (§13), in their words."""

    quote = models.TextField(verbose_name="نقل قول")
    name = models.CharField(max_length=120)
    business = models.CharField(max_length=160, blank=True)
    role = models.CharField(max_length=120, blank=True)
    photo = models.ImageField(upload_to="testimonials/", null=True, blank=True)
    #: One sentence, measurable. Optional, because most quotes do not carry one
    #: and inventing one is exactly what §34 forbids.
    outcome = models.CharField(max_length=200, blank=True, verbose_name="نتیجه")
    case_study = models.ForeignKey(
        CaseStudy, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="testimonials",
    )
    consented = models.BooleanField(
        default=False,
        verbose_name="اجازه‌ی نمایش دارد",
        help_text="نقل قول و عکس هر دو. تا تیک نخورد نمایش داده نمی‌شود.",
    )
    order = models.PositiveSmallIntegerField(default=100)

    class Meta:
        ordering = ["order", "-created_at"]
        verbose_name = "نظر مشتری"
        verbose_name_plural = "نظرات مشتریان"

    def __str__(self):
        return f"{self.name} — {self.quote[:40]}"


class Resource(TimeStampedModel):
    """A guide, template, checklist or e-book (§19).

    Lead generation, so the thing has to be genuinely usable — §34's rule about
    pages built only for Google applies here more than anywhere, because a
    worthless download costs trust as well as a click.
    """

    class Kind(models.TextChoices):
        GUIDE = "guides", "راهنما"
        TEMPLATE = "templates", "قالب"
        CHECKLIST = "checklists", "چک‌لیست"
        EBOOK = "ebooks", "کتاب"

    kind = models.CharField(max_length=12, choices=Kind.choices)
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, allow_unicode=True, blank=True)
    description = models.CharField(max_length=300)
    icon = models.CharField(max_length=8, blank=True, help_text="یک ایموجی")
    #: Either a file to download or a page to read. One of the two is required.
    file = models.FileField(upload_to="resources/", null=True, blank=True)
    body = models.TextField(blank=True, help_text="مارک‌داون — اگر فایلی نیست")
    published = models.BooleanField(default=False)
    order = models.PositiveSmallIntegerField(default=100)

    class Meta:
        ordering = ["kind", "order", "title"]
        verbose_name = "منبع"
        verbose_name_plural = "منابع"

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title, allow_unicode=True)[:200] or "resource"
            slug, n = base, 2
            while Resource.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f"{base}-{n}", n + 1
            self.slug = slug
        super().save(*args, **kwargs)
