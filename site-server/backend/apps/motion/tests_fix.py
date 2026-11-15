"""رفعِ ایرادهای دورِ بازبینی: QA که همگرا نمی‌شد و متن را ریز می‌کرد، دورزدنِ سیاستِ داده در گوینده، هدفِ اشتباهِ اصلاحِ کنتراست،
طرحِ تازه به‌ازای هر بازدید، کندیِ QA و نبودِ پیشرفت، نقطه‌گذاریِ پیام‌ها."""
import json
import shutil
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase
from django.utils import timezone
from PIL import Image

from . import ai, motionlib, plans, qa, qa_browser, sound, specs, tasks, tests_api, timeline
from .models import MotionPlan
from .tests_qa import H, W, box, codes, plan, shot
from .tests_sound import HAVE_FFMPEG, tone

SAFE = {"top": 270, "right": 108, "bottom": 422, "left": 65}          # Instagram Reels


def glyph(b: dict, gx: float, gw: float, gy: float | None = None, gh: float | None = None) -> dict:
    """a text block whose COLUMN (x/w) is wide but whose visible words (gx/gw) are not"""
    return {**b, "gx": gx, "gw": gw, "gy": b["y"] if gy is None else gy, "gh": b["h"] if gh is None else gh}


class VisibleExtent(SimpleTestCase):
    """the first defect: the safe-zone check judged the full-width column of a text, not its words"""

    def setUp(self):
        self.p = plan({"type": "title", "duration": 5, "title": "سلام"}, platform="reels")

    def test_a_wide_column_with_centred_words_is_inside_the_safe_zone(self):
        col = box(0, "عنوانِ کوتاه", 50, 700, 962, 300, size=110)         # x 50..1012: crosses the right margin (1080 - 108)
        self.assertIn("safe_zone", codes(qa.geometry_findings(self.p, [shot([col], safe=SAFE)])))              # the old reports (no word boxes) are still judged by the column
        self.assertEqual(codes(qa.geometry_findings(self.p, [shot([glyph(col, 280, 520)], safe=SAFE)])), [])  # the words sit at 280..800: fine

    def test_words_that_really_leave_the_safe_zone_are_found_and_may_shrink(self):
        col = glyph(box(0, "عنوانِ خیلی خیلی بلند", 20, 700, 1040, 300, size=110), 20, 1040)
        out = qa.geometry_findings(self.p, [shot([col], safe=SAFE)])
        f = next(x for x in out if x["code"] == "safe_zone")
        self.assertEqual(f["ops"][0]["path"], "scenes/0/tokens/font_scale")
        self.assertLess(f["ops"][0]["value"], 1.0)

    def test_shrinking_is_not_offered_when_it_would_make_the_text_too_small(self):
        col = glyph(box(0, "عنوانِ خیلی بلند", 20, 700, 1040, 60, size=36), 20, 1040)     # 36 px x 0.85 = 1.6 % of 1920: below the readable floor
        out = qa.geometry_findings(self.p, [shot([col], safe=SAFE)])
        self.assertEqual(next(x for x in out if x["code"] == "safe_zone")["ops"], [])

    def test_overflow_judges_the_words_too(self):
        col = glyph(box(0, "کوتاه", -40, 800, 1200, 100), 300, 480)                        # a column wider than the frame, words well inside
        self.assertEqual(codes(qa.geometry_findings(self.p, [shot([col])])), [])
        self.assertIn("overflow", codes(qa.geometry_findings(self.p, [shot([glyph(box(0, "بیرون", -40, 800, 400, 100), -40, 400)])])))

    def test_overlap_uses_the_words_not_the_columns(self):
        a = glyph(box(0, "بالا", 100, 800, 900, 200), 400, 280, 800, 100)
        b = glyph(box(1, "پایین", 100, 880, 900, 200), 400, 280, 960, 100)                # the columns overlap, the words are stacked
        self.assertNotIn("overlap", codes(qa.geometry_findings(self.p, [shot([a, b])])))
        c = glyph(box(1, "روی هم", 100, 880, 900, 200), 420, 280, 820, 100)
        self.assertIn("overlap", codes(qa.geometry_findings(self.p, [shot([a, c])])))

    def test_the_vis_helper_falls_back_to_the_column(self):
        self.assertEqual(qa.vis({"x": 1, "y": 2, "w": 3, "h": 4}), {"x": 1, "y": 2, "w": 3, "h": 4})
        self.assertEqual(qa.vis({"x": 1, "y": 2, "w": 3, "h": 4, "gx": 5, "gy": 6, "gw": 7, "gh": 8}), {"x": 5, "y": 6, "w": 7, "h": 8})


class Converge(SimpleTestCase):
    """the loop never repeats a fix that did nothing, never undoes its own fix, and keeps the best plan it saw"""

    def two(self):
        return plan({"type": "kinetic_title", "duration": 5, "title": "همین حالا شروع کنید"}, {"type": "title", "duration": 5, "title": "سلام دنیا"}, platform="reels", style="sport-energy")

    def old_defect_measure(self):
        """the report of the failing run: the text COLUMN (not the words) always crosses the safe zone, whatever the font scale"""
        calls = []

        def measure(spec):
            calls.append(1)
            out = []
            for k in qa.key_frames(spec, 1):
                sc = spec["scenes"][k["scene"]]
                fs = float((sc.get("tokens") or {}).get("font_scale") or 1.0)
                out.append(shot([box(0, "تیتر", 50, 700, 962, 300, scene=k["scene"], size=110 * fs)], scene=k["scene"], kind=k["kind"], frame=k["frame"], safe=SAFE))
            return out

        measure.calls = calls
        return measure

    def test_the_failing_run_no_longer_shrinks_the_text_round_after_round(self):
        m = self.old_defect_measure()
        rep = qa.run_loop(self.two(), measure=m)
        self.assertLessEqual(len(rep["rounds"]), 2)                                   # was 3 rounds + a final check, every round the same findings
        for sc in rep["spec"]["scenes"]:
            self.assertNotIn("font_scale", sc.get("tokens") or {})                    # the pointless shrinking was not kept (was 0.61)
        self.assertFalse(any(f["code"] == "small_text" for f in rep["remaining"]))    # was: 2 small_text ERRORS made by the shrinking
        self.assertTrue(any(f.get("stuck") for f in rep["remaining"]), rep["remaining"])
        self.assertTrue(rep.get("reverted"))
        self.assertIn("بدونِ تغییر", qa.summary_fa(rep))
        self.assertLessEqual(len(m.calls), 3)

    def test_a_fix_that_changes_nothing_is_marked_and_not_repeated(self):
        f = {"code": "safe_zone", "label": "x", "severity": "warn", "scene": 0, "message": "m", "ops": [{"op": "set", "path": "scenes/0/tokens/font_scale", "value": 0.85}],
             "auto": True, "key": "k", "box": {"x": 50, "y": 700, "w": 962, "h": 300}}
        p = self.two()
        out = qa._screen(p, [f], {qa._fkey(f): qa._sig(f)}, {})
        self.assertEqual(out[0]["ops"], [])
        self.assertTrue(out[0]["stuck"])
        moved = {**f, "box": {"x": 50, "y": 700, "w": 800, "h": 300}}                  # the geometry changed: the fix worked a little, one more try is fine
        self.assertTrue(qa._screen(p, [moved], {qa._fkey(f): qa._sig(f)}, {})[0]["ops"])

    def test_a_fix_in_the_opposite_direction_of_an_earlier_one_is_refused(self):
        p = self.two()
        bigger = {"code": "small_text", "label": "x", "severity": "error", "scene": 0, "message": "m", "auto": True, "key": "k", "box": {},
                  "ops": [{"op": "set", "path": "scenes/0/tokens/font_scale", "value": 1.15}]}
        self.assertEqual(qa._screen(p, [bigger], {}, {0: -1})[0]["ops"], [])             # the loop shrank scene 0 before
        self.assertTrue(qa._screen(p, [bigger], {}, {0: 1})[0]["ops"])
        self.assertTrue(qa._screen(p, [bigger], {}, {1: -1})[0]["ops"])                  # another scene's history does not matter

    def test_a_round_that_makes_things_worse_is_not_kept(self):
        p = plan({"type": "title", "duration": 5, "title": "سلام"}, platform="reels")

        def measure(spec):
            fs = float((spec["scenes"][0].get("tokens") or {}).get("font_scale") or 1.0)
            if fs >= 1.0:
                boxes = [box(0, "عنوان", 50, 700, 962, 300, size=110)]              # one warning with a fix (the column crosses the margin)
            else:
                boxes = [box(0, "ریز", 100, 800, 300, 20, size=20), box(1, "ریزتر", 100, 900, 300, 20, size=18)]       # the "fix" made two errors
            return [shot(boxes, safe=SAFE)]

        rep = qa.run_loop(p, measure=measure)
        self.assertTrue(rep["reverted"])
        self.assertEqual(rep["fixed"], 0)
        self.assertNotIn("font_scale", (rep["spec"]["scenes"][0].get("tokens") or {}))
        self.assertTrue(all(f["severity"] != "error" for f in rep["remaining"]))

    def test_an_improving_fix_is_kept(self):
        p = plan({"type": "title", "duration": 5, "title": "سلام"}, platform="reels")

        def measure(spec):
            fs = float((spec["scenes"][0].get("tokens") or {}).get("font_scale") or 1.0)
            w = 1300 * fs
            return [shot([box(0, "عنوان", (W - w) / 2, 700, w, 300, size=110 * fs, overflow=w > 1080)])]

        rep = qa.run_loop(p, measure=measure)
        self.assertTrue(rep["ok"], rep["remaining"])
        self.assertFalse(rep.get("reverted"))
        self.assertGreaterEqual(rep["fixed"], 1)

    def test_no_new_round_starts_after_the_deadline(self):
        m = self.old_defect_measure()
        rep = qa.run_loop(self.two(), measure=m, deadline_s=0)
        self.assertTrue(rep["timed_out"])
        self.assertEqual(len(rep["rounds"]), 1)

    def test_progress_is_reported_per_phase(self):
        ev = []

        def measure(spec):
            fs = float((spec["scenes"][0].get("tokens") or {}).get("font_scale") or 1.0)
            w = 2600 * fs                                           # still too wide after three shrinks: the last round applies a fix, so the final check runs
            return [shot([box(0, "عنوان", (W - w) / 2, 700, w, 300, size=110 * fs, overflow=w > 1080)])]

        qa.run_loop(plan({"type": "title", "duration": 5, "title": "سلام"}, platform="reels"), measure=measure, on_progress=ev.append)
        phases = [e["phase"] for e in ev]
        self.assertEqual(phases[0], "measure")
        self.assertEqual(phases[1], "fix")
        self.assertEqual(phases[-1], "final")
        self.assertTrue(all(e["message"] and e["rounds"] == 3 for e in ev))
        self.assertIn("دور ۱ از ۳", ev[0]["message"])
        self.assertEqual([e["n"] for e in ev if e["phase"] == "measure"], [1, 2, 3])

    def test_a_progress_callback_that_fails_never_breaks_the_loop(self):
        def boom(_):
            raise RuntimeError("ui is gone")

        rep = qa.run_loop(plan({"type": "title", "duration": 4, "title": "سلام"}, platform="reels"), measure=None, on_progress=boom)
        self.assertTrue(rep["ok"])


class FixedColourLabel(SimpleTestCase):
    """the third defect: the white label of the CTA button on coral — the scene text colour does not reach it, the surface behind it must move"""

    def setUp(self):
        self.p = plan({"type": "title", "duration": 5, "title": "همین حالا شروع کنید"}, {"type": "cta", "duration": 4, "title": "شروع", "button": "ثبت‌نامِ رایگان", "tokens": {"accent": "#ff6b6b"}},
                      style="flat-vector", platform="reels")

    def shots(self, spec, accent):
        img = Image.new("RGB", (540, 960), accent)
        label = {**box(0, "ثبت‌نامِ رایگان", 200, 900, 600, 130, scene=1, size=64, color="rgb(255, 255, 255)"), "fixed": True}
        return [shot([label], scene=1, image=img)]

    def test_the_fix_recolours_the_button_not_the_headline(self):
        f = next(x for x in qa.geometry_findings(self.p, self.shots(self.p, (255, 107, 107))) if x["code"] == "low_contrast")
        self.assertEqual(f["scene"], 1)
        self.assertEqual(f["ops"][0]["path"], "scenes/1/tokens/accent")
        self.assertNotIn("tokens/text", json.dumps(f["ops"]))
        hexv = f["ops"][0]["value"]
        self.assertGreaterEqual(qa.contrast((255, 255, 255), qa.parse_color(hexv)), 3.0)
        fixed, applied, _ = qa.apply_fixes(self.p, [f])
        self.assertEqual(fixed["scenes"][1]["tokens"]["accent"], hexv)
        c = qa.parse_color(hexv)
        again = qa.geometry_findings(fixed, self.shots(fixed, c[:3]))
        self.assertEqual([x for x in again if x["code"] == "low_contrast"], [])

    def test_a_fixed_label_that_is_not_on_an_accent_surface_gets_no_wrong_fix(self):
        img = Image.new("RGB", (540, 960), (250, 250, 245))
        label = {**box(0, "برچسب", 200, 900, 600, 130, scene=1, size=64, color="rgb(255, 255, 255)"), "fixed": True}
        f = next(x for x in qa.geometry_findings(self.p, [shot([label], scene=1, image=img)]) if x["code"] == "low_contrast")
        self.assertEqual(f["ops"], [])

    def test_a_label_the_scene_colour_controls_still_uses_the_text_token(self):
        img = Image.new("RGB", (540, 960), (250, 250, 245))
        plain = box(0, "متنِ عادی", 200, 900, 600, 130, scene=1, size=64, color="rgb(255, 255, 255)")
        f = next(x for x in qa.geometry_findings(self.p, [shot([plain], scene=1, image=img)]) if x["code"] == "low_contrast")
        self.assertIn("tokens/", f["ops"][0]["path"])


class IncrementalMeasure(SimpleTestCase):
    """the fifth defect: every round re-rendered every frame; now only the scenes that changed are rendered again"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nm-qa-inc-"))
        self.asked: list = []

        def fake_render(job, workdir=None, cancelled=None, timeout=None, script=None):
            out = Path(job["out_dir"])
            out.mkdir(parents=True, exist_ok=True)
            shots = []
            for f in job["frames"]:
                self.asked.append(f["name"])
                img = out / f"{f['name']}.jpg"
                Image.new("RGB", (540, 960), (20, 30, 60)).save(img)
                shots.append({"name": f["name"], "frame": f["frame"], "image": str(img), "geometry": {"W": 1080, "H": 1920, "safe": {}, "platform": "", "boxes": []}})
            res = out / "results.json"
            res.write_text(json.dumps({"shots": shots}), encoding="utf-8")
            return {"results": str(res)}

        self.patches = [mock.patch.object(qa_browser, "available", return_value=(True, "")), mock.patch("apps.motion.services.materialize", return_value=({}, {})),
                        mock.patch.object(qa_browser.runner, "run_render", side_effect=fake_render)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def spec3(self, d0=4):
        return plan({"type": "title", "duration": d0, "title": "الف"}, {"type": "title", "duration": 4, "title": "ب"}, {"type": "cta", "duration": 4, "title": "ج"}, platform="reels")

    def test_signature_is_stable_for_untouched_scenes_and_changes_for_edited_ones(self):
        a, b = self.spec3(4), self.spec3(6)                       # scene 0 is longer: the later scenes start later but look the same
        ta, tb = timeline.compute(a), timeline.compute(b)
        ka, kb = qa.key_frames(a), qa.key_frames(b)
        sa = [qa.frame_signature(a, ta, f) for f in ka]
        sb = [qa.frame_signature(b, tb, f) for f in kb]
        self.assertEqual(len(sa), 6)
        self.assertEqual(sa[2:], sb[2:])                          # scenes 1 and 2
        self.assertNotEqual(sa[:2], sb[:2])
        self.assertEqual(len(set(sa)), 6)

    def test_a_frame_inside_a_transition_depends_on_the_neighbouring_scene_too(self):
        a, b = self.spec3(), self.spec3()
        b["scenes"][1]["title"] = "ب ب ب"
        ta, tb = timeline.compute(a), timeline.compute(b)
        tin = ta["tfs"][0]                                          # transition 0 -> 1
        if not tin:
            self.skipTest("this style has no transition overlap")
        f_in = {"scene": 0, "kind": "late", "frame": ta["starts"][0] + ta["frames"][0] - 1}      # the last frame of scene 0: scene 1 is already coming in
        self.assertNotEqual(qa.frame_signature(a, ta, f_in), qa.frame_signature(b, tb, f_in))
        f_mid = {"scene": 0, "kind": "enter", "frame": ta["starts"][0] + ta["frames"][0] // 2}
        self.assertEqual(qa.frame_signature(a, ta, f_mid), qa.frame_signature(b, tb, f_mid))     # in the middle of scene 0 the neighbour is not on screen

    def test_the_second_round_renders_only_what_changed(self):
        m = qa_browser.make_measure(SimpleNamespace(pk=1), workdir=self.tmp, media_dir=None, progress=lambda d: self.__dict__.setdefault("prog", []).append(d))
        shots1 = m(self.spec3(4))
        self.assertEqual(len(self.asked), 6)
        self.asked.clear()
        shots2 = m(self.spec3(6))
        self.assertEqual(len(self.asked), 2, self.asked)           # only scene 0 (its two frames)
        self.assertTrue(all("-s0-" in n for n in self.asked))
        self.assertEqual([s["scene"] for s in shots2], [0, 0, 1, 1, 2, 2])
        self.assertEqual([bool(s.get("reused")) for s in shots2], [False, False, True, True, True, True])
        self.assertEqual(shots2[2]["frame"], qa.key_frames(self.spec3(6))[2]["frame"])           # the absolute frame number is the new one
        self.asked.clear()
        m(self.spec3(6))                                            # nothing changed: the browser is not even started
        self.assertEqual(self.asked, [])
        self.assertEqual([(d["fresh"], d["cached"]) for d in self.prog], [(6, 0), (2, 4), (0, 6)])
        self.assertEqual(len(shots1), 6)

    def test_an_edited_scene_in_the_middle_is_rendered_again_with_the_right_scene_index(self):
        m = qa_browser.make_measure(SimpleNamespace(pk=1), workdir=self.tmp, media_dir=None)
        m(self.spec3())
        self.asked.clear()
        edited = self.spec3()
        edited["scenes"][1]["title"] = "ب ب ب"
        shots = m(specs.normalize_spec(edited))
        self.assertEqual(sorted(set(n.split("-")[1] for n in self.asked)), ["s1"])
        self.assertEqual([s["scene"] for s in shots], [0, 0, 1, 1, 2, 2])


class Punctuation(SimpleTestCase):
    """the sixth defect: «است.. یک» and «است.؛ متیس»"""

    def test_tidy(self):
        self.assertEqual(ai.tidy("سرور خاموش است.؛ متیس: خاموش است"), "سرور خاموش است؛ متیس: خاموش است")
        self.assertEqual(ai.tidy("«فقط لوکال» است.. یک پیش‌نویس"), "«فقط لوکال» است. یک پیش‌نویس")
        self.assertEqual(ai.tidy("الف،، ب"), "الف، ب")
        self.assertEqual(ai.tidy("می‌رسد... ادامه"), "می‌رسد... ادامه")                  # a real ellipsis stays
        self.assertEqual(ai.tidy("سلام!؛ خداحافظ"), "سلام؛ خداحافظ")

    def test_then_joins_without_doubling(self):
        self.assertEqual(ai._then("فقط لوکال است.", ". یک پیش‌نویس"), "فقط لوکال است. یک پیش‌نویس")
        self.assertEqual(ai._then("خاموش است.", "؛ با قاعده‌های ساده انجام شد."), "خاموش است؛ با قاعده‌های ساده انجام شد.")
        self.assertEqual(ai._then("خاموش است", "."), "خاموش است.")

    def _provider(self, text):
        from services.ai.priority import Failure
        from services.ai.routing import AllProvidersFailed

        exc = AllProvidersFailed(text, failures={"local": Failure("offline", "سرورِ پردازش خاموش است.", provider="local"),
                                                 "metis": Failure("policy", "سیاستِ دادهٔ این فروشگاه «فقط لوکال» است.", provider="metis")})

        class Prov:
            def generate(self, *a, **k):
                raise exc

        return Prov()

    def test_unavailable_notes_have_no_double_punctuation(self):
        store = SimpleNamespace(name="چغر", description="")
        out = ai.script_from_idea(store, "یک ویدیوی کوتاه از چغر", style="flat-vector", provider=self._provider("سرورِ پردازش خاموش است.؛ متیس: «فقط لوکال» است."), brand={})
        for bad in ("..", ".؛", "؛؛", ".،"):
            self.assertNotIn(bad, out["message"], out["message"])
        res = ai.patch_from_chat(store, plan({"type": "title", "duration": 3, "title": "الف"}), "تیتر بزرگ‌تر شود",
                                 provider=self._provider("خاموش است.؛ متیس: «فقط لوکال» است."))
        for bad in ("..", ".؛", "؛؛", ".،"):
            self.assertNotIn(bad, res["message"], res["message"])


class VoicePolicy(SimpleTestCase):
    """the second defect: an edge: voice id in the plan sent the narration to Microsoft on a «فقط لوکال» store"""

    VOICES = [{"id": "edge:fa-IR-FaridNeural", "available": False, "where": "site", "name": "فرید"},
              {"id": "piper:fa_IR-gyro", "available": True, "where": "site", "name": "Piper"}]

    def asset(self, tmp):
        wav = Path(tmp) / "a.wav"
        wav.write_bytes(b"RIFF")
        return SimpleNamespace(pk=7, status="READY", engine="piper", error=""), wav

    def run_synth(self, local_only, voice_id="edge:fa-IR-FaridNeural", voices=None):
        tmp = tempfile.mkdtemp(prefix="nm-voice-")
        self.addCleanup(shutil.rmtree, tmp, True)
        asset, wav = self.asset(tmp)
        from apps.ai.models import AudioAsset

        asset.status = AudioAsset.Status.READY
        edge = mock.Mock(return_value={"path": Path(tmp) / "e.mp3", "cues": [{"w": "سلام", "s": 0.1, "e": 0.5}]})
        with mock.patch("services.audio.engines.local_only", return_value=local_only), mock.patch.object(sound, "_edge_with_cues", edge), \
                mock.patch("services.audio.studio.voices", return_value=voices or self.VOICES), mock.patch("services.audio.studio.create_speech", return_value=asset) as cs, \
                mock.patch("services.audio.studio.sync", side_effect=lambda a: a), mock.patch("services.audio.studio.asset_path", return_value=wav):
            got = sound.default_synth(SimpleNamespace(pk=1), None, "سلام", voice_id, Path(tmp), "nar0")
        return got, edge, cs

    def test_edge_is_never_called_on_a_local_only_store(self):
        got, edge, cs = self.run_synth(local_only=True)
        edge.assert_not_called()
        self.assertEqual(got["engine"], "piper")
        self.assertEqual(got["voice"], "piper:fa_IR-gyro")
        self.assertEqual(got["note"], sound.POLICY_NOTE)
        self.assertEqual(cs.call_args.kwargs["voice_id"], "piper:fa_IR-gyro")

    def test_edge_still_works_where_the_policy_allows_it(self):
        got, edge, cs = self.run_synth(local_only=False)
        edge.assert_called_once()
        self.assertEqual(got["engine"], "edge")
        self.assertNotIn("note", got)
        cs.assert_not_called()

    def test_a_local_voice_is_never_blocked(self):
        got, edge, cs = self.run_synth(local_only=True, voice_id="piper:fa_IR-gyro")
        edge.assert_not_called()
        self.assertNotIn("note", got)

    def test_no_local_voice_available_is_an_error_not_a_leak(self):
        only_edge = [{"id": "edge:fa-IR-FaridNeural", "available": True, "where": "site", "name": "فرید"}]
        with mock.patch("services.editing.captions.node_registered", return_value=False):
            with self.assertRaises(sound.SoundError):
                self.run_synth(local_only=True, voices=only_edge)

    def test_the_helper(self):
        with mock.patch("services.audio.engines.local_only", return_value=True):
            self.assertTrue(sound._online_voice_blocked(object(), "edge:fa-IR-DilaraNeural"))
            self.assertFalse(sound._online_voice_blocked(object(), "piper:fa"))
            self.assertFalse(sound._online_voice_blocked(object(), "auto"))
        with mock.patch("services.audio.engines.local_only", return_value=False):
            self.assertFalse(sound._online_voice_blocked(object(), "edge:fa-IR-DilaraNeural"))

    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg is needed")
    def test_the_audio_report_says_which_voice_was_really_used(self):
        tmp = Path(tempfile.mkdtemp(prefix="nm-voice-prep-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        wav = tone(tmp / "v.wav", 1.2, lead=0.2, tail=0.2)
        spec = specs.normalize_spec({"style": "flat-vector", "aspect": "9:16", "platform": "reels", "audio": {"voice": {"on": True, "voice_id": "edge:fa-IR-FaridNeural"}},
                                     "scenes": [{"type": "title", "duration": 4, "title": "سلام دنیا", "narration": "سلام دنیا"}]})
        res = sound.prepare(None, None, spec, tmp / "w", synth=lambda text, vid, name: {"path": wav, "engine": "piper", "voice": "piper:fa", "note": sound.POLICY_NOTE})
        v = res["info"]["voice"]
        self.assertEqual(v["engine"], "piper")
        self.assertEqual(v["note"], sound.POLICY_NOTE)
        self.assertEqual(v["requested"], "edge:fa-IR-FaridNeural")


class PlanApi(tests_api.Base):
    """the fourth defect (a plan per visit) and the live QA state"""

    def test_the_same_untouched_draft_is_returned_not_copied(self):
        s = tests_api.spec()
        a = self.api.post(self.base + "/plans/", {"spec": s}, format="json")
        b = self.api.post(self.base + "/plans/", {"spec": s}, format="json")
        self.assertEqual(a.status_code, 201)
        self.assertEqual(b.status_code, 200)
        self.assertEqual(a.json()["plan"]["id"], b.json()["plan"]["id"])
        self.assertTrue(b.json()["reused"])
        self.assertEqual(MotionPlan.objects.filter(store=self.store).count(), 1)
        other = dict(s, scenes=[{**s["scenes"][0], "title": "عنوانِ دیگر"}])
        c = self.api.post(self.base + "/plans/", {"spec": other}, format="json")
        self.assertEqual(c.status_code, 201)
        self.assertEqual(MotionPlan.objects.filter(store=self.store).count(), 2)

    def test_an_edited_plan_is_not_reused_for_a_fresh_sample(self):
        s = tests_api.spec()
        pid = self.api.post(self.base + "/plans/", {"spec": s}, format="json").json()["plan"]["id"]
        edited = dict(s, scenes=[{**s["scenes"][0], "title": "ویرایش شد"}])
        self.api.put(f"{self.base}/plans/{pid}/", {"spec": edited}, format="json")           # rev 2
        again = self.api.post(self.base + "/plans/", {"spec": s}, format="json")
        self.assertEqual(again.status_code, 201)
        self.assertNotEqual(again.json()["plan"]["id"], pid)

    def test_the_list_has_what_the_page_needs_to_reopen_and_delete(self):
        pid = self.api.post(self.base + "/plans/", {"spec": tests_api.spec(), "title": "تیزر"}, format="json").json()["plan"]["id"]
        rows = self.api.get(self.base + "/plans/").json()["plans"]
        self.assertEqual(rows[0]["id"], pid)
        for k in ("title", "updated_at", "rev", "style", "aspect", "scenes", "renders"):
            self.assertIn(k, rows[0])
        self.assertEqual(self.api.delete(f"{self.base}/plans/{pid}/").status_code, 204)
        self.assertEqual(self.api.get(self.base + "/plans/").json()["plans"], [])

    def test_an_online_voice_on_a_local_only_store_is_warned_about_on_the_plan(self):
        s = tests_api.spec(audio={"voice": {"on": True, "voice_id": "edge:fa-IR-FaridNeural"}})
        with mock.patch("services.audio.engines.local_only", return_value=True):
            p = self.api.post(self.base + "/plans/", {"spec": s}, format="json").json()["plan"]
            self.assertEqual(p["warnings"], [sound.POLICY_NOTE])
        pid = p["id"]
        with mock.patch("services.audio.engines.local_only", return_value=False):
            self.assertEqual(self.api.get(f"{self.base}/plans/{pid}/").json()["plan"]["warnings"], [])

    def test_qa_start_state_has_progress_and_a_second_start_is_refused_until_it_goes_stale(self):
        pid = self.api.post(self.base + "/plans/", {"spec": tests_api.spec()}, format="json").json()["plan"]["id"]
        with mock.patch.object(tasks, "_run") as run:
            r = self.api.post(f"{self.base}/plans/{pid}/qa/", {}, format="json")
            self.assertEqual(r.status_code, 202)
            qa_state = r.json()["plan"]["qa"]
            self.assertEqual(qa_state["state"], "running")
            self.assertIn("progress", qa_state)
            self.assertIn("beat", qa_state)
            run.assert_called_once()
            self.assertEqual(self.api.post(f"{self.base}/plans/{pid}/qa/", {}, format="json").status_code, 409)
            old = timezone.now() - timedelta(seconds=tasks.QA_STALE_S + 60)
            plan_row = MotionPlan.objects.get(pk=pid)
            plan_row.qa = {**plan_row.qa, "beat": old.isoformat(), "started_at": old.isoformat()}
            MotionPlan.objects.filter(pk=pid).update(qa=plan_row.qa)
            self.assertEqual(self.api.post(f"{self.base}/plans/{pid}/qa/", {}, format="json").status_code, 202)

    def test_the_qa_task_publishes_progress_and_finished_rounds_while_it_runs(self):
        pid = self.api.post(self.base + "/plans/", {"spec": tests_api.spec()}, format="json").json()["plan"]["id"]
        MotionPlan.objects.filter(pk=pid).update(qa=tasks.qa_start_state())
        seen = {}

        def fake_run_qa(store, spec, *, tag, max_total, geometry, on_progress=None, on_round=None, deadline_s=None, **kw):
            on_progress({"n": 1, "rounds": 3, "phase": "frames", "message": "دور ۱ از ۳: رندرِ ۴ فریم…"})
            seen["mid1"] = MotionPlan.objects.get(pk=pid).qa
            on_round({"n": 1, "findings": [], "applied": [], "shots": []})
            seen["mid2"] = MotionPlan.objects.get(pk=pid).qa
            seen["deadline"] = deadline_s
            return {"rounds": [{"n": 1, "findings": [], "applied": [], "shots": []}], "fixed": 0, "remaining": [], "geometry": True, "spec": spec, "ok": True}

        with mock.patch("apps.motion.pipeline.run_qa", fake_run_qa):
            tasks.qa_task(pid)
        self.assertEqual(seen["mid1"]["state"], "running")
        self.assertEqual(seen["mid1"]["progress"]["phase"], "frames")
        self.assertIn("رندرِ ۴ فریم", seen["mid1"]["summary"])
        self.assertEqual(len(seen["mid2"]["rounds"]), 1)
        self.assertEqual(seen["deadline"], tasks.pipeline.QA_DEADLINE_TASK_S)
        final = MotionPlan.objects.get(pk=pid).qa
        self.assertEqual(final["state"], "done")
        self.assertIn("مشکلی پیدا نشد", final["summary"])

    def test_an_edit_during_the_check_is_not_overwritten_by_the_fixes(self):
        s = tests_api.spec()
        pid = self.api.post(self.base + "/plans/", {"spec": s}, format="json").json()["plan"]["id"]
        MotionPlan.objects.filter(pk=pid).update(qa=tasks.qa_start_state())

        def fake_run_qa(store, spec, **kw):
            edited = dict(s, scenes=[{**s["scenes"][0], "title": "ویرایشِ همزمان"}])
            self.api.put(f"{self.base}/plans/{pid}/", {"spec": edited}, format="json")          # the owner types while the check runs
            fixed = specs.normalize_spec(dict(spec, scenes=[{**spec["scenes"][0], "duration": 6}]))
            return {"rounds": [], "fixed": 1, "remaining": [], "geometry": True, "spec": fixed, "ok": True}

        with mock.patch("apps.motion.pipeline.run_qa", fake_run_qa):
            tasks.qa_task(pid)
        row = MotionPlan.objects.get(pk=pid)
        self.assertEqual(row.spec["scenes"][0]["title"], "ویرایشِ همزمان")
        self.assertNotEqual(row.spec["scenes"][0]["duration"], 6)
        self.assertIn("ویرایش شد", row.qa["summary"])
        self.assertFalse(row.qa["applied"])


class OnColor(SimpleTestCase):
    """the label colour helper the Remotion pieces use is the same rule in Python (kept in step by this table): a pale label on a mid-tone surface is never chosen"""

    @staticmethod
    def on_color(bg: str, light="#ffffff", dark="#111111") -> str:
        c = qa.parse_color(bg)[:3]
        if qa.luminance(c) > 0.42:
            return dark
        L, D = qa.contrast(qa.parse_color(light), c), qa.contrast(qa.parse_color(dark), c)
        return light if (L >= 3 or D <= L) else dark

    def test_every_surface_gets_a_label_that_reads(self):
        for bg in ("#ff6b6b", "#f4a261", "#2a9d8f", "#e76f51", "#126f85", "#163f75", "#ffbe0b", "#8338ec", "#ffffff", "#000000", "#06d6a0", "#ef476f"):
            fg = self.on_color(bg)
            self.assertGreaterEqual(qa.contrast(qa.parse_color(fg), qa.parse_color(bg)), 3.0, (bg, fg))

    def test_the_bundle_source_has_the_same_rule(self):
        src = (Path(__file__).resolve().parents[3] / "motion" / "remotion" / "src" / "util.ts").read_text(encoding="utf-8")
        self.assertIn("contrast(light, bg) >= 3", src)
        qa_src = (Path(__file__).resolve().parents[3] / "motion" / "remotion" / "src" / "qa.tsx").read_text(encoding="utf-8")
        self.assertIn("glyphRect", qa_src)
        self.assertIn("gx: g.x", qa_src)
