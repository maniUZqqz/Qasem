"""The automatic edit, second half: repeated takes, the background (keep / blur / replace), and the words that carry the owner's wishes."""
from django.test import SimpleTestCase

from services.editing import retakes
from services.editing import timeline as tl
from services.editing.director import projectops as ops
from services.editing.director.brief import parse_prompt
from services.editing.director.spec import StepError

from .tests_director import ASSETS, fake_ctx, run_tool, with_clip


def say(text: str, start: float, per: float = 0.34) -> tuple[list[dict], float]:
    """Words of a spoken phrase, one every `per` seconds; returns (words, the end time)."""
    out, t = [], start
    for w in text.split():
        out.append({"w": w, "s": round(t, 3), "e": round(t + per * 0.9, 3)})
        t += per
    return out, round(t, 3)


def talk(*parts) -> list[dict]:
    """parts: phrases (str) and pauses (float seconds), in order."""
    words, t = [], 0.3
    for p in parts:
        if isinstance(p, (int, float)):
            t += float(p)
        else:
            ws, t = say(p, t)
            words += ws
    return words


class RetakeTests(SimpleTestCase):
    def test_a_stumble_and_a_restart_cuts_the_first_try_and_keeps_the_last(self):
        words = talk("من می‌خواستم بگم", 0.7, "من می‌خواستم بگم که چغر یک برنامهٔ ورزشی است")
        found = retakes.find_retakes(words)
        self.assertEqual(len(found), 1, found)
        self.assertEqual(found[0]["text"], "من می‌خواستم بگم")
        self.assertIn("که چغر", found[0]["kept_text"])
        cut = retakes.cuts_from(found, words)
        self.assertEqual(len(cut), 1)
        kept_start = found[0]["kept_start"]
        self.assertLess(cut[0][1], kept_start, "a breath is left in front of the kept take")
        self.assertGreater(cut[0][1], kept_start - 0.3)
        self.assertLessEqual(cut[0][0], found[0]["start"])

    def test_the_same_sentence_said_twice_keeps_the_second(self):
        words = talk("امروز درباره تمرین صبحگاهی حرف می‌زنیم", 0.8, "امروز درباره تمرین صبحگاهی حرف می‌زنیم")
        found = retakes.find_retakes(words)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["kept_start"], words[6]["s"])

    def test_three_attempts_leave_only_the_last(self):
        words = talk("برنامه چغر برای", 0.6, "برنامه چغر برای تمرین", 0.6, "برنامه چغر برای تمرین در خانه است")
        found = retakes.find_retakes(words)
        self.assertEqual(len(found), 2, found)
        cuts = retakes.cuts_from(found, words)
        self.assertEqual(len(cuts), 1, "two back-to-back cuts become one")
        self.assertGreater(cuts[0][1] - cuts[0][0], 3.0)

    def test_emphasis_and_single_words_are_not_retakes(self):
        self.assertEqual(retakes.find_retakes(talk("بله", 0.6, "بله بله خیلی خوب است")), [])
        self.assertEqual(retakes.find_retakes(talk("تکرار کن", 0.6, "ادامه بده لطفاً")), [])

    def test_different_sentences_with_the_same_first_word_are_kept(self):
        words = talk("من امروز تمرین کردم", 0.7, "من فردا استراحت می‌کنم")
        self.assertEqual(retakes.find_retakes(words), [])

    def test_a_repeat_much_later_is_not_a_retake(self):
        words = talk("حالا مهم ترین نکته را بگوییم", 9.0, "حالا مهم ترین نکته را بگوییم")
        self.assertEqual(retakes.find_retakes(words), [])

    def test_a_cut_never_starts_or_ends_inside_a_word(self):
        words = talk("می‌خواستم بگم", 0.45, "می‌خواستم بگم که اینجا چه خبر است")
        found = retakes.find_retakes(words)
        for lo, hi in retakes.cuts_from(found, words):
            for w in words:
                self.assertFalse(w["s"] + 0.01 < lo < w["e"] - 0.01 or w["s"] + 0.01 < hi < w["e"] - 0.01, (lo, hi, w))

    def test_garbage_input_never_raises(self):
        self.assertEqual(retakes.find_retakes([]), [])
        self.assertEqual(retakes.find_retakes([{"w": "x"}, None, {"w": "", "s": 1, "e": 1}]), [])
        self.assertEqual(retakes.describe_fa([]), "")

    def test_the_director_tool_removes_the_first_try(self):
        words = talk("سلام به همه", 0.6, "سلام به همه دوستان خوب من", 1.0, "امروز یک برنامه تازه داریم")
        total = words[-1]["e"] + 0.5
        ctx = fake_ctx(describe=lambda ref: {**ASSETS["video:3"], "duration": total} if ref == "video:3" else ASSETS.get(ref),
                       words=lambda ref, a, b: [{**w, "s": round(w["s"] - a, 3), "e": round(w["e"] - a, 3)} for w in words if a <= w["s"] < b])
        p = with_clip("video:3", start=0, end=total)
        before = ops.project_length(p)
        p, r = run_tool(p, "remove_retakes", {"clip": "all"}, ctx=ctx)
        self.assertTrue(r["ok"], r)
        self.assertIn("دوباره", r["message"])
        self.assertLess(ops.project_length(p), before - 1.0)

    def test_the_tool_says_why_when_the_words_are_not_there(self):
        def off(ref, a, b):
            raise RuntimeError("در صف — منتظرِ روشن شدنِ سرورِ پردازش")

        _, r = run_tool(with_clip("video:3", start=0, end=20), "remove_retakes", {"clip": "all"}, ctx=fake_ctx(words=off))
        self.assertFalse(r["ok"])
        self.assertTrue(str(r["message"]).startswith("در صف"), "so the Director queues it and fills it in when the server is back")


class BackgroundToolTests(SimpleTestCase):
    LONG = {"ref": "video:50", "title": "گفتار", "kind": "video", "duration": 130.0, "has_audio": True, "width": 1920, "height": 1080}

    def ctx(self, calls=None, **kw):
        def make(ref, a, b):
            if calls is not None:
                calls.append((ref, round(a, 2), round(b, 2)))
            return {"key": f"m{len(calls or []):011d}", "s0": a, "engine": "rvm"}

        assets = {**ASSETS, "video:50": self.LONG}
        base = dict(describe=lambda ref: assets.get(ref), make_matte=make)
        base.update(kw)
        return fake_ctx(**base)

    def project(self, length=130.0):
        p, res = run_tool(ops.new_project("reel"), "add_clip", {"ref": "video:50", "track": "main", "id": "a", "start": 0, "end": length}, ctx=self.ctx())
        assert res["ok"], res
        return p

    def resolve(self, ref):
        if ref.startswith("matte:"):
            return {"path": "/tmp/matte.mp4", "s0": 0.0, "kind": "video", "has_audio": False, "duration": 60.0}
        item = {**ASSETS, "video:50": self.LONG}[ref]
        return {"path": f"/tmp/{ref.replace(':', '_')}.bin", "kind": item["kind"], "has_audio": item["has_audio"], "duration": item["duration"],
                "width": item["width"], "height": item["height"]}

    def test_keep_changes_nothing_and_asks_no_one(self):
        calls = []
        p = self.project(40)
        before = ops.project_length(p)
        p2, r = run_tool(p, "background", {"mode": "keep"}, ctx=self.ctx(calls))
        self.assertTrue(r["ok"], r)
        self.assertEqual(calls, [])
        self.assertEqual(ops.project_length(p2), before)

    def test_blur_cuts_a_long_clip_into_pieces_and_puts_the_sharp_subject_on_top(self):
        calls = []
        p, r = run_tool(self.project(), "background", {"mode": "blur", "amount": 60}, ctx=self.ctx(calls))
        self.assertTrue(r["ok"], r)
        self.assertEqual(len(calls), 3, calls)                                    # 130 s → 55 + 55 + 20
        self.assertTrue(all(b - a <= 55.01 for _, a, b in calls))
        self.assertAlmostEqual(calls[0][1], 0.0)
        main = ops.main_track(p)["clips"]
        self.assertTrue(all(c["color"]["blur"] == 60 for c in main), "the whole picture under the subject is blurred")
        overlays = [c for t in ops.video_tracks(p)[1:] for c in t["clips"]]
        self.assertEqual(len(overlays), 3)
        for fg in overlays:
            self.assertTrue(fg["matte"]["key"])
            self.assertEqual(fg["volume"], 0, "the sound stays on the original picture: nothing plays twice")
            self.assertFalse(fg.get("color", {}).get("blur"))
        self.assertAlmostEqual(sum(ops.clip_length(c) for c in main), 130.0, delta=0.2)
        line = tl.from_project(p, self.resolve)
        self.assertGreater(line.length, 120.0)

    def test_a_plain_colour_goes_between_the_picture_and_the_subject(self):
        p, r = run_tool(self.project(30), "background", {"mode": "color", "color": "#101828"}, ctx=self.ctx([]))
        self.assertTrue(r["ok"], r)
        tracks = ops.video_tracks(p)
        self.assertGreaterEqual(len(tracks), 3)
        self.assertEqual(tracks[1]["clips"][0]["shape"]["fill"], "#101828")
        self.assertTrue(tracks[2]["clips"][0]["matte"]["key"])

    def test_an_image_replaces_the_background_and_must_be_an_image(self):
        _, bad = run_tool(self.project(30), "background", {"mode": "image", "ref": "video:50"}, ctx=self.ctx([]))
        self.assertFalse(bad["ok"])
        p, r = run_tool(self.project(30), "background", {"mode": "image", "ref": "pimg:2"}, ctx=self.ctx([]))
        self.assertTrue(r["ok"], r)
        self.assertEqual(ops.video_tracks(p)[1]["clips"][0]["ref"], "pimg:2")

    def test_a_server_that_is_only_off_queues_the_step(self):
        def off(ref, a, b):
            raise StepError("در صف — منتظرِ روشن شدنِ سرورِ پردازش؛ هر وقت روشن شد خودکار انجام می‌شود.")

        start = self.project(30)
        tracks_before = [(t["id"], len(t["clips"])) for t in start["tracks"]]
        p, r = run_tool(start, "background", {"mode": "blur"}, ctx=self.ctx(make_matte=off))
        self.assertFalse(r["ok"])
        self.assertTrue(r["message"].startswith("در صف"))
        from apps.content.tasks_director import NODE_STEPS
        self.assertIn("background", NODE_STEPS)
        self.assertIn("remove_retakes", NODE_STEPS)
        self.assertEqual([(t["id"], len(t["clips"])) for t in p["tracks"]], tracks_before, "nothing half-done is left behind")
        self.assertFalse(any((c.get("color") or {}).get("blur") for c in ops.main_track(p)["clips"]))

    def test_the_words_of_the_owner_choose_the_background(self):
        self.assertEqual(parse_prompt("پس‌زمینه را محو کن")["background"], "blur")
        self.assertEqual(parse_prompt("بک‌گراند blur باشد")["background"], "blur")
        self.assertEqual(parse_prompt("پس زمینه ساده و تیره")["background"], "color")
        self.assertEqual(parse_prompt("یک ویدیوی ریلز بساز")["background"], "")


class SoftSubtitleTests(SimpleTestCase):
    PROJECT = {"tracks": [
        {"id": "v", "kind": "video", "clips": []},
        {"id": "t1", "kind": "text", "caption": True, "clips": [
            {"id": "x2", "type": "text", "text": "دوم", "at": 2.0, "duration": 1.5},
            {"id": "x1", "type": "text", "text": "سلام به همه", "at": 0.5, "duration": 1.2},
            {"id": "x3", "type": "text", "text": "  ", "at": 5, "duration": 1}]},
        {"id": "t2", "kind": "text", "clips": [{"id": "title", "type": "text", "text": "تیتر", "at": 0, "duration": 3}]}]}

    def test_only_the_caption_track_becomes_the_soft_copy_in_time_order(self):
        from services.editing import captions

        cues = captions.soft_cues(self.PROJECT)
        self.assertEqual([c["text"] for c in cues], ["سلام به همه", "دوم"])
        self.assertEqual(cues[1], {"start": 2.0, "end": 3.5, "text": "دوم"})

    def test_the_srt_file_is_utf8_with_a_bom_and_none_is_written_without_captions(self):
        import tempfile
        from pathlib import Path

        from services.editing import captions

        out = Path(tempfile.mkdtemp(prefix="nm-srt-")) / "a.srt"
        self.assertEqual(captions.write_soft_srt(self.PROJECT, out), out)
        raw = out.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        text = raw.decode("utf-8-sig")
        self.assertIn("00:00:00,500 --> 00:00:01,700", text)
        self.assertIn("سلام به همه", text)
        self.assertIsNone(captions.write_soft_srt({"tracks": []}, out.with_name("b.srt")))


    def test_captions_go_into_the_picture_unless_a_separate_file_is_asked_for(self):
        from services.editing import captions

        for export in (None, {}, {"captions": "burn"}, {"captions": "garbage"}):
            self.assertTrue(captions.burned_in(export), export)
        self.assertFalse(captions.burned_in({"captions": "soft"}))

    def test_a_soft_export_takes_only_the_caption_tracks_off_the_picture(self):
        from types import SimpleNamespace as NS

        from services.editing import captions

        tl = NS(tracks=[NS(kind="video", caption=False), NS(kind="text", caption=True), NS(kind="text", caption=False), NS(kind="audio", caption=False)])
        self.assertEqual(captions.strip_burned(tl), 1)
        self.assertEqual([(t.kind, t.caption) for t in tl.tracks], [("video", False), ("text", False), ("audio", False)], "titles and everything else stay")
        self.assertEqual(captions.strip_burned(tl), 0, "nothing left to take: a second call changes nothing")

    def test_the_project_keeps_a_valid_caption_mode_and_drops_a_bad_one(self):
        from services.editing import timeline as tl

        self.assertEqual(tl._clean_master({"export": {"captions": "soft"}})[2].get("captions"), "soft")
        self.assertEqual(tl._clean_master({"export": {"captions": "burn"}})[2].get("captions"), "burn")
        self.assertNotIn("captions", tl._clean_master({"export": {"captions": "hologram"}})[2])


PHONE_BOX = {"found": True, "x": 660, "y": 0, "w": 600, "h": 1080, "frame": [1920, 1080], "aspect": 0.5556, "portrait": True,
             "box": {"x": 0.3438, "y": 0.0, "w": 0.3125, "h": 1.0}, "bars": {"l": 0.3438, "r": 0.3438, "t": 0.0, "b": 0.0},
             "reason": "نوارِ سیاه دو طرفِ ویدیو را گرفته؛ تصویرِ واقعی ۶۰۰×۱۰۸۰ از ۱۹۲۰×۱۰۸۰ است."}


class LetterboxTests(SimpleTestCase):
    """The owner's real upload is a phone screen recorded inside a landscape frame: three quarters of every frame is black."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path

        from services.video.ffmpeg import FFMPEG

        cls.ok = bool(shutil.which(FFMPEG) or shutil.which("ffmpeg"))
        if not cls.ok:
            return
        cls.dir = Path(tempfile.mkdtemp(prefix="nm-letterbox-"))
        cls.phone = cls.dir / "phone.mp4"
        cls.full = cls.dir / "full.mp4"
        run = lambda *a: subprocess.run([FFMPEG, "-y", "-v", "error", *a], check=True, capture_output=True)       # noqa: E731
        run("-f", "lavfi", "-i", "testsrc2=s=200x360:r=12:d=6", "-vf", "pad=640:360:220:0:black", "-pix_fmt", "yuv420p", str(cls.phone))
        run("-f", "lavfi", "-i", "testsrc2=s=640x360:r=12:d=6", "-pix_fmt", "yuv420p", str(cls.full))

    def setUp(self):
        if not self.ok:
            self.skipTest("ffmpeg is not installed")

    def test_a_phone_screen_inside_a_landscape_frame_is_found(self):
        from services.editing import letterbox

        box = letterbox.detect(self.phone, 6.0)
        self.assertTrue(box["found"], box)
        self.assertTrue(box["portrait"])
        self.assertAlmostEqual(box["w"], 200, delta=6)
        self.assertEqual(box["h"], 360)
        self.assertAlmostEqual(box["x"], 220, delta=6)
        win = letterbox.window(box)
        self.assertAlmostEqual(win["cx"], 0.5, delta=0.01)
        self.assertAlmostEqual(win["w"], 200 / 640, delta=0.015)

    def test_a_full_frame_picture_has_no_bars(self):
        from services.editing import letterbox

        self.assertFalse(letterbox.detect(self.full, 6.0)["found"])

    def test_the_director_tool_cuts_to_the_content_shows_a_portrait_whole_and_later_steps_leave_it(self):
        ctx = fake_ctx(content_box=lambda ref: PHONE_BOX if ref == "video:3" else {})
        p = with_clip("video:3", start=0, end=20)
        p, r = run_tool(p, "crop_content", {"clip": "all"}, ctx=ctx)
        self.assertTrue(r["ok"], r)
        clip = ops.main_track(p)["clips"][0]
        self.assertEqual(clip["fit"], "contain")
        self.assertAlmostEqual(clip["reframe"]["w"], 0.3125)
        self.assertAlmostEqual(clip["reframe"]["cx"], 0.5, delta=0.001)
        p2, r2 = run_tool(p, "reframe", {"clip": "all", "aspect": "9:16", "follow": "auto", "compose": True}, ctx=ctx)
        self.assertTrue(r2["ok"], r2)
        self.assertEqual(ops.main_track(p2)["clips"][0]["reframe"]["w"], 0.3125, "a content window is never moved by a later reframe")
        p3, r3 = run_tool(p, "auto_look", {"clip": "all"}, ctx=fake_ctx(content_box=lambda ref: PHONE_BOX, look_stats=lambda ref, a, b: {"p5": 200, "p50": 245, "p95": 255, "clip_hi": 0.6, "faces": 0, "height": 1080}))
        self.assertIn("ضبطِ صفحه", r3["message"])
        self.assertFalse(ops.main_track(p3)["clips"][0].get("color"), "a recorded screen is not colour-graded")
        line = tl.from_project(p, lambda ref: {"path": "/tmp/x.bin", "kind": "video", "has_audio": True, "duration": 20.0, "width": 1920, "height": 1080})
        self.assertTrue(line.length > 10)

    def test_a_video_without_bars_is_left_alone(self):
        p, r = run_tool(with_clip("video:3", start=0, end=20), "crop_content", {"clip": "all"}, ctx=fake_ctx(content_box=lambda ref: {"found": False}))
        self.assertTrue(r["ok"])
        self.assertIn("دست نخورد", r["message"])
        self.assertFalse(ops.main_track(p)["clips"][0].get("reframe"))

    def test_the_polish_recipe_makes_a_vertical_video_of_a_phone_recording(self):
        from services.editing.director import loop
        from services.tests_autoedit_quality import PolishRecipeTests
        from services.tests_director import FakeAI

        t = PolishRecipeTests()
        res = loop.run("", [t.TALK], t.ctx(content_box=lambda ref: PHONE_BOX if ref == "video:9" else {}), store=None,
                       options=loop.Options(variants=1, rounds=1, use_ai=False, preview=False), call=FakeAI(fail="all"))
        self.assertEqual(res["brief"]["platform"], "reels", "a phone recording is a vertical video, not a landscape one")
        tools = [s["tool"] for s in res["variants"][0]["plan"]]
        self.assertIn("crop_content", tools)
        self.assertLess(tools.index("crop_content"), tools.index("smart_cuts"))
        self.assertNotIn("reframe", tools, "the picture already fills the frame; nothing follows a face over the bars")
        clip = ops.main_track(res["variants"][0]["project"])["clips"][0]
        self.assertTrue(clip["reframe"]["w"] < 0.4)
        # and without bars the same video is still a landscape talk
        plain = loop.run("", [t.TALK], t.ctx(), store=None, options=loop.Options(variants=1, rounds=1, use_ai=False, preview=False), call=FakeAI(fail="all"))
        self.assertEqual(plain["brief"]["platform"], "youtube")
        self.assertNotIn("crop_content", [s["tool"] for s in plain["variants"][0]["plan"]])


class SplitShotsTests(SimpleTestCase):
    """«per-shot» light and framing need the shots: the owner's video is a camera shot, then a recorded app screen."""

    def test_the_clip_is_cut_where_the_picture_changes_and_nothing_is_lost(self):
        from unittest.mock import patch

        ctx = fake_ctx(path_of=lambda ref: "/tmp/x.mp4")
        p = with_clip("video:3", start=0, end=20)
        with patch("services.editing.scenes.detect_cuts", return_value={"cuts": [7.0, 14.0]}):
            p, r = run_tool(p, "split_shots", {"clip": "main"}, ctx=ctx)
        self.assertTrue(r["ok"], r)
        main = sorted(ops.main_track(p)["clips"], key=lambda c: c["at"])
        self.assertEqual([(c["start"], c["end"]) for c in main], [(0, 7.0), (7.0, 14.0), (14.0, 20)])
        self.assertAlmostEqual(ops.project_length(p), 20.0, delta=0.01)
        self.assertIn("۳ نما", r["message"])

    def test_no_change_of_shot_means_no_cut(self):
        from unittest.mock import patch

        with patch("services.editing.scenes.detect_cuts", return_value={"cuts": []}):
            p, r = run_tool(with_clip("video:3", start=0, end=20), "split_shots", {"clip": "main"}, ctx=fake_ctx(path_of=lambda ref: "/tmp/x.mp4"))
        self.assertTrue(r["ok"])
        self.assertEqual(len(ops.main_track(p)["clips"]), 1)

    def test_real_scene_detection_finds_a_cut_in_a_two_shot_video(self):
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path

        from services.editing import scenes
        from services.video.ffmpeg import FFMPEG

        if not (shutil.which(FFMPEG) or shutil.which("ffmpeg")):
            self.skipTest("ffmpeg is not installed")
        out = Path(tempfile.mkdtemp(prefix="nm-shots-")) / "two.mp4"
        subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=12:d=3", "-f", "lavfi", "-i", "color=c=0x802020:s=320x180:r=12:d=3",
                        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0", "-pix_fmt", "yuv420p", str(out)], check=True, capture_output=True)
        cuts = scenes.detect_cuts(out, 0.0, 6.0)["cuts"]
        self.assertEqual(len(cuts), 1, cuts)
        self.assertAlmostEqual(cuts[0], 3.0, delta=0.3)
