"""Where a quick draft is rendered (services/editing/placement.py): the estimate and the decision, with the numbers in one place.

No Django, no files, no node: pure functions. The end-to-end behaviour (a fake node, the fallback, the label) is in
apps/content/tests_node_render.py.
"""
from unittest import TestCase, mock

from services.editing import placement as pl
from services.editing.timeline import Clip, TextClip, Timeline, Track

HEAVY_LOOK = {"denoise": 40, "blur": 30, "sharpen": 20, "vignette": 15, "grain": 10}


def line(length, *, w=1080, h=1920, fps=30, color=None, extra_layers=0, mask=None, chroma=None, second=False, transition=None):
    """A timeline of one `length`-second clip on the base track (plus `extra_layers` overlays of the same length, plus a
    `second` clip after the first that comes in with `transition`)."""
    def clip(**kw):
        return Clip(source="/x/a.mp4", at=0.0, start=0.0, end=float(length), color=dict(color or {}), mask=dict(mask or {}),
                    chroma=dict(chroma or {}), **kw)

    tracks = [Track(kind="video", clips=[clip()])]
    tracks += [Track(kind="video", clips=[clip()]) for _ in range(extra_layers)]
    if second:
        tracks[0].clips.append(Clip(source="/x/b.mp4", at=float(length), start=0.0, end=float(length), transition=transition))
    return Timeline(tracks=tracks, width=w, height=h, fps=fps)


class EstimateTests(TestCase):
    def test_a_plain_draft_costs_about_half_a_second_per_second_at_the_reference_picture(self):
        est = pl.estimate_site_seconds(line(60, w=1280, h=720, fps=30))
        self.assertAlmostEqual(est, 30.0, delta=1.0)

    def test_the_picture_size_and_frame_rate_scale_the_cost(self):
        small = pl.estimate_site_seconds(line(60, w=1280, h=720, fps=30))
        reel = pl.estimate_site_seconds(line(60, w=1080, h=1920, fps=30))
        self.assertAlmostEqual(reel / small, 2.25, delta=0.05)
        self.assertAlmostEqual(pl.estimate_site_seconds(line(60, w=1280, h=720, fps=60)) / small, 2.0, delta=0.05)

    def test_effects_make_it_heavier_and_a_keyframed_mask_most_of_all(self):
        plain = pl.estimate_site_seconds(line(30, w=1280, h=720))
        looks = pl.estimate_site_seconds(line(30, w=1280, h=720, color=HEAVY_LOOK))
        chroma = pl.estimate_site_seconds(line(30, w=1280, h=720, chroma={"color": "#00ff00"}))
        masked = pl.estimate_site_seconds(line(30, w=1280, h=720, mask={"shape": "ellipse", "kf": {"x": [[0, 0.2], [1, 0.8]]}}))
        self.assertGreater(looks, 2.5 * plain)
        self.assertGreater(chroma, 1.8 * plain)
        self.assertGreater(masked, 6 * plain)

    def test_overlays_transitions_and_titles_count(self):
        base = pl.estimate_site_seconds(line(30, w=1280, h=720))
        self.assertGreater(pl.estimate_site_seconds(line(30, w=1280, h=720, extra_layers=2)), 1.9 * base)
        t = line(30, w=1280, h=720)
        t.tracks.append(Track(kind="text", clips=[TextClip(text="سلام", at=0, duration=30)]))
        self.assertGreater(pl.estimate_site_seconds(t), base * 1.25)
        cut = pl.estimate_site_seconds(line(30, w=1280, h=720, second=True))
        faded = pl.estimate_site_seconds(line(30, w=1280, h=720, second=True, transition={"kind": "fade", "duration": 1.0}))
        self.assertGreater(faded, cut)

    def test_a_default_colour_block_costs_nothing_extra(self):
        base = pl.estimate_site_seconds(line(30, w=1280, h=720))
        self.assertAlmostEqual(pl.estimate_site_seconds(line(30, w=1280, h=720, color={"saturation": 100, "blur": 0, "denoise": 0})), base, delta=0.01)

    def test_a_range_preview_never_reaches_the_threshold_in_practice(self):
        """«پیش‌نمایشِ دقیقِ بازه» is ≤ 20 s at 360 px: even a stack of looks on three overlays estimates well under the draft threshold,
        so previews stay on the site (the node would only add a round trip)."""
        t = line(20, w=360, h=640, fps=24, color=HEAVY_LOOK, extra_layers=2, chroma={"color": "#00ff00"})
        self.assertLess(pl.estimate_site_seconds(t), pl.HEAVY_SITE_SECONDS)

    def test_the_size_of_the_draft_file_follows_the_picture(self):
        small = pl.estimate_output_bytes(60, 1280, 720, 30)
        self.assertAlmostEqual(small, 60 * 130_000, delta=1000)
        self.assertAlmostEqual(pl.estimate_output_bytes(60, 1080, 1920, 30) / small, 2.25, delta=0.05)
        self.assertEqual(pl.estimate_output_bytes(0, 1280, 720, 30), 0)


class DecisionTests(TestCase):
    HEAVY = 200.0

    def d(self, site=None, **kw):
        return pl.decide(self.HEAVY if site is None else site, **{"node_online": True, **kw})

    def test_no_node_online_means_the_site(self):
        d = self.d(node_online=False)
        self.assertEqual((d.where, d.reason, d.on_node), ("server", "offline", False))

    def test_a_busy_node_is_not_sent_a_draft(self):
        self.assertEqual(self.d(node_busy=True).reason, "busy")

    def test_a_light_draft_stays_on_the_site_whatever_the_node_has(self):
        for site in (1.0, 20.0, pl.HEAVY_SITE_SECONDS):
            d = self.d(site, uncached_bytes=0, out_bytes=0)
            self.assertEqual((d.where, d.reason), ("server", "light"), site)

    def test_a_heavy_draft_whose_originals_the_node_already_has_goes_there(self):
        d = self.d(uncached_bytes=0, out_bytes=10_000_000)
        self.assertEqual((d.where, d.reason), ("node", "node"))
        self.assertLess(d.node_seconds, pl.NODE_MARGIN * self.HEAVY)

    def test_a_heavy_draft_with_a_big_upload_stays_because_the_transfer_is_the_bottleneck(self):
        d = self.d(uncached_bytes=400_000_000, out_bytes=10_000_000)
        self.assertEqual((d.where, d.reason), ("server", "transfer_bound"))
        self.assertGreater(d.uncached_bytes, 0)

    def test_a_heavy_draft_with_small_originals_goes_even_when_the_node_holds_none(self):
        d = self.d(uncached_bytes=5_000_000, out_bytes=10_000_000)
        self.assertEqual(d.where, "node")

    def test_the_result_coming_back_can_be_the_bottleneck_too(self):
        d = self.d(60.0, uncached_bytes=0, out_bytes=30_000_000)
        self.assertEqual((d.where, d.reason), ("server", "transfer_bound"), "a 60 s plain draft: the upload of its file costs more than the render saves")

    def test_a_small_win_is_not_worth_it(self):
        """The node must be clearly (NODE_MARGIN) faster, not just a little."""
        site = 100.0
        out = int((pl.NODE_MARGIN * site - pl.NODE_FIXED_SECONDS - site / pl.NODE_SPEEDUP) * pl.LINK_UP_BPS)
        self.assertEqual(pl.decide(site, node_online=True, out_bytes=out - 1_000_000).where, "node")
        self.assertEqual(pl.decide(site, node_online=True, out_bytes=out + 1_000_000).where, "server")

    def test_the_node_gets_a_bounded_budget_before_the_site_takes_over(self):
        d = self.d(uncached_bytes=0, out_bytes=10_000_000)
        self.assertAlmostEqual(d.budget, max(pl.NODE_MIN_BUDGET, pl.BUDGET_FACTOR * d.node_seconds), delta=0.01)
        self.assertEqual(pl.Decision("node", "node", 1.0, 99999.0).budget, pl.NODE_MAX_BUDGET)
        self.assertEqual(pl.Decision("server", "light", 1.0).budget, pl.NODE_MIN_BUDGET)

    def test_the_knobs_are_in_one_place_and_move_the_decision(self):
        d = self.d(uncached_bytes=0, out_bytes=10_000_000)
        self.assertEqual(d.where, "node")
        with mock.patch.object(pl, "HEAVY_SITE_SECONDS", 1000.0):
            self.assertEqual(self.d(uncached_bytes=0, out_bytes=10_000_000).reason, "light")
        with mock.patch.object(pl, "LINK_UP_BPS", 1000.0):
            self.assertEqual(self.d(uncached_bytes=0, out_bytes=10_000_000).reason, "transfer_bound")
        with mock.patch.object(pl, "NODE_SPEEDUP", 1.0):
            self.assertEqual(self.d(uncached_bytes=0, out_bytes=10_000_000).reason, "transfer_bound")

    def test_a_node_that_does_not_report_its_cache_counts_every_byte_as_a_download(self):
        files = {"f0": {"size": 400_000_000, "sha256": "a" * 64}, "f1": {"size": 3_000, "sha256": "b" * 64}}
        self.assertEqual(pl.uncached_bytes(files, None), 400_003_000)
        self.assertEqual(pl.uncached_bytes(files, []), 400_003_000)
        self.assertEqual(pl.uncached_bytes(files, ["a" * 16]), 3_000)
        self.assertEqual(pl.uncached_bytes(files, ["a" * 16, "b" * 16]), 0)
        self.assertEqual(pl.uncached_bytes(files, ["c" * 16]), 400_003_000)
        d = pl.decide(300.0, node_online=True, uncached_bytes=pl.uncached_bytes(files, None), out_bytes=5_000_000)
        self.assertEqual(d.reason, "transfer_bound")
        d = pl.decide(300.0, node_online=True, uncached_bytes=pl.uncached_bytes(files, ["a" * 16, "b" * 16]), out_bytes=5_000_000)
        self.assertEqual(d.where, "node")

    def test_the_documented_scenarios(self):
        """The examples in placement.py's docstring, end to end (estimate → decision)."""
        reel = line(60, color=HEAVY_LOOK)                                        # 60 s reel with a heavy look
        est = pl.estimate_site_seconds(reel)
        out = pl.estimate_output_bytes(60, 1080, 1920, 30)
        self.assertEqual(pl.decide(est, node_online=True, uncached_bytes=0, out_bytes=out).where, "node")
        self.assertEqual(pl.decide(est, node_online=True, uncached_bytes=300_000_000, out_bytes=out).where, "server")
        est = pl.estimate_site_seconds(line(60))                                 # the same reel without effects: the site is nearly as fast
        self.assertEqual(pl.decide(est, node_online=True, uncached_bytes=0, out_bytes=out).where, "server")
        short = pl.estimate_site_seconds(line(10))                               # a 10 s draft is light
        self.assertEqual(pl.decide(short, node_online=True).reason, "light")
