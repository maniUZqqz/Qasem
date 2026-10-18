from django.test import TestCase

from .events import Event
from .funnel import by_channel, funnel

URL = "/api/v1/events/"


def ev(name, session="s1", **extra):
    return {"name": name, "session": session, "path": "/", **extra}


class EventIngestTests(TestCase):
    def test_batch_is_stored(self):
        res = self.client.post(
            URL,
            {"events": [ev("page_view"), ev("cta_click")]},
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 202)
        self.assertEqual(res.json()["stored"], 2)
        self.assertEqual(Event.objects.count(), 2)

    def test_unknown_event_name_dropped_without_failing_the_batch(self):
        """One bad row must not lose the good ones — analytics is best-effort."""
        res = self.client.post(
            URL,
            {"events": [ev("page_view"), ev("definitely_not_real")]},
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 202)
        self.assertEqual(res.json()["stored"], 1)

    def test_event_without_session_dropped(self):
        res = self.client.post(
            URL, {"events": [ev("page_view", session="")]}, content_type="application/json"
        )
        self.assertEqual(res.json()["stored"], 0)

    def test_garbage_body_is_accepted_quietly(self):
        """A tracker bug must never surface as an error to the visitor."""
        for body in ({"events": "nope"}, {}, {"events": [1, 2, None]}):
            res = self.client.post(URL, body, content_type="application/json")
            self.assertEqual(res.status_code, 202)
        self.assertEqual(Event.objects.count(), 0)

    def test_batch_is_capped(self):
        res = self.client.post(
            URL,
            {"events": [ev("page_view", session=f"s{i}") for i in range(60)]},
            content_type="application/json",
        )
        self.assertEqual(res.json()["stored"], 25)

    def test_props_and_utm_are_bounded(self):
        res = self.client.post(
            URL,
            {
                "events": [
                    ev(
                        "plan_selected",
                        utm={"source": "instagram", "evil": "x" * 400},
                        props={f"k{i}": "y" * 400 for i in range(30)},
                    )
                ]
            },
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 202)
        e = Event.objects.get()
        self.assertEqual(set(e.utm), {"source"})
        self.assertLessEqual(len(e.props), 10)
        self.assertTrue(all(len(v) <= 200 for v in e.props.values()))

    def test_no_auth_required(self):
        """Visitors are anonymous; requiring a token would collect nothing."""
        res = self.client.post(
            URL, {"events": [ev("page_view")]}, content_type="application/json"
        )
        self.assertEqual(res.status_code, 202)


class FunnelTests(TestCase):
    def _seed(self):
        # three sessions, each getting one step further
        Event.objects.bulk_create(
            [
                Event(name="page_view", session="a", path="/"),
                Event(name="page_view", session="b", path="/"),
                Event(name="page_view", session="b", path="/features/ai-video-generation"),
                Event(name="pricing_view", session="b", path="/pricing"),
                Event(name="page_view", session="c", path="/"),
                Event(name="page_view", session="c", path="/solutions/online-shops"),
                Event(name="pricing_view", session="c", path="/pricing"),
                # a real signup always fires started before completed
                Event(name="signup_started", session="c", path="/register"),
                Event(name="signup_completed", session="c", path="/register"),
            ]
        )

    def test_steps_count_distinct_sessions_not_events(self):
        Event.objects.bulk_create(
            [Event(name="page_view", session="a", path="/") for _ in range(5)]
        )
        self.assertEqual(funnel()["steps"][0]["count"], 1)

    def test_required_steps_narrow(self):
        self._seed()
        steps = funnel()["steps"]
        counts = [s["count"] for s in steps]
        self.assertEqual(counts[0], 3)  # visitors
        self.assertEqual(counts[1], 2)  # explored a feature/solution page
        self.assertEqual(counts[2], 2)  # saw pricing
        self.assertEqual(counts[5], 1)  # completed signup
        # Only the required chain has to narrow. "plan selected" is optional —
        # you can register from any page without ever choosing one.
        required = [s["count"] for s in steps if not s["optional"]]
        self.assertEqual(required, sorted(required, reverse=True))

    def test_optional_step_reports_no_dropoff(self):
        """Measuring a leak against an optional step would invent one."""
        self._seed()
        plan_step = next(s for s in funnel()["steps"] if s["optional"])
        self.assertIsNone(plan_step["of_previous"])

    def test_missing_event_is_reported_honestly_not_smoothed(self):
        """If the tracker drops `signup_started`, the report must show the gap
        rather than back-filling it from `signup_completed`."""
        Event.objects.bulk_create(
            [
                Event(name="page_view", session="m", path="/"),
                Event(name="signup_completed", session="m", path="/register"),
            ]
        )
        steps = funnel()["steps"]
        self.assertEqual(steps[4]["count"], 0)  # started — genuinely absent
        self.assertEqual(steps[5]["count"], 1)  # completed — genuinely present

    def test_signup_without_plan_still_counts(self):
        """Someone who registers from the home page never picks a plan first."""
        Event.objects.bulk_create(
            [
                Event(name="page_view", session="q", path="/"),
                Event(name="signup_completed", session="q", path="/register"),
            ]
        )
        steps = funnel()["steps"]
        self.assertEqual(steps[3]["count"], 0)  # plan_selected
        self.assertEqual(steps[5]["count"], 1)  # completed anyway

    def test_percentages_are_relative_to_previous_step(self):
        self._seed()
        steps = funnel()["steps"]
        self.assertEqual(steps[0]["of_total"], 100.0)
        # 2 of 3 explored
        self.assertAlmostEqual(steps[1]["of_previous"], 66.7, places=1)

    def test_channel_attribution_counts_signups(self):
        Event.objects.bulk_create(
            [
                Event(name="page_view", session="x", utm={"source": "instagram"}),
                Event(name="signup_completed", session="x"),
                Event(name="page_view", session="y", utm={"source": "instagram"}),
                Event(name="page_view", session="z", utm={}),
            ]
        )
        rows = {r["source"]: r for r in by_channel()}
        self.assertEqual(rows["instagram"]["sessions"], 2)
        self.assertEqual(rows["instagram"]["signups"], 1)
        # no utm at all is reported as direct rather than dropped
        self.assertEqual(rows["مستقیم"]["sessions"], 1)

    def test_session_belongs_to_one_channel_only(self):
        """A visit that lands with a utm and then browses without one must not
        be counted under both that campaign and 'direct'."""
        Event.objects.bulk_create(
            [
                Event(name="page_view", session="p", path="/", utm={"source": "instagram"}),
                Event(name="page_view", session="p", path="/pricing", utm={}),
                Event(name="signup_completed", session="p"),
            ]
        )
        rows = {r["source"]: r for r in by_channel()}
        self.assertEqual(rows["instagram"]["sessions"], 1)
        self.assertEqual(rows["instagram"]["signups"], 1)
        self.assertNotIn("مستقیم", rows)
        # and the totals add up to the real number of visits
        self.assertEqual(sum(r["sessions"] for r in by_channel()), 1)
