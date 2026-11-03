"""The «دستی» workspace's timeline: what the panel's JSON becomes, the filtergraph it builds, and a few REAL ffmpeg
renders (clip sound, speed, stills, text, transitions, per-clip effects, program-wide tools in stage two).

The graph tests are string-level and fast; the render tests run the real ffmpeg on tiny synthetic clips and look at
the pixels / streams that come out — a filtergraph that merely parses proves nothing."""
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from services.editing import agent, edl
from services.editing import timeline as T
from services.video.ffmpeg import FFMPEG, probe

HAVE_FFMPEG = bool(shutil.which(FFMPEG) or shutil.which("ffmpeg"))


def project(*tracks, **fmt):
    return {"format": {"width": 320, "height": 240, "fps": 25, **fmt}, "tracks": list(tracks)}


def resolver(table):
    def resolve(ref):
        if ref not in table:
            raise T.TimelineError(f"منبع «{ref}» پیدا نشد.")
        return table[ref]
    return resolve


class FromProjectTests(SimpleTestCase):
    SRC = {
        "video:1": {"path": "a.mp4", "kind": "video", "has_audio": True, "duration": 10.0},
        "video:2": {"path": "b.mp4", "kind": "video", "has_audio": False, "duration": 6.0},
        "audio:3": {"path": "m.wav", "kind": "audio", "has_audio": True, "duration": 30.0},
        "pimg:4": {"path": "p.png", "kind": "image", "has_audio": False, "duration": 0.0},
    }

    def build(self, *tracks, **fmt):
        return T.from_project(project(*tracks, **fmt), resolver(self.SRC))

    def test_a_clip_carries_its_own_sound_and_properties(self):
        line = self.build({"kind": "video", "clips": [
            {"ref": "video:1", "at": 0, "start": 2, "end": 6, "volume": 0.5, "speed": 2, "fit": "contain",
             "fade_in": 0.5, "x": 0.1, "y": 0.1, "width": 0.5, "height": 0.5}]})
        c = line.tracks[0].clips[0]
        self.assertTrue(c.has_audio)
        self.assertEqual((c.volume, c.speed, c.fit), (0.5, 2.0, "contain"))
        self.assertEqual(c.length, 2.0)                       # ۴ ثانیه از منبع با سرعتِ ۲ برابر
        self.assertEqual(c.ends_at, 2.0)
        self.assertEqual((line.width, line.height, line.fps), (320, 240, 25))

    def test_out_of_range_values_are_clamped_and_unknown_keys_are_dropped(self):
        line = self.build({"kind": "video", "clips": [
            {"ref": "video:1", "at": -5, "start": 0, "end": 99, "volume": 99, "speed": 99, "opacity": 7, "evil": "x",
             "path": "/etc/passwd"}]})
        c = line.tracks[0].clips[0]
        self.assertEqual((c.at, c.volume, c.speed, c.opacity), (0.0, 3.0, 4.0, 1.0))
        self.assertLessEqual(c.end, 10.1)                      # از مدتِ واقعیِ منبع بیشتر نمی‌شود
        self.assertEqual(c.source, "a.mp4", "فقط ref ِ شناخته‌شده مسیر می‌دهد، نه فیلدِ path")

    def test_unknown_ref_wrong_track_and_bad_effect_are_refused_in_persian(self):
        with self.assertRaises(T.TimelineError):
            self.build({"kind": "video", "clips": [{"ref": "video:999", "at": 0}]})
        with self.assertRaises(T.TimelineError) as ctx:
            self.build({"kind": "video", "clips": [{"ref": "audio:3", "at": 0}]})
        self.assertIn("ترکِ تصویر", str(ctx.exception))
        with self.assertRaises(T.TimelineError) as ctx:
            self.build({"kind": "audio", "clips": [{"ref": "pimg:4", "at": 0, "end": 3}]})
        self.assertIn("عکس", str(ctx.exception))
        with self.assertRaises(T.TimelineError) as ctx:
            self.build({"kind": "video", "clips": [{"ref": "video:1", "at": 0, "effects": [{"tool": "cut", "params": {}}]}]})
        self.assertIn("کلِ ویدیو", str(ctx.exception))
        with self.assertRaises(T.TimelineError):
            self.build({"kind": "video", "clips": [{"ref": "video:1", "at": 0, "effects": [{"tool": "shell"}]}]})
        with self.assertRaises(T.TimelineError):
            self.build({"kind": "movie", "clips": []})
        with self.assertRaises(T.TimelineError):
            T.from_project({"tracks": []}, resolver(self.SRC))

    def test_clip_effects_are_validated_by_the_toolbox_and_clamped(self):
        line = self.build({"kind": "video", "clips": [{"ref": "video:1", "at": 0, "effects": [
            {"tool": "brightness", "params": {"amount": 9, "from_s": 3, "to_s": 4}},
            {"tool": "blur_region", "params": {"x": 10, "y": 10, "width": 30, "height": 30}}]}]})
        fx = line.tracks[0].clips[0].effects
        self.assertEqual(fx[0]["params"]["amount"], 0.4)       # در بازهٔ ابزار
        self.assertEqual(fx[0]["params"]["from_s"], -1, "پنجرهٔ زمانی روی یک قطعه معنی ندارد")
        self.assertEqual(fx[1]["tool"], "blur_region")

    def test_program_tools_are_listed_for_stage_two(self):
        ops = T.program_operations({"global_ops": [{"tool": "normalize_audio", "params": {"target": -16}},
                                                    {"tool": "fade", "params": {"where": "out"}}]})
        self.assertEqual([o["tool"] for o in ops], ["normalize_audio", "fade"])
        with self.assertRaises(T.TimelineError):
            T.program_operations({"global_ops": [{"tool": "subtitle"}]})   # زیرنویس = ترکِ متن، نه افکتِ کل


class GraphTests(SimpleTestCase):
    def line(self, *tracks):
        return T.Timeline(tracks=list(tracks), width=320, height=240, fps=25)

    def test_sound_of_video_clips_is_mixed_with_speed_fades_and_level(self):
        c = T.Clip("a.mp4", at=1.0, start=0, end=4, has_audio=True, volume=0.5, speed=2.0, fade_in=0.2, fade_out=0.3)
        _, g = T.build_filtergraph(self.line(T.Track(clips=[c])))
        self.assertIn("[0:a]atrim=0.000:4.000", g)
        self.assertIn("atempo=2", g)
        self.assertIn("afade=t=in:st=0:d=0.200", g)
        self.assertIn("afade=t=out:st=1.700:d=0.300", g)
        self.assertIn("volume=0.500", g)
        self.assertIn("adelay=1000|1000", g)
        self.assertIn("setpts=(PTS-STARTPTS)/2", g)
        self.assertIn("setpts=PTS+1.000/TB", g)
        self.assertIn("[aout]", g)
        # ویدیوی بی‌صدا یا ترکِ بی‌صدا ⇒ بی خروجیِ صدا
        _, g = T.build_filtergraph(self.line(T.Track(clips=[T.Clip("a.mp4", at=0, end=3, has_audio=True)], muted=True)))
        self.assertNotIn("[aout]", g)
        _, g = T.build_filtergraph(self.line(T.Track(clips=[T.Clip("a.mp4", at=0, end=3)])))
        self.assertNotIn("[aout]", g)

    def test_fits_effects_and_transitions(self):
        a = T.Clip("a.mp4", at=0, end=3, fit="cover", effects=[{"tool": "brightness", "params": {"amount": 0.1, "from_s": -1, "to_s": -1}},
                                                                {"tool": "rotate", "params": {"degrees": "90"}}])
        b = T.Clip("b.mp4", at=3, end=6, fit="contain", transition={"kind": "crossfade", "duration": 0.5})
        _, g = T.build_filtergraph(self.line(T.Track(clips=[a, b])))
        self.assertIn("force_original_aspect_ratio=increase,crop=320:240", g)
        self.assertIn("pad=320:240", g)
        self.assertIn("eq=brightness=0.1", g)
        self.assertLess(g.index("transpose=1"), g.index("force_original_aspect_ratio=increase"), "چرخش پیش از جا دادن")
        # گذار = پنجره‌ای دورِ برش [۲٫۷۵ تا ۳٫۲۵]: هر دو قطعه روی سیاه، xfade، و روی ترک
        self.assertIn("xfade=transition=fade:duration=0.500:offset=0", g)
        self.assertIn("between(t,2.750,3.250)", g)
        self.assertIn("between(t,0.000,2.750)", g, "قطعهٔ اول فقط تا آغازِ پنجره دیده می‌شود")
        self.assertIn("between(t,3.250,9.000)", g, "قطعهٔ دوم فقط از پایانِ پنجره")
        self.assertIn("tpad=stop_mode=clone", g, "منبعی که هندلِ بعد از برش ندارد، آخرین فریم را نگه می‌دارد")
        # fade (نه crossfade) ⇒ به سیاه و برگشت
        b2 = T.Clip("b.mp4", at=3, end=6, transition={"kind": "fade", "duration": 1.0})
        _, g = T.build_filtergraph(self.line(T.Track(clips=[T.Clip("a.mp4", at=0, end=3), b2])))
        self.assertIn("xfade=transition=fadeblack:duration=1.000", g)
        # با هندل (منبعِ بلندتر) از خودِ فیلم می‌خواند، نه از فریمِ ثابت
        a3 = T.Clip("a.mp4", at=0, start=1, end=3, src_len=10.0)
        b3 = T.Clip("b.mp4", at=2, start=2, end=5, src_len=10.0, transition={"kind": "wipeleft", "duration": 1.0})
        built = T.build_graph(self.line(T.Track(clips=[a3, b3])))
        self.assertIn("xfade=transition=wipeleft", built.graph)
        self.assertNotIn("tpad", built.graph)
        self.assertIn(["-ss", "2.500", "-t", "1.100"], built.input_args, "پایانِ قطعهٔ اول: ۰٫۵ ثانیه بعد از نقطهٔ خروج می‌خواند")

    def test_stills_text_and_the_inputs_that_go_with_them(self):
        img = T.Clip("p.png", at=0, start=0, end=4, kind="image", fit="cover")
        txt = T.TextClip("سلام ۵۰٪ تخفیف", at=1, duration=2, position="top", size=8, color="#ffcc00")
        built = T.build_graph(self.line(T.Track(clips=[img]), T.Track(kind="text", clips=[txt])))
        self.assertEqual(built.inputs, ["p.png"])
        self.assertEqual(built.input_args[0][:2], ["-loop", "1"])
        self.assertIn("ass=filename=", built.graph, "عنوان‌ها را libass می‌کشد (شکل‌دهیِ فارسی)")
        self.assertNotIn("drawtext", built.graph)
        (doc,) = built.texts.values()
        self.assertIn("سلام ۵۰٪ تخفیف", doc)
        self.assertIn("Dialogue:", doc)
        self.assertIn("0:00:01.00", doc)
        self.assertNotIn("سلام", built.graph, "متن فقط از راهِ فایل می‌رود، نه خودِ گراف")

    def test_long_text_is_wrapped_to_the_frame(self):
        wrapped = T.wrap_text("قهوهٔ تازه با تخفیفِ ویژهٔ امروز و ارسالِ رایگان برای همهٔ سفارش‌ها", 540, 960, 7)
        self.assertGreaterEqual(wrapped.count("\n"), 1)
        self.assertTrue(all(len(line) <= 14 for line in wrapped.split("\n")), wrapped)
        self.assertEqual(T.wrap_text("کوتاه", 540, 960, 7), "کوتاه")
        self.assertLessEqual(len(T.wrap_text("x " * 200, 100, 100, 20).split("\n")), 6)

    def test_validation_messages_name_the_clip(self):
        with self.assertRaises(T.TimelineError):
            self.line(T.Track(clips=[T.Clip("a.mp4", at=0, end=3, speed=9)])).validate()
        with self.assertRaises(T.TimelineError):
            self.line(T.Track(clips=[T.Clip("a.mp4", at=0, end=3, fade_in=2.5, fade_out=2.5)])).validate()
        with self.assertRaises(T.TimelineError):
            self.line(T.Track(clips=[T.Clip("a.png", at=0, kind="image")])).validate()
        with self.assertRaises(T.TimelineError):
            self.line(T.Track(clips=[T.Clip("a.mp4", at=0, end=3)]), T.Track(kind="text", clips=[T.TextClip("  ", at=0, duration=1)])).validate()


def sh(*args):
    subprocess.run(list(args), check=True, capture_output=True, stdin=subprocess.DEVNULL)


def make_clip(path, *, size="320x240", seconds=2, freq=440, audio=True, color=None):
    src = f"color=c={color}:s={size}:r=25:d={seconds}" if color else f"testsrc2=size={size}:rate=25:duration={seconds}"
    cmd = [FFMPEG, "-y", "-f", "lavfi", "-i", src]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}", "-c:a", "aac", "-shortest"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    sh(*cmd)
    return path


def stats(path):
    info = probe(path)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    a = [s for s in info["streams"] if s["codec_type"] == "audio"]
    return {"w": int(v["width"]), "h": int(v["height"]), "dur": float(info["format"]["duration"]), "audio": bool(a)}


def frame_mean(path, at, crop=None):
    """Mean luma of one frame (optionally a crop box w:h:x:y)."""
    vf = (f"crop={crop}," if crop else "") + "scale=16:16,format=gray"
    out = subprocess.run([FFMPEG, "-v", "error", "-ss", str(at), "-i", str(path), "-vf", vf, "-frames:v", "1", "-f", "rawvideo", "-"],
                         capture_output=True, stdin=subprocess.DEVNULL).stdout
    return sum(out) / max(1, len(out))


def bright_pixels(path, at, crop):
    """How many pixels of a crop are near-white (text on a mid-grey flat clip)."""
    vf = f"crop={crop},format=gray"
    out = subprocess.run([FFMPEG, "-v", "error", "-ss", str(at), "-i", str(path), "-vf", vf, "-frames:v", "1", "-f", "rawvideo", "-"],
                         capture_output=True, stdin=subprocess.DEVNULL).stdout
    return sum(1 for b in out if b > 200)


def mean_volume(path):
    r = subprocess.run([FFMPEG, "-i", str(path), "-af", "volumedetect", "-vn", "-f", "null", "-"], capture_output=True,
                       text=True, stdin=subprocess.DEVNULL)
    for line in r.stderr.splitlines():
        if "mean_volume" in line:
            return float(line.split("mean_volume:")[1].split("dB")[0])
    return -91.0


class RealRenderTests(SimpleTestCase):
    counter = 0

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not HAVE_FFMPEG:
            return
        cls.dir = Path(tempfile.mkdtemp(prefix="nm-tl-"))
        cls.a = make_clip(cls.dir / "a.mp4", seconds=3, freq=440)
        cls.b = make_clip(cls.dir / "b.mp4", seconds=3, freq=880, color="red")
        cls.mute = make_clip(cls.dir / "mute.mp4", seconds=3, audio=False)
        cls.flat = make_clip(cls.dir / "flat.mp4", seconds=3, audio=False, color="0x606060")
        cls.music = cls.dir / "m.wav"
        sh(FFMPEG, "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=6", str(cls.music))
        from PIL import Image
        cls.png = cls.dir / "logo.png"
        Image.new("RGB", (200, 200), (0, 255, 0)).save(cls.png)

    @classmethod
    def tearDownClass(cls):
        if HAVE_FFMPEG:
            shutil.rmtree(cls.dir, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        if not HAVE_FFMPEG:
            self.skipTest("ffmpeg نیست")

    def table(self):
        return {
            "v:a": {"path": str(self.a), "kind": "video", "has_audio": True, "duration": 3.0},
            "v:b": {"path": str(self.b), "kind": "video", "has_audio": True, "duration": 3.0},
            "v:m": {"path": str(self.mute), "kind": "video", "has_audio": False, "duration": 3.0},
            "v:f": {"path": str(self.flat), "kind": "video", "has_audio": False, "duration": 3.0},
            "a:m": {"path": str(self.music), "kind": "audio", "has_audio": True, "duration": 6.0},
            "i:p": {"path": str(self.png), "kind": "image", "has_audio": False, "duration": 0.0},
        }

    def render(self, *tracks, quality="draft", **fmt):
        line = T.from_project(project(*tracks, **fmt), resolver(self.table()))
        RealRenderTests.counter += 1
        out = self.dir / f"out{RealRenderTests.counter}.mp4"
        T.render(line, out, quality=quality)
        return out, line

    def test_two_clips_back_to_back_with_their_own_sound(self):
        out, line = self.render({"kind": "video", "clips": [
            {"ref": "v:a", "at": 0, "start": 0, "end": 2}, {"ref": "v:b", "at": 2, "start": 0, "end": 2}]})
        s = stats(out)
        self.assertEqual((s["w"], s["h"]), (320, 240))
        self.assertAlmostEqual(s["dur"], 4.0, delta=0.15)
        self.assertTrue(s["audio"], "صدای خودِ قطعه‌ها باید در خروجی باشد")
        self.assertGreater(mean_volume(out), -40)
        # قطعهٔ دوم قرمز است: روشنایی (خاکستری) با قطعهٔ اول فرق دارد
        self.assertNotAlmostEqual(frame_mean(out, 0.5), frame_mean(out, 3.0), delta=10)

    def test_speed_halves_the_length_and_a_muted_clip_adds_no_sound(self):
        out, _ = self.render({"kind": "video", "clips": [{"ref": "v:a", "at": 0, "start": 0, "end": 3, "speed": 2}]})
        self.assertAlmostEqual(stats(out)["dur"], 1.5, delta=0.2)
        out, _ = self.render({"kind": "video", "clips": [{"ref": "v:a", "at": 0, "start": 0, "end": 2, "audio_on": False}]})
        self.assertFalse(stats(out)["audio"])
        out, _ = self.render({"kind": "video", "clips": [{"ref": "v:m", "at": 0, "start": 0, "end": 2}]})
        self.assertFalse(stats(out)["audio"])

    def test_music_track_volume_and_track_mute(self):
        base = {"kind": "video", "clips": [{"ref": "v:m", "at": 0, "start": 0, "end": 3}]}
        loud, _ = self.render(base, {"kind": "audio", "clips": [{"ref": "a:m", "at": 0, "start": 0, "end": 3}]})
        loud_db = mean_volume(loud)
        quiet, _ = self.render(base, {"kind": "audio", "clips": [{"ref": "a:m", "at": 0, "start": 0, "end": 3, "volume": 0.25}]})
        self.assertLess(mean_volume(quiet), loud_db - 8)
        muted, _ = self.render(base, {"kind": "audio", "muted": True, "clips": [{"ref": "a:m", "at": 0, "start": 0, "end": 3}]})
        self.assertFalse(stats(muted)["audio"])

    def test_a_still_and_a_persian_text_appear_on_the_picture(self):
        base = {"kind": "video", "clips": [{"ref": "v:f", "at": 0, "start": 0, "end": 3}]}
        plain, _ = self.render(base)
        self.assertEqual(bright_pixels(plain, 1.5, "320:60:0:0"), 0)
        out, _ = self.render(base,
                             {"kind": "video", "clips": [{"ref": "i:p", "at": 1, "end": 1, "x": 0.6, "y": 0.6, "width": 0.3, "height": 0.3,
                                                          "fit": "stretch"}]},
                             {"kind": "text", "clips": [{"text": "قهوهٔ تازه ۵۰٪ تخفیف", "at": 1, "duration": 1.5, "position": "top",
                                                         "size": 12, "color": "#ffffff"}]})
        self.assertAlmostEqual(stats(out)["dur"], 3.0, delta=0.2)
        # متن (سفید روی کادرِ تیره) بالای تصویر آمده
        self.assertGreater(bright_pixels(out, 1.5, "320:60:0:0"), 150, "متنِ سفید در بالا دیده نشد")
        self.assertEqual(bright_pixels(out, 2.8, "320:60:0:0"), 0, "متن باید بعد از ۲٫۵ ثانیه برود")
        import os as _os
        if _os.environ.get("NM_KEEP_FRAMES"):
            sh(FFMPEG, "-y", "-ss", "1.5", "-i", str(out), "-frames:v", "1", _os.environ["NM_KEEP_FRAMES"])
        # عکسِ سبز در گوشهٔ پایین-راست فقط تا ثانیهٔ ۲ است
        with_img = frame_mean(out, 1.5, "60:60:230:150")
        without = frame_mean(out, 2.7, "60:60:230:150")
        self.assertNotAlmostEqual(with_img, without, delta=8)

    def test_effects_fades_and_crossfade_change_the_picture_as_asked(self):
        plain, _ = self.render({"kind": "video", "clips": [{"ref": "v:a", "at": 0, "start": 0, "end": 3}]})
        bright, _ = self.render({"kind": "video", "clips": [{"ref": "v:a", "at": 0, "start": 0, "end": 3, "effects": [
            {"tool": "brightness", "params": {"amount": 0.35}}]}]})
        self.assertGreater(frame_mean(bright, 1.0), frame_mean(plain, 1.0) + 15)
        faded, _ = self.render({"kind": "video", "clips": [{"ref": "v:a", "at": 0, "start": 0, "end": 3, "fade_out": 1.0}]})
        self.assertLess(frame_mean(faded, 2.9), frame_mean(plain, 2.9) * 0.5)
        cross, line = self.render({"kind": "video", "clips": [
            {"ref": "v:a", "at": 0, "start": 0, "end": 2}, {"ref": "v:b", "at": 2, "start": 0, "end": 2,
                                                              "transition": {"kind": "crossfade", "duration": 1.0}}]})
        a_only, b_only = frame_mean(cross, 1.5), frame_mean(cross, 3.5)
        mid = frame_mean(cross, 2.5)
        self.assertTrue(min(a_only, b_only) - 2 <= mid <= max(a_only, b_only) + 2, (a_only, mid, b_only))

    def test_stage_two_program_tools_run_over_the_finished_program(self):
        out, _ = self.render({"kind": "video", "clips": [{"ref": "v:a", "at": 0, "start": 0, "end": 3}]})
        ops = T.program_operations({"global_ops": [
            {"tool": "brightness", "params": {"amount": 0.3, "from_s": 1, "to_s": 2}},
            {"tool": "normalize_audio", "params": {"target": -16}},
            {"tool": "fade", "params": {"where": "out", "duration": 0.5}}]})
        work = self.dir / "stage2"
        plan = agent.plan(out, work, mode=agent.MANUAL, operations=ops)
        self.assertEqual([o.tool for o in plan.edl.operations], ["brightness", "normalize_audio", "fade"])
        final = self.dir / "final.mp4"
        edl.render(plan.edl, final)
        self.assertTrue(stats(final)["audio"])
        self.assertGreater(frame_mean(final, 1.5), frame_mean(out, 1.5) + 12, "روشن کردنِ بازهٔ ۱ تا ۲")
        self.assertAlmostEqual(frame_mean(final, 0.2), frame_mean(out, 0.2), delta=4)   # بیرونِ بازه دست نخورد
        self.assertLess(frame_mean(final, 2.95), frame_mean(out, 2.95) * 0.6, "محو شدنِ انتها")

    def test_proxy_of_a_big_clip_keeps_the_frame_rate_and_can_be_forced_for_small_ones(self):
        big = make_clip(self.dir / "big.mp4", size="1280x720", seconds=1, audio=False)
        proxy = T.make_proxy(big, self.dir / "big_proxy.mp4")
        s = stats(proxy)
        self.assertEqual(s["h"], T.PROXY_HEIGHT)
        with self.assertRaises(T.TimelineError):
            T.make_proxy(self.a, self.dir / "small_proxy.mp4")
        forced = T.make_proxy(self.a, self.dir / "small_proxy.mp4", force=True)
        self.assertEqual(stats(forced)["h"], 240, "اجباری: بزرگ‌تر نمی‌شود")
        self.assertEqual(probe(forced)["streams"][0]["r_frame_rate"], probe(self.a)["streams"][0]["r_frame_rate"])
