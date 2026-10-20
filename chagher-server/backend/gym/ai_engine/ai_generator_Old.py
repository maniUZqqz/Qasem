# ai_engine/ai_generator.py
# تولید برنامه بر اساس نوع درخواستی (workout / meal / both) — فقط بخش خواسته‌شده
# تولید می‌شود تا توکن پلتفرم و هزینه API هوش مصنوعی هدر نرود.

import logging

from openai import OpenAI
from django.db.models import Q
from app.models import ClientProgram, Equipment, Meal, APIConfig

logger = logging.getLogger(__name__)


# تعداد برنامه‌های قبلی که برای هوش مصنوعی ارسال می‌شوند
PREVIOUS_PROGRAMS_COUNT = 2


class AllProvidersFailed(RuntimeError):
    """هیچ‌کدام از ارائه‌دهنده‌های زنجیره پاسخ ندادند."""

    def __init__(self, attempts):
        self.attempts = attempts
        detail = ' | '.join(f'{name}: {err}' for name, err in attempts) or 'بدون ارائه‌دهنده'
        super().__init__(f'هیچ ارائه‌دهنده هوش مصنوعی پاسخ نداد ({detail})')


class AIUsage:
    """مصرف توکن یک فراخوانی مدل — برای حساب‌کتاب هزینه در پنل ادمین.

    قیمت همان ارائه‌دهنده‌ای که واقعاً پاسخ داده همراه مصرف نگه داشته می‌شود.
    بدون این، اگر زنجیره به ارائه‌دهنده‌ی دوم می‌رفت، هزینه با تعرفه‌ی
    ارائه‌دهنده‌ی اول حساب می‌شد و حساب‌کتاب غلط درمی‌آمد.
    """

    __slots__ = ('model_name', 'input_tokens', 'output_tokens', 'provider_config')

    def __init__(self, model_name='', input_tokens=0, output_tokens=0,
                 provider_config=None):
        self.model_name = model_name
        self.input_tokens = int(input_tokens or 0)
        self.output_tokens = int(output_tokens or 0)
        self.provider_config = provider_config

    @classmethod
    def from_response(cls, response, model_name, provider_config=None):
        usage = getattr(response, 'usage', None)
        return cls(
            model_name=model_name,
            input_tokens=getattr(usage, 'prompt_tokens', 0) or 0,
            output_tokens=getattr(usage, 'completion_tokens', 0) or 0,
            provider_config=provider_config,
        )

    def __repr__(self):
        provider = (self.provider_config or {}).get('name', '-')
        return (
            f"AIUsage(provider={provider!r}, model={self.model_name!r}, "
            f"in={self.input_tokens}, out={self.output_tokens})"
        )


def build_client(config):
    """کلاینت سازگار با OpenAI برای یک ارائه‌دهنده.

    اولاما و اکثر سرورهای محلی همین پروتکل را ارائه می‌دهند، پس مسیر ابری و
    محلی از یک کلاینت استفاده می‌کنند و تنها تفاوتشان آدرس و کلید است.
    """
    api_key = config.get('api_key') or ''
    if not api_key:
        raise ValueError(
            f"ارائه‌دهنده «{config.get('name')}» کلید API ندارد. "
            'برای سرویس ابری کلید را وارد کنید یا نوع آن را «مدل محلی» بگذارید.'
        )
    return OpenAI(
        base_url=config['base_url'],
        api_key=api_key,
        timeout=float(config.get('timeout_seconds') or 90),
        max_retries=0,  # تکرار را خودمان در سطح زنجیره مدیریت می‌کنیم
    )


# def call_model(messages, max_tokens, temperature=0.35):
#     """فراخوانی مدل روی زنجیره‌ی اولویت.

#     ارائه‌دهنده‌ها به ترتیب `priority` امتحان می‌شوند و اولین پاسخ موفق
#     برگردانده می‌شود. هدف این است که خرابی یک ارائه‌دهنده (سرور محلی خاموش،
#     اعتبار تمام‌شده، قطعی شبکه) به کاربر نرسد.

#     خروجی: (response, provider_config)
#     """
#     providers = APIConfig.get_chain()
#     if not providers:
#         raise ValueError(
#             'هیچ ارائه‌دهنده فعالی برای هوش مصنوعی تنظیم نشده است. '
#             'در پنل ادمین حداقل یک مورد را فعال کنید.'
#         )

#     attempts = []
#     for provider in providers:
#         config = provider.as_config()
#         label = f"#{provider.priority} {provider.name}"
#         try:
#             client = build_client(config)
#             # ارائه‌دهنده محلی ممکن است نام مدل نداشته باشد؛ در آن صورت
#             # فهرست مدل‌های خود سرور خوانده می‌شود (با کش).
#             model = provider.resolve_model(client)
#             config['model_name'] = model
#             response = client.chat.completions.create(
#                 model=model,
#                 messages=messages,
#                 temperature=temperature,
#                 max_tokens=max_tokens,
#             )
#         except Exception as exc:
#             # هر خطایی (قطعی شبکه، مهلت، ۵xx، کلید نامعتبر، مدل ناموجود)
#             # یعنی این ارائه‌دهنده الان قابل اتکا نیست؛ سراغ بعدی می‌رویم.
#             provider.mark_failure(exc)
#             attempts.append((label, f'{type(exc).__name__}: {exc}'))
#             logger.warning(
#                 'AI provider failed, moving to next: %s — %s', label, exc
#             )
#             continue

#         choices = getattr(response, 'choices', None) or []
#         content = choices[0].message.content if choices else None
#         if not (content or '').strip():
#             # پاسخ رسیده اما خالی است؛ از دید کاربر با قطعی فرقی ندارد،
#             # پس مثل خطا رفتار می‌کنیم و سراغ ارائه‌دهنده بعدی می‌رویم.
#             provider.mark_failure('خروجی خالی')
#             attempts.append((label, 'خروجی خالی'))
#             logger.warning('AI provider returned empty output: %s', label)
#             continue

#         provider.mark_success()
#         if attempts:
#             logger.info(
#                 'AI provider %s served after %d failed attempt(s)',
#                 label, len(attempts),
#             )
#         return response, config

#     raise AllProvidersFailed(attempts)


def call_model(messages, max_tokens, temperature=0.35):
    """فراخوانی مدل روی زنجیره‌ی اولویت.

    ابتدا درخواست با max_tokens ارسال می‌شود.
    اگر مدل اعلام کند که max_tokens را پشتیبانی نمی‌کند،
    همان درخواست با max_completion_tokens دوباره ارسال می‌شود.

    خروجی: (response, provider_config)
    """
    providers = APIConfig.get_chain()
    if not providers:
        raise ValueError(
            'هیچ ارائه‌دهنده فعالی برای هوش مصنوعی تنظیم نشده است. '
            'در پنل ادمین حداقل یک مورد را فعال کنید.'
        )

    attempts = []

    for provider in providers:
        config = provider.as_config()
        label = f"#{provider.priority} {provider.name}"

        try:
            client = build_client(config)

            # ارائه‌دهنده محلی ممکن است نام مدل نداشته باشد؛
            # در آن صورت فهرست مدل‌های خود سرور خوانده می‌شود.
            model = provider.resolve_model(client)
            config['model_name'] = model

            request_params = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
            }

            # ابتدا با پارامتر استاندارد قدیمی امتحان می‌کنیم.
            try:
                response = client.chat.completions.create(
                    **request_params,
                    max_tokens=max_tokens,
                )

            except Exception as exc:
                error_message = str(exc).lower()

                # بعضی مدل‌های جدید max_tokens را قبول نمی‌کنند
                # و به‌جای آن max_completion_tokens می‌خواهند.
                if (
                    "max_tokens" in error_message
                    and (
                        "max_completion_tokens" in error_message
                        or "unsupported parameter" in error_message
                    )
                ):
                    logger.info(
                        "Provider %s / model %s does not support "
                        "max_tokens; retrying with max_completion_tokens",
                        label,
                        model,
                    )

                    response = client.chat.completions.create(
                        **request_params,
                        max_completion_tokens=max_tokens,
                    )
                else:
                    raise

        except Exception as exc:
            # هر خطای واقعی Provider باعث می‌شود سراغ Provider بعدی برویم.
            provider.mark_failure(exc)
            attempts.append(
                (label, f'{type(exc).__name__}: {exc}')
            )
            logger.warning(
                'AI provider failed, moving to next: %s — %s',
                label,
                exc,
            )
            continue

        choices = getattr(response, 'choices', None) or []
        content = choices[0].message.content if choices else None

        if not (content or '').strip():
            provider.mark_failure('خروجی خالی')
            attempts.append((label, 'خروجی خالی'))
            logger.warning(
                'AI provider returned empty output: %s',
                label,
            )
            continue

        provider.mark_success()

        if attempts:
            logger.info(
                'AI provider %s served after %d failed attempt(s)',
                label,
                len(attempts),
            )

        return response, config

    raise AllProvidersFailed(attempts)




def get_openai_client():
    """کلاینت اولین ارائه‌دهنده‌ی زنجیره (برای مصارف تک‌کاره)."""
    return build_client(APIConfig.get_active_config())


def get_model_name():
    """نام مدل اولین ارائه‌دهنده‌ی زنجیره."""
    return APIConfig.get_active_config()['model_name']


# توضیح تجهیزات برای محیط‌های تمرین از پیش تعریف‌شده (کاربر شخصی — B2C)
TRAINING_PLACE_EQUIPMENT = {
    'public_gym': (
        "کاربر به یک باشگاه عمومی دسترسی دارد. تجهیزات استاندارد و رایج در نظر بگیر: "
        "هالتر و دمبل، دستگاه پرس سینه، لت پول‌داون، قفسه اسکات، پرس پا، سیم‌کش، "
        "تردمیل و دوچرخه ثابت. از دستگاه‌های نادر یا تخصصی استفاده نکن."
    ),
    'home_basic': (
        "کاربر در خانه تمرین می‌کند و فقط تجهیزات ساده دارد: چند دمبل، کش ورزشی و مت. "
        "برنامه را با همین‌ها طراحی کن و برای هر حرکت جایگزین وزن بدن هم بده."
    ),
    'home_none': (
        "کاربر در خانه و بدون هیچ تجهیزاتی تمرین می‌کند. کل برنامه باید با وزن بدن اجرا شود "
        "و از وسایل معمول خانه (صندلی، دیوار، حوله) استفاده کند."
    ),
}


def get_equipment_context(client_obj, equipments_str):
    """متن تجهیزات را بر اساس محیط تمرین برنامه برمی‌گرداند.

    باشگاه (gym_equipment): همان رفتار قبلی — تجهیزات ثبت‌شده.
    کاربر شخصی: توضیح محیط از پیش تعریف‌شده.
    """
    place = getattr(client_obj, 'training_place', 'gym_equipment')
    if place in TRAINING_PLACE_EQUIPMENT:
        return TRAINING_PLACE_EQUIPMENT[place]
    return equipments_str or "هیچ تجهیزی ثبت نشده است. برنامه را با تمرینات وزن بدن طراحی کن."


def get_coach_instructions(client_obj):
    """دستورالعمل ثابت مربی (در صورت وجود) برای رعایت در تولید برنامه.

    برای برنامه‌ای که مربی می‌سازد از برند خودش خوانده می‌شود و برای ورزشکار
    باشگاه از برند مربی‌اش. کاربر شخصی (B2C) دستورالعمل مربی ندارد.
    """
    from app.models import GymBrand

    user = client_obj.user
    owner = user
    profile = user.client_profile.first()
    if profile:
        owner = profile.gym_owner

    brand = GymBrand.objects.filter(user=owner).first()
    text = (brand.program_instructions or '').strip() if brand else ''
    return text or 'ندارد'


def get_context_data(user):
    """دریافت دستگاه‌ها و غذاهای اختصاصی کاربر/باشگاه."""
    profile = user.client_profile.first()
    source_user = profile.gym_owner if profile else user

    equipments = Equipment.objects.filter(user=source_user)
    meals = Meal.objects.filter(user=source_user)

    eq_str = "\n".join([
        f"- {e.name} | گروه عضلانی: {e.muscle_group} | دسته‌بندی: {e.category.name if e.category else 'نامشخص'} | توضیحات: {e.description or 'ندارد'}"
        for e in equipments
    ])

    meal_str = "\n".join([
        f"- {m.name} | کالری: {m.calories} | پروتئین: {m.protein}g | کربوهیدرات: {m.carbs}g | چربی: {m.fat}g | آلرژن: {m.allergens or 'ندارد'}"
        for m in meals
    ])

    equipment_names = [e.name for e in equipments]
    meal_names = [m.name for m in meals]

    return eq_str, meal_str, equipment_names, meal_names


def get_previous_programs(client_obj, program_type='both'):
    """
    دریافت آخرین برنامه‌های قبلی همین مشتری.
    فقط بخش‌های مرتبط با نوع برنامه درخواستی در پرامپت قرار می‌گیرند.
    """
    qs = (
        ClientProgram.objects
        .filter(
            user=client_obj.user,
            name=client_obj.name
        )
        .exclude(id=client_obj.id)
    )

    has_workout = ~Q(generated_workout__isnull=True) & ~Q(generated_workout="")
    has_meal = ~Q(generated_meal_plan__isnull=True) & ~Q(generated_meal_plan="")

    if program_type == 'workout':
        qs = qs.filter(has_workout)
    elif program_type == 'meal':
        qs = qs.filter(has_meal)
    else:
        qs = qs.filter(has_workout | has_meal)

    previous_programs = qs.order_by("-created_at")[:PREVIOUS_PROGRAMS_COUNT]

    if not previous_programs.exists():
        return "این مشتری تاکنون برنامه قبلی ندارد."

    result = []

    for i, program in enumerate(previous_programs, start=1):
        sections = []
        if program_type in ('both', 'workout') and program.generated_workout:
            sections.append(f"## برنامه ورزشی\n{program.generated_workout}")
        if program_type in ('both', 'meal') and program.generated_meal_plan:
            sections.append(f"## برنامه غذایی\n{program.generated_meal_plan}")

        result.append(f"### برنامه قبلی {i}\n\n" + "\n\n".join(sections))

    return "\n\n".join(result)


def _split_program_sections(full_text):
    """جدا کردن برنامه ورزشی و غذایی از متن خروجی مدل."""
    markers = [
        "## برنامه غذایی",
        "### برنامه غذایی",
        "# برنامه غذایی",
        "برنامه غذایی:",
        "## بخش دوم - برنامه غذایی",
        "## رژیم غذایی"
    ]
    for marker in markers:
        if marker in full_text:
            left, right = full_text.split(marker, 1)
            return left.strip(), f"{marker}{right.strip()}"
    return full_text.strip(), "برنامه غذایی به صورت جداگانه استخراج نشد."


# ---------------------------------------------------------------------------
# بلوک‌های پرامپت — بر اساس نوع برنامه ترکیب می‌شوند
#
# قالب خروجی عمداً سخت‌گیرانه است: ساخت PDF مستقیماً روی همین نشانه‌ها
# (### جلسه N و ### روز N و خط جداکننده ---) ستون‌بندی می‌کند. تغییر این
# نشانه‌ها یعنی شکستن ستون‌بندی PDF.
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "تو یک Head Coach حرفه‌ای در حوزه تمرین، تغذیه ورزشی و ایمنی ورزشی هستی. "
    "خروجی تو باید اجرایی، ایمن، دقیق، مختصر و کاملاً شخصی‌سازی‌شده باشد و "
    "فقط به زبان فارسی نوشته شود. هیچ مقدمه، نتیجه‌گیری، جمله انگیزشی یا "
    "توضیح آموزشی اضافه ننویس."
)

_DECISION_RULES = """
# قوانین تصمیم‌گیری

قبل از تولید خروجی، تمام اطلاعات ورودی را تحلیل کن.

هر تصمیم درباره برنامه باید نتیجه تحلیل شرایط همان ورزشکار باشد.

از ایجاد برنامه بر اساس قالب ثابت برای همه ورزشکاران خودداری کن.

به هیچ عنوان یک حرکت، تعداد ست، تعداد تکرار، شدت، ماده غذایی، وعده غذایی، مکمل یا ساختار را صرفاً به دلیل رایج بودن آن انتخاب نکن.

اگر اطلاعات ورزشکار باعث شود انتخاب معمول مناسب نباشد، شرایط اختصاصی ورزشکار را اولویت بده.

ترتیب اولویت تصمیم‌گیری:

1. ایمنی و محدودیت‌های جسمی و پزشکی
2. اطلاعات اختصاصی ورزشکار
3. دستورالعمل ثابت مربی
4. هدف ورزشکار
5. سابقه و سطح تمرینی
6. تجهیزات و امکانات واقعی
7. اصول علمی تمرین و تغذیه
8. تنوع و قابلیت اجرای برنامه

هیچ اطلاعاتی را که در ورودی وجود ندارد، بدون ضرورت فرض نکن.

---

# اصلاح برنامه موجود

اگر برنامه‌های قبلی وجود دارند، ابتدا آن‌ها را تحلیل کن.

برنامه جدید باید از نظر منطقی ادامه مناسبی برای روند قبلی باشد، اما نباید صرفاً نسخه تکرارشده برنامه قبلی باشد.

اصل Progressive Overload را متناسب با سطح ورزشکار، سابقه تمرینی و برنامه‌های قبلی در نظر بگیر.

از تکرار غیرضروری حرکات و ساختارهای قبلی جلوگیری کن.

نقاط ضعف برنامه قبلی را اصلاح کن.

اگر بخشی از برنامه قبلی با شرایط فعلی ورزشکار ناسازگار یا ناایمن است، ایمنی و شرایط فعلی ورزشکار بر حفظ آن بخش اولویت دارد.
"""

_WORKOUT_RULES = """
# برنامه ورزشی

برنامه ورزشی باید بر اساس شرایط واقعی ورزشکار طراحی شود و از نظر حجم، شدت، تعداد حرکات، تعداد ست، تعداد تکرار، ترتیب حرکات و استراحت بین ست‌ها با همان ورزشکار تناسب داشته باشد.

هیچ مقدار ثابت یا الگوی ثابتی را برای همه ورزشکاران تکرار نکن.

## حجم هر جلسه

هر جلسه باید **حداقل ۹ حرکت** داشته باشد. این کف، غیرقابل مذاکره است و شامل حرکات گرم کردن و سرد کردن هم می‌شود؛ یعنی حتی سبک‌ترین جلسه هم باید دست‌کم ۹ خط حرکت داشته باشد.

جلسه‌ی معمول بین ۱۰ تا ۱۴ حرکت دارد. برای ورزشکار باتجربه‌تر یا جلسه‌ای که چند گروه عضلانی را پوشش می‌دهد، به سمت سقف برو.

اگر شرایط ورزشکار (آسیب، بیماری، سن بالا، مبتدی بودن) اجازه‌ی شدت بالا نمی‌دهد، **تعداد حرکات را کم نکن**؛ به‌جای آن شدت، تعداد ست، تعداد تکرار و نوع حرکت را سبک‌تر بگیر و از حرکات کششی، تحرک‌پذیری و هوازی سبک برای رسیدن به کف تعداد استفاده کن.

## استراحت بین ست‌ها

در ابتدای برنامه ورزشی، قبل از شروع جلسات، مدت استراحت مناسب بین ست‌ها را در یک خط کوتاه مشخص کن.

زمان استراحت باید با توجه به شدت، نوع حرکت، هدف تمرینی و سطح ورزشکار تعیین شود.

اگر نیاز است برای گروه‌های مختلف حرکتی یا شدت‌های مختلف زمان استراحت متفاوت باشد، آن تفاوت را در همان خط کوتاه مشخص کن.

## محتوای قابل نمایش برای هر حرکت

در بدنه برنامه ورزشی، اطلاعات هر حرکت را فقط به موارد ضروری زیر محدود کن:

* شماره حرکت
* نام حرکت
* تعداد تکرار
* تعداد ست

فقط در صورت نیاز می‌توان از دو برچسب زیر استفاده کرد:

* «وزن بدن»
* «تا حد اکثر توان»

هیچ برچسب دیگری استفاده نکن.

هیچ توضیحی درباره نحوه اجرای حرکت، عضله هدف، فواید حرکت، تکنیک، وضعیت بدن، نکات آموزشی یا توضیحات طولانی کنار حرکات نوشته نشود.

هدف کلی برنامه یا هدف هر جلسه نیز در برنامه ورزشی نمایش داده نشود.

---

# ترتیب حرکات و گروه‌بندی

ترتیب حرکات باید از نظر ساختار تمرین منطقی باشد.

حرکات نباید به صورت تصادفی پشت سر یکدیگر قرار بگیرند. در هر جلسه، حرکاتی که از نظر نوع تمرین، عضله یا الگوی حرکتی به یکدیگر مرتبط هستند، تا حد امکان در نزدیکی یکدیگر قرار بگیرند.

هنگام تغییر از یک گروه عضلانی به گروه عضلانی دیگر، یک خط جداکننده بگذار.

هنگام تغییر محسوس بین سبک‌های مختلف تمرینی نیز از همین جداکننده استفاده کن.

حرکات مشابه باید تا حد امکان در یک گروه متوالی قرار بگیرند و بین آن‌ها پراکندگی غیرضروری ایجاد نشود.

حرکات هوازی، مقاومتی و سایر دسته‌های متفاوت تمرینی نیز باید در صورت وجود، بر اساس نوع تمرین به شکل منظم و قابل تشخیص گروه‌بندی شوند.

جداکننده‌ها فقط برای ایجاد نظم بصری هستند و نباید شامل متن، عنوان، توضیح یا عنصر تزئینی باشند.

---

# گرم کردن و سرد کردن

گرم کردن باید در ابتدای هر جلسه قرار گیرد و سرد کردن در انتهای هر جلسه.

اما برای این بخش‌ها هیچ عنوان یا تیتر مستقلی مانند «گرم کردن»، «تمرین» یا «سرد کردن» ننویس؛ فقط به‌صورت حرکت‌های شماره‌دار در ابتدا و انتهای همان جلسه بیایند.

ترتیب آن‌ها باید از روی جایگاهشان در جلسه مشخص باشد.

---

# سوپرست

فقط زمانی از سوپرست استفاده کن که از نظر علمی و برنامه‌ریزی تمرینی برای همان ورزشکار مناسب باشد.

حرکات یک سوپرست باید با علامت «×» به یکدیگر متصل شوند و در یک شماره قرار بگیرند.

از هیچ عنوان یا برچسب اضافی برای مشخص کردن سوپرست استفاده نکن.

سوپرست را صرفاً برای ایجاد تنوع استفاده نکن.

---

# شماره‌گذاری جلسات

هر جلسه باید مستقل باشد و شماره‌گذاری حرکات در هر جلسه از ۱ شروع شود.

شماره‌گذاری یک جلسه نباید تحت تأثیر جلسه قبلی یا بعدی قرار بگیرد.

---

# محدودیت تجهیزات

فقط از تجهیزاتی استفاده کن که در فهرست تجهیزات و نام تجهیزات مجاز آمده‌اند.

وجود نام یک حرکت در دانش عمومی تو به معنی موجود بودن وسیله موردنیاز آن در این باشگاه نیست.

اگر یک حرکت به وسیله‌ای نیاز دارد که در تجهیزات موجود نیست، آن حرکت را انتخاب نکن.

اگر یک حرکت بدون تجهیزات انجام می‌شود، فقط در صورت نیاز از برچسب «وزن بدن» استفاده کن.

هرگز وجود تجهیزات را حدس نزن.

---

# آسیب‌ها و شرایط پزشکی

آسیب‌ها، مشکلات بدنی و بیماری‌های ذکرشده را پیش از انتخاب حرکات بررسی کن.

حرکاتی که با شرایط ورزشکار ناسازگار هستند حذف یا با گزینه مناسب‌تر جایگزین شوند.

برنامه نباید باعث افزایش غیرضروری ریسک تشدید آسیب یا مشکل موجود شود.

اگر شرایط پزشکی ورزشکار نیازمند ارزیابی تخصصی است، از تصمیم‌های پزشکی قطعی و خارج از اطلاعات موجود خودداری کن.

---

# ساختار محتوایی برنامه ورزشی

برنامه ورزشی باید فقط شامل جلسات، حرکات، تعداد تکرار، تعداد ست و اطلاعات ضروری تعریف‌شده در قوانین بالا باشد.

هیچ مقدمه آموزشی، توضیح درباره منطق برنامه، توضیح درباره عضلات، فواید حرکات، توصیه انگیزشی یا متن اضافه در این بخش قرار نده.
"""

_MEAL_RULES = """
# برنامه غذایی

برنامه غذایی باید کاملاً بر اساس شرایط همان ورزشکار طراحی شود.

سن، شرایط فیزیکی، سابقه تمرینی، سطح فعالیت، هدف، محدودیت‌های غذایی، آلرژی‌ها، بیماری‌ها و شرایط اقتصادی و اجتماعی قابل‌دسترسی در ایران باید در طراحی آن تأثیر مستقیم داشته باشند.

برنامه غذایی نباید یک قالب ثابت داشته باشد که برای تمام ورزشکاران تکرار شود.

نوع وعده‌ها، ترکیب مواد غذایی، میزان تقریبی مصرف و تنوع غذایی باید متناسب با همان ورزشکار تعیین شود.

---

# اصول دسترسی مواد غذایی

برنامه غذایی باید با شرایط جغرافیایی و اقتصادی ایران تا حد امکان سازگار باشد.

محور اصلی برنامه باید مواد غذایی رایج، محبوب، قابل تهیه و واقعاً در دسترس عموم در ایران باشد.

از مواد غذایی، ترکیبات یا محصولات غذایی غیرمعمول، کمیاب یا دشوار برای تهیه در ایران استفاده نکن؛ مگر اینکه خود ورزشکار وجود یا دسترسی به آن را مشخص کرده باشد.

برنامه لازم نیست سنتی یا کاملاً ایرانی باشد.

غذاهای مختلف می‌توانند استفاده شوند، اما انتخاب آن‌ها باید با سبک زندگی، دسترسی و شرایط واقعی ورزشکار سازگار باشد.

از ایجاد وابستگی برنامه به چند ماده غذایی تکراری خودداری کن.

---

# غذاهای ورودی

فهرست غذاهای پیشنهادی فقط منبع ایده و الهام است.

وجود یک غذا در این فهرست به معنی الزام به استفاده از آن نیست.

از این فهرست فقط زمانی استفاده کن که با شرایط، هدف، آلرژی‌ها، بیماری‌ها، نیازهای تغذیه‌ای و شرایط اقتصادی ورزشکار سازگار باشد.

در صورت مناسب نبودن یک گزینه، آزاد هستی که از گزینه مناسب‌تر و رایج دیگری استفاده کنی.

هرگز فهرست ورودی غذاها را به قالب ثابت برنامه تبدیل نکن.

---

# ساختار اطلاعات تغذیه‌ای روزانه

در ابتدای بخش برنامه غذایی، پیش از ارائه وعده‌های غذایی، یک خلاصه تغذیه‌ای روزانه متناسب با همان ورزشکار بنویس.

این خلاصه باید مقدار یا سطح مناسب انرژی و درشت‌مغذی‌های موردنیاز را بر اساس شرایط همان ورزشکار مشخص کند.

حداقل باید وضعیت انرژی روزانه و وضعیت مصرف پروتئین، کربوهیدرات و چربی مشخص شود.

برای درشت‌مغذی‌ها، علاوه بر مشخص کردن سطح مصرف، در صورت امکان و منطقی بودن محاسبات، مقدار تقریبی موردنیاز نیز تعیین شود.

مقادیر و سطوح نباید ثابت یا از پیش تعیین‌شده باشند. هر ورزشکار باید بر اساس شرایط خودش مقدار و سطح متفاوت و منطقی دریافت کند.

این خلاصه باید کوتاه و خوانا باشد و فقط اطلاعاتی را نشان دهد که برای همان ورزشکار کاربرد دارند.

---

# وعده‌های غذایی

ساختار پایه برنامه شامل وعده‌های اصلی و میان‌وعده‌ها باشد.

## وعده‌ی قبل از تمرین و بعد از تمرین

در **هر روز** برنامه غذایی، علاوه بر وعده‌های اصلی، حتماً یک وعده‌ی «قبل از تمرین» و یک وعده‌ی «بعد از تمرین» بنویس. این دو وعده اختیاری نیستند و هیچ روزی نباید بدون آن‌ها باشد.

وعده‌ی قبل از تمرین باید متناسب با زمان باقی‌مانده تا تمرین، شدت جلسه و گوارش‌پذیری انتخاب شود؛ فاصله‌ی تقریبی تا تمرین را هم در همان خط بنویس.

وعده‌ی بعد از تمرین باید بازسازی و ریکاوری را پوشش دهد و با حجم و شدت همان جلسه تناسب داشته باشد.

محتوای این دو وعده نباید در همه روزها یکسان باشد و باید با شرایط، آلرژی‌ها و امکانات ورزشکار هم بخواند.

تعداد و زمان‌بندی بقیه‌ی وعده‌ها را بر اساس شرایط، سبک زندگی، میزان فعالیت و نیاز واقعی ورزشکار تنظیم کن.

سه وعده اصلی و میان‌وعده‌ها محور اصلی برنامه باشند، اما در صورت نیاز می‌توان ساختار را متناسب با همان ورزشکار تغییر داد.

وعده‌های روزهای مختلف نباید صرفاً نسخه تکراری یکدیگر باشند.

تنوع غذایی باید وجود داشته باشد، اما پیچیدگی برنامه نباید باعث کاهش قابلیت اجرای آن شود.

مواد غذایی را به شکلی پیشنهاد کن که ورزشکار بتواند آن‌ها را در زندگی روزمره تهیه و مصرف کند.

از طراحی برنامه‌ای که به اندازه‌گیری‌های بیش از حد دقیق، دستورهای پیچیده یا آماده‌سازی غیرعملی نیاز دارد خودداری کن.

---

# جایگزین‌های غذایی

در صورت نیاز برای مواد غذایی مهم یا وعده‌های اصلی، گزینه‌های جایگزین مناسب ارائه کن.

جایگزین‌ها باید از نظر کاربرد تغذیه‌ای و شرایط دسترسی منطقی باشند و با آلرژی‌ها، بیماری‌ها، هدف و شرایط اقتصادی ورزشکار سازگار باشند.

از ایجاد فهرست‌های طولانی و غیرضروری از جایگزین‌ها خودداری کن.

---

# مکمل‌ها و ویتامین‌ها

در پایان برنامه غذایی، نیاز احتمالی ورزشکار به ویتامین‌ها و مکمل‌ها را بر اساس شرایط اختصاصی او بررسی کن.

سن، هدف، سابقه تمرینی، رژیم غذایی، شرایط فیزیکی، بیماری‌ها، آلرژی‌ها و اطلاعات پزشکی موجود باید در این تصمیم تأثیر داشته باشند.

فقط مکمل‌هایی را پیشنهاد کن که برای همان ورزشکار دلیل منطقی داشته باشند.

برای هر مکمل یا ویتامین پیشنهادی، در صورت وجود اطلاعات کافی، نام ماده، دوز استاندارد و زمان یا نحوه مصرف را مشخص کن.

نام شرکت، تولیدکننده یا برند به هیچ عنوان ذکر نشود.

مکمل اختیاری را به عنوان مکمل ضروری معرفی نکن.

اگر نیاز به یک ویتامین یا مکمل تنها در صورت وجود کمبود یا شرایط خاص قابل تشخیص است، آن را قطعی تجویز نکن و نیاز به تأیید پزشک، آزمایش یا متخصص مربوطه را مشخص کن.

برای افراد زیر ۱۸ سال، از تجویز خودسرانه مکمل‌ها یا دوزهای بالای ویتامین‌ها خودداری کن و در صورت مطرح بودن نیاز، ارزیابی و تأیید پزشک یا متخصص تغذیه را در اولویت قرار بده.

در صورت وجود بیماری، مصرف دارو یا شرایط پزشکی خاص، ایمنی بر پیشنهاد مکمل اولویت دارد.

---

# اصول علمی تغذیه

از رژیم‌های افراطی، محدودیت شدید انرژی، حذف غیرضروری گروه‌های غذایی و توصیه‌های غیرعلمی خودداری کن.

برنامه باید با هدف ورزشکار هماهنگ باشد و در عین حال قابلیت اجرای طولانی‌مدت داشته باشد.

مقدار انرژی و درشت‌مغذی‌ها را بر اساس شرایط همان فرد تعیین کن.

از یک میزان کالری یا نسبت ثابت برای همه ورزشکاران استفاده نکن.

برنامه غذایی باید بین دقت علمی و قابلیت اجرای روزمره تعادل برقرار کند.
"""

# ---------------------------------------------------------------------------
# قالب خروجی — ستون‌بندی PDF مستقیماً روی همین نشانه‌ها ساخته می‌شود
# ---------------------------------------------------------------------------

_WORKOUT_FORMAT = """
## قالب دقیق برنامه ورزشی

خروجی برنامه ورزشی دقیقاً به این شکل باشد و از هیچ عنصر دیگری استفاده نکن:

```
## برنامه ورزشی

استراحت بین ست‌ها: <یک خط کوتاه>

### جلسه ۱
1. <نام حرکت> — <تعداد ست>×<تعداد تکرار>
2. <نام حرکت> — <تعداد ست>×<تعداد تکرار>
3. <نام حرکت> — <تعداد ست>×<تعداد تکرار>
---
4. <نام حرکت> — <تعداد ست>×<تعداد تکرار>
5. <نام حرکت> — <تعداد ست>×<تعداد تکرار>
6. <نام حرکت> — <تعداد ست>×<تعداد تکرار>
---
7. <نام حرکت> — <تعداد ست>×<تعداد تکرار>
8. <نام حرکت> — <تعداد ست>×<تعداد تکرار>
9. <نام حرکت> — <تعداد ست>×<تعداد تکرار>

### جلسه ۲
1. ...
```

قواعد الزامی این قالب:

* عنوان هر جلسه دقیقاً به شکل `### جلسه ۱` باشد (فقط کلمه «جلسه» و شماره، بدون نام عضله و بدون توضیح).
* دقیقاً {program_days} جلسه تولید کن، نه بیشتر و نه کمتر.
* هر حرکت یک خط شماره‌دار باشد که با `1.` شروع می‌شود و شماره‌گذاری هر جلسه از ۱ آغاز شود.
* بین نام حرکت و ست/تکرار از علامت `—` استفاده کن.
* جداکننده گروه عضلانی فقط یک خط با سه خط تیره `---` در سطر مستقل باشد؛ نه متن، نه عنوان.
* سوپرست: هر دو حرکت در یک خط شماره‌دار و با `×` به هم وصل شوند، مثل `3. جلو بازو دمبل × پشت بازو سیم‌کش — 3×12`.
* برچسب اختیاری در انتهای خط داخل پرانتز بیاید: `(وزن بدن)` یا `(تا حد اکثر توان)`.
* هر خط حرکت باید کوتاه باشد و در یک سطر جا شود؛ هیچ توضیح اضافه‌ای در آن نیاید.
* هر جلسه حداقل ۹ حرکت و حداکثر ۱۴ حرکت داشته باشد. کمتر از ۹ حرکت در هیچ شرایطی قابل قبول نیست.
"""

_MEAL_FORMAT = """
## قالب دقیق برنامه غذایی

خروجی برنامه غذایی دقیقاً به این شکل باشد:

```
## برنامه غذایی

انرژی روزانه: <مقدار/سطح>
پروتئین: <مقدار> | کربوهیدرات: <مقدار> | چربی: <مقدار>

### روز ۱
**صبحانه:** <مواد و مقادیر>
**میان‌وعده صبح:** ...
**قبل از تمرین:** <مواد و مقادیر> — <فاصله تقریبی تا تمرین>
**بعد از تمرین:** <مواد و مقادیر>
**ناهار:** ...
**میان‌وعده عصر:** ...
**شام:** ...
جایگزین: <در صورت نیاز، یک خط کوتاه>

### روز ۲
...

### مکمل‌ها
- <نام ماده> — <دوز> — <زمان مصرف>
```

قواعد الزامی این قالب:

* خلاصه تغذیه‌ای روزانه پیش از اولین `### روز` بیاید.
* عنوان هر روز دقیقاً به شکل `### روز ۱` باشد.
* دقیقاً {program_days} روز تولید کن، نه بیشتر و نه کمتر.
* نام هر وعده بولد و در ابتدای خط خودش باشد.
* هر روز باید دقیقاً دو خط با عنوان‌های `**قبل از تمرین:**` و `**بعد از تمرین:**` داشته باشد؛ هیچ روزی بدون این دو خط نباشد.
* بخش مکمل‌ها در انتها و با عنوان `### مکمل‌ها` بیاید؛ اگر مکملی لازم نیست، همین را در یک خط بنویس.
* هر خط کوتاه و خوانا باشد.
"""

_OUTPUT_SPEC = {
    'both': """خروجی دقیقاً دو بخش اصلی و به همین ترتیب داشته باشد:

1. `## برنامه ورزشی`
2. `## برنامه غذایی`

هیچ بخش اصلی دیگری ایجاد نکن.""",
    'workout': """خروجی فقط و فقط یک بخش اصلی داشته باشد: `## برنامه ورزشی`

به هیچ عنوان برنامه غذایی، رژیم یا وعده غذایی تولید نکن.""",
    'meal': """خروجی فقط و فقط یک بخش اصلی داشته باشد: `## برنامه غذایی`

به هیچ عنوان برنامه ورزشی یا تمرین تولید نکن.""",
}

_FINAL_REQUIREMENTS = """
# الزامات نهایی خروجی

{output_spec}

اطلاعات شخصی ورزشکار مانند نام، سن، قد، وزن، BMI، جنسیت و سایر مشخصات هویتی نباید در خروجی نمایش داده شوند. این اطلاعات فقط برای شخصی‌سازی برنامه استفاده می‌شوند.

از نمایش اطلاعاتی که کاربر برای مشاهده برنامه نیاز ندارد خودداری کن.

تمام خروجی فقط به زبان فارسی باشد.

لحن خروجی حرفه‌ای، دقیق، مختصر و اجرایی باشد.

از کلی‌گویی، توضیحات آموزشی طولانی، مقدمه، نتیجه‌گیری، جملات انگیزشی و تکرار قوانین خودداری کن.

اگر در بخشی از درخواست ابهام وجود داشت، بر اساس اطلاعات واقعی ورزشکار بهترین تصمیم حرفه‌ای و ایمن را بگیر و از ساختن اطلاعات غیرواقعی خودداری کن.
"""

_PROMPT_TEMPLATE = """تو یک Head Coach حرفه‌ای در حوزه تمرین، تغذیه ورزشی و ایمنی ورزشی هستی.

وظیفه تو طراحی یا اصلاح یک برنامه ورزشی و غذایی کاملاً شخصی‌سازی‌شده، علمی، استاندارد، قابل اجرا و متناسب با شرایط واقعی ورزشکار است.

تمام تصمیمات باید بر اساس اطلاعات اختصاصی همان ورزشکار اتخاذ شوند.
هیچ بخش از برنامه نباید صرفاً بر اساس الگوهای ثابت، برنامه‌های عمومی، نمونه‌های آموزشی یا فرضیات از پیش تعیین‌شده تولید شود.

مهم‌ترین اصل:
اطلاعات ورزشکار، هدف، سابقه تمرینی، شرایط فیزیکی، آسیب‌ها، بیماری‌ها، آلرژی‌ها، دستورالعمل مربی، تجهیزات موجود و طول برنامه باید مستقیماً در تصمیم‌گیری درباره محتوای نهایی برنامه تأثیر بگذارند.

---

# اطلاعات ورزشکار

* نام: {name}
* سن: {age}
* جنسیت: {gender}
* قد: {height}
* وزن: {weight}
* BMI: {bmi}
* هدف پیشنهادی: {goal_hint}
* آسیب‌ها: {injuries}
* آلرژی‌ها: {food_allergies}
* مشکلات بدنی: {body_issues}
* بیماری‌های مزمن: {chronic_diseases}
* توضیحات تکمیلی: {extra_notes}

## دستورالعمل ثابت مربی — اولویت بالا

{coach_instructions}

* طول برنامه: {program_days} روز
* سابقه ورزشی: {exercise_history}

## برنامه‌های قبلی

{previous_programs}
{context_blocks}
---
{decision_rules}
{domain_rules}
---
{format_rules}
---
{final_requirements}"""

_WORKOUT_CONTEXT_TEMPLATE = """
## تجهیزات موجود باشگاه

{equipments}

## نام تجهیزات مجاز

{equipment_names}
"""

_MEAL_CONTEXT_TEMPLATE = """
## غذاهای پیشنهادی برای ایده و الهام

{meals}

## نام غذاهای پیشنهادی

{meal_names}
"""


def _build_prompt(client_obj, program_type, previous_programs,
                  equipments_str, meals_str, equipment_names, meal_names):
    """پرامپت نهایی را بر اساس نوع برنامه و اطلاعات واقعی ورزشکار می‌سازد."""
    bmi = None
    goal_hint = "نامشخص"
    if client_obj.height and client_obj.weight:
        height_m = client_obj.height / 100
        bmi = client_obj.weight / (height_m ** 2)
        if bmi < 18.5:
            goal_hint = "افزایش وزن و حجم عضلانی"
        elif bmi > 25:
            goal_hint = "کاهش وزن و چربی‌سوزی"
        else:
            goal_hint = "حفظ وزن و بهبود ترکیب بدن"

    include_workout = program_type in ('both', 'workout')
    include_meal = program_type in ('both', 'meal')

    program_days = client_obj.program_days

    context_blocks = ""
    domain_rules = ""
    format_rules = ""

    if include_workout:
        context_blocks += _WORKOUT_CONTEXT_TEMPLATE.format(
            equipments=get_equipment_context(client_obj, equipments_str),
            equipment_names=", ".join(equipment_names) if equipment_names else "بدون دستگاه",
        )
        domain_rules += _WORKOUT_RULES
        format_rules += _WORKOUT_FORMAT.format(program_days=program_days)

    if include_meal:
        context_blocks += _MEAL_CONTEXT_TEMPLATE.format(
            meals=meals_str or "غذایی ثبت نشده است. از مواد غذایی رایج و در دسترس در ایران استفاده کن.",
            meal_names=", ".join(meal_names) if meal_names else "بدون غذای ثبت‌شده",
        )
        domain_rules += "\n---\n" + _MEAL_RULES if include_workout else _MEAL_RULES
        format_rules += "\n" + _MEAL_FORMAT.format(program_days=program_days)

    return _PROMPT_TEMPLATE.format(
        name=client_obj.name or "نامشخص",
        age=client_obj.age or "نامشخص",
        gender=dict(ClientProgram.GENDER_CHOICES).get(client_obj.gender, "نامشخص"),
        height=f"{client_obj.height} سانتی‌متر" if client_obj.height else "نامشخص",
        weight=f"{client_obj.weight} کیلوگرم" if client_obj.weight else "نامشخص",
        bmi=f"{bmi:.1f}" if bmi else "نامشخص",
        goal_hint=goal_hint,
        injuries=client_obj.injuries or "ندارد",
        food_allergies=client_obj.food_allergies or "ندارد",
        body_issues=client_obj.body_issues or "ندارد",
        chronic_diseases=client_obj.chronic_diseases or "ندارد",
        extra_notes=client_obj.extra_notes or "ندارد",
        coach_instructions=get_coach_instructions(client_obj),
        program_days=program_days,
        exercise_history=client_obj.exercise_history or "بدون سابقه ورزشی",
        previous_programs=previous_programs,
        context_blocks=context_blocks,
        decision_rules=_DECISION_RULES,
        domain_rules=domain_rules,
        format_rules=format_rules,
        final_requirements=_FINAL_REQUIREMENTS.format(
            output_spec=_OUTPUT_SPEC[program_type]
        ),
    )


def generate_program(client_id, program_type='both'):
    """تولید برنامه شخصی‌سازی شده.

    program_type:
        'both'    → برنامه ورزشی + غذایی
        'workout' → فقط برنامه ورزشی
        'meal'    → فقط برنامه غذایی

    خروجی: (workout, meal_plan, usage) — بخش تولیدنشده None است و usage
    مصرف توکن واقعی مدل را برای حساب‌کتاب هزینه برمی‌گرداند.
    """
    if program_type not in ('both', 'workout', 'meal'):
        raise ValueError(f'نوع برنامه نامعتبر است: {program_type}')

    client_obj = ClientProgram.objects.get(id=client_id)

    previous_programs = get_previous_programs(client_obj, program_type)
    equipments_str, meals_str, equipment_names, meal_names = get_context_data(client_obj.user)

    prompt = _build_prompt(
        client_obj, program_type, previous_programs,
        equipments_str, meals_str, equipment_names, meal_names,
    )

    logger.info(
        f"Generating program for ClientProgram #{client_id} (type={program_type})"
    )

    # سقف توکن خروجی: برنامه ستونی فشرده است، اما ۶ جلسه‌ی ۹ تا ۱۴ حرکتی
    # به‌علاوه ۷ روز غذایی با وعده‌های قبل و بعد از تمرین فضای بیشتری
    # می‌خواهد؛ با سقف قبلی خروجی وسط جلسه قطع می‌شد.
    max_tokens = 7500 if program_type == 'both' else 4500

    response, provider_config = call_model(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_tokens=max_tokens,
        temperature=0.35,
    )

    usage = AIUsage.from_response(
        response, provider_config['model_name'], provider_config
    )

    full_text = (response.choices[0].message.content or "").strip()

    logger.info(
        f"Program #{client_id} generated ({len(full_text)} chars, "
        f"type={program_type}, {usage})"
    )

    if program_type == 'workout':
        return full_text, None, usage
    if program_type == 'meal':
        return None, full_text, usage

    workout, meal_plan = _split_program_sections(full_text)
    return workout, meal_plan, usage
