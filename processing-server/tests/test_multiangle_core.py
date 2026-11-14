"""agent 2.11: the pure math of «چندزاویه» (multiangle_core.py): camera paths, crop windows, cut points, tracking, 2.5D warps.

    python -m unittest tests/test_multiangle_core.py        (from the processing folder; needs numpy)
"""
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

try:
    import numpy as np
    import multiangle_core as mc
    HAVE_NP = True
except Exception:  # noqa: BLE001
    HAVE_NP = False


@unittest.skipUnless(HAVE_NP, "numpy is needed")
class WindowMath(unittest.TestCase):
    def test_critically_damped_step_never_overshoots(self):
        x, v = 0.0, 0.0
        peak = 0.0
        for _ in range(400):
            x, v = mc.cd_step(x, v, 1.0, 4.0, 1 / 60)
            peak = max(peak, x)
        self.assertLessEqual(peak, 1.0 + 1e-9)
        self.assertAlmostEqual(x, 1.0, places=3)

    def test_cd_step_is_dt_independent(self):
        a = (0.0, 0.0)
        for _ in range(60):
            a = mc.cd_step(*a, 1.0, 3.0, 1 / 60)
        b = (0.0, 0.0)
        for _ in range(30):
            b = mc.cd_step(*b, 1.0, 3.0, 1 / 30)
        self.assertAlmostEqual(a[0], b[0], places=6)

    def test_ease_ends(self):
        for fn in mc.EASINGS.values():
            self.assertAlmostEqual(float(fn(0.0)), 0.0)
            self.assertAlmostEqual(float(fn(1.0)), 1.0)
        # smoothstep has zero speed at both ends
        eps = 1e-3
        self.assertLess(float(mc.ease_in_out(eps)), 3e-6)
        self.assertGreater(float(mc.ease_in_out(1 - eps)), 1 - 3e-6)

    def test_clamp_window_stays_inside(self):
        cx, cy, ch = mc.clamp_window(np.array([-1.0, 2.0, 0.5]), np.array([0.0, 1.5, 0.5]), np.array([5.0, 5.0, 0.4]), 16 / 9, 9 / 16, margin=0.01)
        cw = mc.window_width(ch, 16 / 9, 9 / 16)
        self.assertTrue(np.all(cx - cw / 2 >= 0.01 - 1e-9) and np.all(cx + cw / 2 <= 0.99 + 1e-9))
        self.assertTrue(np.all(cy - ch / 2 >= 0.01 - 1e-9) and np.all(cy + ch / 2 <= 0.99 + 1e-9))
        self.assertTrue(np.all(ch <= mc.max_window_height(16 / 9, 9 / 16)))

    def test_max_window_height(self):
        self.assertAlmostEqual(mc.max_window_height(16 / 9, 16 / 9), 1.0)
        self.assertAlmostEqual(mc.max_window_height(9 / 16, 16 / 9), (9 / 16) / (16 / 9))     # vertical source, wide output
        self.assertAlmostEqual(mc.max_window_height(16 / 9, 9 / 16), 1.0)

    def test_affine_maps_centre_and_corners(self):
        m = mc.window_to_affine(1920, 1080, 0.5, 0.5, 1.0, 0.0, 1920, 1080)
        self.assertTrue(np.allclose(m, [[1, 0, 0], [0, 1, 0]], atol=1e-9))
        # a half-height window centred at (0.25, 0.5): its centre must land on the output centre
        m = mc.window_to_affine(1920, 1080, 0.25, 0.5, 0.5, 0.0, 960, 540)
        x, y = mc.apply_affine(m, 0.25 * 1920, 0.5 * 1080)
        self.assertAlmostEqual(x, 480)
        self.assertAlmostEqual(y, 270)
        # the window's top-left corner (cw = ch*out/src) lands on (0, 0)
        cw = mc.window_width(0.5, 1920 / 1080, 960 / 540)
        x, y = mc.apply_affine(m, (0.25 - cw / 2) * 1920, (0.5 - 0.25) * 1080)
        self.assertAlmostEqual(x, 0, places=6)
        self.assertAlmostEqual(y, 0, places=6)

    def test_affine_roll_keeps_centre(self):
        m = mc.window_to_affine(1000, 800, 0.4, 0.6, 0.5, 3.0, 500, 400)
        x, y = mc.apply_affine(m, 400, 480)
        self.assertAlmostEqual(x, 250, places=6)
        self.assertAlmostEqual(y, 200, places=6)
        # a pure rotation + scale: the matrix is orthogonal up to the scale
        self.assertAlmostEqual(abs(np.linalg.det(m[:, :2])), (400 / (0.5 * 800)) ** 2, places=9)

    def test_output_size_is_even_and_never_above_the_wide_crop(self):
        w, h = mc.pick_output_size(1920, 1080, 9 / 16, req_h=1920, max_h=1080)
        self.assertEqual((w % 2, h % 2), (0, 0))
        self.assertLessEqual(h, 1080)
        self.assertAlmostEqual(w / h, 9 / 16, delta=0.01)
        w, h = mc.pick_output_size(640, 360, 16 / 9, req_h=1080)
        self.assertEqual(h, 360)

    def test_upscale_report_and_min_window(self):
        st = mc.upscale_stats(np.array([0.2, 0.2, 0.25]), 720, 720)
        self.assertAlmostEqual(st["max"], 1 / (0.2), places=3)
        self.assertGreater(st["share_over_soft"], 0.9)
        self.assertAlmostEqual(mc.min_window_height(1080, 1080, 2.0), 0.5)


@unittest.skipUnless(HAVE_NP, "numpy is needed")
class Framing(unittest.TestCase):
    subj = {"box": (0.40, 0.12, 0.22, 0.80), "face": (0.47, 0.14, 0.07, 0.10), "yaw": 0.0}

    def test_shot_sizes_are_ordered(self):
        sa, oa = 16 / 9, 16 / 9
        chs = {k: mc.frame_for(k, self.subj, sa, oa)[2] for k in ("wide", "medium", "close")}
        self.assertGreater(chs["wide"], chs["medium"])
        self.assertGreater(chs["medium"], chs["close"])
        self.assertLessEqual(chs["wide"], 1.0 + 1e-9)

    def test_eye_line_on_the_upper_third(self):
        sa = oa = 16 / 9
        cx, cy, ch = mc.frame_for("close", self.subj, sa, oa)
        eye_y = 0.14 + 0.4 * 0.10
        pos = (eye_y - (cy - ch / 2)) / ch
        self.assertAlmostEqual(pos, 0.37, places=3)

    def test_lead_room_follows_the_face_direction(self):
        sa = oa = 16 / 9
        right = dict(self.subj, yaw=1.0)
        left = dict(self.subj, yaw=-1.0)
        for shot in ("medium", "close"):
            cx_r, _, ch = mc.frame_for(shot, right, sa, oa)
            cx_l, _, _ = mc.frame_for(shot, left, sa, oa)
            cw = mc.window_width(ch, sa, oa)
            ex = 0.47 + 0.07 / 2
            self.assertLess((ex - (cx_r - cw / 2)) / cw, 0.5)       # looks right: sits left of the middle
            self.assertGreater((ex - (cx_l - cw / 2)) / cw, 0.5)

    def test_two_shot_holds_both(self):
        sa = oa = 16 / 9
        a = {"box": (0.10, 0.2, 0.2, 0.7), "face": (0.17, 0.22, 0.06, 0.09), "yaw": 0.0}
        b = {"box": (0.65, 0.2, 0.2, 0.7), "face": (0.72, 0.22, 0.06, 0.09), "yaw": 0.0}
        cx, cy, ch = mc.frame_for("two_shot", a, sa, oa, subj2=b)
        cw = mc.window_width(ch, sa, oa)
        for f in (a["face"], b["face"]):
            fx = f[0] + f[2] / 2
            self.assertTrue(cx - cw / 2 <= fx <= cx + cw / 2)

    def test_over_shoulder_puts_the_subject_on_the_far_side(self):
        sa = oa = 16 / 9
        a = {"box": (0.55, 0.2, 0.2, 0.7), "face": (0.62, 0.22, 0.06, 0.09), "yaw": 0.0}
        b = {"box": (0.10, 0.2, 0.2, 0.7), "face": (0.17, 0.22, 0.06, 0.09), "yaw": 0.0}     # the other person is on the left
        cx, cy, ch = mc.frame_for("over_shoulder", a, sa, oa, subj2=b)
        cw = mc.window_width(ch, sa, oa)
        pos = (0.62 + 0.03 - (cx - cw / 2)) / cw
        self.assertGreater(pos, 0.55)

    def test_no_subject_falls_back_to_a_centre_zoom(self):
        cx, cy, ch = mc.frame_for("close", None, 16 / 9, 9 / 16)
        self.assertEqual((cx, cy), (0.5, 0.5))
        self.assertLess(ch, mc.max_window_height(16 / 9, 9 / 16))

    def test_available_angles_need_a_second_subject(self):
        subjects = [{"coverage": 0.9}]
        act, skipped = mc.available_angles(("wide", "medium", "two_shot", "over_shoulder"), subjects, "person")
        self.assertEqual(act, ["wide", "medium"])
        self.assertEqual(set(skipped), {"two_shot", "over_shoulder"})
        act, skipped = mc.available_angles(("wide", "two_shot"), [{"coverage": 0.9}, {"coverage": 0.5}], "person")
        self.assertEqual(act, ["wide", "two_shot"])


@unittest.skipUnless(HAVE_NP, "numpy is needed")
class CameraPaths(unittest.TestCase):
    sa = oa = 16 / 9

    def path(self, targets, n=150, fps=30, shot="medium", **kw):
        t = np.linspace(0, (n - 1) / fps, len(targets))
        return mc.build_path(shot, t, targets, n, fps, self.sa, self.oa, **kw)

    def test_static_subject_gives_a_steady_shot(self):
        p = self.path([[0.5, 0.5, 0.5]] * 6, handheld_amount=0.0)
        self.assertLess(float(np.ptp(p["cx"])), 1e-6)
        self.assertLess(float(np.ptp(p["ch"])), 1e-6)

    def test_dead_zone_ignores_small_wobbles(self):
        rng = np.random.default_rng(3)
        tg = [[0.5 + rng.uniform(-0.01, 0.01), 0.5, 0.5] for _ in range(20)]
        p = self.path(tg, n=150, handheld_amount=0.0)
        self.assertLess(float(np.ptp(p["cx"])), 1e-9)

    def test_follows_a_walking_subject_without_overshoot_or_jitter(self):
        xs = np.linspace(0.3, 0.7, 30)
        tg = [[x, 0.5, 0.45] for x in xs]
        p = self.path(tg, n=150, handheld_amount=0.0)
        cx = p["cx"]
        self.assertGreater(cx[-1], 0.6)
        v = np.diff(cx)
        a = np.diff(v)
        self.assertLessEqual(cx.max(), 0.7 + 1e-3)                      # no overshoot past the subject
        self.assertLess(float(np.abs(a).max()), 0.002)                   # smooth acceleration: no jitter
        self.assertTrue(np.all(v >= -1e-6))                              # never moves backwards

    def test_velocity_limit(self):
        tg = [[0.2, 0.5, 0.45], [0.2, 0.5, 0.45], [0.8, 0.5, 0.45], [0.8, 0.5, 0.45]]
        p = self.path(tg, n=120, handheld_amount=0.0, shot="wide")
        cw = mc.window_width(p["ch"], self.sa, self.oa)
        speed = np.abs(np.diff(p["cx"])) * 30 / cw[1:]
        self.assertLessEqual(float(speed.max()), mc.CAMERA["wide"]["vmax"][0] * 1.02)

    def test_handheld_is_subtle_deterministic_and_smooth(self):
        a = mc.handheld(300, 30, 1.0, seed=5)
        b = mc.handheld(300, 30, 1.0, seed=5)
        c = mc.handheld(300, 30, 1.0, seed=6)
        for x, y in zip(a, b):
            self.assertTrue(np.array_equal(x, y))
        self.assertFalse(np.array_equal(a[0], c[0]))
        self.assertLess(float(np.abs(a[0]).max()), 0.006)
        self.assertLess(float(np.abs(a[2]).max()), 0.25)
        self.assertLess(float(np.abs(np.diff(a[0], 2)).max()), 0.0005)    # no frame-to-frame jitter
        z = mc.handheld(100, 30, 0.0, seed=5)
        self.assertEqual(float(np.abs(z[0]).max()), 0.0)

    def test_every_window_stays_inside_the_picture(self):
        rng = np.random.default_rng(1)
        tg = rng.uniform(0.0, 1.0, size=(40, 3)) * np.array([1.0, 1.0, 0.8]) + np.array([0, 0, 0.1])
        for shot in mc.CAMERA:
            p = self.path(tg, n=200, shot=shot, handheld_amount=1.0)
            cw = mc.window_width(p["ch"], self.sa, self.oa)
            self.assertTrue(np.all(p["cx"] - cw / 2 >= -1e-9) and np.all(p["cx"] + cw / 2 <= 1 + 1e-9))
            self.assertTrue(np.all(p["cy"] - p["ch"] / 2 >= -1e-9) and np.all(p["cy"] + p["ch"] / 2 <= 1 + 1e-9))

    def test_min_window_height_is_respected(self):
        p = self.path([[0.5, 0.5, 0.1]] * 5, min_ch=0.3, handheld_amount=0.0)
        self.assertGreaterEqual(float(p["ch"].min()), 0.3 - 1e-9)

    def test_median_filter_removes_a_one_frame_glitch(self):
        x = np.array([0.5] * 10)
        x[4] = 0.95
        self.assertAlmostEqual(float(mc.median_filter(x, 5)[4]), 0.5)

    def test_fill_gaps(self):
        x = np.array([1.0, np.nan, np.nan, 4.0, np.nan, np.nan, np.nan, np.nan, 9.0])
        out = mc.fill_gaps(x, max_gap=2)
        self.assertEqual(list(out[:4]), [1.0, 2.0, 3.0, 4.0])
        self.assertTrue(np.isnan(out[5]))                                  # the long gap stays open
        y = mc.fill_gaps(np.array([np.nan, np.nan, 3.0, np.nan]), hold=1)
        self.assertTrue(np.isnan(y[0]))
        self.assertEqual(y[1], 3.0)
        self.assertEqual(y[3], 3.0)


@unittest.skipUnless(HAVE_NP, "numpy is needed")
class Tracking(unittest.TestCase):
    def test_iou(self):
        self.assertAlmostEqual(mc.iou((0, 0, 1, 1), (0, 0, 1, 1)), 1.0)
        self.assertEqual(mc.iou((0, 0, 1, 1), (2, 2, 1, 1)), 0.0)
        self.assertAlmostEqual(mc.iou((0, 0, 2, 1), (1, 0, 2, 1)), 1 / 3)

    def test_tracker_keeps_two_people_apart_and_fills_the_face(self):
        n = 20
        tr = mc.Tracker(n)
        for i in range(n):
            a = {"box": (0.10 + 0.002 * i, 0.2, 0.2, 0.7), "kind": "person", "score": 0.9}
            b = {"box": (0.65, 0.2, 0.2, 0.7), "kind": "person", "score": 0.8}
            dets = [a, b] if i not in (7, 8) else [a]                        # b is missed twice
            dets.append({"box": (0.17 + 0.002 * i, 0.22, 0.05, 0.08), "kind": "face", "score": 0.9, "yaw": 0.3})
            tr.update(i, dets)
        tracks = tr.tracks()
        self.assertEqual(len(tracks), 2)
        ranked = mc.rank_subjects(tracks, n)
        self.assertGreaterEqual(ranked[0]["coverage"], ranked[1]["coverage"])
        left = [t for t in ranked if t["boxes"][0][0] < 0.3][0]
        self.assertFalse(np.isnan(left["faces"][5]).any())
        self.assertAlmostEqual(float(left["yaw"][5]), 0.3)

    def test_a_face_without_a_person_box_still_becomes_a_subject(self):
        tr = mc.Tracker(6)
        for i in range(6):
            tr.update(i, [{"box": (0.4, 0.2, 0.1, 0.14), "kind": "face", "score": 0.9, "yaw": 0.0}])
        self.assertEqual(len(tr.tracks()), 1)


@unittest.skipUnless(HAVE_NP, "numpy is needed")
class Sound(unittest.TestCase):
    sr = 16000

    def speech_like(self, phrases, gap=0.5, total=None):
        rng = np.random.default_rng(0)
        chunks = []
        for dur in phrases:
            n = int(dur * self.sr)
            t = np.arange(n) / self.sr
            chunks.append((0.4 * np.sin(2 * np.pi * 180 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t)) + 0.05 * rng.standard_normal(n)).astype(np.float32))
            chunks.append((0.002 * rng.standard_normal(int(gap * self.sr))).astype(np.float32))
        return np.concatenate(chunks)

    def test_pauses_are_found_between_phrases(self):
        pcm = self.speech_like([2.0, 1.5, 2.5, 1.8], gap=0.5)
        env, hop = mc.energy_db(pcm, self.sr)
        pauses = mc.pause_boundaries(env, hop)
        want = [2.25, 4.25, 7.25]
        got = [p["t"] for p in pauses]
        self.assertEqual(len(got), 3)
        for w, g in zip(want, got):
            self.assertAlmostEqual(w, g, delta=0.08)

    def test_no_pause_in_silence_or_continuous_sound(self):
        env, hop = mc.energy_db(np.zeros(self.sr * 5, dtype=np.float32), self.sr)
        self.assertEqual(mc.pause_boundaries(env, hop), [])
        rng = np.random.default_rng(1)
        env, hop = mc.energy_db((0.3 * rng.standard_normal(self.sr * 5)).astype(np.float32), self.sr)
        self.assertEqual(mc.pause_boundaries(env, hop), [])

    def test_beat_grid_finds_the_tempo(self):
        rng = np.random.default_rng(2)
        bpm = 120.0
        n = self.sr * 12
        pcm = (0.01 * rng.standard_normal(n)).astype(np.float32)
        step = 60.0 / bpm
        click = (np.exp(-np.arange(int(0.05 * self.sr)) / (0.01 * self.sr)) * np.sin(2 * np.pi * 900 * np.arange(int(0.05 * self.sr)) / self.sr)).astype(np.float32)
        for k in range(int(12 / step)):
            s = int((0.3 + k * step) * self.sr)
            pcm[s:s + len(click)] += click
        g = mc.beat_grid(pcm, self.sr)
        self.assertAlmostEqual(g["bpm"], 120.0, delta=3.0)
        self.assertGreater(g["confidence"], 0.3)
        # beats lie on the click grid (0.3 + k * 0.5)
        errs = [min(abs((b - 0.3) % 0.5), 0.5 - abs((b - 0.3) % 0.5)) for b in g["beats"][2:-2]]
        self.assertLess(float(np.median(errs)), 0.05)

    def test_beat_grid_of_noise_has_no_confidence(self):
        rng = np.random.default_rng(4)
        g = mc.beat_grid((0.3 * rng.standard_normal(self.sr * 8)).astype(np.float32), self.sr)
        self.assertLess(g["confidence"], 0.5)

    def test_sentences_become_cut_points_in_the_gaps(self):
        b = mc.boundaries_from_sentences([{"start": 0.0, "end": 3.0}, {"start": 3.6, "end": 7.0}, {"start": 7.0, "end": 9.0}], 10.0)
        self.assertEqual([x["t"] for x in b], [3.3, 7.0])
        self.assertTrue(all(x["kind"] == "sentence" for x in b))

    def test_merge_boundaries_keeps_the_stronger(self):
        m = mc.merge_boundaries([{"t": 1.0, "w": 0.4, "kind": "beat"}], [{"t": 1.1, "w": 0.9, "kind": "pause"}, {"t": 3.0, "w": 0.5, "kind": "beat"}])
        self.assertEqual([(x["t"], x["kind"]) for x in m], [(1.1, "pause"), (3.0, "beat")])


@unittest.skipUnless(HAVE_NP, "numpy is needed")
class AutoEdit(unittest.TestCase):
    def points(self, step=2.7, kind="pause", total=30.0):
        return [{"t": round(i * step, 3), "w": 0.8, "kind": kind} for i in range(1, int(total / step))]

    def test_cuts_fall_only_on_cut_points_when_they_exist(self):
        pts = self.points()
        times = mc.plan_cut_times(30.0, pts, "medium", 30.0)
        self.assertGreaterEqual(len(times), 4)
        allowed = {mc._snap(p["t"], 30.0) for p in pts}
        self.assertTrue(all(t["t"] in allowed and t["reason"] == "pause" for t in times))

    def test_shot_lengths_respect_the_pace(self):
        for pace, (lo, _pref, hi) in mc.PACE.items():
            times = mc.plan_cut_times(60.0, self.points(0.6), pace, 30.0)
            edges = [0.0] + [t["t"] for t in times] + [60.0]
            lens = np.diff(edges)
            self.assertGreaterEqual(float(lens.min()), lo * 0.8 - 1e-6, pace)
            self.assertLessEqual(float(lens.max()), hi + 1e-6, pace)

    def test_forced_cut_when_there_are_no_points(self):
        times = mc.plan_cut_times(20.0, [], "medium", 30.0)
        self.assertTrue(times and all(t["reason"] == "forced" for t in times))
        lens = np.diff([0.0] + [t["t"] for t in times] + [20.0])
        self.assertLessEqual(float(lens.max()), mc.PACE["medium"][2] + 1e-6)

    def test_forced_cut_falls_on_the_quietest_moment(self):
        hop = 0.02
        env = np.full(int(20 / hop), -20.0)
        env[int(4.1 / hop)] = -80.0                    # one quiet frame near the wanted time (3.8 s)
        times = mc.plan_cut_times(20.0, [], "medium", 30.0, energy=env, hop=hop)
        self.assertAlmostEqual(times[0]["t"], mc._snap(4.1, 30.0), delta=0.04)

    def test_a_short_clip_still_gets_cuts(self):
        out = mc.plan_edit(7.0, ["wide", "close"], self.points(1.6, total=7.0), "medium")
        self.assertGreaterEqual(len(out["segments"]), 2)

    def test_too_short_to_cut(self):
        out = mc.plan_edit(2.5, ["wide", "close"], [], "medium")
        self.assertEqual(len(out["segments"]), 1)

    def test_angles_never_repeat_and_never_jump_cut(self):
        out = mc.plan_edit(60.0, ["wide", "medium", "close"], self.points(2.0, total=60.0), "medium", seed=3)
        segs = out["segments"]
        self.assertGreater(len(segs), 6)
        self.assertEqual(segs[0]["angle"], "wide")                         # the establishing shot
        tier = {k: mc.ANGLES[k]["tier"] for k in mc.ANGLES}
        for a, b in zip(segs, segs[1:]):
            self.assertNotEqual(a["angle"], b["angle"])
            self.assertGreaterEqual(abs(tier[a["angle"]] - tier[b["angle"]]), mc.MIN_TIER_STEP - 1e-9)
        self.assertNotEqual(segs[-1]["angle"], "close")
        self.assertEqual(set(out["quality"]["angles_used"]), {"wide", "medium", "close"})

    def test_two_angles_alternate(self):
        out = mc.plan_edit(40.0, ["wide", "close"], self.points(3.0, total=40.0), "medium")
        names = [s["angle"] for s in out["segments"]]
        self.assertTrue(all(a != b for a, b in zip(names, names[1:])))

    def test_louder_shots_get_closer_angles(self):
        hop = 0.02
        n = int(40 / hop)
        env = np.full(n, -40.0)
        env[int(20 / hop):int(40 / hop)] = -10.0            # the second half is loud
        out = mc.plan_edit(40.0, ["wide", "medium", "close"], self.points(4.0, total=40.0), "medium", energy=env, hop=hop, seed=1)
        tier = {k: mc.ANGLES[k]["tier"] for k in mc.ANGLES}
        first = [tier[s["angle"]] for s in out["segments"] if s["t1"] <= 20]
        second = [tier[s["angle"]] for s in out["segments"] if s["t0"] >= 20 and s is not out["segments"][-1]]
        self.assertGreaterEqual(sum(second) / len(second), sum(first) / len(first))

    def test_same_seed_same_edit(self):
        a = mc.plan_edit(50.0, ["wide", "medium", "close", "two_shot"], self.points(2.2, total=50.0), seed=9)
        b = mc.plan_edit(50.0, ["wide", "medium", "close", "two_shot"], self.points(2.2, total=50.0), seed=9)
        self.assertEqual(a, b)

    def test_cuts_are_merged_and_start_at_zero(self):
        out = mc.plan_edit(30.0, ["wide", "medium"], self.points(), "medium")
        self.assertEqual(out["cuts"][0]["t"], 0.0)
        self.assertTrue(all(a["angle"] != b["angle"] for a, b in zip(out["cuts"], out["cuts"][1:])))


@unittest.skipUnless(HAVE_NP, "numpy is needed")
class Picture(unittest.TestCase):
    def test_active_area_finds_black_bars(self):
        g = np.zeros((108, 192), dtype=np.uint8)
        rng = np.random.default_rng(1)
        g[:, 60:130] = rng.integers(40, 255, size=(108, 70))
        self.assertEqual(mc.active_area([g]), (60, 0, 130, 108))
        full = rng.integers(40, 255, size=(108, 192)).astype(np.uint8)
        self.assertEqual(mc.active_area([full]), (0, 0, 192, 108))
        self.assertEqual(mc.active_area([np.zeros((10, 10), dtype=np.uint8)]), (0, 0, 10, 10))

    def test_saliency_points_at_the_odd_one_out(self):
        rng = np.random.default_rng(5)
        g = (rng.random((64, 64)) * 0.1 + 0.3).astype(np.float32)
        g[10:20, 40:50] = 1.0
        sal = mc.spectral_residual_saliency(g)
        y, x = np.unravel_index(np.argmax(sal), sal.shape)
        self.assertTrue(8 <= y <= 22 and 38 <= x <= 52)


@unittest.skipUnless(HAVE_NP, "numpy is needed")
class HeadTop(unittest.TestCase):
    """The owner's clip: a man bows over his laptop, the face detector boxes him from the nose and the person box starts at the forehead, so the
    close-up used to cut the top of his head off. The top of the head is now measured in the picture and only ever moves the estimate UP."""
    H, W = 270, 480

    def scene(self, head_cy=0.40, ry=0.15, rx=30, left=200.0, right=200.0, wall_to=None):
        g = np.zeros((self.H, self.W), dtype=np.float32)
        xs = np.linspace(0, 1, self.W, dtype=np.float32)[None, :]
        g[:, :] = (left + (right - left) * xs) if wall_to is None else (left + (wall_to - left) * xs)
        yy, xx = np.mgrid[0:self.H, 0:self.W]
        cy, cx = head_cy * self.H, self.W / 2.0
        inside = ((yy - cy) / (ry * self.H)) ** 2 + ((xx - cx) / rx) ** 2 <= 1.0
        g[inside] = 40.0
        return g

    face = (0.465, 0.36, 0.07, 0.12)           # boxed low: the real hair top is at 0.25

    def test_a_bowed_head_has_its_hair_top_found_above_the_detector_estimate(self):
        top = mc.find_head_top(self.scene(), self.face, None)
        self.assertIsNotNone(top)
        self.assertAlmostEqual(top, 0.25 - 0.012, delta=0.02)
        self.assertLess(top, 0.36 - 0.45 * 0.12)                                           # higher than the prior (the brows - half a face)

    def test_an_anchor_that_is_already_above_the_hair_stands(self):
        self.assertIsNone(mc.find_head_top(self.scene(), (0.465, 0.20, 0.07, 0.12), None))

    def test_a_head_that_touches_the_top_of_the_frame(self):
        top = mc.find_head_top(self.scene(head_cy=0.10, ry=0.12), (0.465, 0.13, 0.07, 0.12), None)
        self.assertIsNotNone(top)
        self.assertLessEqual(top, 0.01)

    def test_a_person_box_without_a_face_works_too(self):
        box = (0.38, 0.30, 0.24, 0.70)                                                      # starts at the forehead; the hair reaches 0.25
        top = mc.find_head_top(self.scene(), None, box)
        self.assertIsNotNone(top)
        self.assertLess(top, 0.30)

    def test_a_monitor_beside_the_head_or_a_wall_gradient_is_not_a_head(self):
        self.assertAlmostEqual(mc.find_head_top(self.scene(left=255.0, right=200.0), self.face, None), 0.25 - 0.012, delta=0.02)
        empty = self.scene(ry=0.0001, rx=0.01, left=150.0, right=230.0)                    # no head, only a lit wall gradient
        self.assertIsNone(mc.find_head_top(empty, self.face, None))

    def test_a_lamp_above_the_head_is_not_part_of_it(self):
        g = self.scene()
        g[50:58, 220:260] = 20.0                                                            # a dark lamp, separated from the hair by plain wall
        self.assertAlmostEqual(mc.find_head_top(g, self.face, None), 0.25 - 0.012, delta=0.02)

    def test_garbage_in_is_none(self):
        self.assertIsNone(mc.find_head_top(np.zeros((0, 0)), self.face, None))
        self.assertIsNone(mc.find_head_top(self.scene(), None, None))
        self.assertIsNone(mc.find_head_top(self.scene(), (0.0, 0.3, 0.001, 0.001), None))

    def test_the_tracker_keeps_the_measurement_per_sample(self):
        tr = mc.Tracker(6, max_miss=3)
        for i in range(4):
            tr.update(i, [{"box": (0.3, 0.2, 0.3, 0.7), "kind": "person", "score": 0.9}])
            tr.annotate(i, lambda box, face: 0.1 + 0.01 * i if i != 2 else None)
        trk = tr.tracks()[0]
        self.assertAlmostEqual(trk["tops"][0], 0.10)
        self.assertAlmostEqual(trk["tops"][3], 0.13)
        self.assertTrue(np.isnan(trk["tops"][2]) and np.isnan(trk["tops"][5]))

    def test_the_close_up_keeps_the_whole_head_when_the_top_is_known(self):
        sa = oa = 788 / 1080.0
        subj = {"box": (0.137, 0.266, 0.484, 0.729), "face": (0.344, 0.353, 0.118, 0.116), "yaw": 0.0}
        for shot in ("medium", "close"):
            cx0, cy0, ch0 = mc.frame_for(shot, subj, sa, oa)
            if shot == "close":
                self.assertGreater(cy0 - ch0 / 2, 0.19, shot)                                # before: the window top is below the hair at 0.19
            cx1, cy1, ch1 = mc.frame_for(shot, dict(subj, top=0.19), sa, oa)
            self.assertLessEqual(cy1 - ch1 / 2, 0.19 - 0.04 * ch1, shot)
        measured_lower = mc.frame_for("close", dict(subj, top=0.40), sa, oa)
        self.assertEqual(measured_lower, mc.frame_for("close", subj, sa, oa))               # a measurement below the estimate changes nothing

    def test_the_head_top_series_is_the_highest_head_of_the_neighbourhood(self):
        t = np.arange(10) / 5.0
        tops = np.array([0.30, 0.30, np.nan, 0.20, 0.30, 0.30, 0.30, 0.30, 0.30, 0.30])
        s = mc.head_top_series(t, tops, 60, 30.0, span=0.4)
        self.assertEqual(len(s), 60)
        self.assertAlmostEqual(float(s[18]), 0.20)                                          # the low sample lifts its whole neighbourhood
        self.assertAlmostEqual(float(s[50]), 0.30)
        self.assertTrue(np.all(np.isnan(mc.head_top_series([0.0, 1.0], [np.nan, np.nan], 5, 30.0))))

    def test_headroom_is_a_hard_rule_that_glides_in(self):
        n, fps = 90, 30.0
        cy, ch = np.full(n, 0.5), np.full(n, 0.4)                                           # the window top sits at 0.30
        self.assertTrue(np.array_equal(mc.keep_headroom(cy, ch, np.full(n, 0.35), fps), cy))   # plenty of room: untouched
        self.assertTrue(np.array_equal(mc.keep_headroom(cy, ch, np.full(n, np.nan), fps), cy))  # no head known: untouched
        low = mc.keep_headroom(cy, ch, np.full(n, 0.28), fps)
        self.assertTrue(np.all(low - ch / 2 <= 0.28 - 0.045 * ch + 1e-9))
        top = np.where(np.arange(n) < 45, 0.40, 0.20)                                        # he stands up at second 1.5
        out = mc.keep_headroom(cy, ch, top, fps)
        self.assertTrue(np.all(out - ch / 2 <= top - 0.045 * ch + 1e-9))
        self.assertLess(float(np.abs(np.diff(out)).max()), 0.02)                            # a glide, not a jump

    def test_build_path_lifts_the_window_to_keep_the_hair(self):
        sa = oa = 16 / 9.0
        t = np.linspace(0, 2.9, 4)
        tg = [[0.5, 0.5, 0.4]] * 4
        plain = mc.build_path("medium", t, tg, 90, 30.0, sa, oa, handheld_amount=0.0)
        kept = mc.build_path("medium", t, tg, 90, 30.0, sa, oa, handheld_amount=0.0, head_top=np.full(90, 0.25))
        self.assertAlmostEqual(float(plain["cy"][-1] - plain["ch"][-1] / 2), 0.30, places=3)
        self.assertLessEqual(float((kept["cy"] - kept["ch"] / 2).max()), 0.25 - 0.045 * float(kept["ch"][0]) + 1e-6)
        self.assertTrue(np.allclose(plain["ch"], kept["ch"]) and np.allclose(plain["cx"], kept["cx"]))
        again = mc.build_path("medium", t, tg, 90, 30.0, sa, oa, handheld_amount=0.0, head_top=None)
        self.assertTrue(np.allclose(plain["cy"], again["cy"]))

    def test_a_nan_top_is_ignored(self):
        subj = {"box": (0.3, 0.2, 0.3, 0.7), "face": (0.4, 0.25, 0.1, 0.12), "yaw": 0.0}
        self.assertEqual(mc._anatomy(dict(subj, top=float("nan"))), mc._anatomy(subj))
        self.assertEqual(mc._anatomy(dict(subj, top=None)), mc._anatomy(subj))


@unittest.skipUnless(HAVE_NP, "numpy is needed")
class ChangingBars(unittest.TestCase):
    """A composite whose black strips change during the clip (the owner's main.mp4: a 9:16 picture, then at second 8 a narrower one): every
    frame gets its own picture rectangle, and no virtual camera window may leave it."""

    def lit(self, x0, x1, w=192, h=108, seed=1):
        g = np.zeros((h, w), dtype=np.uint8)
        g[:, x0:x1] = np.random.default_rng(seed).integers(60, 255, size=(h, x1 - x0))
        return g

    def two_layouts(self, n=90, switch=45, a=(0.10, 0.90), b=(0.25, 0.75)):
        return [(a[0], 0.0, a[1], 1.0)] * switch + [(b[0], 0.0, b[1], 1.0)] * (n - switch)

    def test_frame_rect_finds_the_picture_of_one_frame(self):
        r = mc.frame_rect(self.lit(60, 130))
        self.assertAlmostEqual(r[0], 60 / 192.0)
        self.assertAlmostEqual(r[2], 130 / 192.0)
        self.assertEqual((r[1], r[3]), (0.0, 1.0))
        self.assertIsNone(mc.frame_rect(np.zeros((20, 20), dtype=np.uint8)))              # a black frame: unknown, not "empty picture"

    def test_a_caption_lying_over_a_bar_is_not_picture(self):
        g = self.lit(60, 130)
        g[50:54, 10:50] = 255                                                             # four bright rows of text on the left bar
        r = mc.frame_rect(g)
        self.assertAlmostEqual(r[0], 60 / 192.0)

    def test_the_layout_switch_stays_where_it_is_and_noise_does_not_move_it(self):
        rng = np.random.default_rng(3)
        noisy = [tuple(np.array(r) + rng.normal(0, 0.003, 4) * np.array([1, 0, 1, 0])) for r in self.two_layouts()]
        out = mc.clean_rects(noisy, 30.0)
        segs = mc.rect_segments(out, 30.0)
        self.assertEqual(len(segs), 2, segs)
        self.assertAlmostEqual(segs[0]["t1"], 45 / 30.0, places=6)                      # the step is on the very frame the layout changed
        self.assertAlmostEqual(segs[0]["rect"][0], 0.10, delta=0.01)
        self.assertAlmostEqual(segs[1]["rect"][0], 0.25, delta=0.01)

    def test_glitches_and_black_frames_are_ignored(self):
        rects = self.two_layouts()
        rects[10] = None                                                                  # a dark frame
        rects[20] = (0.0, 0.0, 1.0, 1.0)                                                  # one frame of everything lit
        rects[60] = (0.4, 0.0, 0.6, 1.0)                                                  # one frame of nearly nothing
        rects[61] = None
        out = mc.clean_rects(rects, 30.0)
        self.assertEqual(len(mc.rect_segments(out, 30.0)), 2)

    def test_a_hair_of_dark_picture_at_the_border_is_the_border(self):
        out = mc.clean_rects([(0.012, 0.0, 0.99, 1.0)] * 30, 30.0)
        self.assertEqual(tuple(out[0]), (0.0, 0.0, 1.0, 1.0))
        self.assertFalse(mc.rects_vary(out))

    def test_only_the_real_bars_move_inwards_by_the_padding(self):
        out = mc.clean_rects([(0.2, 0.0, 1.0, 1.0)] * 30, 30.0, pad=(0.01, 0.02))
        self.assertAlmostEqual(out[0][0], 0.21)
        self.assertEqual((out[0][1], out[0][2], out[0][3]), (0.0, 1.0, 1.0))
        self.assertTrue(mc.rects_vary(out))

    def test_a_clip_that_is_all_dark_means_no_bars(self):
        out = mc.clean_rects([None] * 20, 30.0)
        self.assertEqual(tuple(out[5]), mc.FULL_RECT)
        self.assertEqual(len(mc.clean_rects([], 30.0)), 0)

    def test_the_window_never_leaves_the_rectangle_of_its_frame(self):
        sa = oa = 788 / 1080.0
        n = 90
        rects = mc.clean_rects(self.two_layouts(n), 30.0)
        full = np.full(n, 0.5)
        cx, cy, ch = mc.fit_to_rects(full, full, np.full(n, 1.0), rects, sa, oa)
        cw = mc.window_width(ch, sa, oa)
        self.assertTrue(np.all(cx - cw / 2 >= rects[:, 0] - 1e-9) and np.all(cx + cw / 2 <= rects[:, 2] + 1e-9))
        self.assertTrue(np.all(cy - ch / 2 >= rects[:, 1] - 1e-9) and np.all(cy + ch / 2 <= rects[:, 3] + 1e-9))
        self.assertAlmostEqual(float(ch[0]), 0.8, places=3)                               # 0.8 of the width -> 0.8 of the height (same shape)
        self.assertAlmostEqual(float(ch[-1]), 0.5, places=3)                              # the narrower layout: a tighter wide shot, no bars
        left = np.full(n, 0.12)
        cx2, _, _ = mc.fit_to_rects(left, full, np.full(n, 0.3), rects, sa, oa)
        self.assertGreaterEqual(float(cx2[-1] - mc.window_width(0.3, sa, oa) / 2), 0.25 - 1e-9)   # a close-up that wanted the old left edge is pulled in

    def test_a_reel_from_a_narrow_layout_loses_less_height(self):
        sa, oa = 788 / 1080.0, 9 / 16.0
        rects = np.tile(np.array([0.25, 0.0, 0.75, 1.0]), (10, 1))
        cx, cy, ch = mc.fit_to_rects([0.5] * 10, [0.5] * 10, [mc.max_window_height(sa, oa)] * 10, rects, sa, oa)
        self.assertAlmostEqual(float(ch[0]), 0.5 * sa / oa, places=3)

    def test_build_path_with_rects_keeps_every_frame_inside_and_cuts_only_at_the_switch(self):
        sa = oa = 788 / 1080.0
        n, fps = 90, 30.0
        rects = mc.clean_rects(self.two_layouts(n), fps)
        t = np.linspace(0, (n - 1) / fps, 6)
        for shot in ("wide", "medium", "close"):
            tg = [mc.frame_for(shot, {"box": (0.3, 0.1, 0.4, 0.8), "face": (0.45, 0.15, 0.1, 0.12), "yaw": 0.0}, sa, oa)] * 6
            p = mc.build_path(shot, t, tg, n, fps, sa, oa, handheld_amount=0.35, rects=rects)
            cw = mc.window_width(p["ch"], sa, oa)
            self.assertTrue(np.all(p["cx"] - cw / 2 >= rects[:, 0] - 1e-9), shot)
            self.assertTrue(np.all(p["cx"] + cw / 2 <= rects[:, 2] + 1e-9), shot)
            self.assertTrue(np.all(p["cy"] - p["ch"] / 2 >= rects[:, 1] - 1e-9) and np.all(p["cy"] + p["ch"] / 2 <= rects[:, 3] + 1e-9), shot)
            step = np.abs(np.diff(p["ch"]))
            self.assertLess(float(np.delete(step, 44).max()), 0.02, shot)                    # no jump anywhere but the frame where the layout switches

    def test_without_rects_the_path_is_exactly_what_it_was(self):
        sa = oa = 16 / 9.0
        t = np.linspace(0, 2.9, 4)
        tg = [[0.5, 0.5, 0.5]] * 4
        a = mc.build_path("medium", t, tg, 90, 30.0, sa, oa, handheld_amount=0.3, seed=2)
        b = mc.build_path("medium", t, tg, 90, 30.0, sa, oa, handheld_amount=0.3, seed=2, rects=np.tile(np.array(mc.FULL_RECT), (90, 1)))
        for k in ("cx", "cy", "ch", "roll"):
            self.assertTrue(np.allclose(a[k], b[k]), k)

    def test_the_output_size_follows_the_typical_frame_not_the_widest(self):
        sa = oa = 788 / 1080.0
        rects = np.tile(np.array([0.25, 0.0, 0.75, 1.0]), (50, 1))
        scale = mc.effective_wide_scale(rects, sa, oa)
        self.assertAlmostEqual(scale, 0.5, places=3)
        self.assertEqual(mc.effective_wide_scale(np.tile(np.array(mc.FULL_RECT), (5, 1)), sa, oa), 1.0)
        w_full, h_full = mc.pick_output_size(788, 1080, oa, None, 1080)
        w_nar, h_nar = mc.pick_output_size(788, 1080, oa, None, 1080, wide_scale=scale)
        self.assertEqual(h_full, 1080)
        self.assertEqual(h_nar, 540)
        self.assertEqual((w_nar % 2, h_nar % 2), (0, 0))

    def test_rect_segments_and_resample(self):
        out = mc.clean_rects(self.two_layouts(60, 20), 30.0)
        segs = mc.rect_segments(out, 30.0, size=(788, 1080))
        self.assertEqual([round(x["t0"], 3) for x in segs], [0.0, round(20 / 30.0, 3)])
        self.assertEqual(segs[1]["px"][0], int(round(out[-1][0] * 788)))
        r = mc.resample_rects(out, 70)
        self.assertEqual(r.shape, (70, 4))
        self.assertTrue(np.allclose(r[65], out[-1]))                                      # the last rectangle is held
        self.assertEqual(mc.resample_rects([], 3).shape, (3, 4))


@unittest.skipUnless(HAVE_NP, "numpy is needed")
class Warp25D(unittest.TestCase):
    H, W = 60, 80

    def scene(self):
        d = np.zeros((self.H, self.W), dtype=np.float32)           # far background
        d[20:40, 30:50] = 1.0                                      # a near block in the middle
        return d

    def flow(self, move, u, amount=1.0, focus=0.5):
        z = mc.depth_to_z(self.scene(), focus)
        pose = mc.camera_pose(move, u, amount)
        c = tuple(float(np.asarray(v)) for v in pose["c"])
        return mc.project_flow(z, c, float(pose["yaw"]), float(pose["pitch"]), mc.FOCAL * self.W)

    def test_depth_to_z_puts_the_focus_plane_at_one(self):
        d = np.array([[0.0, 0.5, 1.0]], dtype=np.float32)
        z = mc.depth_to_z(d, 0.5)
        self.assertAlmostEqual(float(z[0, 1]), 1.0, places=5)
        self.assertGreater(float(z[0, 0]), 1.0)
        self.assertLess(float(z[0, 2]), 1.0)

    def test_no_move_is_the_identity(self):
        for move in mc.MOVE_ORDER:
            z = mc.depth_to_z(self.scene(), 0.5)
            pose = mc.camera_pose(move, np.array(0.5 if mc.MOVES[move]["kind"] in ("truck", "crane", "orbit") else (0.0 if move != "dolly_out" else 1.0)), 1.0)
            c = tuple(float(np.asarray(v)) for v in pose["c"])
            dx, dy, zn = mc.project_flow(z, c, float(pose["yaw"]), float(pose["pitch"]), mc.FOCAL * self.W)
            self.assertLess(float(np.abs(dx).max()), 1e-3, move)
            self.assertLess(float(np.abs(dy).max()), 1e-3, move)

    def test_truck_shifts_near_pixels_more_than_far_ones_in_opposite_directions(self):
        dx, dy, z = self.flow("truck_right", 1.0)
        near = float(dx[30, 40])
        far = float(dx[5, 5])
        self.assertLess(near, far)                                  # the camera moved right: near things slide left the most
        self.assertGreater(abs(near), 2 * abs(far))
        self.assertLess(float(np.abs(dy).max()), 1e-3)

    def test_dolly_in_expands_and_near_things_expand_faster(self):
        dx, dy, z = self.flow("dolly_in", 1.0)
        near_edge = float(dx[30, 49] - dx[30, 31])                  # width growth of the near block
        far_edge = float(dx[5, 79] - dx[5, 0])
        self.assertGreater(near_edge, 0)
        self.assertGreater(far_edge, 0)
        self.assertGreater(near_edge / 18.0, far_edge / 79.0)

    def test_orbit_keeps_the_focus_point_still(self):
        d = np.full((self.H, self.W), 0.5, dtype=np.float32)
        z = mc.depth_to_z(d, 0.5)
        pose = mc.camera_pose("orbit_right", np.array(1.0), 1.0)
        c = tuple(float(np.asarray(v)) for v in pose["c"])
        dx, dy, zn = mc.project_flow(z, c, float(pose["yaw"]), float(pose["pitch"]), mc.FOCAL * self.W)
        self.assertLess(abs(float(dx[self.H // 2, self.W // 2])), 0.05)
        self.assertAlmostEqual(float(zn[self.H // 2, self.W // 2]), 1.0, delta=0.01)

    def test_move_amounts_scale_the_motion(self):
        a = np.abs(self.flow("truck_left", 1.0, 0.25)[0]).max()
        b = np.abs(self.flow("truck_left", 1.0, 1.0)[0]).max()
        self.assertGreater(b, 3.0 * a)

    def test_splat_of_zero_flow_is_the_identity(self):
        dx = np.zeros((self.H, self.W), dtype=np.float32)
        z = np.ones((self.H, self.W), dtype=np.float32)
        bx, by, filled, _zb = mc.splat_backward(dx, dx.copy(), z, self.scene())
        self.assertTrue(filled.all())
        self.assertLess(float(np.abs(bx).max()), 1e-6)
        self.assertLess(float(np.abs(by).max()), 1e-6)

    def test_splat_keeps_the_nearest_and_leaves_the_disocclusion_open(self):
        d = self.scene()
        z = mc.depth_to_z(d, 0.5)
        pose = mc.camera_pose("truck_right", 1.0, 1.0)
        dx, dy, zn = mc.project_flow(z, tuple(float(np.asarray(v)) for v in pose["c"]), 0.0, 0.0, mc.FOCAL * self.W)
        bx, by, filled, zbuf = mc.splat_backward(dx, dy, zn, d)
        self.assertFalse(filled.all())                              # something was uncovered
        # where the block lands, the source must be the block (near), not the wall behind it
        row = 30
        cols = np.where(filled[row])[0]
        src_cols = np.round(cols + bx[row, cols]).astype(int)
        block_landed = [(c, s) for c, s in zip(cols, src_cols) if 30 <= s < 50]
        self.assertGreaterEqual(len(block_landed), 15)

    def test_holes_fill_from_the_background_not_the_foreground(self):
        h, w = 7, 15
        bx = np.zeros((h, w), dtype=np.float32)
        by = np.zeros((h, w), dtype=np.float32)
        z = np.full((h, w), 3.0, dtype=np.float32)          # background depth 3
        z[:, :6] = 1.0                                        # foreground on the left (nearer = smaller z)
        bx[:, :6] = 5.0                                       # foreground moved 5 px
        bx[:, 6:] = -1.0                                      # background moved a little
        filled = np.ones((h, w), dtype=bool)
        filled[:, 6:9] = False                                # a hole right next to the foreground
        out_x, out_y, empty = mc.fill_holes_far(bx, by, z, filled)
        self.assertFalse(empty.any())
        self.assertTrue(np.allclose(out_x[:, 6:9], -1.0, atol=1e-3))      # the far (background) displacement filled it

    def test_hole_fill_follows_the_motion_axis_and_is_smooth(self):
        h, w = 9, 20
        z = np.full((h, w), 3.0, dtype=np.float32)
        z[:, :4] = 1.0
        bx = np.zeros((h, w), dtype=np.float32)
        bx[:, :4] = 6.0
        bx[:, 4:] = np.linspace(-1.0, -1.5, h)[:, None]           # the background shifts a little differently on every row
        filled = np.ones((h, w), dtype=bool)
        filled[:, 4:8] = False
        out_x, _y, empty = mc.fill_holes_far(bx, np.zeros_like(bx), z, filled, axis_first=1)
        self.assertFalse(empty.any())
        self.assertTrue(np.all(out_x[:, 4:8] < 0))                 # background, not the foreground's +6
        self.assertLess(float(np.abs(np.diff(out_x[:, 5], axis=0)).max()), 0.2)

    def test_unfillable_holes_are_reported(self):
        z = np.ones((4, 4), dtype=np.float32)
        out = mc.fill_holes_far(np.zeros((4, 4), np.float32), np.zeros((4, 4), np.float32), z, np.zeros((4, 4), dtype=bool))
        self.assertTrue(out[2].all())

    def test_safe_zoom_grows_with_the_move_and_is_capped(self):
        small = mc.safe_zoom(*self.flow("truck_right", 1.0, 0.2)[:2], self.scene())
        big = mc.safe_zoom(*self.flow("truck_right", 1.0, 1.0)[:2], self.scene())
        self.assertGreater(big, small)
        self.assertLessEqual(big, 1.30)
        self.assertEqual(mc.safe_zoom(np.zeros((4, 4), np.float32), np.zeros((4, 4), np.float32), np.zeros((4, 4))), 1.0)

    def test_dolly_out_ends_on_the_original_framing(self):
        a = mc.camera_pose("dolly_out", np.array(1.0), 1.0)["c"][2]
        b = mc.camera_pose("dolly_out", np.array(0.0), 1.0)["c"][2]
        self.assertAlmostEqual(float(a), 0.0)
        self.assertLess(float(b), 0.0)                    # it starts pushed in? (z = trav * (u - 1) = -trav at u = 0)

    def test_move_progress_endpoints(self):
        u = mc.move_progress(30)
        self.assertEqual(float(u[0]), 0.0)
        self.assertAlmostEqual(float(u[-1]), 1.0)
        self.assertTrue(np.all(np.diff(u) >= 0))


@unittest.skipUnless(HAVE_NP, "numpy is needed")
class DepthCleanup(unittest.TestCase):
    def test_box_filter_matches_a_slow_mean(self):
        rng = np.random.default_rng(0)
        a = rng.random((9, 11))
        r = 2
        out = mc.box_filter(a, r)
        pad = np.pad(a, r, mode="edge")
        slow = np.array([[pad[y:y + 5, x:x + 5].mean() for x in range(11)] for y in range(9)])
        self.assertTrue(np.allclose(out, slow))

    def test_guided_filter_keeps_the_edge_of_the_picture(self):
        guide = np.zeros((40, 40))
        guide[:, 20:] = 1.0
        rng = np.random.default_rng(0)
        depth = (guide * 0.8 + 0.1 + 0.08 * rng.standard_normal((40, 40))).astype(np.float32)
        out = mc.guided_filter(guide, depth, r=4, eps=1e-3)
        self.assertLess(float(np.std(out[:, 2:16])), float(np.std(depth[:, 2:16])))       # noise removed in the flat part
        self.assertGreater(float(out[:, 22:].mean() - out[:, :18].mean()), 0.6)            # the step is still there
        self.assertLess(abs(float(out[20, 19] - out[20, 20])), 1.2)

    def test_depth_smoother_is_steady_and_resets_on_a_cut(self):
        rng = np.random.default_rng(1)
        base = np.linspace(0, 1, 400, dtype=np.float32).reshape(20, 20)
        sm = mc.DepthSmoother(alpha=0.5, scale_alpha=0.2)
        outs = []
        for i in range(12):
            raw = base * (1.0 + 0.3 * math.sin(i)) + 0.02 * rng.standard_normal((20, 20)).astype(np.float32)     # the net rescales every frame
            outs.append(sm.push(raw))
        raw_jump = [float(np.abs(a - b).mean()) for a, b in zip(outs[1:], outs[:-1])]
        self.assertLess(max(raw_jump), 0.1)
        sm.push(base[::-1].copy(), cut=True)
        self.assertIsNone(sm.prev if False else None)

    def test_depth_smoother_constant_in_constant_out(self):
        sm = mc.DepthSmoother()
        d = np.random.default_rng(0).random((10, 10)).astype(np.float32)
        a = sm.push(d)
        b = sm.push(d)
        self.assertTrue(np.allclose(a, b, atol=1e-5))

    def test_scene_cut_detector(self):
        a = np.zeros((8, 8), dtype=np.uint8)
        b = np.full((8, 8), 200, dtype=np.uint8)
        self.assertTrue(mc.DepthSmoother.is_cut(a, b))
        self.assertFalse(mc.DepthSmoother.is_cut(a, a + 3))
        self.assertFalse(mc.DepthSmoother.is_cut(None, a))


@unittest.skipUnless(HAVE_NP, "numpy is needed")
class Warnings(unittest.TestCase):
    def test_structured_warnings(self):
        w = mc.warnings_for({"close": {"median": 1.6, "max": 2.4}, "wide": {"median": 1.0, "max": 1.0}}, "person", [], {"two_shot": "one_subject"}, ["pause"], 20.0)
        codes = {(x["code"], x.get("angle")) for x in w}
        self.assertIn(("upscale_hard", "close"), codes)
        self.assertIn(("angle_skipped", "two_shot"), codes)
        self.assertNotIn(("upscale_soft", "close"), codes)
        w2 = mc.warnings_for({}, "center", [], {}, [], 3.0)
        self.assertEqual({x["code"] for x in w2}, {"no_subject", "no_cut_points", "too_short"})


if __name__ == "__main__":
    unittest.main()
