import logging

from ai_engine.ai_generator import (
    AIUsage, call_model,
    get_coach_instructions, get_context_data, get_equipment_context,
)

logger = logging.getLogger(__name__)


_EDIT_FORMAT_RULES = """
## قالب خروجی — بدون استثنا رعایت شود

ساختار خروجی باید دقیقاً همان ساختار برنامه فعلی باشد، چون خروجی مستقیماً
به PDF ستونی تبدیل می‌شود:

* عنوان بخش‌ها دقیقاً `## برنامه ورزشی` و `## برنامه غذایی` باشد — بدون کلمه «اصلاح‌شده» یا هر پسوند دیگر.
* عنوان هر جلسه دقیقاً `### جلسه ۱` و عنوان هر روز غذایی دقیقاً `### روز ۱` باشد.
* حرکات هر جلسه خط‌های شماره‌دار `1.` باشند و شماره‌گذاری هر جلسه از ۱ شروع شود.
* بین نام حرکت و ست/تکرار از `—` و برای سوپرست از `×` استفاده شود.
* جداکننده گروه عضلانی فقط یک سطر `---` بدون هیچ متنی باشد.
* برچسب مجاز فقط `(وزن بدن)` و `(تا حد اکثر توان)` است؛ هیچ توضیح، تکنیک، عضله هدف یا نکته آموزشی کنار حرکات نوشته نشود.
* تعداد جلسات و تعداد روزهای غذایی نسبت به برنامه فعلی تغییر نکند، مگر بازخورد صریحاً همین را خواسته باشد.
* هیچ اطلاعات هویتی ورزشکار (نام، سن، قد، وزن، BMI، جنسیت) در خروجی نیاید.
"""


def edit_program_with_feedback(client_obj, feedback):
    """ویرایش برنامه بر اساس بازخورد کاربر با حفظ ساختار حرفه‌ای.

    فقط بخش‌های موجود برنامه ویرایش می‌شوند — برای برنامه تک‌بخشی
    (فقط ورزشی یا فقط غذایی) بخش ناموجود تولید نمی‌شود.

    خروجی: (workout, meal_plan, usage)
    """
    has_workout = bool(client_obj.generated_workout)
    has_meal = bool(client_obj.generated_meal_plan)

    if not has_workout and not has_meal:
        raise ValueError('برنامه‌ای برای ویرایش وجود ندارد.')

    # فقط بخش‌های موجود در پرامپت قرار می‌گیرند
    current_sections = ""
    if has_workout:
        current_sections += f"""
## برنامه ورزشی فعلی
{client_obj.generated_workout}
"""
    if has_meal:
        current_sections += f"""
## برنامه غذایی فعلی
{client_obj.generated_meal_plan}
"""

    if has_workout and has_meal:
        output_rule = """خروجی دقیقاً دو بخش مجزا و به همین ترتیب داشته باشد:
   - `## برنامه ورزشی`
   - `## برنامه غذایی`"""
    elif has_workout:
        output_rule = """خروجی فقط یک بخش داشته باشد: `## برنامه ورزشی`
   به هیچ عنوان برنامه غذایی تولید نکن."""
    else:
        output_rule = """خروجی فقط یک بخش داشته باشد: `## برنامه غذایی`
   به هیچ عنوان برنامه ورزشی تولید نکن."""

    # زمینه واقعی ورزشکار هم لازم است: بازخورد نباید باعث شود حرکتی خارج از
    # تجهیزات موجود یا مغایر دستورالعمل مربی وارد برنامه شود.
    equipments_str, meals_str, equipment_names, meal_names = get_context_data(client_obj.user)

    context_blocks = ""
    if has_workout:
        context_blocks += f"""
## تجهیزات موجود باشگاه
{get_equipment_context(client_obj, equipments_str)}

## نام تجهیزات مجاز
{", ".join(equipment_names) if equipment_names else "بدون دستگاه"}
"""
    if has_meal:
        context_blocks += f"""
## غذاهای پیشنهادی برای ایده و الهام
{meals_str or "غذایی ثبت نشده است. از مواد غذایی رایج و در دسترس در ایران استفاده کن."}
"""

    prompt = f"""تو یک Head Coach حرفه‌ای هستی. باید برنامه فعلی را دقیقاً با بازخورد زیر اصلاح کنی.

## شرایط ورزشکار (برای رعایت ایمنی هنگام اصلاح)
* آسیب‌ها: {client_obj.injuries or 'ندارد'}
* آلرژی‌ها: {client_obj.food_allergies or 'ندارد'}
* مشکلات بدنی: {client_obj.body_issues or 'ندارد'}
* بیماری‌های مزمن: {client_obj.chronic_diseases or 'ندارد'}

## دستورالعمل ثابت مربی — اولویت بالا
{get_coach_instructions(client_obj)}
{context_blocks}{current_sections}
## بازخورد ورزشکار
{feedback}

## قوانین اصلاح

1) پاسخ فقط فارسی و کاملاً اجرایی باشد.
2) {output_rule}
3) فقط بخش‌هایی را که بازخورد نیاز به تغییر داده است اصلاح کن و بقیه را بدون تغییر غیرضروری حفظ کن.
4) ایمنی و محدودیت‌های پزشکی ورزشکار بر خواسته بازخورد اولویت دارد؛ اگر بازخورد چیزی ناایمن خواسته، نزدیک‌ترین گزینه ایمن را جایگزین کن.
5) فقط از تجهیزات موجود استفاده کن و هرگز وجود تجهیزات را حدس نزن.
6) هیچ مقدمه، توضیح درباره تغییرات، جمع‌بندی یا جمله انگیزشی ننویس. فقط خود برنامه اصلاح‌شده.
{_EDIT_FORMAT_RULES}"""

    logger.info(f"Editing program #{client_obj.id}")

    # همان زنجیره‌ی اولویت تولید برنامه: اگر ارائه‌دهنده‌ی اول در دسترس
    # نباشد، ویرایش هم نباید شکست بخورد.
    response, provider_config = call_model(
        messages=[
            {
                "role": "system",
                "content": (
                    "تو مربی ارشد هستی. اصلاحات باید دقیق، ایمن و قابل‌اجرا باشد و "
                    "ساختار ستونی برنامه دست‌نخورده بماند."
                ),
            },
            {"role": "user", "content": prompt}
        ],
        max_tokens=5000 if (has_workout and has_meal) else 3000,
        temperature=0.25,
    )

    usage = AIUsage.from_response(
        response, provider_config['model_name'], provider_config
    )

    revised_text = (response.choices[0].message.content or "").strip()
    if not revised_text:
        logger.warning(
            f"Empty AI response while editing program #{client_obj.id}; keeping previous version"
        )
        return client_obj.generated_workout, client_obj.generated_meal_plan, usage

    # برنامه تک‌بخشی: کل خروجی همان بخش موجود است، بخش دیگر دست‌نخورده می‌ماند
    if has_workout and not has_meal:
        return revised_text, client_obj.generated_meal_plan, usage
    if has_meal and not has_workout:
        return client_obj.generated_workout, revised_text, usage

    # مدل ممکن است هنوز عنوان قدیمی «اصلاح‌شده» را بنویسد؛ هر دو حالت پذیرفته شود
    split_markers = [
        "## برنامه غذایی اصلاح‌شده",
        "### برنامه غذایی اصلاح‌شده",
        "## برنامه غذایی",
        "### برنامه غذایی",
        "برنامه غذایی اصلاح‌شده:",
        "برنامه غذایی:"
    ]

    workout = revised_text
    meal = client_obj.generated_meal_plan

    for marker in split_markers:
        if marker in revised_text:
            parts = revised_text.split(marker, 1)
            workout = parts[0].strip()
            meal = marker + parts[1].strip()
            break

    return _normalize_headings(workout), _normalize_headings(meal), usage


def _normalize_headings(text):
    """عنوان‌های «اصلاح‌شده» را به عنوان استاندارد برمی‌گرداند.

    ساخت PDF روی عنوان‌های دقیق تکیه می‌کند؛ بدون این یکسان‌سازی، برنامه
    ویرایش‌شده در PDF ستون‌بندی نمی‌شود.
    """
    if not text:
        return text
    return (
        text.replace('## برنامه ورزشی اصلاح‌شده', '## برنامه ورزشی')
            .replace('### برنامه ورزشی اصلاح‌شده', '## برنامه ورزشی')
            .replace('## برنامه غذایی اصلاح‌شده', '## برنامه غذایی')
            .replace('### برنامه غذایی اصلاح‌شده', '## برنامه غذایی')
    )
