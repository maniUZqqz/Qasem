"""The «pro» timeline: keyframes, compositing (transforms, chroma key, blend, crop/mask), speed ramp / reverse / freeze,
the xfade transition library with handles, the audio mixer (solo / mute / buses / pan / EQ / ducking), export presets,
the range preview, progress and cancel.

String-level tests are fast; the render tests run the real ffmpeg on tiny synthetic clips and look at the pixels and the
loudness that come out — a filtergraph that merely parses proves nothing."""
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from django.test import SimpleTestCase

from services.editing import audiofx, compose, export, keyframes
from services.editing import timeline as T
from services.editing.errors import TimelineError
from services.tests_timeline_project import HAVE_FFMPEG, make_clip, mean_volume, project, resolver, sh, stats
from services.video.ffmpeg import FFMPEG, probe

DEVNULL = subprocess.DEVNULL


def pixel(path, at, x, y):
    out = subprocess.run([FFMPEG, "-v", "error", "-ss", str(at), "-i", str(path), "-vf", f"crop=1:1:{x}:{y},format=rgb24",
                          "-frames:v", "1", "-f", "rawvideo", "-"], capture_output=True, stdin=DEVNULL).stdout
    return tuple(out[:3]) if len(out) >= 3 else (-1, -1, -1)


def near(c, target, tol=40):
    return all(abs(a - b) <= tol for a, b in zip(c, target))


def seg_volume(path, start, length):
    r = subprocess.run([FFMPEG, "-ss", str(start), "-t", str(length), "-i", str(path), "-af", "volumedetect", "-vn", "-f", "null", "-"],
                       capture_output=True, text=True, stdin=DEVNULL)
    for line in r.stderr.splitlines():
        if "mean_volume" in line:
            return float(line.split("mean_volume:")[1].split("dB")[0])
    return -91.0


def ffexpr(expr, **variables):
    """Evaluate an ffmpeg expression made of if/lt/numbers by turning it into Python (enough for keyframes.expr)."""
    py = expr.replace("if(", "iff(")
    return eval(py, {"iff": lambda c, a, b: a if c else b, "lt": lambda a, b: 1 if a < b else 0}, variables)  # noqa: S307


class KeyframeTests(SimpleTestCase):
    KEYS = [{"t": 0.0, "v": 0.0, "e": "ease_in"}, {"t": 1.0, "v": 1.0, "e": "ease_out"}, {"t": 2.0, "v": 0.2, "e": "ease_in_out"},
            {"t": 3.0, "v": 0.8, "e": "hold"}, {"t": 4.0, "v": 0.1, "e": "linear"}]

    def test_easings_and_edges(self):
        self.assertAlmostEqual(keyframes.ease("linear", 0.5), 0.5)
        self.assertAlmostEqual(keyframes.ease("ease_in", 0.5), 0.25)
        self.assertAlmostEqual(keyframes.ease("ease_out", 0.5), 0.75)
        self.assertAlmostEqual(keyframes.ease("ease_in_out", 0.5), 0.5)
        self.assertEqual(keyframes.ease("hold", 0.99), 0.0)
        self.assertEqual(keyframes.ease("linear", 7), 1.0)
        self.assertEqual(keyframes.value_at(self.KEYS, -1, 9), 0.0, "before the first key: its value")
        self.assertEqual(keyframes.value_at(self.KEYS, 9, 9), 0.1, "after the last key: its value")
        self.assertEqual(keyframes.value_at([], 1, 5), 5, "no keys: the static value")
        self.assertEqual(keyframes.value_at(self.KEYS, 3.5, 0), 0.8, "hold keeps the value until the next key")

    def test_the_ffmpeg_expression_equals_value_at(self):
        expr = keyframes.expr(self.KEYS, 0.0, "t")
        for t in (-0.5, 0, 0.3, 0.99, 1.0, 1.5, 2.2, 2.9, 3.0, 3.7, 4.0, 6.0):
            self.assertAlmostEqual(ffexpr(expr, t=t), keyframes.value_at(self.KEYS, t, 0.0), places=3, msg=f"t={t}")
        shifted = keyframes.expr(self.KEYS, 0.0, "(t-3.2)")
        self.assertAlmostEqual(ffexpr(shifted, t=4.2), keyframes.value_at(self.KEYS, 1.0, 0.0), places=3)
        self.assertEqual(keyframes.expr([], 0.5), "0.5")
        self.assertEqual(keyframes.expr([{"t": 1, "v": 2, "e": "linear"}], 0.5), "2")

    def test_clean_keys_sorts_clamps_dedupes_and_caps(self):
        raw = [{"t": 2, "v": 9, "e": "bogus"}, {"t": 1, "v": -9}, {"t": 1.0004, "v": 0.5}, "x", {"t": "a", "v": 1}, {"t": 3, "v": float("nan")}]
        keys = keyframes.clean_keys(raw, 0, 1)
        self.assertEqual([(k["t"], k["v"], k["e"]) for k in keys], [(1.0, 0.5, "linear"), (2.0, 1.0, "linear")])
        many = [{"t": i, "v": 0.5} for i in range(100)]
        self.assertEqual(len(keyframes.clean_keys(many, 0, 1)), keyframes.MAX_KEYS)

    def test_slicing_a_clip_keeps_the_exact_values_at_the_cut(self):
        part = keyframes.sliced(self.KEYS, 0.5, 2.5)
        for t in (0.0, 0.4, 0.5, 1.0, 1.5, 2.0):
            self.assertAlmostEqual(keyframes.value_at(part, t, 0), keyframes.value_at(self.KEYS, t + 0.5, 0), delta=0.01, msg=t)


class ProjectProTests(SimpleTestCase):
    SRC = {
        "v": {"path": "a.mp4", "kind": "video", "has_audio": True, "duration": 10.0},
        "m": {"path": "m.wav", "kind": "audio", "has_audio": True, "duration": 30.0},
    }

    TOP = ("markers", "inout", "master", "ducking", "export")

    def build(self, *tracks, **extra):
        top = {k: extra.pop(k) for k in self.TOP if k in extra}
        data = project(*tracks, **extra)
        data.update(top)
        return T.from_project(data, resolver(self.SRC))

    def clip(self, **kw):
        return self.build({"kind": "video", "clips": [{"ref": "v", "at": 0, "start": 0, "end": 4, **kw}]}).tracks[0].clips[0]

    def test_pro_fields_are_clamped_and_defaults_stay_plain(self):
        plain = self.clip()
        self.assertEqual((plain.rot, plain.scale, plain.px, plain.blend, plain.kf, plain.chroma, plain.color, plain.ramp), (0.0, 1.0, 0.0, "normal", {}, {}, {}, []))
        c = self.clip(rot=999, scale=99, px=9, blend="evil", crop={"l": 0.9, "r": 0.9}, kf={"scale": [{"t": 2, "v": 50}, {"t": 1, "v": 0.001}],
                      "nope": [{"t": 1, "v": 1}]}, chroma={"on": True, "color": "red", "similarity": 9, "blend": -1, "spill": 5},
                      color={"exposure": 99, "look": "nonexistent"}, ramp=[{"p": 0, "v": 99}, {"p": 1, "v": 0.001}, {"p": 0.5, "v": 1}],
                      mask={"shape": "ellipse", "w": 9, "feather": 9}, audio={"eq": "evil", "pan": 9, "comp": 9})
        self.assertEqual((c.rot, c.scale, c.px, c.blend), (360.0, 8.0, 2.0, "normal"))
        self.assertLessEqual(c.crop["l"] + c.crop["r"], 0.981)
        self.assertEqual([(k["t"], k["v"]) for k in c.kf["scale"]], [(1.0, 0.05), (2.0, 8.0)])
        self.assertNotIn("nope", c.kf)
        self.assertEqual((c.chroma["color"], c.chroma["similarity"], c.chroma["blend"], c.chroma["spill"]), ("#00ff00", 0.8, 0.0, 1.0))
        self.assertEqual(c.color["exposure"], 3.0)
        self.assertEqual(c.color["look"], "")
        self.assertEqual([r["v"] for r in c.ramp], [8.0, 1.0, 0.1], "sorted by p, speeds clamped to 0.1..8")
        self.assertEqual((c.mask["w"], c.mask["feather"]), (1.0, 0.5))
        self.assertEqual(c.audio, {"pan": 1.0, "comp": 1.0})
        self.assertEqual(self.clip(ramp=[{"p": 0, "v": 2}]).ramp, [], "one key is not a ramp")

    def test_tracks_markers_master_and_ducking_are_read(self):
        line = self.build({"kind": "video", "role": "speech", "solo": True, "gain_db": -99, "pan": 7, "clips": [{"ref": "v", "at": 0, "end": 2}]},
                          {"kind": "audio", "role": "bogus", "clips": []},
                          markers=[{"id": "m1", "t": 3, "label": "x", "color": "zz", "kind": "beat"}, {"t": -4}],
                          inout={"in": 5, "out": 2}, master={"gain_db": 99, "limiter": False},
                          ducking={"on": True, "amount_db": 99, "attack_ms": 1}, export={"preset": "reels", "evil": 1})
        t0, t1 = line.tracks
        self.assertEqual((t0.role, t0.solo, t0.gain_db, t0.pan, t1.role), ("speech", True, -40.0, 1.0, ""))
        self.assertEqual([(m["t"], m["color"], m["kind"]) for m in line.markers], [(3.0, "#ffcc00", "beat"), (0.0, "#ffcc00", "marker")])
        self.assertIsNone(line.inout, "out before in is dropped")
        self.assertEqual((line.master["gain_db"], line.master["limiter"]), (12.0, False))
        self.assertEqual((line.ducking["on"], line.ducking["amount_db"], line.ducking["attack_ms"]), (True, 30.0, 5.0))
        self.assertEqual(line.export, {"preset": "reels"})

    def test_clip_length_follows_speed_ramp_freeze_and_stills(self):
        self.assertAlmostEqual(self.clip(speed=2).length, 2.0)
        flat = self.clip(ramp=[{"p": 0, "v": 2}, {"p": 1, "v": 2}])
        self.assertAlmostEqual(flat.length, 2.0, places=3)
        slow_fast = self.clip(ramp=[{"p": 0, "v": 1}, {"p": 1, "v": 4}])
        self.assertTrue(1.4 < slow_fast.length < 3.0, slow_fast.length)
        self.assertEqual(sum(1 for _ in slow_fast.segments()), T.RAMP_STEPS)
        self.assertAlmostEqual(sum((b - a) / v for a, b, v in slow_fast.segments()), slow_fast.length)
        self.assertAlmostEqual(self.clip(freeze=True, start=1, end=3.5).length, 2.5)

    def test_window_cuts_clips_keyframes_fades_and_text(self):
        line = self.build({"kind": "video", "clips": [{"ref": "v", "at": 2, "start": 1, "end": 7, "speed": 2, "fade_in": 0.5, "fade_out": 0.5,
                                                       "kf": {"opacity": [{"t": 0, "v": 0}, {"t": 3, "v": 1}]}}]},
                          {"kind": "text", "clips": [{"text": "سلام", "at": 3, "duration": 2, "words": [{"w": "الف", "s": 0, "e": 0.5}, {"w": "ب", "s": 1, "e": 1.5}]}]})
        part = T.window(line, 3.0, 4.2)
        c = part.tracks[0].clips[0]
        self.assertAlmostEqual(c.at, 0.0)
        self.assertAlmostEqual(c.start, 3.0)              # one second in at speed 2 = two source seconds
        self.assertAlmostEqual(c.end, 5.4)
        self.assertEqual((c.fade_in, c.fade_out), (0.0, 0.0), "the fades belong to the real edges")
        self.assertAlmostEqual(keyframes.value_at(c.kf["opacity"], 0.0, 0), 1 / 3, places=2)
        txt = part.tracks[1].clips[0]
        self.assertAlmostEqual(txt.at, 0.0)
        self.assertAlmostEqual(txt.duration, 1.2)
        self.assertEqual([w["w"] for w in txt.spec["words"]], ["الف", "ب"])
        ramped = self.build({"kind": "video", "clips": [{"ref": "v", "at": 0, "start": 0, "end": 4, "ramp": [{"p": 0, "v": 1}, {"p": 1, "v": 4}]}]})
        full = ramped.tracks[0].clips[0].length
        cut = T.window(ramped, 0.5, full - 0.5).tracks[0].clips[0]
        self.assertAlmostEqual(cut.length, full - 1.0, places=2, msg="a ramped clip is cut by its segments")
        rev = self.build({"kind": "video", "clips": [{"ref": "v", "at": 0, "start": 0, "end": 4, "reverse": True}]})
        r = T.window(rev, 0, 1).tracks[0].clips[0]
        self.assertAlmostEqual((r.start, r.end), (3.0, 4.0), msg="the first second of a reversed clip is the LAST source second")

    def test_reverse_is_bounded_by_memory(self):
        big = self.build({"kind": "video", "clips": [{"ref": "v", "at": 0, "start": 0, "end": 10, "reverse": True}]}, width=1080, height=1920, fps=30)
        with self.assertRaises(TimelineError) as ctx:
            big.validate()
        self.assertIn("وارونه", str(ctx.exception))
        small = self.build({"kind": "video", "clips": [{"ref": "v", "at": 0, "start": 0, "end": 4, "reverse": True}]})
        small.validate()


class GraphProTests(SimpleTestCase):
    def line(self, *tracks, **kw):
        return T.Timeline(tracks=list(tracks), width=320, height=240, fps=25, **kw)

    def test_layer_filters_for_every_pro_feature(self):
        clip = T.Clip("a.mp4", at=1, start=0, end=4, width=0.5, height=0.5, x=0.25, y=0.25, rot=20, scale=1.5, blend="multiply",
                      chroma={"on": True, "color": "#00ff00", "similarity": 0.2, "blend": 0.1, "spill": 0.5}, crop={"l": 0.1},
                      mask={"shape": "ellipse", "cx": 0.5, "cy": 0.5, "w": 0.5, "h": 0.5, "feather": 0.1, "invert": False},
                      kf={"px": [{"t": 0, "v": 0, "e": "linear"}, {"t": 2, "v": 0.2, "e": "ease_out"}]}, flip_h=True,
                      color={"contrast": 30})
        base = T.Clip("b.mp4", at=0, start=0, end=5)
        g = compose.build_graph(self.line(T.Track(clips=[base]), T.Track(clips=[clip]))).graph
        for needle in ("hflip", "chromakey=color=0x00ff00:similarity=0.2:blend=0.1", "despill=type=green", "curves=interp=pchip", "geq=lum=", "alphamerge",
                       "rotate=a='(20)*PI/180'", "scale=w='max(2,trunc(iw*1.5/2)*2)'", "color=c=white:s=320x240", "blend=all_mode=multiply"):
            self.assertIn(needle, g, needle)
        self.assertIn("x='320*(0.5+if(lt(", g, "centre-based position with the keyframed offset")
        self.assertIn("-w/2'", g)

    def test_animated_scale_uses_a_per_frame_expression_and_stays_inside_the_cap(self):
        clip = T.Clip("a.mp4", at=0, end=3, kf={"scale": [{"t": 0, "v": 1, "e": "linear"}, {"t": 3, "v": 8, "e": "linear"}]})
        g = compose.build_graph(self.line(T.Track(clips=[clip]))).graph
        self.assertIn("eval=frame", g)
        # a full-frame layer may grow at most 3x (memory): the key of 8 is clamped to 3, so the segment rises by 2, not 7
        self.assertIn("1+(2)*", g)
        self.assertNotIn("(7)*", g)

    def test_ramp_reverse_freeze_filters(self):
        ramp = T.Clip("a.mp4", at=0, start=0, end=4, ramp=[{"p": 0, "v": 1}, {"p": 1, "v": 3}], has_audio=True)
        g = compose.build_graph(self.line(T.Track(clips=[ramp]))).graph
        self.assertIn(f"split={T.RAMP_STEPS}", g)
        self.assertIn(f"concat=n={T.RAMP_STEPS}:v=1:a=0", g)
        self.assertIn(f"asplit={T.RAMP_STEPS}", g, "the sound follows the same steps")
        self.assertIn(f"concat=n={T.RAMP_STEPS}:v=0:a=1", g)
        rev = T.Clip("a.mp4", at=0, start=0, end=2, reverse=True, has_audio=True)
        g = compose.build_graph(self.line(T.Track(clips=[rev]))).graph
        self.assertIn("reverse,", g)
        self.assertIn("areverse", g)
        frozen = T.Clip("a.mp4", at=0, start=1.5, end=3.5, freeze=True, has_audio=True)
        built = compose.build_graph(self.line(T.Track(clips=[frozen])))
        self.assertIn("trim=start_frame=0:end_frame=1", built.graph)
        self.assertIn("tpad=stop_mode=clone", built.graph)
        self.assertFalse(built.has_audio, "a frozen frame has no sound")
        self.assertEqual(built.input_args[0], ["-ss", "1.500", "-t", "1.000"], "only one frame is read")

    def test_transition_window_uses_handles_and_holds_when_the_source_ends(self):
        a = T.Clip("a.mp4", at=0, start=1, end=3, src_len=10.0)
        b = T.Clip("b.mp4", at=2, start=0, end=3, src_len=3.0, transition={"kind": "wipeleft", "duration": 1.0})
        built = compose.build_graph(self.line(T.Track(clips=[a, b])))
        self.assertIn("xfade=transition=wipeleft:duration=1.000:offset=0", built.graph)
        self.assertIn(["-ss", "2.500", "-t", "1.100"], built.input_args, "the out-handle: 0.5 s after the out point")
        self.assertIn("tpad=start_mode=clone:start_duration=0.500", built.graph, "no footage before the in point: the first frame is held")
        self.assertIn("between(t,1.500,2.500)", built.graph)
        self.assertIn("between(t,2.500,5.000)", built.graph)
        legacy = T.Clip("b.mp4", at=2, start=0, end=3, transition={"kind": "fade", "duration": 1.0})
        self.assertIn("xfade=transition=fadeblack", compose.build_graph(self.line(T.Track(clips=[a, legacy]))).graph)
        far = T.Clip("b.mp4", at=2.6, start=0, end=3, transition={"kind": "wipeleft", "duration": 1.0})
        self.assertNotIn("xfade", compose.build_graph(self.line(T.Track(clips=[a, far]))).graph, "clips that do not touch have no transition")

    def test_audio_graph_mixer_buses_and_master(self):
        voice = T.Clip("v.mp4", at=0, start=0, end=4, has_audio=True, audio={"eq": "voice", "comp": 0.5, "pan": -0.5, "normalize": True})
        music = T.Clip("m.wav", at=0, start=0, end=4, kind="audio", kf={"volume": [{"t": 0, "v": 1, "e": "linear"}, {"t": 2, "v": 0.2, "e": "linear"}]})
        vt = T.Track(clips=[voice], role="speech", gain_db=-3, pan=0.4)
        mt = T.Track(kind="audio", clips=[music], role="music")
        line = self.line(vt, mt, master={"gain_db": -2.0, "limiter": True})
        g = compose.build_graph(line).graph
        for needle in ("equalizer=f=3000", "acompressor=threshold=0.150", "pan=stereo|c0=1.000*c0|c1=0.500*c1", "loudnorm=I=-16", "volume=-3.00dB",
                       "volume=eval=frame:volume='(", "volume=-2.00dB,alimiter=limit=0.95[aout]"):
            self.assertIn(needle, g, needle)
        solo = self.line(T.Track(clips=[voice]), T.Track(kind="audio", clips=[music], solo=True))
        self.assertNotIn("[0:a]", compose.build_graph(solo).graph, "solo: the other track is not mixed")
        muted = self.line(T.Track(clips=[voice], muted=True), T.Track(kind="audio", clips=[music], muted=True))
        self.assertFalse(compose.build_graph(muted).has_audio)
        no_limit = self.line(T.Track(clips=[voice]), master={"gain_db": 0.0, "limiter": False})
        self.assertNotIn("alimiter", compose.build_graph(no_limit).graph)

    def test_ducking_curve_in_ffmpeg_equals_the_python_curve(self):
        spans = [(1.0, 2.0), (4.0, 4.5)]
        expr = audiofx.duck_gain_expr(spans, 12, 0.05, 0.4)
        for t in (0, 0.9, 0.96, 1.0, 1.5, 2.0, 2.2, 2.45, 3.0, 3.97, 4.2, 4.5, 4.8, 5.5):
            self.assertAlmostEqual(_eval_duck(expr, t), audiofx.duck_gain_at(spans, 12, 0.05, 0.4, t), places=3, msg=t)
        self.assertAlmostEqual(audiofx.duck_gain_at(spans, 12, 0.05, 0.4, 1.5), 10 ** (-12 / 20), places=4)
        self.assertEqual(audiofx.duck_gain_at([], 12, 0.05, 0.4, 1.0), 1.0)

    def test_speech_spans_follow_speed_and_reverse(self):
        c = T.Clip("v.mp4", at=10, start=2, end=6, speed=2.0)
        self.assertAlmostEqual(audiofx.src_to_timeline(c, 2), 10.0)
        self.assertAlmostEqual(audiofx.src_to_timeline(c, 4), 11.0)
        self.assertAlmostEqual(audiofx.src_to_timeline(c, 99), 12.0)
        r = T.Clip("v.mp4", at=10, start=2, end=6, reverse=True)
        self.assertAlmostEqual(audiofx.src_to_timeline(r, 6), 10.0, msg="the last source second is the first on the timeline")
        self.assertAlmostEqual(audiofx.src_to_timeline(r, 2), 14.0)

    def test_ducking_graph_is_built_from_injected_speech_spans(self):
        voice = T.Clip("v.mp4", at=0, start=0, end=6, has_audio=True)
        music = T.Clip("m.wav", at=0, start=0, end=6, kind="audio")
        line = self.line(T.Track(clips=[voice], role="speech"), T.Track(kind="audio", clips=[music], role="music"),
                         ducking={"on": True, "amount_db": 12.0, "threshold": 0.04, "attack_ms": 40.0, "release_ms": 500.0})
        built = compose.build_graph(line, spans=lambda path: [[1.0, 2.0], [4.0, 5.0]])
        self.assertIn("volume=eval=frame:volume='1-0.7", built.graph)
        none = compose.build_graph(line, spans=lambda path: [])
        self.assertIn("گفتاری", " ".join(none.notes))
        self.assertNotIn("volume=eval=frame:volume='1-", none.graph)

        def boom(path):
            raise TimelineError("خراب")
        broken = compose.build_graph(line, spans=boom)
        self.assertTrue(broken.notes, "an analysis failure becomes a note, not a failed render")


def _eval_duck(expr, t):
    env = {"t": t, "min": min, "max": max, "clip": lambda v, a, b: max(a, min(b, v))}
    return eval(expr, {}, env)  # noqa: S307


class RealProRenderTests(SimpleTestCase):
    counter = 0

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not HAVE_FFMPEG:
            return
        cls.dir = Path(tempfile.mkdtemp(prefix="nm-pro-"))
        cls.red = make_clip(cls.dir / "red.mp4", seconds=4, audio=False, color="red")
        cls.blue = make_clip(cls.dir / "blue.mp4", seconds=4, audio=False, color="blue")
        cls.gray = make_clip(cls.dir / "gray.mp4", seconds=4, audio=False, color="0x808080")
        cls.green = cls.dir / "green.mp4"        # a green screen with a red box in the middle
        sh(FFMPEG, "-y", "-f", "lavfi", "-i", "color=c=0x00b140:s=320x240:r=25:d=4", "-vf", "drawbox=x=100:y=80:w=120:h=80:color=0xd02020:t=fill",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", str(cls.green))
        cls.redblue = cls.dir / "redblue.mp4"    # one second red, then one second blue
        sh(FFMPEG, "-y", "-f", "lavfi", "-i", "color=c=red:s=320x240:r=25:d=1", "-f", "lavfi", "-i", "color=c=blue:s=320x240:r=25:d=1",
           "-filter_complex", "[0][1]concat=n=2:v=1:a=0", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(cls.redblue))
        cls.tone = cls.dir / "tone.wav"
        sh(FFMPEG, "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=6", str(cls.tone))
        cls.bass = cls.dir / "bass.wav"
        sh(FFMPEG, "-y", "-f", "lavfi", "-i", "sine=frequency=100:duration=3", str(cls.bass))
        cls.speech = make_clip(cls.dir / "speech.mp4", seconds=6, audio=True, color="0x303030", freq=300)

    @classmethod
    def tearDownClass(cls):
        if HAVE_FFMPEG:
            shutil.rmtree(cls.dir, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        if not HAVE_FFMPEG:
            self.skipTest("ffmpeg نیست")

    def table(self):
        d = lambda p, **kw: {"path": str(p), "kind": "video", "has_audio": False, "duration": 4.0, **kw}  # noqa: E731
        return {"red": d(self.red), "blue": d(self.blue), "gray": d(self.gray), "green": d(self.green), "rb": d(self.redblue, duration=2.0),
                "tone": {"path": str(self.tone), "kind": "audio", "has_audio": True, "duration": 6.0},
                "bass": {"path": str(self.bass), "kind": "audio", "has_audio": True, "duration": 3.0},
                "speech": {"path": str(self.speech), "kind": "video", "has_audio": True, "duration": 6.0}}

    def render(self, *tracks, spans=None, **fmt):
        extra = {k: fmt.pop(k) for k in ("ducking", "master", "export") if k in fmt}
        data = project(*tracks, **fmt)
        data.update(extra)
        line = T.from_project(data, resolver(self.table()))
        RealProRenderTests.counter += 1
        out = self.dir / f"o{RealProRenderTests.counter}.mp4"
        export.render(line, out, quality="draft", spans=spans)
        return out, line

    def clip(self, ref, at=0, start=0, end=3, **kw):
        return {"ref": ref, "at": at, "start": start, "end": end, **kw}

    # ----------------------------------------------------------- compositing
    def test_keyframed_position_moves_the_layer_and_opacity_fades_it_in(self):
        pip = self.clip("red", end=2, x=0.35, y=0.35, width=0.3, height=0.3, fit="stretch",
                        kf={"px": [{"t": 0, "v": -0.3, "e": "linear"}, {"t": 2, "v": 0.3, "e": "linear"}],
                            "opacity": [{"t": 0, "v": 0, "e": "linear"}, {"t": 1, "v": 1, "e": "linear"}]})
        out, _ = self.render({"kind": "video", "clips": [self.clip("blue", end=2)]}, {"kind": "video", "clips": [pip]})
        # frame 4 of 25 (t=0.16): the layer is at the left, nearly transparent; t=1.8: at the right, opaque
        self.assertTrue(near(pixel(out, 1.0, 160, 120), (255, 0, 0), 60), "at t=1 the layer is at the centre, opaque")
        self.assertTrue(near(pixel(out, 1.9, 270, 120), (255, 0, 0), 60), pixel(out, 1.9, 270, 120))
        self.assertTrue(near(pixel(out, 1.9, 50, 120), (0, 0, 255), 40), "the layer left the left side")
        left = pixel(out, 0.1, 50, 120)
        self.assertTrue(left[2] > 150 and left[0] < 120, f"opacity 0 at the start keeps the base visible: {left}")

    def test_scale_and_rotation_are_applied_around_the_centre(self):
        pip = self.clip("red", end=2, x=0.4, y=0.4, width=0.2, height=0.2, fit="stretch", scale=3.0)
        out, _ = self.render({"kind": "video", "clips": [self.clip("blue", end=2)]}, {"kind": "video", "clips": [pip]})
        self.assertTrue(near(pixel(out, 1.0, 160 - 40, 120), (255, 0, 0), 50), "3x of a 64 px box is 192 px: reaches 40 px left of the centre")
        self.assertTrue(near(pixel(out, 1.0, 10, 10), (0, 0, 255), 40))
        rot = self.clip("red", end=2, x=0.4, y=0.4, width=0.2, height=0.1, fit="stretch", rot=90, scale=2.0)
        out, _ = self.render({"kind": "video", "clips": [self.clip("blue", end=2)]}, {"kind": "video", "clips": [rot]})
        # a wide box turned by 90° becomes tall: red above the centre, blue left of it
        self.assertTrue(near(pixel(out, 1.0, 160, 120 - 40), (255, 0, 0), 60), pixel(out, 1.0, 160, 80))
        self.assertTrue(near(pixel(out, 1.0, 160 - 50, 120), (0, 0, 255), 60))

    def test_chroma_key_removes_the_screen_and_keeps_the_subject(self):
        keyed = self.clip("green", end=2, chroma={"on": True, "color": "#00b140", "similarity": 0.2, "blend": 0.1, "spill": 0.3}, fit="stretch")
        out, _ = self.render({"kind": "video", "clips": [self.clip("blue", end=2)]}, {"kind": "video", "clips": [keyed]})
        self.assertTrue(near(pixel(out, 1.0, 20, 20), (0, 0, 255), 40), f"the green screen is gone: {pixel(out, 1.0, 20, 20)}")
        self.assertTrue(near(pixel(out, 1.0, 160, 120), (208, 32, 32), 60), "the red subject stays")
        plain = self.clip("green", end=2, fit="stretch")
        out, _ = self.render({"kind": "video", "clips": [self.clip("blue", end=2)]}, {"kind": "video", "clips": [plain]})
        self.assertTrue(pixel(out, 1.0, 20, 20)[1] > 120, "without the key the screen stays green")

    def test_blend_multiply_crop_and_masks(self):
        mult = self.clip("red", end=2, x=0.25, y=0.25, width=0.5, height=0.5, fit="stretch", blend="multiply")
        out, _ = self.render({"kind": "video", "clips": [self.clip("gray", end=2)]}, {"kind": "video", "clips": [mult]})
        centre, corner = pixel(out, 1.0, 160, 120), pixel(out, 1.0, 10, 10)
        self.assertTrue(centre[1] < 40 and 90 < centre[0] < 150, f"multiply: red x gray = dark red, got {centre}")
        self.assertTrue(near(corner, (128, 128, 128), 20), f"outside the layer nothing changes: {corner}")
        crop = self.clip("red", end=2, fit="stretch", crop={"l": 0.5})
        out, _ = self.render({"kind": "video", "clips": [self.clip("blue", end=2)]}, {"kind": "video", "clips": [crop]})
        self.assertTrue(near(pixel(out, 1.0, 60, 120), (0, 0, 255), 40), "cropped half shows the base")
        self.assertTrue(near(pixel(out, 1.0, 260, 120), (255, 0, 0), 40))
        mask = self.clip("red", end=2, fit="stretch", mask={"shape": "ellipse", "cx": 0.5, "cy": 0.5, "w": 0.5, "h": 0.5, "feather": 0.0, "invert": False})
        out, _ = self.render({"kind": "video", "clips": [self.clip("blue", end=2)]}, {"kind": "video", "clips": [mask]})
        self.assertTrue(near(pixel(out, 1.0, 160, 120), (255, 0, 0), 40))
        self.assertTrue(near(pixel(out, 1.0, 10, 10), (0, 0, 255), 40), "an ellipse leaves the corners")
        inv = dict(mask, mask=dict(mask["mask"], invert=True))
        out, _ = self.render({"kind": "video", "clips": [self.clip("blue", end=2)]}, {"kind": "video", "clips": [inv]})
        self.assertTrue(near(pixel(out, 1.0, 160, 120), (0, 0, 255), 40), "an inverted mask cuts the hole")
        self.assertTrue(near(pixel(out, 1.0, 10, 10), (255, 0, 0), 40))

    def test_colour_block_changes_the_picture(self):
        grey = self.clip("gray", end=2, color={"exposure": 1.0})
        out, _ = self.render({"kind": "video", "clips": [grey]})
        self.assertGreater(pixel(out, 1.0, 100, 100)[0], 170, "one stop up")
        bw = self.clip("red", end=2, color={"saturation": 0})
        out, _ = self.render({"kind": "video", "clips": [bw]})
        r, g, b = pixel(out, 1.0, 100, 100)
        self.assertLess(max(r, g, b) - min(r, g, b), 12, "saturation 0 = grey")

    # ----------------------------------------------------------- time remap
    def test_reverse_plays_backwards_freeze_holds_and_a_ramp_has_the_computed_length(self):
        out, _ = self.render({"kind": "video", "clips": [self.clip("rb", end=2, reverse=True)]})
        self.assertTrue(near(pixel(out, 0.2, 100, 100), (0, 0, 255), 60), "reversed: blue first")
        self.assertTrue(near(pixel(out, 1.7, 100, 100), (255, 0, 0), 60), "…then red")
        out, _ = self.render({"kind": "video", "clips": [self.clip("rb", start=0.5, end=1.5, freeze=True)]})
        self.assertAlmostEqual(stats(out)["dur"], 1.0, delta=0.2)
        self.assertTrue(near(pixel(out, 0.1, 100, 100), pixel(out, 0.9, 100, 100), 25), "the held frame does not change")
        ramp = self.clip("rb", end=2, ramp=[{"p": 0, "v": 1}, {"p": 1, "v": 2}])
        out, line = self.render({"kind": "video", "clips": [ramp]})
        expected = line.tracks[0].clips[0].length
        self.assertTrue(1.0 < expected < 2.0)
        self.assertAlmostEqual(stats(out)["dur"], expected, delta=0.2)
        out, _ = self.render({"kind": "video", "clips": [self.clip("rb", end=2, speed=2)]})
        self.assertAlmostEqual(stats(out)["dur"], 1.0, delta=0.2)

    # ----------------------------------------------------------- transitions
    def test_the_transition_library_blends_inside_the_window_only(self):
        for kind in ("wipeleft", "circleopen", "slideleft", "fadeblack"):
            a, b = self.clip("red", at=0, end=2), self.clip("blue", at=2, end=2, transition={"kind": kind, "duration": 1.0})
            out, _ = self.render({"kind": "video", "clips": [a, b]})
            self.assertAlmostEqual(stats(out)["dur"], 4.0, delta=0.2, msg=kind)
            self.assertTrue(near(pixel(out, 1.2, 160, 120), (255, 0, 0), 40), f"{kind}: before the window")
            self.assertTrue(near(pixel(out, 2.8, 160, 120), (0, 0, 255), 40), f"{kind}: after the window")
        a, b = self.clip("red", at=0, end=2), self.clip("blue", at=2, end=2, transition={"kind": "wipeleft", "duration": 1.0})
        out, _ = self.render({"kind": "video", "clips": [a, b]})
        mid_left, mid_right = pixel(out, 2.0, 30, 120), pixel(out, 2.0, 290, 120)
        self.assertTrue(near(mid_left, (255, 0, 0), 60) and near(mid_right, (0, 0, 255), 60), f"half-way the wipe is between: {mid_left} {mid_right}")

    # ----------------------------------------------------------- the mixer
    def test_track_gain_pan_eq_solo_and_master(self):
        base = {"kind": "video", "clips": [self.clip("gray", end=3)]}
        loud, _ = self.render(base, {"kind": "audio", "clips": [self.clip("tone", end=3)]})
        quiet, _ = self.render(base, {"kind": "audio", "gain_db": -12, "clips": [self.clip("tone", end=3)]})
        self.assertAlmostEqual(mean_volume(quiet), mean_volume(loud) - 12, delta=1.5)
        master, _ = self.render(base, {"kind": "audio", "clips": [self.clip("tone", end=3)]}, master={"gain_db": -6.0, "limiter": True})
        self.assertAlmostEqual(mean_volume(master), mean_volume(loud) - 6, delta=1.5)
        flat, _ = self.render(base, {"kind": "audio", "clips": [self.clip("bass", end=3)]})
        phone, _ = self.render(base, {"kind": "audio", "clips": [self.clip("bass", end=3, audio={"eq": "phone"})]})
        self.assertLess(mean_volume(phone), mean_volume(flat) - 10, "the phone EQ removes a 100 Hz tone")
        hard_left, _ = self.render(base, {"kind": "audio", "clips": [self.clip("tone", end=3, audio={"pan": -1})]})
        right = subprocess.run([FFMPEG, "-i", str(hard_left), "-af", "pan=mono|c0=c1,volumedetect", "-vn", "-f", "null", "-"], capture_output=True, text=True,
                               stdin=DEVNULL).stderr
        left = subprocess.run([FFMPEG, "-i", str(hard_left), "-af", "pan=mono|c0=c0,volumedetect", "-vn", "-f", "null", "-"], capture_output=True, text=True,
                              stdin=DEVNULL).stderr
        vol = lambda s: float(s.split("mean_volume:")[1].split("dB")[0])  # noqa: E731
        self.assertGreater(vol(left), vol(right) + 20, "pan -1 sends everything left")
        soloed, _ = self.render(base, {"kind": "audio", "solo": True, "clips": [self.clip("tone", end=3)]},
                                {"kind": "audio", "clips": [self.clip("bass", end=3)]})
        self.assertAlmostEqual(mean_volume(soloed), mean_volume(loud), delta=1.5, msg="only the solo track is heard")

    def test_music_ducks_under_speech_spans_and_comes_back(self):
        base = {"kind": "video", "clips": [self.clip("gray", end=5)]}
        # the speech clip is silent (volume 0) on purpose: only its SPANS matter, so the music level can be measured alone
        speech = {"kind": "audio", "role": "speech", "clips": [self.clip("speech", at=1, start=0, end=2, volume=0)]}
        music = {"kind": "audio", "role": "music", "clips": [self.clip("tone", end=5)]}
        duck = {"on": True, "amount_db": 18.0, "threshold": 0.04, "attack_ms": 20.0, "release_ms": 100.0}
        out, _ = self.render(base, speech, music, ducking=duck, spans=lambda path: [[0.0, 2.0]])
        during, before, after = seg_volume(out, 1.4, 1.0), seg_volume(out, 0.0, 0.6), seg_volume(out, 3.8, 1.0)
        self.assertLess(during, before - 12, f"ducked: {during} vs {before}")
        self.assertAlmostEqual(after, before, delta=2.0, msg="released after the speech")
        no_duck, _ = self.render(base, speech, music, ducking=dict(duck, on=False), spans=lambda path: [[0.0, 2.0]])
        self.assertAlmostEqual(seg_volume(no_duck, 1.4, 1.0), before, delta=2.0)

    # ----------------------------------------------------------- export, preview, progress, cancel
    def test_export_presets_set_size_codec_and_fps(self):
        line = T.from_project(project({"kind": "video", "clips": [self.clip("red", end=2)]}, width=540, height=960, fps=30), resolver(self.table()))
        spec = export.resolve({"preset": "reels"}, line)
        self.assertEqual((spec.codec, spec.short_side, spec.fps), ("h264", 1080, 30))
        self.assertEqual(export.size_for(line, 1080), (1080, 1920))
        self.assertEqual(export.size_for(line, 720), (720, 1280))
        self.assertEqual(export.size_for(line, None), (540, 960))
        wide = T.from_project(project({"kind": "video", "clips": [self.clip("red", end=2)]}, width=1920, height=1080), resolver(self.table()))
        self.assertIn("ریلز", export.resolve({"preset": "reels"}, wide).note, "a landscape project warns about the 9:16 preset")
        self.assertEqual(export.resolve({"preset": "hevc"}, line).codec, "h265")
        self.assertEqual(export.resolve({"preset": "reels", "codec": "h265", "height": 99999, "fps": 1}, line).short_side, export.HEAVY_SHORT_SIDE)
        self.assertEqual(export.resolve({"fps": 1}, line).fps, 12)
        long_line = T.Timeline(tracks=[T.Track(clips=[T.Clip("a.mp4", at=0, end=200)])], width=540, height=960)
        self.assertIn("90", export.resolve({"preset": "reels"}, long_line).note)
        self.assertGreaterEqual(len(export.catalogue()["presets"]), 8)

    def test_a_real_h265_export_at_another_size_and_frame_rate(self):
        line = T.from_project(project({"kind": "video", "clips": [self.clip("red", end=2)]}), resolver(self.table()))
        out = self.dir / "hevc.mp4"
        export.render(line, out, quality="final", export={"codec": "h265", "height": 480, "fps": 24, "quality": "small", "audio_kbps": 96})
        info = probe(out)
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        self.assertEqual(v["codec_name"], "hevc")
        self.assertEqual((int(v["width"]), int(v["height"])), (640, 480))
        self.assertEqual(v["r_frame_rate"], "24/1")

    def test_range_preview_renders_only_the_window_at_a_small_size(self):
        tl = T.from_project(project({"kind": "video", "clips": [self.clip("rb", end=2), self.clip("blue", at=2, end=2)]}, width=640, height=480),
                            resolver(self.table()))
        out = self.dir / "preview.mp4"
        info = export.render_preview(tl, out, 1.5, 2.5, height=240)
        s = stats(out)
        self.assertEqual((s["w"], s["h"]), (320, 240))
        self.assertAlmostEqual(s["dur"], 1.0, delta=0.2)
        self.assertEqual(info["size"], "320x240")
        self.assertTrue(near(pixel(out, 0.2, 100, 100), (0, 0, 255), 60))
        with self.assertRaises(TimelineError):
            export.render_preview(tl, out, 50, 52)

    def test_progress_is_reported_and_cancel_stops_the_render(self):
        line = T.from_project(project({"kind": "video", "clips": [self.clip("red", end=4)]}), resolver(self.table()))
        seen: list[float] = []
        export.render(line, self.dir / "p.mp4", quality="draft", progress=seen.append)
        self.assertTrue(all(0 <= x < 1 for x in seen))
        self.assertEqual(seen, sorted(seen))
        started = time.monotonic()
        with self.assertRaises(export.RenderCancelled):
            export.render(line, self.dir / "c.mp4", quality="draft", cancel=lambda: True)
        self.assertLess(time.monotonic() - started, 10)

    def test_persian_titles_and_a_project_without_the_base_track_in_a_window(self):
        data = project({"kind": "video", "clips": [self.clip("gray", end=3)]},
                       {"kind": "text", "clips": [{"text": "قهوهٔ تازه ۵۰٪ تخفیف", "at": 0.5, "duration": 2, "size": 12, "anim_in": "fade", "stroke": 20}]})
        line = T.from_project(data, resolver(self.table()))
        out = self.dir / "title.mp4"
        export.render(line, out, quality="draft")
        before = subprocess.run([FFMPEG, "-v", "error", "-ss", "1.5", "-i", str(out), "-vf", "crop=320:60:0:150,format=gray", "-frames:v", "1", "-f", "rawvideo", "-"],
                                capture_output=True, stdin=DEVNULL).stdout
        bright = sum(1 for b in before if b > 200)
        self.assertGreater(bright, 150, "the Persian title is drawn near the bottom")
