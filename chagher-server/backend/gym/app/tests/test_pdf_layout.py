# -*- coding: utf-8 -*-
"""تست چیدمان PDF — قواعدی که در «توسعه.txt» به‌عنوان الزام چاپی آمده‌اند.

این قواعد ظاهری نیستند؛ خروجی چاپی است و نقض هرکدام یعنی برگه‌ای که به دست
ورزشکار می‌رسد اشتباه است. پس همگی اینجا قفل می‌شوند.
"""
import re

from django.test import TestCase
from django.utils import timezone

from reportlab.lib.units import mm

from pdf_generator.pdf_gen import (
    COACH_NOTE_FONT_PT, COLUMN_PAD_X_MM, COLUMN_PAD_Y_MM,
    HEADER_FONT_PT, HEADER_GAP_BELOW_MM, LOGO_FILE, LOGO_HEIGHT_MM,
    MEAL_BOXES_PER_PAGE, MEAL_MAX_PAGES, MEAL_PAD_X_MM, MEAL_PAD_Y_MM,
    NOTE_BOTTOM_GAP_MM, NOTE_FONT_PT, NOTE_LINE_GAP_MM, NOTE_TOP_GAP_MM,
    PAGE_MARGIN_TOP_MM, WORKOUT_COLS_PER_PAGE, WORKOUT_MAX_PAGES,
    _build_html, _chunk_columns, _column_pad_x_mm, _gym_logo_path,
    _protect_sets_reps, generate_pdf, group_meal_rows, parse_meal, parse_workout,
)


WORKOUT_MD = """## برنامه ورزشی

استراحت بین ست‌ها: ۶۰ تا ۹۰ ثانیه برای حرکات ترکیبی و ۴۵ ثانیه برای تک‌مفصلی.

### جلسه ۱
1. دوچرخه ثابت — 1×5 دقیقه
2. اسکات هالتر — 4×8
---
3. جلو بازو دمبل × پشت بازو سیم‌کش — 3×12

### جلسه ۲
1. تردمیل — 1×5 دقیقه
2. پرس سینه هالتر — 4×8
---
3. لت پول‌داون — 4×10
---
4. کشش سینه — 2×30 ثانیه

### جلسه ۳
1. طناب زدن — 1×3 دقیقه
2. ددلیفت — 4×6
---
3. پلانک — 3×45 ثانیه (وزن بدن)

### جلسه ۴
1. دوچرخه ثابت — 1×5 دقیقه
2. اسکات بلغاری — 3×10
---
3. ساق پا ایستاده — 4×15
"""

MEAL_MD = """## برنامه غذایی

انرژی روزانه: حدود ۲۶۰۰ کیلوکالری
پروتئین: ۱۴۰ گرم | کربوهیدرات: ۳۰۰ گرم | چربی: ۷۵ گرم

### روز ۱
**صبحانه:** نان سنگک، پنیر ۳۰ گرم، گردو ۳ عدد
**ناهار:** سینه مرغ گریل ۱۵۰ گرم، برنج ۱ پیمانه
**شام:** عدسی ۱ کاسه

### روز ۲
**صبحانه:** املت ۲ تخم‌مرغ، نان جو
**ناهار:** خورشت قیمه کم‌روغن، برنج
**شام:** ماهی تنوری ۱۵۰ گرم

### روز ۳
**صبحانه:** حلیم بدون روغن
**ناهار:** ماکارونی سبوس‌دار با گوشت
**شام:** سوپ جو با مرغ

### روز ۴
**صبحانه:** پنیر و گردو
**ناهار:** زرشک‌پلو با مرغ
**شام:** کوکو سبزی

### مکمل‌ها
- ویتامین D — ۱۰۰۰ واحد روزانه — پس از تایید آزمایش
- کراتین مونوهیدرات — ۳ گرم روزانه
"""


def count_pdf_pages(pdf_bytes):
    """شمارش صفحات PDF.

    «/Type /Pages» گره درخت صفحات است و نباید شمرده شود، وگرنه همیشه یک
    صفحه بیشتر گزارش می‌شود.
    """
    return len(re.findall(rb'/Type\s*/Page(?![s])', pdf_bytes))


class _FakeUser:
    gym_name = 'باشگاه نمونه'

    class _Rel:
        def first(self):
            return None

    client_profile = _Rel()


class _FakeProgram:
    """کمینه‌ی چیزی که generate_pdf لازم دارد — بدون رفت‌وبرگشت دیتابیس."""

    GENDER_CHOICES = [('M', 'مرد'), ('F', 'زن')]

    def __init__(self, workout='', meal='', days=4):
        self.name = 'علی رضایی'
        self.age = 28
        self.gender = 'M'
        self.height = 178
        self.weight = 76
        self.program_days = days
        self.tokens_consumed = 50
        self.generated_workout = workout
        self.generated_meal_plan = meal
        self.created_at = timezone.now()
        self.user = _FakeUser()


class WorkoutParsingTests(TestCase):
    def test_sessions_and_rest_line_are_parsed(self):
        intro, sessions = parse_workout(WORKOUT_MD)
        self.assertEqual(len(sessions), 4)
        self.assertTrue(intro)
        self.assertIn('استراحت', intro[0])

    def test_thin_rule_splits_muscle_groups(self):
        """`---` باید گروه حرکتی جدید بسازد، نه یک خط متنی."""
        _, sessions = parse_workout(WORKOUT_MD)
        self.assertEqual([len(s['blocks']) for s in sessions], [2, 3, 2, 2])

    def test_session_numbers_follow_the_program(self):
        _, sessions = parse_workout(WORKOUT_MD)
        self.assertEqual([s['number'] for s in sessions], [1, 2, 3, 4])

    def test_section_heading_is_not_treated_as_content(self):
        intro, _ = parse_workout(WORKOUT_MD)
        self.assertFalse(any('برنامه ورزشی' in line for line in intro))


class MealParsingTests(TestCase):
    def test_days_summary_and_supplements(self):
        summary, days, supplements = parse_meal(MEAL_MD)
        self.assertEqual(len(days), 4)
        self.assertEqual(len(supplements), 2)
        self.assertTrue(any('انرژی روزانه' in line for line in summary))

    def test_supplements_are_not_mixed_into_last_day(self):
        _, days, _ = parse_meal(MEAL_MD)
        self.assertFalse(any('ویتامین D' in line for line in days[-1]['lines']))


class ColumnChunkingTests(TestCase):
    """سقف صفحه نباید نقض شود و هیچ جلسه/روزی نباید گم شود."""

    def test_workout_never_exceeds_two_pages(self):
        for count in range(1, 8):
            groups = _chunk_columns(
                list(range(count)), WORKOUT_COLS_PER_PAGE, WORKOUT_MAX_PAGES
            )
            self.assertLessEqual(len(groups), WORKOUT_MAX_PAGES, f'{count} جلسه')
            self.assertEqual(sum(len(g) for g in groups), count, f'{count} جلسه')

    def test_meal_never_exceeds_its_page_budget(self):
        for count in range(1, 8):
            groups = _chunk_columns(
                list(range(count)), MEAL_BOXES_PER_PAGE, MEAL_MAX_PAGES
            )
            self.assertLessEqual(len(groups), MEAL_MAX_PAGES, f'{count} روز')
            self.assertEqual(sum(len(g) for g in groups), count, f'{count} روز')

    def test_normal_case_uses_three_columns_and_two_meal_boxes(self):
        self.assertEqual(
            [len(g) for g in _chunk_columns(list(range(6)), WORKOUT_COLS_PER_PAGE, WORKOUT_MAX_PAGES)],
            [3, 3],
        )
        self.assertEqual(
            [len(g) for g in _chunk_columns(list(range(6)), MEAL_BOXES_PER_PAGE, MEAL_MAX_PAGES)],
            [2, 2, 2],
        )


class PdfRenderingTests(TestCase):
    def test_workout_pdf_fits_two_pages(self):
        content, _ = generate_pdf(_FakeProgram(WORKOUT_MD, MEAL_MD), section='workout')
        self.assertTrue(content.startswith(b'%PDF'))
        self.assertLessEqual(count_pdf_pages(content), WORKOUT_MAX_PAGES)

    def test_meal_pdf_fits_three_pages(self):
        content, _ = generate_pdf(_FakeProgram(WORKOUT_MD, MEAL_MD), section='meal')
        self.assertTrue(content.startswith(b'%PDF'))
        self.assertLessEqual(count_pdf_pages(content), MEAL_MAX_PAGES)

    def test_workout_and_meal_never_share_a_page(self):
        """اگر بخشی صفحه مشترک داشت، مجموع صفحات «both» کمتر از جمع دو بخش می‌شد."""
        program = _FakeProgram(WORKOUT_MD, MEAL_MD)
        both, _ = generate_pdf(program, section='both')
        workout, _ = generate_pdf(program, section='workout')
        meal, _ = generate_pdf(program, section='meal')

        self.assertEqual(
            count_pdf_pages(both),
            count_pdf_pages(workout) + count_pdf_pages(meal),
        )

    def test_legacy_format_still_renders(self):
        """برنامه‌های قدیمی (بدون قالب ستونی) نباید خطا بدهند."""
        legacy = _FakeProgram(
            '## برنامه ورزشی\n\n**روز اول**\n- اسکات ۳ ست ۱۰ تکرار\n',
            '## برنامه غذایی\n\nصبحانه: نان و پنیر\nناهار: مرغ و برنج\n',
        )
        content, _ = generate_pdf(legacy, section='both')
        self.assertTrue(content.startswith(b'%PDF'))

    def test_empty_program_still_renders(self):
        content, _ = generate_pdf(_FakeProgram('', ''), section='both')
        self.assertTrue(content.startswith(b'%PDF'))

    def test_personal_info_table_is_gone(self):
        """جدول اطلاعات فردی باید کاملاً حذف شده باشد."""
        from pdf_generator.pdf_gen import _build_html

        html = _build_html(_FakeProgram(WORKOUT_MD, MEAL_MD), section='both')
        for label in ('قد / وزن', 'جنسیت', 'توکن مصرف‌شده', 'BMI'):
            self.assertNotIn(label, html, f'«{label}» نباید در PDF بیاید')

    def test_header_and_footer_present(self):
        from pdf_generator.pdf_gen import (
            COACH_NOTE_TEXT, DISCLAIMER_TEXT, _build_html,
        )

        html = _build_html(_FakeProgram(WORKOUT_MD, MEAL_MD), section='both')
        self.assertIn(DISCLAIMER_TEXT, html)
        self.assertIn(COACH_NOTE_TEXT, html)
        self.assertIn('علی رضایی', html)       # نام ورزشکار
        self.assertIn('۴ روز', html)            # تعداد روز — با ارقام فارسی

    def test_generated_numbers_use_persian_digits(self):
        """ارقامی که خودمان می‌سازیم باید با بدنه فارسی هم‌خوان باشند."""
        from pdf_generator.pdf_gen import _build_html

        html = _build_html(_FakeProgram(WORKOUT_MD, MEAL_MD), section='both')
        self.assertIn('جلسه ۱', html)
        self.assertIn('روز ۱', html)
        self.assertNotIn('جلسه 1', html)
        self.assertNotIn('روز 1', html)


class BidiProtectionTests(TestCase):
    """«ست × تکرار» نباید در متن راست‌به‌چپ وارونه چاپ شود."""

    LRE = chr(0x202A)
    POP = chr(0x202C)

    def test_sets_reps_are_wrapped(self):
        out = _protect_sets_reps('اسکات — 4×8')
        self.assertIn(self.LRE, out)
        self.assertIn(self.POP, out)

    def test_persian_digits_are_handled(self):
        self.assertIn(self.LRE, _protect_sets_reps('پرس سینه — ۳×۱۲'))

    def test_superset_separator_is_not_wrapped(self):
        """`×` بین نام دو حرکت عدد نیست و نباید جاسازی شود."""
        out = _protect_sets_reps('جلو بازو × پشت بازو')
        self.assertNotIn(self.LRE, out)

    def test_is_idempotent(self):
        once = _protect_sets_reps('4×8')
        self.assertEqual(_protect_sets_reps(once), once)

    def test_a_rep_range_stays_in_one_piece(self):
        """«۳×۸-۱۰» باید کامل جاسازی شود، نه فقط «۳×۸».

        اگر «-۱۰» بیرون بماند، الگوریتم دوسویه آن را جدا جابه‌جا می‌کند و
        ورزشکار عدد اشتباه می‌خواند.
        """
        out = _protect_sets_reps('زیربغل دستگاه H — ۳×۸-۱۰')
        self.assertIn(f'{self.LRE}۳×۸-۱۰{self.POP}', out)

    def test_a_range_on_the_sets_side_is_covered_too(self):
        out = _protect_sets_reps('پرس — ۲-۳×۱۰')
        self.assertIn(f'{self.LRE}۲-۳×۱۰{self.POP}', out)

    def test_the_name_separator_is_not_swallowed_by_the_range(self):
        """جداکننده‌ی نام حرکت (—) نباید بخشی از بازه شمرده شود."""
        out = _protect_sets_reps('پلانک — 3×30-45 ثانیه')
        self.assertIn(f'{self.LRE}3×30-45{self.POP}', out)
        self.assertIn('پلانک — ', out)


# ===========================================================================
# سربرگ، لوگوها و کادرهای توضیحی
# ===========================================================================

WORKOUT_WITH_STRATEGY = """## برنامه ورزشی

استراتژی کلی: تمرکز بر افزایش قدرت پایه با حجم متوسط و پیشرفت تدریجی.

استراحت بین ست‌ها: ۶۰ تا ۹۰ ثانیه برای حرکات ترکیبی.

### جلسه ۱
1. اسکات هالتر — 4×8
2. پرس پا دستگاه — 4×10
---
3. پلانک — 3×45 ثانیه (وزن بدن)

### جلسه ۲
1. پرس سینه هالتر — 4×8
2. نشر جانب — 3×12
"""


class _FakeLogo:
    def __init__(self, path):
        self.path = path

    def __bool__(self):
        return bool(self.path)


class _FakeBrand:
    def __init__(self, path):
        self.logo = _FakeLogo(path)


class _CoachUser:
    """مربی‌ای که برند (و لوگو) دارد."""

    gym_name = 'باشگاه نمونه'

    class _Rel:
        def first(self):
            return None

    client_profile = _Rel()

    def __init__(self, logo_path):
        self.gym_brand = _FakeBrand(logo_path)


class _AthleteUser:
    """ورزشکار متصل به باشگاه — لوگو باید از مربی‌اش بیاید."""

    gym_name = 'باشگاه نمونه'

    class _Membership:
        def __init__(self, coach):
            self.gym_owner = coach

    class _Rel:
        def __init__(self, membership):
            self._membership = membership

        def first(self):
            return self._membership

    def __init__(self, logo_path):
        self.client_profile = self._Rel(self._Membership(_CoachUser(logo_path)))


def _branded_program(logo_path, user_class=_CoachUser, **kwargs):
    program = _FakeProgram(**kwargs)
    program.user = user_class(logo_path)
    return program


class HeaderAndLogoTests(TestCase):
    """لوگوی ثابت ما و لوگوی همان باشگاه، بالای هر صفحه."""

    def setUp(self):
        # از خود فایل لوگوی پروژه استفاده می‌شود تا تست به فایل موقت وابسته نباشد
        self.logo_path = LOGO_FILE

    def test_both_logos_are_placed_at_the_top(self):
        html = _build_html(
            _branded_program(self.logo_path, workout=WORKOUT_WITH_STRATEGY),
            section='workout',
        )
        self.assertIn('@top-left', html, 'لوگوی ثابت ما باید بالای صفحه باشد')
        self.assertIn('@top-right', html, 'لوگوی باشگاه باید بالای صفحه باشد')

    def test_without_a_gym_logo_only_ours_is_drawn(self):
        html = _build_html(
            _FakeProgram(WORKOUT_WITH_STRATEGY), section='workout'
        )
        self.assertIn('@top-left', html)
        self.assertNotIn('@top-right', html)

    def test_athlete_account_inherits_the_logo_of_its_gym(self):
        """برنامه‌ای که خود ورزشکار ساخته هم باید لوگوی باشگاهش را بگیرد."""
        program = _branded_program(
            self.logo_path, user_class=_AthleteUser, workout=WORKOUT_WITH_STRATEGY
        )
        self.assertEqual(_gym_logo_path(program), self.logo_path)

    def test_a_missing_logo_file_does_not_break_the_pdf(self):
        program = _branded_program(
            r'/no/such/logo.png', workout=WORKOUT_WITH_STRATEGY
        )
        self.assertEqual(_gym_logo_path(program), '')
        content, _ = generate_pdf(program, section='workout')
        self.assertTrue(content.startswith(b'%PDF'))

    def test_header_and_warning_are_readable_sizes(self):
        """سربرگ و اخطار هماهنگی با مربی نباید به ریزی قبل برگردند."""
        self.assertGreaterEqual(HEADER_FONT_PT, 11)
        self.assertGreaterEqual(COACH_NOTE_FONT_PT, 9)
        self.assertGreaterEqual(NOTE_FONT_PT, 11)

    def test_the_header_line_keeps_its_distance_from_the_content(self):
        self.assertGreaterEqual(HEADER_GAP_BELOW_MM, 6)
        self.assertGreater(PAGE_MARGIN_TOP_MM, LOGO_HEIGHT_MM)


class NoteBoxTests(TestCase):
    """استراتژی و استراحت بین ست‌ها: دو متن، یک کادر."""

    def test_strategy_and_rest_share_a_single_box(self):
        html = _build_html(
            _FakeProgram(WORKOUT_WITH_STRATEGY), section='workout'
        )
        boxes = re.findall(r'<div class="note note-intro">(.*?)</div>', html, re.S)
        self.assertEqual(len(boxes), 1, 'باید دقیقاً یک کادر باشد')
        self.assertEqual(
            boxes[0].count('<span>'), 2,
            'استراتژی و استراحت باید دو سطر جدا داخل همان کادر باشند',
        )

    def test_the_box_breathes_from_the_page_and_from_the_columns(self):
        html = _build_html(
            _FakeProgram(WORKOUT_WITH_STRATEGY), section='workout'
        )
        self.assertIn(f'margin: {NOTE_TOP_GAP_MM}mm 0 {NOTE_BOTTOM_GAP_MM}mm', html)
        self.assertGreater(NOTE_LINE_GAP_MM, 0)

    def test_supplements_get_the_same_box_as_the_strategy(self):
        html = _build_html(_FakeProgram(meal=MEAL_MD), section='meal')
        self.assertIn('class="note note-supp"', html)
        self.assertIn('مکمل‌ها', html)

    def test_the_old_borderless_intro_is_gone(self):
        html = _build_html(
            _FakeProgram(WORKOUT_WITH_STRATEGY), section='workout'
        )
        self.assertNotIn('<div class="intro">', html)


class MealStackingTests(TestCase):
    """برنامه غذایی ستون کنار هم ندارد: کادرهای سرتاسری، زیر هم."""

    @staticmethod
    def _body(html):
        """فقط بدنه — نه شیوه‌نامه، که تعریف ستون‌بندی ورزشی در آن می‌ماند."""
        return html.split('</style>')[1]

    def test_days_are_stacked_not_placed_side_by_side(self):
        body = self._body(_build_html(_FakeProgram(meal=MEAL_MD), section='meal'))
        self.assertNotIn('--cols', body, 'کادر روز نباید ستونی چیده شود')
        self.assertIn('<div class="grid">', body)

    def test_the_stacked_grid_is_a_single_full_width_column(self):
        html = _build_html(_FakeProgram(meal=MEAL_MD), section='meal')
        self.assertIn('.meal .grid', html)
        self.assertIn('grid-template-columns: 1fr;', html)

    def test_meal_text_breathes_more_than_the_workout_columns(self):
        self.assertGreater(MEAL_PAD_Y_MM, COLUMN_PAD_Y_MM)
        self.assertGreater(MEAL_PAD_X_MM, COLUMN_PAD_X_MM)

    def test_workout_still_uses_side_by_side_columns(self):
        body = self._body(
            _build_html(_FakeProgram(WORKOUT_WITH_STRATEGY), section='workout')
        )
        self.assertIn('--cols:', body)

    def test_a_full_seven_day_plan_still_fits_the_page_budget(self):
        """برنامه غذایی واقعی هفت روز است — سنگین‌ترین حالت."""
        day = (
            '\n### روز {n}\n'
            '**صبحانه:** نان سنگک، پنیر، گردو، چای کم‌رنگ\n'
            '**میان‌وعده:** موز ۱ عدد، بادام ۱۰ عدد\n'
            '**ناهار:** سینه مرغ گریل ۱۵۰ گرم، برنج قهوه‌ای، سالاد فصل\n'
            '**قبل از تمرین:** خرما ۲ عدد، ماست کم‌چرب\n'
            '**بعد از تمرین:** وی پروتئین ۱ اسکوپ، نان تست\n'
            '**شام:** عدسی ۱ کاسه، نان جو، سبزی خوردن\n'
        )
        meal = '## برنامه غذایی\n\nاستراتژی: کالری کمی بالاتر از نگهداری.\n'
        meal += ''.join(day.format(n=n) for n in '۱۲۳۴۵۶۷')
        meal += '\n### مکمل‌ها\nویتامین D — ۱۰۰۰ واحد روزانه\nکراتین — ۳ گرم روزانه\n'

        content, _ = generate_pdf(_FakeProgram(meal=meal), section='meal')
        self.assertTrue(content.startswith(b'%PDF'))
        self.assertLessEqual(count_pdf_pages(content), MEAL_MAX_PAGES)


class GeneratedCssTests(TestCase):
    """خروجی HTML باید معتبر بماند — این فایل یک f-string بزرگ است."""

    def test_the_style_block_has_balanced_braces(self):
        html = _build_html(
            _branded_program(LOGO_FILE, workout=WORKOUT_WITH_STRATEGY, meal=MEAL_MD),
            section='both',
        )
        style = html.split('<style>')[1].split('</style>')[0]
        self.assertEqual(
            style.count('{'), style.count('}'),
            'آکولادهای CSS نامتوازن‌اند — احتمالاً یک {{ در f-string جا افتاده',
        )
        # نباید هیچ آکولاد دوتایی خام در خروجی بماند
        self.assertNotIn('{{', style)
        self.assertNotIn('}}', style)

    def test_column_padding_shrinks_when_columns_get_narrow(self):
        """کادر باریک نباید نصف عرض متنش را به حاشیه بدهد."""
        wide = _column_pad_x_mm(90 * mm)
        narrow = _column_pad_x_mm(42 * mm)
        self.assertEqual(wide, COLUMN_PAD_X_MM)
        self.assertLess(narrow, wide)
        self.assertGreaterEqual(narrow, 2.5)


class MealRowGroupingTests(TestCase):
    """مدل هر قلم غذا را یک سطر می‌نویسد؛ مربی هر وعده را یک ردیف.

    بدون این گروه‌بندی، یک روز واقعی بیست‌وچند سطر می‌شود و کادر سرتاسری
    آن‌قدر کوچک می‌شود که خوانا نیست.
    """

    DAY = [
        'صبحانه:',
        'جو دوسر ۶۰ گرم',
        'شیر کم‌چرب ۳۰۰ میلی‌لیتر',
        'تخم‌مرغ کامل ۳ عدد',
        'ناهار:',
        'سینه مرغ پخته ۲۰۰ گرم',
        'برنج پخته ۲۵۰ گرم',
        'قبل از تمرین (۹۰ دقیقه مانده):',
        'نان سنگک ۶۰ گرم',
        'خرما ۲۰ گرم',
        'جمع روز ۱: کالری ۲۸۹۰ | پروتئین ۲۰۸g',
    ]

    def test_each_meal_becomes_one_row(self):
        rows = group_meal_rows(self.DAY)
        self.assertEqual(
            [row['label'] for row in rows],
            ['صبحانه', 'ناهار', 'قبل از تمرین', 'جمع روز ۱'],
        )

    def test_items_of_a_meal_are_joined_on_one_line(self):
        rows = group_meal_rows(self.DAY)
        breakfast = rows[0]
        self.assertEqual(
            breakfast['text'],
            'جو دوسر ۶۰ گرم، شیر کم‌چرب ۳۰۰ میلی‌لیتر، تخم‌مرغ کامل ۳ عدد',
        )

    def test_a_meal_with_a_time_keeps_the_time_next_to_its_items(self):
        """«قبل از تمرین (۹۰ دقیقه مانده)» نباید ستون باریک نام وعده را بترکاند."""
        rows = group_meal_rows(self.DAY)
        pre_workout = rows[2]
        self.assertEqual(pre_workout['label'], 'قبل از تمرین')
        self.assertTrue(pre_workout['text'].startswith('(۹۰ دقیقه مانده) '))
        self.assertIn('نان سنگک ۶۰ گرم', pre_workout['text'])

    def test_a_self_contained_line_becomes_its_own_row(self):
        rows = group_meal_rows(self.DAY)
        total = rows[-1]
        self.assertEqual(total['label'], 'جمع روز ۱')
        self.assertIn('کالری ۲۸۹۰', total['text'])

    def test_no_meal_is_swallowed_by_the_previous_one(self):
        """ردیف قبل/بعد از تمرین نباید به ناهار بچسبد."""
        rows = group_meal_rows(self.DAY)
        lunch = rows[1]
        self.assertNotIn('نان سنگک', lunch['text'])
        self.assertNotIn('دقیقه مانده', lunch['text'])

    def test_a_dense_day_shrinks_to_a_handful_of_rows(self):
        """۲۶ سطر خام باید به تعداد وعده‌ها برسد، نه بیشتر."""
        dense = []
        for meal in ('صبحانه:', 'میان‌وعده صبح:', 'ناهار:', 'شام:'):
            dense.append(meal)
            dense.extend(f'قلم {n}' for n in range(5))
        rows = group_meal_rows(dense)
        self.assertEqual(len(rows), 4)

    def test_lines_before_any_meal_label_are_kept(self):
        rows = group_meal_rows(['یادداشت آزاد بدون عنوان'])
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]['label'])
        self.assertEqual(rows[0]['text'], 'یادداشت آزاد بدون عنوان')

    def test_the_html_meal_row_carries_the_label_and_the_items(self):
        meal = (
            '## برنامه غذایی\n\n### روز ۱\n'
            '**صبحانه:**\nجو دوسر ۶۰ گرم\nشیر ۳۰۰ میلی‌لیتر\n'
        )
        html = _build_html(_FakeProgram(meal=meal), section='meal')
        self.assertIn('<span class="ml-k">صبحانه</span>', html)
        self.assertIn('جو دوسر ۶۰ گرم، شیر ۳۰۰ میلی‌لیتر', html)
