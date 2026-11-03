"""Lumetri-style colour (services/editing/color.py): the parameter clamps, the tone maths a browser mirrors, the ffmpeg
filters — and REAL frames through the real ffmpeg, because a filter string that merely parses proves nothing.

`REFERENCE` below pins `tone_points` (exact, pure Python) and the mean RGB of an SMPTE-bars frame after the real filters
for six parameter sets: the TypeScript mirror of the tone chain can be checked against exactly these numbers."""
import json
import re
import shutil
import subprocess

from django.test import SimpleTestCase

from services.editing import color
from services.video.ffmpeg import FFMPEG

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

HAVE_FFMPEG = bool(shutil.which(FFMPEG) or shutil.which("ffmpeg")) and np is not None

RAMP = "color=c=black:s=256x4:r=1:d=1,format=gbrp,geq=r='X':g='X':b='X'"       # grey ramp, value == x (0..255)
BARS = "smptebars=size=160x120:rate=1:d=1"


def px(color_hex: str) -> str:
    return f"color=c={color_hex}:s=8x8:r=1:d=1"


def frame(vf_parts, src=RAMP):
    """One frame through `format=gbrp` + the given filters → float array (h, w, 3) in RGB."""
    vf = ",".join(["format=gbrp", *vf_parts])
    cmd = [FFMPEG, "-v", "error", "-nostdin", "-f", "lavfi", "-i", src, "-vf", vf, "-frames:v", "1", "-pix_fmt", "rgb24",
           "-f", "rawvideo", "-"]
    out = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")[:400]
    size = re.search(r"(?:^|[:,=])(?:s|size)=(\d+)x(\d+)", src)
    w, h = (int(size.group(1)), int(size.group(2))) if size else (256, 4)
    return np.frombuffer(out.stdout, dtype=np.uint8).astype(float).reshape(h, w, 3)


def ramp_at(arr, *xs):
    return [float(arr[0, x].mean()) for x in xs]


def mean_rgb(arr):
    flat = arr.reshape(-1, 3)
    return [float(flat[:, i].mean()) for i in range(3)]


REFERENCE = [
    {"params": {"exposure": 0.5, "contrast": 30},
     "tone": {"r": [0.0, 0.1362, 0.3197, 0.5382, 0.7488, 0.9148, 1.0, 1.0, 1.0],
              "g": [0.0, 0.1362, 0.3197, 0.5382, 0.7488, 0.9148, 1.0, 1.0, 1.0],
              "b": [0.0, 0.1362, 0.3197, 0.5382, 0.7488, 0.9148, 1.0, 1.0, 1.0]},
     "mean_rgb": [122.8, 122.6, 132.1]},
    {"params": {"temperature": 40, "tint": -15, "saturation": 120},
     "tone": {"r": [0.0, 0.1341, 0.2681, 0.4022, 0.5363, 0.6703, 0.8044, 0.9384, 1.0],
              "g": [0.0, 0.1278, 0.2556, 0.3834, 0.5112, 0.6391, 0.7669, 0.8947, 1.0],
              "b": [0.0, 0.1141, 0.2281, 0.3422, 0.4562, 0.5703, 0.6844, 0.7984, 0.9125]},
     "mean_rgb": [108.5, 99.0, 97.9]},
    {"params": {"shadows": 40, "highlights": -40, "whites": 20, "blacks": -20, "vibrance": 30},
     "tone": {"r": [0.0, 0.1916, 0.3404, 0.434, 0.5, 0.566, 0.6596, 0.8084, 1.0],
              "g": [0.0, 0.1916, 0.3404, 0.434, 0.5, 0.566, 0.6596, 0.8084, 1.0],
              "b": [0.0, 0.1916, 0.3404, 0.434, 0.5, 0.566, 0.6596, 0.8084, 1.0]},
     "mean_rgb": [101.6, 91.3, 109.6]},
    {"params": {"curves": {"m": [[0.25, 0.18], [0.5, 0.55], [0.8, 0.9]], "r": [[0, 0], [0.5, 0.45], [1, 1]]},
                "wheels": {"shadows": [0.1, 0, -0.1], "mids": [0, 0.05, 0], "highs": [-0.05, 0, 0.1]}},
     "tone": {"r": [0.0, 0.0574, 0.1509, 0.3093, 0.5001, 0.6753, 0.8351, 0.9375, 1.0],
              "g": [0.0, 0.0704, 0.18, 0.3544, 0.55, 0.7166, 0.8595, 0.9475, 1.0],
              "b": [0.0, 0.0704, 0.18, 0.3544, 0.55, 0.7166, 0.8595, 0.9475, 1.0]},
     "mean_rgb": [101.4, 106.3, 125.0]},
    {"params": {"look": "cinematic", "look_amount": 60},
     "tone": {"r": [0.0, 0.0999, 0.2154, 0.3459, 0.4851, 0.6244, 0.7573, 0.8812, 1.0],
              "g": [0.0, 0.0999, 0.2154, 0.3459, 0.4851, 0.6244, 0.7573, 0.8812, 1.0],
              "b": [0.0, 0.0999, 0.2154, 0.3459, 0.4851, 0.6244, 0.7573, 0.8812, 1.0]},
     "mean_rgb": [103.5, 98.6, 99.9]},
    {"params": {"hsl": {"red": {"h": 30, "s": -20, "l": 10}}, "saturation": 90, "look": "sepia", "look_amount": 40},
     "tone": {"r": [0.0, 0.1215, 0.2453, 0.3718, 0.5, 0.6282, 0.7547, 0.8785, 1.0],
              "g": [0.0, 0.1215, 0.2453, 0.3718, 0.5, 0.6282, 0.7547, 0.8785, 1.0],
              "b": [0.0, 0.1215, 0.2453, 0.3718, 0.5, 0.6282, 0.7547, 0.8785, 1.0]},
     "mean_rgb": [105.5, 97.2, 87.9]},
]


class CleanTests(SimpleTestCase):
    def test_neutral_defaults_and_no_filters(self):
        p = color.clean(None)
        self.assertEqual((p["exposure"], p["contrast"], p["saturation"], p["look_amount"]), (0.0, 0.0, 100.0, 100.0))
        self.assertEqual(p["look"], "")
        self.assertEqual(set(p["curves"]), {"m", "r", "g", "b"})
        self.assertEqual(p["curves"]["m"], [[0.0, 0.0], [1.0, 1.0]])
        self.assertEqual(set(p["hsl"]), set(color.HSL_RANGES))
        self.assertEqual(color.build_filters({}), [])
        self.assertTrue(color.is_neutral(None))
        self.assertTrue(color.is_neutral({"saturation": 100, "look": "nope", "evil": 1}))
        self.assertEqual(color.clean("junk"), color.neutral())
        self.assertEqual(color.clean([1, 2]), color.neutral())

    def test_values_are_clamped_and_unknown_keys_dropped(self):
        p = color.clean({"exposure": 99, "contrast": -999, "saturation": 9999, "temperature": "x", "tint": float("nan"),
                         "vibrance": None, "blur": 1000, "evil": "rm -rf", "look": "evil", "look_amount": 500,
                         "wheels": {"shadows": [5, -5, "q"], "mids": "no", "highs": [0.5]},
                         "hsl": {"red": {"h": 999, "s": -999, "l": 7}, "purple": {"h": 1}}})
        self.assertEqual((p["exposure"], p["contrast"], p["saturation"]), (3.0, -100.0, 200.0))
        self.assertEqual((p["temperature"], p["tint"], p["vibrance"], p["blur"]), (0.0, 0.0, 0.0, 100.0))
        self.assertNotIn("evil", p)
        self.assertEqual((p["look"], p["look_amount"]), ("", 100.0))
        self.assertEqual(p["wheels"]["shadows"], [1.0, -1.0, 0.0])
        self.assertEqual(p["wheels"]["mids"], [0.0, 0.0, 0.0])
        self.assertEqual(p["wheels"]["highs"], [0.5, 0.0, 0.0])
        self.assertEqual(p["hsl"]["red"], {"h": 180.0, "s": -100.0, "l": 7.0})
        self.assertNotIn("purple", p["hsl"])

    def test_curves_are_sorted_padded_deduplicated_and_capped(self):
        c = color.clean({"curves": {"m": [[0.8, 0.9], [0.25, 0.3], {"x": 0.5, "y": 0.6}, "junk", [2, 2]], "r": [[0, 0], [1, 1]],
                                    "g": [[0.5, 0.5]], "b": [[i / 20, 0.5] for i in range(21)]}})["curves"]
        xs = [p[0] for p in c["m"]]
        self.assertEqual(xs, sorted(xs))
        self.assertEqual(c["m"][0], [0.0, 0.0])
        self.assertEqual(c["m"][-1], [1.0, 1.0])
        self.assertIn([0.5, 0.6], c["m"])
        self.assertEqual(c["r"], [[0.0, 0.0], [1.0, 1.0]])
        self.assertEqual(c["g"], [[0.0, 0.0], [1.0, 1.0]], "a point on the diagonal is the identity")
        self.assertLessEqual(len(c["b"]), color.MAX_CURVE_POINTS)
        self.assertEqual((c["b"][0][0], c["b"][-1][0]), (0.0, 1.0))
        self.assertEqual(color.clean({"curves": {"m": []}})["curves"]["m"], [[0.0, 0.0], [1.0, 1.0]])

    def test_clean_is_idempotent(self):
        once = color.clean({"exposure": 1.234567, "look": "bw", "look_amount": 55, "curves": {"m": [[0.3, 0.2]]},
                            "wheels": {"mids": [0.1, 0.2, 0.3]}})
        self.assertEqual(color.clean(once), once)

    def test_catalogue_is_json_and_every_look_is_wellformed(self):
        cat = color.catalogue()
        json.dumps(cat, ensure_ascii=False)
        self.assertGreaterEqual(len(cat["looks"]), 12)
        self.assertEqual({s["key"] for s in cat["sliders"]}, set(color.SLIDERS))
        for look in cat["looks"]:
            self.assertTrue(look["title"])
            self.assertFalse(color.is_neutral({"look": look["key"]}), look["key"])
        self.assertEqual(len(cat["hsl"]), 6)
        self.assertEqual(len(cat["wheels"]), 3)


class MathTests(SimpleTestCase):
    def test_pchip_matches_scipy_reference_and_is_monotone(self):
        pts = [(0, 0), (0.125, 0.05), (0.25, 0.2), (0.375, 0.4), (0.5, 0.5), (0.625, 0.7), (0.75, 0.75), (0.875, 0.95), (1, 1)]
        f = color.pchip(pts)
        for x, y in pts:
            self.assertAlmostEqual(f(x), y, places=9, msg="passes through its points")
        # SciPy PchipInterpolator at i/255 for i = 16, 48, … 240 (rounded to 8-bit), measured in the design experiment
        scipy_ref = [4, 29, 78, 115, 156, 185, 218, 252]
        for i, want in zip((16, 48, 80, 112, 144, 176, 208, 240), scipy_ref):
            self.assertLessEqual(abs(round(f(i / 255) * 255) - want), 1)
        last = -1
        for i in range(256):
            v = f(i / 255)
            self.assertGreaterEqual(v + 1e-12, last)
            last = v
        self.assertAlmostEqual(color.pchip([(0, 0.3), (1, 0.9)])(0.5), 0.6, places=9)          # two points: a straight line
        self.assertEqual(color.pchip([(0.2, 0.3), (0.6, 0.9)])(0.0), 0.3)      # clamped outside

    def test_tone_points_shape_neutral_and_monotone(self):
        tp = color.tone_points(None)
        for ch in "rgb":
            self.assertEqual([x for x, _ in tp[ch]], [i / 8 for i in range(9)])
            for x, y in tp[ch]:
                self.assertAlmostEqual(x, y, places=4)
        for params in ({"contrast": 100, "shadows": 100, "highlights": -100}, {"exposure": 3, "blacks": -100},
                       {"look": "cross_process"}, {"curves": {"m": [[0.3, 0.7], [0.6, 0.4]]}}):
            for pts in color.tone_points(params).values():
                ys = [y for _, y in pts]
                self.assertEqual(ys, sorted(ys), params)
                self.assertTrue(all(0.0 <= y <= 1.0 for y in ys))

    def test_each_slider_moves_the_curve_the_documented_way(self):
        y = lambda p, ch="g": [v for _, v in color.tone_points(p)[ch]]      # noqa: E731
        base = y({})
        self.assertAlmostEqual(y({"exposure": 1})[2], 0.5, places=4)        # x=.25 → ×2
        self.assertLess(y({"exposure": -1})[4], 0.26)
        c = y({"contrast": 60})
        self.assertLess(c[2], base[2])
        self.assertGreater(c[6], base[6])
        self.assertAlmostEqual(c[4], 0.5, places=3, msg="contrast pivots about the middle")
        sh = y({"shadows": 50})
        self.assertGreater(sh[2], base[2] + 0.02)
        self.assertAlmostEqual(sh[7], base[7], delta=0.02)
        hi = y({"highlights": -50})
        self.assertLess(hi[6], base[6] - 0.02)
        self.assertAlmostEqual(hi[2], base[2], delta=0.02)
        self.assertGreater(y({"blacks": 50})[1], base[1] + 0.01)
        self.assertGreater(y({"whites": 50})[7], base[7] - 0.001)
        warm = color.tone_points({"temperature": 50})
        self.assertGreater(warm["r"][4][1], warm["g"][4][1])
        self.assertGreater(warm["g"][4][1], warm["b"][4][1])
        magenta = color.tone_points({"tint": 60})
        self.assertLess(magenta["g"][4][1], magenta["r"][4][1])
        self.assertAlmostEqual(y({"curves": {"m": [[0.5, 0.7]]}})[4], 0.7, delta=0.003)
        self.assertAlmostEqual(color.tone_value({"exposure": 1}, "r", 0.2), 0.4, places=6)

    def test_look_amount_lerps_towards_the_preset(self):
        full = color.tone_points({"look": "faded_film", "look_amount": 100})["r"]
        half = color.tone_points({"look": "faded_film", "look_amount": 50})["r"]
        zero = color.tone_points({"look": "faded_film", "look_amount": 0})["r"]
        self.assertEqual(color.build_filters({"look": "faded_film", "look_amount": 0}), [])
        self.assertEqual(zero, color.tone_points(None)["r"])
        self.assertEqual(full, color.tone_points(color.LOOKS["faded_film"]["params"])["r"])
        for f, h, z in zip(full, half, zero):
            self.assertTrue(min(f[1], z[1]) - 1e-3 <= h[1] <= max(f[1], z[1]) + 1e-3)
        eff = color.effective({"look": "vivid", "look_amount": 50, "saturation": 90})
        self.assertAlmostEqual(eff["saturation"], 90 + 0.5 * (132 - 100))
        self.assertAlmostEqual(eff["vibrance"], 15.0)

    def test_filter_strings(self):
        self.assertEqual(color.build_filters({"exposure": 0.0001}), [])
        fl = color.build_filters({"exposure": 1, "saturation": 0, "vibrance": 40, "sharpen": 50, "vignette": 30,
                                  "grain": 10, "denoise": 20, "blur": 10, "wheels": {"mids": [0.1, 0, -0.1]},
                                  "hsl": {"red": {"h": 10, "s": 20, "l": -5}}})
        text = "\n".join(fl)
        self.assertTrue(fl[0].startswith("hqdn3d="), "denoise first, in YUV")
        for needle in ("boxblur=", "curves=interp=pchip:", "colorchannelmixer=", "vibrance=intensity=0.4",
                       "huesaturation=hue=10:saturation=0.2:intensity=-0.05:colors=r", "colorbalance=rm=0.1:bm=-0.1",
                       "unsharp=5:5:0.75:5:5:0", "vignette=angle=PI/", "noise=alls=4:allf=t+u"):
            self.assertIn(needle, text)
        order = [text.index(n) for n in ("curves=", "colorchannelmixer=", "vibrance=", "huesaturation=", "colorbalance=", "unsharp=")]
        self.assertEqual(order, sorted(order), "saturation before wheels, so a sepia survives")
        only_r = color.build_filters({"curves": {"r": [[0.5, 0.7]]}})
        self.assertEqual(len(only_r), 1)
        self.assertIn(":r='", only_r[0] if ":r='" in only_r[0] else only_r[0].replace("pchip:r", "pchip::r"))
        self.assertNotIn("g='", only_r[0], "identity channels are left out")
        self.assertNotIn("b='", only_r[0])

    def test_reference_tone_points_are_stable(self):
        """The TypeScript mirror is checked against these exact numbers."""
        for case in REFERENCE:
            tp = color.tone_points(case["params"])
            for ch in "rgb":
                self.assertEqual([y for _, y in tp[ch]], case["tone"][ch], case["params"])


class RealFfmpegTests(SimpleTestCase):
    def setUp(self):
        if not HAVE_FFMPEG:
            self.skipTest("ffmpeg یا numpy نیست")

    def run_filters(self, params, src=RAMP):
        return frame(color.build_filters(params), src)

    def test_pchip_python_matches_ffmpegs_curves_on_a_ramp(self):
        for params in ({"curves": {"m": [[0.25, 0.15], [0.5, 0.55], [0.75, 0.9]]}}, {"contrast": 70, "exposure": 0.4},
                       {"curves": {"r": [[0, 0], [0.25, 0.18], [0.75, 0.86], [1, 1]], "b": [[0, 0.10], [0.5, 0.45], [1, 0.86]]}},
                       {"shadows": 60, "highlights": -60, "temperature": 30}):
            tp = color.tone_points(params)
            out = self.run_filters(params)
            for ci, ch in enumerate("rgb"):
                f = color.pchip(tp[ch])
                for x in (16, 48, 80, 112, 144, 176, 208, 240):
                    want = round(f(x / 255) * 255)
                    got = out[0, x, ci]
                    self.assertLessEqual(abs(got - want), 2, f"{params} {ch} x={x}: ffmpeg {got} vs pchip {want}")

    def test_exposure_contrast_zones_and_curves_on_a_ramp(self):
        base = self.run_filters({})
        self.assertEqual(ramp_at(base, 64, 192), [64.0, 192.0])
        up = self.run_filters({"exposure": 1})
        down = self.run_filters({"exposure": -1})
        self.assertGreater(ramp_at(up, 64)[0], 120)
        self.assertLess(ramp_at(down, 128)[0], 70)
        c = self.run_filters({"contrast": 60})
        self.assertLess(ramp_at(c, 64)[0], 55)
        self.assertGreater(ramp_at(c, 192)[0], 205)
        self.assertAlmostEqual(ramp_at(c, 128)[0], 128, delta=2)
        sh = self.run_filters({"shadows": 70})
        self.assertGreater(ramp_at(sh, 64)[0], 80)
        self.assertAlmostEqual(ramp_at(sh, 224)[0], 224, delta=6)
        hi = self.run_filters({"highlights": -70})
        self.assertLess(ramp_at(hi, 192)[0], 170)
        self.assertAlmostEqual(ramp_at(hi, 32)[0], 32, delta=6)
        bl = self.run_filters({"blacks": 60})
        self.assertGreater(ramp_at(bl, 8)[0], 14)
        wh = self.run_filters({"whites": -60})
        self.assertLess(ramp_at(wh, 250)[0], 238)
        m = self.run_filters({"curves": {"m": [[0.5, 0.75]]}})
        self.assertGreater(ramp_at(m, 128)[0], 185)

    def test_temperature_tint_and_saturation_on_colours(self):
        grey = px("0x808080")
        warm = mean_rgb(self.run_filters({"temperature": 60}, grey))
        cold = mean_rgb(self.run_filters({"temperature": -60}, grey))
        self.assertGreater(warm[0], warm[2] + 20)
        self.assertGreater(cold[2], cold[0] + 20)
        mag = mean_rgb(self.run_filters({"tint": 80}, grey))
        self.assertLess(mag[1], min(mag[0], mag[2]) - 8, "positive tint = magenta (less green)")
        patch = px("0xc04020")
        mono = frame(color.build_filters({"saturation": 0}), patch)
        self.assertLessEqual(float((mono.max(axis=2) - mono.min(axis=2)).max()), 2, "saturation 0 → R=G=B")
        hot = mean_rgb(self.run_filters({"saturation": 200}, patch))
        plain = mean_rgb(self.run_filters({}, patch))
        self.assertGreater(max(hot) - min(hot), max(plain) - min(plain) + 20)
        faded = mean_rgb(self.run_filters({"saturation": 40}, patch))
        self.assertLess(max(faded) - min(faded), max(plain) - min(plain) - 20)

    def test_vibrance_boosts_dull_colours_more_than_vivid_ones(self):
        def spread(hexc, v):
            m = mean_rgb(self.run_filters({"vibrance": v}, px(hexc)))
            return max(m) - min(m)
        dull_gain = spread("0x908070", 80) - spread("0x908070", 0)
        vivid_gain = spread("0xff2000", 80) - spread("0xff2000", 0)
        self.assertGreater(dull_gain, 6)
        self.assertGreater(dull_gain, vivid_gain)
        self.assertLess(spread("0x908070", -80), spread("0x908070", 0))

    def test_wheels_hit_the_documented_zone_and_match_ffmpegs_weights(self):
        shadows = self.run_filters({"wheels": {"shadows": [0.6, 0, 0]}})
        self.assertGreater(float(shadows[0, 16, 0] - 16), 60)
        self.assertEqual(float(shadows[0, 224, 0]), 224.0)
        highs = self.run_filters({"wheels": {"highs": [0, 0, -0.6]}})
        self.assertLess(float(highs[0, 176, 2]), 176 - 30)
        self.assertEqual(float(highs[0, 16, 2]), 16.0)
        mids = self.run_filters({"wheels": {"mids": [0, 0.5, 0]}})
        self.assertGreater(float(mids[0, 64, 1]), 64 + 60)
        self.assertEqual(float(mids[0, 250, 1]), 250.0)
        # the documented formula (l = max+min of a grey = 2x) reproduces ffmpeg to ±2 levels
        clamp = lambda v: max(0.0, min(1.0, v))  # noqa: E731
        both = self.run_filters({"wheels": {"shadows": [0.5, 0, 0], "mids": [0.4, 0, 0], "highs": [0.3, 0, 0]}})
        for x in (0, 16, 32, 48, 64, 80, 96, 112):
            l = 2 * x / 255
            w_s = clamp((0.333 - l) * 4 + 0.5)
            w_m = clamp((l - 0.333) * 4 + 0.5) * clamp((1 - l - 0.333) * 4 + 0.5)
            w_h = clamp((l + 0.333 - 1) * 4 + 0.5)
            want = round(255 * clamp(x / 255 + 0.7 * (0.5 * w_s + 0.4 * w_m + 0.3 * w_h)))
            self.assertLessEqual(abs(float(both[0, x, 0]) - want), 2, f"x={x}")
        self.assertEqual(color.build_filters({"wheels": {"shadows": [0.5, 0, 0]}}), ["colorbalance=rs=0.5"])

    def test_hsl_range_only_moves_its_own_colour(self):
        red, green = px("0xe02020"), px("0x20c020")
        moved = mean_rgb(self.run_filters({"hsl": {"red": {"h": 60}}}, red))
        self.assertGreater(moved[1], 90, "red rotated towards yellow gains green")
        self.assertEqual([round(v) for v in mean_rgb(self.run_filters({"hsl": {"red": {"h": 60}}}, green))],
                         [round(v) for v in mean_rgb(self.run_filters({}, green))], "green is untouched by the red range")
        dull = mean_rgb(self.run_filters({"hsl": {"red": {"s": -100}}}, red))
        self.assertLess(max(dull) - min(dull), 120)
        brighter = mean_rgb(self.run_filters({"hsl": {"red": {"l": 60}}}, red))
        self.assertGreater(sum(brighter), sum(mean_rgb(self.run_filters({}, red))) + 30)

    def test_detail_effects(self):
        bars = BARS
        flat = px("0x808080")
        edges = "testsrc2=size=160x120:rate=1:d=1"
        sharp = self._std(frame(color.build_filters({"sharpen": 100}), edges))
        soft = self._std(frame(color.build_filters({"blur": 100}), edges))
        plain = self._std(frame([], edges))
        self.assertGreater(sharp, plain)
        self.assertLess(soft, plain)
        vig = frame(color.build_filters({"vignette": 80}), "color=c=0x808080:s=160x120:r=1:d=1")
        self.assertLess(float(vig[2, 2].mean()), float(vig[60, 80].mean()) - 20, "corners darker than the centre")
        grain = self._std(frame(color.build_filters({"grain": 80}), "color=c=0x808080:s=64x64:r=1:d=1"))
        self.assertGreater(grain, 2.0)
        self.assertEqual(self._std(frame([], flat)), 0.0)
        noisy = "color=c=0x808080:s=160x120:r=1:d=1,noise=alls=40:allf=t"
        self.assertLess(self._std(frame(color.build_filters({"denoise": 100}), noisy)), self._std(frame([], noisy)))
        self.assertTrue(len(frame(color.build_filters({"blur": 100, "sharpen": 100}), bars)))

    @staticmethod
    def _std(arr):
        return float(arr.reshape(-1, 3).mean(axis=1).std())

    def test_every_look_renders_and_differs_and_is_named_right(self):
        neutral = frame([], BARS)
        means = {}
        for key in color.LOOKS:
            out = frame(color.build_filters({"look": key}), BARS)
            means[key] = mean_rgb(out)
            self.assertGreater(float(np.abs(out - neutral).mean()), 0.8, f"{key} should change the picture")
        bw = frame(color.build_filters({"look": "bw"}), BARS)
        self.assertLessEqual(float((bw.max(axis=2) - bw.min(axis=2)).max()), 2, "B&W look: R=G=B")
        bw2 = frame(color.build_filters({"look": "bw_contrast"}), BARS)
        self.assertLessEqual(float((bw2.max(axis=2) - bw2.min(axis=2)).max()), 4)
        r, g, b = means["sepia"]
        self.assertTrue(r > g > b, means["sepia"])
        self.assertGreater(means["warm_vintage"][0] - means["warm_vintage"][2], mean_rgb(neutral)[0] - mean_rgb(neutral)[2] + 8)
        self.assertGreater(means["cool_blue"][2] - means["cool_blue"][0], mean_rgb(neutral)[2] - mean_rgb(neutral)[0] + 8)
        self.assertGreater(means["golden_hour"][0] - means["golden_hour"][2], mean_rgb(neutral)[0] - mean_rgb(neutral)[2] + 8)
        spread = lambda m: max(m) - min(m)  # noqa: E731
        self.assertGreater(spread(means["vivid"]), spread(mean_rgb(neutral)) - 1)
        self.assertLess(sum(means["moody"]), sum(mean_rgb(neutral)) - 10)
        self.assertLess(self._std(frame(color.build_filters({"look": "matte"}), BARS)), self._std(neutral))

    def test_the_full_chain_parses_in_one_graph_and_reference_means_hold(self):
        everything = {"exposure": .3, "contrast": 20, "temperature": 10, "saturation": 120, "vibrance": 30, "sharpen": 40,
                      "denoise": 30, "blur": 20, "vignette": 30, "grain": 20, "wheels": {"shadows": [.1, 0, -.1]},
                      "hsl": {"red": {"h": 20, "s": 10, "l": -10}}, "curves": {"b": [[0.5, 0.6]]}, "look": "moody",
                      "look_amount": 50}
        self.assertEqual(frame(color.build_filters(everything), BARS).shape, (120, 160, 3))
        for case in REFERENCE:
            got = mean_rgb(frame(color.build_filters(case["params"]), BARS))
            for g, w in zip(got, case["mean_rgb"]):
                self.assertAlmostEqual(g, w, delta=2.0, msg=str(case["params"]))
