# -*- coding: utf-8 -*-
"""دورِ پنجمِ بازبینی (۱۱/۱۸) روی «منبع‌های طراحی + 21st.dev»:

* رانتایمِ کوچکِ تعامل (آکاردئون، تب، کلید، بنرِ بسته‌شو) در سایتِ منتشرشده؛ مرورگرِ واقعی (اگر باشد) روی همین اسکریپت کلیک می‌زند؛
* همهٔ پنل‌های بسته در HTML می‌آیند و روی بوم باز و قابلِ ویرایش‌اند (FAQ با ۵ سؤال و ۱ پاسخ نداریم)؛
* «ثابت (بدونِ حرکت)»: قطعه‌ای که اصلِ کارش حالت/رویداد است و بازسازی نمی‌شود نشان می‌گیرد، بعد از قطعه‌های کارا می‌آید و پیش از انتشار گفته می‌شود؛
* رولرِ رقمِ قیمت متنِ ساده می‌شود (ده رقمِ ۰ تا ۹ دیگر «متنِ قابلِ ویرایش» نیست و «۲۴$» در RTL «۴۲$» نمی‌شود)؛
* دروازه‌های چیدمان: «پاسخِ ردیف‌ها در قطعه نیست»، حرف‌به‌حرف‌شکسته، نیمه‌بریده، تصویرمحورِ بی‌تصویر، «فقط دکمهٔ بازکنندهٔ پنجره»؛
* کاتالوگ: نوشتارِ یکدستِ مجوز و MIT-0 که «غیرقابلِ استفاده» مانده بود؛ جست‌وجوی فارسی در همهٔ تبِ‌های «منبع‌های طراحی»؛
* AI: رهنمودِ ui-ux-pro-max با سبکِ انتخاب‌شده هم می‌ماند و stats راست می‌گوید؛ قطعهٔ 21stِ نامرتبط پیشنهاد نمی‌شود.
مرورگر و AI ِ واقعی صدا زده نمی‌شوند مگر آزمونی که صریحاً «اگر مرورگر بود» می‌گوید.
"""
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from django.test import SimpleTestCase

from apps.ai_engine.services import validate_template
from apps.projects.builder import (ai_context as AC, c21_convert as CV, c21_embed as EM, c21_pipeline, c21_rtl, c21_runtime as RT, c21st, placeholders as PH, render as R, theme as T)
from apps.projects.builder.clean import clean_doc, new_block
from apps.projects.builder.styles import uiux
from apps.projects.tests_c21x import DataDirMixin, FakeNode


def render(doc, canvas=False):
    return R.render_doc(clean_doc(doc, "page"), R.Ctx(canvas=canvas, target="page", theme=T.default_theme()["colors"]))


# سه سطرِ FAQ: ردیفِ اول باز، دو ردیفِ دیگر بسته (hidden)؛ یک تب؛ یک کلید
FAQ_HTML = ('<div id="c21-root"><section data-slot="faq"><div data-nbc-acc="single">'
            '<div data-nbc-item data-state="open"><h3 data-nbc-head><button type="button" aria-expanded="true" data-nbc-trigger>Question one here</button></h3>'
            '<div role="region" data-nbc-panel>Answer number one is long enough</div></div>'
            '<div data-nbc-item data-state="closed"><h3 data-nbc-head><button type="button" aria-expanded="false" data-nbc-trigger>Question two here</button></h3>'
            '<div role="region" hidden data-nbc-panel>Answer number two is long enough</div></div>'
            '</div></section></div>')


class C21Base(DataDirMixin):
    def convert(self, cid="acme/faq-x", html=FAQ_HTML, title="FAQ Two Column", cats=("accordion",), interact=None, rtl=None):
        rec = CV.convert_bundle(cid, {"entry": {"path": "U.tsx", "code": "x"}, "files": {}, "aliases": {}, "roots": [],
                                      "source": {"kind": "upstream", "repo": "https://github.com/acme/ui", "license": "MIT"}},
                                meta={"title": title, "license": "mit", "author": "Acme", "library": "Acme UI", "cats": list(cats)}, runner=FakeNode(html=html))
        if interact is not None:
            rec["interact"] = {"state": interact, "kinds": ["accordion"] if interact == "works" else [], "dead": 0, "prims": [], "v": 1}
        if rtl is not None:
            rec["rtl"] = dict(rec.get("rtl") or {}, **rtl)
        CV.save_record(rec)
        return rec


# ───────────────────────────── ۱) رولرِ رقم

ROLLER = ('<div id="c21-root"><div class="price"><span class="sr-only">$24</span><span aria-hidden="true" class="inline-flex"><span>$</span>'
          '<span class="relative"><span class="col">%s</span></span></span><span>/ mo</span></div></div>')
DIGITS = "".join('<span class="cell">%d</span>' % d for d in range(10))


class RollerTests(SimpleTestCase):
    def test_roller_with_screen_reader_twin_becomes_plain_editable_text(self):
        sl = CV.sanitize(ROLLER % DIGITS, "nbc21-xabc")
        self.assertEqual(sl["texts"], ["$24", "/ mo"], "ده رقمِ ۰ تا ۹ و «$» دیگر شکافِ قابلِ ویرایش نیستند")
        self.assertNotIn("sr-only", sl["template"])
        self.assertNotIn('aria-hidden="true"', sl["template"])
        self.assertIn("{{T0}}", sl["template"])

    def test_roller_without_a_twin_keeps_digits_literal_and_not_editable(self):
        html = '<div id="c21-root"><div><span aria-hidden="true"><span class="col">%s</span></span></div></div>' % DIGITS
        sl = CV.sanitize(html, "nbc21-xabc")
        self.assertEqual(sl["texts"], [])
        for d in "0123456789":
            self.assertIn(">%s<" % d, sl["template"])

    def test_ordinary_lists_of_digits_are_not_rollers(self):
        html = '<div id="c21-root"><ol><li>1</li><li>2</li><li>3</li></ol><p>Hello there friend</p></div>'
        sl = CV.sanitize(html, "nbc21-xabc")
        self.assertEqual(sl["texts"], ["1", "2", "3", "Hello there friend"])

    def test_the_sample_guard_no_longer_counts_roller_digits(self):
        sl = CV.sanitize(ROLLER % DIGITS, "nbc21-xabc")
        self.assertFalse([t for t in sl["texts"] if t in list("0123456789")])


# ───────────────────────────── ۲) رانتایمِ تعامل

PAGE = ('<!doctype html><meta charset="utf-8"><body><div class="nbc21-host"><div class="nbc21-xt" dir="rtl">'
        '<div data-nbc-acc="single">'
        '<div data-nbc-item data-state="closed"><h3 data-nbc-head><button id="q1" type="button" aria-expanded="false" data-nbc-trigger>Q1</button></h3><div id="a1" role="region" hidden data-nbc-panel>A1</div></div>'
        '<div data-nbc-item data-state="open"><h3 data-nbc-head><button id="q2" type="button" aria-expanded="true" data-nbc-trigger>Q2</button></h3><div id="a2" role="region" data-nbc-panel>A2</div></div>'
        '</div>'
        '<div><div role="tablist"><button id="t1" role="tab" aria-selected="true" data-state="active">T1</button><button id="t2" role="tab" aria-selected="false" data-state="inactive">T2</button></div>'
        '<div id="p1" role="tabpanel" data-state="active">P1</div><div id="p2" role="tabpanel" hidden data-state="inactive">P2</div></div>'
        '<button id="sw" role="switch" aria-checked="false" data-state="unchecked"><span id="thumb" data-state="unchecked"></span></button>'
        '<div id="banner" role="alert"><span>Hello banner</span><button id="x" aria-label="Close">x</button></div>'
        '<div data-open id="bu"><button id="bq" aria-expanded="false"><b>Q</b></button><div id="bp" hidden data-closed role="region">BP</div></div>'
        '</div></div>%s<button id="site-menu" aria-expanded="false">menu</button><div id="site-menu-panel" hidden>site</div></body>')
CHECK_JS = r"""() => {
  const $ = (id) => document.getElementById(id);
  const out = {};
  $('q1').click();
  out.single = [$('a1').hidden, $('a2').hidden, $('q1').getAttribute('aria-expanded'), $('q2').getAttribute('aria-expanded'), $('q1').closest('[data-nbc-item]').getAttribute('data-state')];
  $('q1').click();
  out.close = [$('a1').hidden, $('q1').getAttribute('aria-expanded')];
  $('t2').click();
  out.tabs = [$('p1').hidden, $('p2').hidden, $('t1').getAttribute('aria-selected'), $('t2').getAttribute('aria-selected'), $('t2').getAttribute('data-state'), $('p2').getAttribute('data-state')];
  $('sw').click();
  out.sw = [$('sw').getAttribute('aria-checked'), $('sw').getAttribute('data-state'), $('thumb').getAttribute('data-state')];
  $('x').click();
  out.banner = $('banner').hidden;
  $('bq').click();
  out.base = [$('bp').hidden, $('bu').hasAttribute('data-open'), $('bu').hasAttribute('data-closed'), $('bp').hasAttribute('data-open')];
  const nested = document.createElement('div'); nested.innerHTML = '<div data-open><button id="nb" aria-expanded="false"><button id="nbi">in</button></button><div hidden data-closed role="region">P</div></div>';
  document.querySelector('.nbc21-host').appendChild(nested); $('nbi').click();
  out.nested = nested.querySelector('[role=region]').hidden;
  $('site-menu').click();
  out.site = [$('site-menu').getAttribute('aria-expanded'), $('site-menu-panel').hidden];
  return out;
}"""


def run_browser(html: str, js: str, timeout: int = 120):
    with tempfile.TemporaryDirectory(prefix="c21r5-") as d:
        Path(d, "p.html").write_text(html, encoding="utf-8")
        Path(d, "run.py").write_text(
            "import json,sys\nfrom playwright.sync_api import sync_playwright\n"
            "with sync_playwright() as p:\n b=p.chromium.launch(); pg=b.new_page(); pg.goto('file://%s/p.html'); print(json.dumps(pg.evaluate(%r))); b.close()\n" % (d, js), encoding="utf-8")
        env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or c21_rtl.DEFAULT_BROWSERS)
        r = subprocess.run([os.environ.get("NM_C21_PLAYWRIGHT_PY") or c21_rtl.DEFAULT_PY, str(Path(d, "run.py"))], capture_output=True, text=True, env=env, timeout=timeout)
        return json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {"error": r.stderr[-300:]}


class RuntimeScriptTests(SimpleTestCase):
    def test_script_is_safe_for_the_django_template_and_small(self):
        self.assertTrue(RT.runtime_ok())
        self.assertLess(len(RT.RUNTIME_JS), 6000)
        self.assertFalse(re.search(r"\{[{%#]", RT.RUNTIME_JS))
        ok, issues = validate_template("<p>x</p>\n" + RT.script_tag(), None)
        self.assertTrue(ok, issues)
        self.assertFalse([i for i in issues if "بیرونی" in i], "اسکریپتِ درون‌خطی است، نه بیرونی")

    def test_script_is_one_tag_marked_with_its_version(self):
        tag = RT.script_tag()
        self.assertEqual(tag.count("<script"), 1)
        self.assertIn('data-nbc21-rt="%d"' % RT.VERSION, tag)
        self.assertNotIn("</script>", RT.RUNTIME_JS)

    @unittest.skipUnless(c21_rtl.available()[0], "Playwright/Chromium نیست")
    def test_real_browser_accordion_tabs_switch_banner_and_base_ui_markers(self):
        got = run_browser(PAGE % RT.script_tag(), CHECK_JS)
        self.assertNotIn("error", got, got)
        self.assertEqual(got["single"][:4], [False, True, "true", "false"], "type=single: باز کردنِ اولی دومی را می‌بندد")
        self.assertEqual(got["single"][4], "open")
        self.assertEqual(got["close"], [True, "false"])
        self.assertEqual(got["tabs"], [True, False, "false", "true", "active", "active"])
        self.assertEqual(got["sw"], ["true", "checked", "checked"])
        self.assertTrue(got["banner"], "دکمهٔ Close در role=alert کلِ بنر را می‌بندد")
        self.assertEqual(got["base"], [False, True, False, True], "نشانه‌های data-open/data-closed ِ Base UI هم هم‌گام می‌شوند")
        self.assertFalse(got["nested"], "دکمهٔ تودرتو (shadcn Collapsible) هم کار می‌کند: کلیک روی دکمهٔ درونی به بیرونی می‌رسد")
        self.assertEqual(got["site"], ["false", True], "دکمه‌های خودِ سایت (بیرون از .nbc21-host) را رانتایم لمس نمی‌کند")

    @unittest.skipUnless(c21_rtl.available()[0], "Playwright/Chromium نیست")
    def test_without_the_script_nothing_changes(self):
        got = run_browser(PAGE % "", CHECK_JS.replace("$('q1').click();", "", 1))
        self.assertNotIn("error", got, got)
        self.assertTrue(got["banner"] is False)


# ───────────────────────────── ۳) طبقه‌بندی: تعاملی / ثابت / ساده

def probe(**kinds):
    return {"kinds": {k: {"n": n, "changed": c} for k, (n, c) in kinds.items()}, "triggers": 0, "with_panel": 0}


class InteractClassificationTests(SimpleTestCase):
    def of(self, src=None, **kinds):
        rec = {"interact_src": src, "rtl": {"probe": probe(**kinds)} if kinds else {}}
        return CV.interact_of(rec)

    def test_clicks_that_change_the_page_make_it_work(self):
        out = self.of({"state": False, "prims": ["accordion"]}, accordion=(5, 5))
        self.assertEqual((out["state"], out["kinds"], out["dead"]), ("works", ["accordion"], 0))

    def test_any_dead_control_makes_it_static_even_when_something_else_works(self):
        out = self.of({"state": True, "events": True}, accordion=(3, 3), toggle=(1, 0))
        self.assertEqual((out["state"], out["dead"]), ("static", 1))
        self.assertEqual(out["kinds"], ["accordion"])

    def test_state_or_effects_without_a_working_control_is_static(self):
        self.assertEqual(self.of({"state": True, "prims": []})["state"], "static")
        self.assertEqual(self.of({"effect": True})["state"], "static")
        self.assertEqual(self.of({"events": True})["state"], "static")
        self.assertEqual(self.of({"prims": ["dialog"]})["state"], "static")

    def test_pure_decoration_and_entrance_motion_are_plain(self):
        self.assertEqual(self.of({"state": False, "effect": False, "events": False, "motion": True, "prims": []})["state"], "plain")
        self.assertEqual(self.of({"prims": ["internals", "utils", "merge-props"]})["state"], "plain", "زیرساختِ Base UI حالت‌دار حساب نمی‌شود")

    def test_old_records_without_signals_are_judged_by_the_probe_only(self):
        self.assertEqual(self.of(None)["state"], "plain")
        self.assertEqual(self.of(None, accordion=(2, 0))["state"], "static")
        self.assertEqual(CV.interact_state({"interact": {"state": "works"}}), "works")
        self.assertEqual(CV.interact_state({}), "plain")

    def test_labels_are_the_agreed_wording(self):
        self.assertEqual(CV.STATIC_BADGE, "ثابت (بدونِ حرکت)")
        self.assertEqual(PH.KIND_LABEL["static"], "قطعهٔ ثابت (بدونِ حرکت)")
        self.assertIn("static", PH.KINDS)


# ───────────────────────────── ۴) دروازه‌های چیدمان و تعامل

class LayoutGateTests(SimpleTestCase):
    def prob(self, row=None, rec=None, state="plain"):
        return c21_rtl.layout_problem(row or {}, rec or {"images": [], "title": "Thing"}, {"state": state})

    def test_a_faq_with_five_questions_and_one_answer_is_blocked(self):
        why = self.prob({"probe": {"triggers": 5, "with_panel": 1}})
        self.assertIn("5", why)
        self.assertIn("پاسخِ 4", why)
        self.assertEqual(self.prob({"probe": {"triggers": 5, "with_panel": 5}}), "")
        self.assertEqual(self.prob({"probe": {"triggers": 1, "with_panel": 0}}), "", "یک دکمهٔ بازشو (منو) خودش ایراد نیست؛ «مرده» بودنش جدا حساب می‌شود")

    def test_letter_by_letter_wrapping_and_cut_texts_are_counted(self):
        items = [{"len": 14, "nlines": 8}, {"len": 14, "nlines": 2}, {"len": 3, "nlines": 3}, {"len": 20, "nlines": 20}]
        self.assertEqual(c21_rtl.vwrap_count(items), 2, "14 نویسه در ۸ سطر و ۲۰ در ۲۰ سطر؛ سه‌نویسه‌ای و دوسطری نه")
        self.assertEqual(c21_rtl.cut_count([{"len": 12, "cut": 1}, {"len": 12, "cut": 0}, {"len": 2, "cut": 1}]), 1)
        self.assertIn("حرف", self.prob({"vwrap": 1}))
        self.assertIn("بریده", self.prob({"cut": c21_rtl.CUT_MAX}))
        self.assertEqual(self.prob({"cut": c21_rtl.CUT_MAX - 1}), "")

    def test_image_only_components_without_images_are_blocked(self):
        rec = {"images": [{"alt": ""}] * 13, "title": "Marquee along SVG path"}
        self.assertIn("13", self.prob({"chars": 0}, rec))
        self.assertEqual(self.prob({"chars": 0}, {"images": [{"alt": ""}] * 3, "title": "x"}), "")
        self.assertEqual(self.prob({"chars": 40}, rec), "")

    def test_a_lone_window_opener_is_blocked_but_a_plain_cta_button_is_not(self):
        rec = {"images": [], "title": "Command Palette", "interact_src": {"prims": [], "state": True}}
        self.assertIn("دکمهٔ بازکننده", self.prob({"chars": 12}, rec, state="static"))
        cta = {"images": [], "title": "Shiny Button", "interact_src": {"prims": [], "state": True}}
        self.assertEqual(self.prob({"chars": 12}, cta, state="static"), "")
        dlg = {"images": [], "title": "Open", "interact_src": {"prims": ["dialog"], "state": True}}
        self.assertTrue(self.prob({"chars": 12}, dlg, state="static"))
        self.assertEqual(self.prob({"chars": 400}, dlg, state="static"), "", "دیالوگی که متنِ زیادی دارد دکمهٔ تنها نیست")

    def test_check_version_is_bumped(self):
        self.assertGreaterEqual(c21_rtl.CHECK_VERSION, 6)


# ───────────────────────────── ۵) رندر: بوم باز، سایت بسته + رانتایم، هشدارِ ثابت

class EmbedInteractTests(C21Base, SimpleTestCase):
    def test_canvas_shows_every_panel_so_every_answer_is_editable(self):
        rec = self.convert(interact="works")
        b = new_block(EM.TYPE, **EM.default_props(rec))
        canvas = render({"v": 1, "blocks": [b]}, canvas=True).html
        self.assertNotRegex(canvas, r"\shidden[\s>]")
        self.assertIn("Answer number two", canvas)
        self.assertEqual(len(rec["texts"]), 4, "هر دو پاسخ در شکاف‌های متن‌اند")

    def test_published_page_keeps_panels_closed_and_adds_one_runtime_script(self):
        rec = self.convert(interact="works")
        b1, b2 = (new_block(EM.TYPE, **EM.default_props(rec)) for _ in range(2))
        out = render({"v": 1, "blocks": [b1, b2]})
        self.assertRegex(out.html, r"\shidden[\s>]")
        self.assertEqual(out.html.count("data-nbc21-rt"), 1, "دو قطعه ⇒ یک اسکریپت")
        self.assertIn("[hidden]{display:none!important}", out.css)
        ok, issues = validate_template(out.html, None)
        self.assertTrue(ok, issues)

    def test_no_script_for_static_or_plain_components_or_on_the_canvas(self):
        for state in ("static", "plain"):
            rec = self.convert(cid="acme/x-%s" % state, interact=state)
            out = render({"v": 1, "blocks": [new_block(EM.TYPE, **EM.default_props(rec))]})
            self.assertNotIn("data-nbc21-rt", out.html, state)
        rec = self.convert(cid="acme/x-works", interact="works")
        self.assertNotIn("data-nbc21-rt", render({"v": 1, "blocks": [new_block(EM.TYPE, **EM.default_props(rec))]}, canvas=True).html)

    def test_static_component_is_announced_before_publishing(self):
        rec = self.convert(interact="static")
        out = render({"v": 1, "blocks": [new_block(EM.TYPE, **EM.default_props(rec))]})
        found = [w for w in out.warnings if w.get("kind") == "static"]
        self.assertEqual(len(found), 1, out.warnings)
        self.assertIn("ثابت", found[0]["text"])
        self.assertIn(found[0]["kind"], PH.KINDS)
        works = self.convert(cid="acme/faq-y", interact="works")
        self.assertFalse([w for w in render({"v": 1, "blocks": [new_block(EM.TYPE, **EM.default_props(works))]}).warnings if w.get("kind") == "static"])

    def test_skeleton_for_ai_and_the_studio_preview_are_expanded(self):
        rec = self.convert(interact="works")
        self.assertNotRegex(EM.skeleton(rec["key"]), r"\shidden[\s>]")
        self.assertRegex(EM.preview_page(rec["key"])["html"], r"\shidden[\s>]", "پیش‌فرض همان است که سایت می‌گیرد")
        self.assertNotRegex(EM.preview_page(rec["key"], expand=True)["html"], r"\shidden[\s>]")

    def test_interact_note_wording(self):
        self.assertIn("تعاملی", EM.interact_note({"interact": {"state": "works", "kinds": ["accordion", "tabs"]}}))
        self.assertIn("ثابت", EM.interact_note({"interact": {"state": "static"}}))
        self.assertEqual(EM.interact_note({"interact": {"state": "plain"}}), "")


# ───────────────────────────── ۶) کاتالوگ: مجوز و ترتیب

class LicenseCanonTests(SimpleTestCase):
    def test_spellings_are_unified(self):
        for raw, want in (("mit", "MIT"), ("MIT", "MIT"), ("apache-2.0", "Apache-2.0"), ("Apache-2.0", "Apache-2.0"), ("MIT-0", "MIT-0"), ("cc0", "CC0-1.0"),
                          ("MIT License, Copyright (c) 2026 ozzy", "MIT"), ("AGPL-3.0", "AGPL-3.0"), ("", ""), (None, "")):
            self.assertEqual(c21st.canon_license(raw), want, raw)
        self.assertEqual(c21st.canon_license("MIT + Commons Clause"), "MIT + Commons Clause", "ناشناخته/محدودکننده دست‌نخورده")

    def test_reconcile_makes_usable_follow_the_licence(self):
        rows = [{"id": "a/x", "detail": True, "license": "MIT-0", "usable": False},
                {"id": "a/y", "detail": True, "license": "mit", "usable": True},
                {"id": "a/z", "detail": True, "license": "MIT + Commons Clause", "usable": True},
                {"id": "a/w", "detail": True, "license": "MIT License, Copyright (c) 2026 ozzy", "usable": False},
                {"id": "a/v", "detail": False, "license": "", "usable": False},
                {"id": "a/u", "detail": True, "license": "unknown", "usable": False}]
        got = {r["id"]: r for r in c21st.reconcile(rows)}
        self.assertTrue(got["a/x"]["usable"], "MIT-0 روا است (پرچمِ قدیمی از پیش از افزودنِ MIT-0 مانده بود)")
        self.assertEqual(got["a/y"]["license"], "MIT")
        self.assertFalse(got["a/z"]["usable"], "MIT + Commons Clause محدودکننده است")
        self.assertTrue(got["a/w"]["usable"])
        self.assertFalse(got["a/v"]["usable"])
        self.assertFalse(got["a/u"]["usable"])

    def test_loading_the_catalogue_reconciles_rows(self):
        with tempfile.TemporaryDirectory() as d:
            from django.test import override_settings
            with override_settings(NM_DATA_DIR=d):
                c21st._cache.update(mtime=0.0, rows=[])
                Path(d, "c21st").mkdir()
                Path(d, "c21st", "catalog.json").write_text(json.dumps([{"id": "a/x", "title": "X", "detail": True, "license": "MIT-0", "usable": False}]), encoding="utf-8")
                row = c21st.load()[0]
                self.assertTrue(row["usable"])
                self.assertEqual(row["license"], "MIT-0")
                c21st._cache.update(mtime=0.0, rows=[])


class OrderingTests(C21Base, SimpleTestCase):
    def setUp(self):
        super().setUp()
        rows = []
        for cid, state in (("acme/static-one", "static"), ("acme/plain-one", "plain"), ("acme/works-one", "works")):
            rec = self.convert(cid=cid, title="Pricing %s" % state, cats=("pricing-section",), interact=state, rtl={"status": "ok", "kind": "section"})
            rows.append({"id": cid, "title": "Pricing %s" % state, "usable": True, "detail": True, "license": "MIT", "cats": ["pricing-section"], "tags": [], "description": "", "library": "Acme",
                         "author_name": "A", "conv": {"state": "ok", "key": rec["key"], "rtl": "ok", "kind": "section"}, "url": "https://21st.dev/@a/components/" + cid.split("/")[1]})
        rows.append({"id": "acme/catalogue-only", "title": "Pricing catalogue", "usable": False, "detail": True, "license": "unknown", "cats": ["pricing-section"], "tags": [], "description": "", "library": "Acme",
                     "author_name": "A", "url": "https://21st.dev/@a/components/c"})
        c21st.save(rows)

    def test_working_first_then_plain_then_static_then_catalogue_only(self):
        ids = [it["id"] for it in c21st.search("", size=10)["items"]]
        self.assertEqual(ids, ["acme/works-one", "acme/plain-one", "acme/static-one", "acme/catalogue-only"])

    def test_with_a_query_relevance_still_leads_but_ties_follow_the_same_order(self):
        ids = [it["id"] for it in c21st.search("pricing", size=10)["items"]]
        self.assertEqual(ids[:3], ["acme/works-one", "acme/plain-one", "acme/static-one"])

    def test_cards_carry_the_interact_state_and_the_summary_counts(self):
        out = c21st.search("", insertable_only=True, size=10)
        self.assertEqual({it["id"]: it["interact"] for it in out["items"]}, {"acme/works-one": "works", "acme/plain-one": "plain", "acme/static-one": "static"})
        self.assertEqual(out["interact"], {"works": 1, "plain": 1, "static": 1})
        cat_only = [it for it in c21st.search("catalogue")["items"] if it["id"] == "acme/catalogue-only"][0]
        self.assertEqual(cat_only["interact"], "")


# ───────────────────────────── ۷) AI

class AiContextRound5Tests(C21Base, SimpleTestCase):
    def test_guidance_survives_a_tight_budget_with_a_style_and_stats_tell_the_truth(self):
        for brief in ("سایتِ رستورانِ سنتی با منوی آنلاین و رزرو میز", "داشبوردِ تحلیلیِ فروشگاهِ آنلاین با نمودار", "باشگاهِ ورزشی و مربیِ شخصی"):
            p = AC.build(style_key="dark-luxury", brief=brief, kind="home")
            self.assertIn("guidance", p, brief)
            self.assertEqual(p["stats"]["guidance"], len(p["guidance"]), "عددِ stats همان است که ماند")
            self.assertLessEqual(AC._size(p), AC.MAX_CHARS, brief)
            self.assertGreaterEqual(len(p["guidance"]), 3, "چند ردیفِ مرتبط (UX، الگو، محصول …) می‌ماند، نه یک ردیفِ تکی")
            self.assertTrue(p["components"], "قطعه‌ها هم می‌مانند")

    def test_without_a_style_guidance_is_still_there(self):
        p = AC.build(style_key="", brief="سایتِ رستورانِ سنتی", kind="home")
        self.assertIn("guidance", p)

    def test_unrelated_components_are_not_suggested_for_a_brief(self):
        rec = self.convert(cid="acme/folded-card", title="Folded Card", cats=("card",), interact="plain", rtl={"status": "ok", "kind": "widget"})
        rows = [{"id": "acme/folded-card", "title": "Folded Card", "usable": True, "detail": True, "license": "MIT", "cats": ["card"], "tags": ["origami"], "description": "A folded paper card",
                 "library": "Acme", "author_name": "A", "conv": {"state": "ok", "key": rec["key"]}}]
        c21st.save(rows)
        self.assertEqual(AC.c21_suggest("سایتِ رستورانِ سنتی با منوی آنلاین و رزرو میز", "home"), [], "فقط هم‌دسته با نقشهٔ صفحه بودن کافی نیست")
        got = AC.c21_suggest("a folded paper card", "home")
        self.assertEqual([x["id"] for x in got], ["acme/folded-card"], "واژهٔ مشترک ⇒ پیشنهاد می‌شود")

    def test_static_components_are_only_suggested_when_the_section_is_asked_for(self):
        rec = self.convert(cid="acme/pricing-st", title="Pricing Toggle", cats=("pricing-section",), interact="static", rtl={"status": "ok", "kind": "section"})
        c21st.save([{"id": "acme/pricing-st", "title": "Pricing Toggle", "usable": True, "detail": True, "license": "MIT", "cats": ["pricing-section"], "tags": ["pricing"], "description": "pricing plans",
                     "library": "Acme", "author_name": "A", "conv": {"state": "ok", "key": rec["key"]}}])
        self.assertEqual(AC.c21_suggest("یک سایتِ ساده", "home"), [])
        self.assertTrue(AC.c21_suggest("صفحهٔ قیمت و تعرفه", "home"))


# ───────────────────────────── ۸) «منبع‌های طراحی»: جست‌وجوی فارسی در همهٔ تب‌ها

class PersianSearchEverywhereTests(SimpleTestCase):
    def test_product_type_tab_understands_persian_domains(self):
        self.assertEqual(uiux.count("products", "ورزش"), 0, "پایه: دادهٔ انگلیسی بدونِ برگردان چیزی نمی‌یابد")
        q = c21st.expand_query("ورزش")
        self.assertGreater(uiux.count("products", q), 0)
        self.assertTrue(any("fitness" in r.get("product", "").lower() for r in uiux.search("products", q, limit=40)))

    def test_sections_and_widgets_in_persian_reach_the_ux_and_landing_tabs(self):
        self.assertGreater(uiux.count("landing", c21st.expand_query("قیمت")), 0)
        self.assertGreater(uiux.count("colors", c21st.expand_query("رستوران")), 0)


# ───────────────────────────── ۹) بهداشتِ آزمون: هیچ اسکریپتی پیش‌نویسِ واقعیِ مالک را لمس نمی‌کند

class OwnerDraftsAreNeverTouchedTests(SimpleTestCase):
    def test_browser_checks_never_name_the_owners_project_or_save_a_design(self):
        root = Path(__file__).resolve().parent / "browser_checks"
        for f in sorted(root.glob("*.py")):
            text = f.read_text(encoding="utf-8")
            self.assertNotIn("chagher-landing", text, f.name)
            self.assertNotIn("builder/design/", text, f.name)
            self.assertNotRegex(text, r"\.put\(", f.name)

    def test_the_panel_check_uses_a_throw_away_project(self):
        text = (Path(__file__).resolve().parent / "browser_checks" / "check_panel_pages.py").read_text(encoding="utf-8")
        self.assertIn("throwaway", text.lower())
        self.assertNotIn("Project.objects.first()", text)


# ───────────────────────────── ۱۰) هم‌ترازیِ کاتالوگ پس از رکوردهای بازسازی‌شده

class SyncCatalogTests(C21Base, SimpleTestCase):
    def test_catalog_conv_copy_follows_the_index(self):
        rec = self.convert(cid="acme/sync-one", title="Pricing sync", cats=("pricing-section",), interact="static", rtl={"status": "fail", "kind": "widget"})
        c21st.save([{"id": "acme/sync-one", "title": "Pricing sync", "usable": True, "detail": True, "license": "MIT", "cats": ["pricing-section"], "tags": [], "description": "", "library": "Acme",
                     "author_name": "A", "conv": {"state": "ok", "key": rec["key"], "rtl": "ok", "kind": "section"}, "url": "https://21st.dev/@a/components/x"},
                    {"id": "acme/none", "title": "No conv", "usable": True, "detail": True, "license": "MIT", "cats": [], "tags": [], "description": "", "library": "Acme", "author_name": "A", "url": "u"}])
        self.assertEqual(c21_pipeline.sync_catalog_conv(), 1)
        row = {r["id"]: r for r in c21st.load()}["acme/sync-one"]
        self.assertEqual((row["conv"]["rtl"], row["conv"]["kind"]), ("fail", "widget"))
        self.assertFalse(c21st.insertable(row))
        self.assertEqual(c21_pipeline.sync_catalog_conv(), 0)                     # idempotent
