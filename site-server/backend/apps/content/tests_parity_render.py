"""Round 6: the render-side parity items — video denoise, frame blending / optical flow, interpret (deinterlace, pixel aspect), the morph-cut approximation,
reverb / dereverb, the «ambience» track role and ProRes 422 / 4444 with alpha. Real ffmpeg on tiny clips."""
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from django.test import SimpleTestCase, TestCase, override_settings

from services.editing import audiofx, compose, export
from services.editing import timeline as tl
from services.editing import transitions
from services.video.ffmpeg import FFMPEG, probe

from .tests_clipfx_r5 import build, frame, layer, media, project
from .tests_editor_modes import make_video

TEMP = tempfile.mkdtemp(prefix="nm-parity-render-")
HAVE = bool(shutil.which(FFMPEG) or shutil.which("ffmpeg"))
AUDIO = {"audio_on": True, "has_audio": True}


def graph_of(data, **kw):
    return compose.build_graph(build(data), need_base=True, **kw)


class CleanTests(SimpleTestCase):
    def test_denoise_frames_and_interpret_are_clamped_and_neutral_values_vanish(self):
        c = build(project([media(denoise={"amount": 7, "mode": "strong"}, frames="flow", interpret={"par": 9, "deinterlace": True})])).tracks[0].clips[0]
        self.assertEqual(c.denoise, {"amount": 1.0, "mode": "strong"})
        self.assertEqual(c.frames, "flow")
        self.assertEqual(c.interpret, {"par": 2.0, "deinterlace": True})
        c = build(project([media(denoise={"amount": 0.0}, frames="warp", interpret={"par": 1.0, "deinterlace": False})])).tracks[0].clips[0]
        self.assertFalse(c.denoise)
        self.assertEqual(c.frames, "")
        self.assertFalse(c.interpret)
        c = build(project([media(denoise={"on": False, "amount": 0.9})])).tracks[0].clips[0]
        self.assertFalse(c.denoise)

    def test_new_audio_settings_and_the_ambience_role(self):
        a = tl._clean_audio_pro({"reverb": {"on": True, "room": "moon", "mix": 9}, "dereverb": {"on": True, "amount": 0}})
        self.assertEqual(a["reverb"], {"on": True, "room": "small", "mix": 1.0})
        self.assertEqual(a["dereverb"], {"on": True, "amount": 0.1})
        self.assertIn("ambience", tl.ROLES)
        self.assertEqual(tl._clean_audio_pro({"reverb": {"on": False}}), {})

    def test_morph_cut_is_a_known_transition(self):
        self.assertIn("morphcut", transitions.XFADE)
        self.assertEqual(transitions.xfade_name("morphcut"), "morphcut")
        self.assertIn("morphcut", tl.transitions_all())


class GraphTests(SimpleTestCase):
    def test_denoise_filters(self):
        self.assertIn("hqdn3d=", graph_of(project([media(denoise={"amount": 0.5, "mode": "fast"})])).graph)
        self.assertIn("nlmeans=", graph_of(project([media(denoise={"amount": 0.5, "mode": "strong"})])).graph)
        self.assertNotIn("hqdn3d", graph_of(project([media()])).graph)

    def test_frame_modes_apply_only_to_slowed_clips(self):
        slow = graph_of(project([media(speed=0.5, frames="blend")])).graph
        self.assertIn("minterpolate=fps=12:mi_mode=blend", slow)
        flow = graph_of(project([media(speed=0.5, frames="flow")])).graph
        self.assertIn("mi_mode=mci", flow)
        self.assertNotIn("minterpolate", graph_of(project([media(speed=1.0, frames="flow")])).graph, "a clip at normal speed needs no interpolation")
        self.assertNotIn("minterpolate", graph_of(project([media(speed=2.0, frames="flow")])).graph)

    def test_optical_flow_is_not_run_in_the_sites_quick_draft_but_says_so(self):
        g = graph_of(project([media(speed=0.5, frames="flow")]), flow=False)
        self.assertNotIn("minterpolate", g.graph)
        self.assertTrue(any("اپتیکال‌فلو" in n for n in g.notes), g.notes)
        blend = graph_of(project([media(speed=0.5, frames="blend")]), flow=False).graph
        self.assertIn("mi_mode=blend", blend, "frame blending is cheap and stays")

    def test_interpret_deinterlace_and_pixel_aspect(self):
        g = graph_of(project([media(interpret={"par": 1.333, "deinterlace": True})])).graph
        self.assertIn("yadif=mode=0", g)
        self.assertIn("scale=trunc(iw*1.333/2)*2:ih", g)
        self.assertNotIn("yadif", graph_of(project([media()])).graph)

    def test_morph_cut_builds_an_interpolated_window_and_downgrades_in_the_draft(self):
        data = project([media(0, at=0, end=2), media(1, at=2, end=2, transition={"kind": "morphcut", "duration": 0.6})])
        g = graph_of(data)
        self.assertIn("concat=n=2:v=1:a=0", g.graph)
        self.assertIn("minterpolate=fps=12:mi_mode=mci", g.graph)
        self.assertNotIn("xfade=transition=morphcut", g.graph)
        d = graph_of(data, flow=False)
        self.assertIn("xfade=transition=fade", d.graph)
        self.assertTrue(any("برشِ مورف" in n for n in d.notes))

    def test_alpha_graph_has_a_transparent_base_and_keeps_alpha(self):
        data = project([media(0, at=0, end=2, x=0.1, y=0.1, width=0.5, height=0.5)])
        g = graph_of(data, alpha=True).graph
        self.assertIn("color=c=black@0", g)
        self.assertIn("overlay=", g)
        self.assertIn(":format=auto", g)
        self.assertIn("format=yuva444p10le", g)
        self.assertNotIn("black@0", graph_of(data).graph)


class AudioFilterTests(SimpleTestCase):
    def test_reverb_rooms_and_mix(self):
        for room, (taps, decays) in audiofx.REVERB_ROOMS.items():
            self.assertEqual(len(taps), len(decays), room)
        self.assertGreater(max(audiofx.REVERB_ROOMS["cathedral"][0]), max(audiofx.REVERB_ROOMS["small"][0]) * 5, "a cathedral rings far longer than a closet")

    def test_filters_are_emitted_for_dereverb_and_reverb_in_the_right_order(self):
        out = audiofx.fx_chain({"dereverb": {"on": True, "amount": 0.5}, "reverb": {"on": True, "room": "hall", "mix": 0.4}})
        text = ",".join(out)
        self.assertIn("afftdn=nr=", text)
        self.assertIn("agate=", text)
        self.assertIn("aecho=0.85:", text)
        self.assertLess(text.index("afftdn"), text.index("aecho"), "the room is cleaned BEFORE a new one is added")
        self.assertEqual(audiofx.fx_chain({}), [])

    def test_a_bigger_mix_makes_louder_taps(self):
        low = ",".join(audiofx.fx_chain({"reverb": {"on": True, "room": "small", "mix": 0.1}}))
        high = ",".join(audiofx.fx_chain({"reverb": {"on": True, "room": "small", "mix": 0.9}}))
        self.assertNotEqual(low, high)


@override_settings(MEDIA_ROOT=TEMP)
class RenderTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if HAVE:
            cls.src = make_video(Path(TEMP) / "p.mp4", size="320x180", seconds=4)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMP, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        if not HAVE:
            self.skipTest("ffmpeg نیست")

    def render(self, data, name, **kw):
        info = {"path": str(self.src), "kind": "video", "has_audio": True, "duration": 4.0, "width": 320, "height": 180}
        return export.render(tl.from_project(data, lambda ref: dict(info)), Path(TEMP) / name, **kw)

    def streams(self, path):
        return {s["codec_type"]: s for s in probe(path)["streams"]}

    def frames_unique(self, path):
        raw = subprocess.run([FFMPEG, "-v", "error", "-i", str(path), "-vf", "scale=32:18", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
        n = len(raw) // (32 * 18)
        arr = np.frombuffer(raw, dtype=np.uint8).reshape(n, 18, 32)
        return n, sum(1 for i in range(1, n) if float(np.mean(np.abs(arr[i].astype(float) - arr[i - 1]))) > 0.01)

    def test_slow_motion_with_blending_and_optical_flow_makes_new_frames(self):
        plain = self.render(project([media(speed=0.4, end=1.0)]), "s0.mp4", quality="final")
        flow = self.render(project([media(speed=0.4, end=1.0, frames="flow")]), "s1.mp4", quality="final")
        blend = self.render(project([media(speed=0.4, end=1.0, frames="blend")]), "s2.mp4", quality="final")
        n0, changes0 = self.frames_unique(plain)
        n1, changes1 = self.frames_unique(flow)
        n2, changes2 = self.frames_unique(blend)
        self.assertTrue(n0 == n1 == n2, (n0, n1, n2))
        self.assertGreater(changes1, changes0 + 3, "interpolation fills the repeated frames with moving ones")
        self.assertGreater(changes2, changes0 + 3)

    def test_denoise_interpret_and_morph_render(self):
        out = self.render(project([media(0, at=0, end=1.5, denoise={"amount": 0.6}, interpret={"par": 1.0, "deinterlace": True}),
                                   media(1, at=1.5, end=1.5, transition={"kind": "morphcut", "duration": 0.6})]), "m.mp4", quality="final")
        self.assertAlmostEqual(float(probe(out)["format"]["duration"]), 3.0, delta=0.4)
        self.assertEqual(self.streams(out)["video"]["codec_name"], "h264")

    def test_pixel_aspect_widens_a_stretched_picture(self):
        wide = self.render(project([media(fit="stretch", interpret={"par": 2.0, "deinterlace": False})]), "par.mp4", quality="draft")
        self.assertEqual(self.streams(wide)["video"]["codec_name"], "h264")

    def test_prores_422_in_a_mov_with_pcm_sound(self):
        out = self.render(project([media(end=1.5, **AUDIO)]), "pr.mov", quality="final", export={"codec": "prores"})
        s = self.streams(out)
        self.assertEqual(s["video"]["codec_name"], "prores")
        self.assertEqual(s["audio"]["codec_name"], "pcm_s16le")
        self.assertEqual(Path(out).suffix, ".mov")

    def test_prores_4444_keeps_a_transparent_background(self):
        data = project([media(0, at=0, end=1.5, x=0.0, y=0.0, width=0.5, height=0.5, audio_on=False, has_audio=False)])
        out = self.render(data, "pa.mov", quality="final", export={"codec": "prores4444"})
        v = self.streams(out)["video"]
        self.assertEqual(v["codec_name"], "prores")
        self.assertTrue(v["pix_fmt"].startswith("yuva"), v["pix_fmt"])
        raw = subprocess.run([FFMPEG, "-v", "error", "-ss", "0.5", "-i", str(out), "-frames:v", "1", "-vf", "alphaextract,scale=64:36", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                             capture_output=True, check=True).stdout
        a = np.frombuffer(raw, dtype=np.uint8).reshape(36, 64).astype(float)
        self.assertGreater(float(a[5, 5]), 200, "inside the clip: opaque")
        self.assertLess(float(a[30, 58]), 20, "outside the clip: transparent")

    def test_prores_in_slices_matches(self):
        out = self.render(project([media(i, at=i * 0.5, end=0.5, **AUDIO) for i in range(6)]), "ps.mov", quality="final", export={"codec": "prores"}, slice_budget=1)
        s = self.streams(out)
        self.assertEqual((s["video"]["codec_name"], s["audio"]["codec_name"]), ("prores", "pcm_s16le"))
        self.assertAlmostEqual(float(probe(out)["format"]["duration"]), 3.0, delta=0.4)

    def test_reverb_and_dereverb_render(self):
        data = project([media(0, end=1.5, **AUDIO, audio={"reverb": {"on": True, "room": "hall", "mix": 0.5}, "dereverb": {"on": True, "amount": 0.4}})])
        out = self.render(data, "rv.mp4", quality="final")
        self.assertEqual(self.streams(out)["audio"]["codec_name"], "aac")
