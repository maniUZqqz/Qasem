"""The editing engine: the toolbox boundary, the plan, and what it learns.

Most of these are about refusals rather than results, and that is deliberate.
§9 puts the security property plainly — «مدل هرگز دسترسی مستقیم به سیستم ندارد.
فقط می‌تواند از جعبه‌ابزار ما استفاده کند» — and a boundary is only worth having
if something proves it holds when the thing on the other side misbehaves. So the
model here is assumed to be wrong: inventing tools, inventing parameters, asking
for timestamps past the end of the video, asking to remove everything.

The rendering itself is not tested against real ffmpeg. It is not installed on
this machine, and more to the point the interesting decisions all happen before
a frame is read.
"""
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from services.editing import agent, analysis, edl, preferences, tools
from services.editing.edl import Span


def op(tool, **params):
    return {"tool": tool, "params": params}


# ------------------------------------------------------------- the boundary


class ToolboxRefusalTests(SimpleTestCase):
    """What the model is not allowed to do."""

    def test_a_tool_we_do_not_have_is_refused_by_name(self):
        with self.assertRaises(tools.ToolError) as caught:
            tools.validate_one(op("rm -rf /"))
        self.assertIn("rm -rf /", str(caught.exception))

    def test_the_refusal_lists_what_does_exist(self):
        """So the next attempt is a better one rather than another guess."""
        with self.assertRaises(tools.ToolError) as caught:
            tools.validate_one(op("magic"))
        self.assertIn("brightness", str(caught.exception))

    def test_an_invented_parameter_is_refused_not_ignored(self):
        """A model that invented a parameter misunderstood the tool. Running the
        rest of its request is how an edit does something nobody asked for."""
        with self.assertRaises(tools.ToolError):
            tools.validate_one(op("brightness", amount=0.1, path="/etc/passwd"))

    def test_a_backwards_range_is_refused(self):
        with self.assertRaises(tools.ToolError):
            tools.validate_one(op("cut", start=10, end=3), duration=60)

    def test_a_range_past_the_end_of_the_video_is_refused(self):
        with self.assertRaises(tools.ToolError):
            tools.validate_one(op("cut", start=900, end=950), duration=60)

    def test_a_range_that_overruns_the_end_is_pulled_back(self):
        operation = tools.validate_one(op("cut", start=50, end=90), duration=60)
        self.assertEqual(operation.params["end"], 60)
        self.assertTrue(operation.notes)

    def test_text_where_a_number_belongs_is_refused(self):
        with self.assertRaises(tools.ToolError):
            tools.validate_one(op("trim_silence", min_silence="abc"))

    def test_infinity_is_refused(self):
        with self.assertRaises(tools.ToolError):
            tools.validate_one(op("brightness", amount=float("inf")))

    def test_a_choice_outside_the_list_is_refused(self):
        with self.assertRaises(tools.ToolError):
            tools.validate_one(op("crop_format", format="vertical-ish"))

    def test_a_required_parameter_cannot_be_left_out(self):
        with self.assertRaises(tools.ToolError):
            tools.validate_one(op("cut", start=1))

    def test_an_audio_tool_is_refused_on_a_video_with_no_audio(self):
        with self.assertRaises(tools.ToolError):
            tools.validate_one(op("denoise_audio"), has_audio=False)


class ClampingTests(SimpleTestCase):
    def test_an_extreme_value_is_pulled_into_range(self):
        """The model had the right idea and the wrong magnitude. Refusing it
        throws away a good decision over a bad number."""
        operation = tools.validate_one(op("brightness", amount=3.0))
        self.assertEqual(operation.params["amount"], 0.4)

    def test_the_clamp_is_written_down(self):
        """A silent clamp makes the edit different from the one described in
        the plan a human approved."""
        operation = tools.validate_one(op("brightness", amount=3.0))
        self.assertTrue(operation.notes)
        self.assertIn("0.4", operation.notes[0])

    def test_a_sensible_value_is_left_exactly_as_asked(self):
        operation = tools.validate_one(op("brightness", amount=0.12))
        self.assertEqual(operation.params["amount"], 0.12)
        self.assertEqual(operation.notes, [])


class PartialPlanTests(SimpleTestCase):
    def test_one_bad_operation_does_not_discard_the_good_ones(self):
        """Nine right and one wrong should apply nine. Discarding all ten
        teaches nobody anything and leaves the shop with an unedited video."""
        accepted, refused = tools.validate(
            [op("brightness", amount=0.1), op("nonsense"), op("contrast", amount=1.2)],
            duration=60,
        )
        self.assertEqual(len(accepted), 2)
        self.assertEqual(len(refused), 1)

    def test_a_plan_is_capped(self):
        accepted, _ = tools.validate([op("brightness", amount=0.1)] * 200, duration=60)
        self.assertLessEqual(len(accepted), 60)


# -------------------------------------------------------------------- EDL


class KeepListTests(SimpleTestCase):
    def _edl(self, operations, duration=30.0, **kwargs):
        accepted, refused = tools.validate(operations, duration=duration)
        return edl.build(
            "x.mp4", accepted, duration=duration, refusals=refused, **kwargs,
        )

    def test_no_cuts_keeps_the_whole_video(self):
        plan = self._edl([op("brightness", amount=0.1)])
        self.assertEqual(plan.result_seconds, 30.0)
        self.assertFalse(plan.cuts_anything)

    def test_a_cut_removes_exactly_its_span(self):
        plan = self._edl([op("cut", start=5, end=10)])
        self.assertEqual(plan.removed_seconds, 5.0)

    def test_overlapping_cuts_are_merged_not_double_counted(self):
        """Removals compose badly; this is the bug the keep-list exists to
        prevent — 5–10 and 9–12 together remove seven seconds, not eight."""
        plan = self._edl([op("cut", start=5, end=10), op("cut", start=9, end=12)])
        self.assertEqual(plan.removed_seconds, 7.0)
        self.assertEqual(
            [(s.start, s.end) for s in plan.keep], [(0.0, 5.0), (12.0, 30.0)],
        )

    def test_cuts_given_out_of_order_still_work(self):
        forwards = self._edl([op("cut", start=2, end=4), op("cut", start=20, end=25)])
        backwards = self._edl([op("cut", start=20, end=25), op("cut", start=2, end=4)])
        self.assertEqual(forwards.result_seconds, backwards.result_seconds)

    def test_a_cut_at_the_very_start_works(self):
        plan = self._edl([op("cut", start=0, end=3)])
        self.assertEqual(plan.keep[0].start, 3.0)

    def test_silences_come_from_measurement_not_from_the_model(self):
        """The model says *that* silence should go; where it is belongs to the
        eye. A model guessing timestamps would cut speech."""
        plan = self._edl(
            [op("trim_silence", min_silence=0.5, keep=0.2)],
            silences=[Span(4.0, 6.0), Span(10.0, 10.2)],
        )
        # The 0.2s gap is below min_silence and survives; the 2s one does not.
        self.assertAlmostEqual(plan.removed_seconds, 1.8, places=2)

    def test_a_breath_is_left_at_each_end_of_a_removed_pause(self):
        """Cutting silence flush splices speech together, which is a worse
        artefact than the pause it removed."""
        plan = self._edl(
            [op("trim_silence", min_silence=0.5, keep=0.4)], silences=[Span(4.0, 6.0)],
        )
        self.assertAlmostEqual(plan.removed_seconds, 1.6, places=2)

    def test_the_summary_is_readable(self):
        plan = self._edl([op("cut", start=5, end=10), op("brightness", amount=0.1)])
        summary = plan.summary()
        self.assertIn("ثانیه", summary)
        self.assertIn("روشنایی", summary)

    def test_doing_nothing_says_so(self):
        self.assertIn("تغییری", self._edl([]).summary())


class RenderGuardTests(SimpleTestCase):
    """ffmpeg is stubbed — it is not installed here, and every decision worth
    testing happens while the command is being built."""

    def setUp(self):
        import tempfile

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.out = Path(directory.name) / "out.mp4"

    def _write(self, command):
        """Stand in for ffmpeg: write the file it would have written."""
        Path(command[-1]).write_bytes(b"video")

    def test_an_edit_that_removes_everything_is_refused(self):
        """Always a mistake upstream — usually a silent audio track making every
        second look like a pause — and writing the file lets it reach the
        customer."""
        from services.video.ffmpeg import VideoProcessingError

        plan = edl.EDL(source="x.mp4", duration=30.0, keep=[Span(0.0, 0.3)])
        with self.assertRaises(VideoProcessingError) as caught:
            edl.render(plan, self.out)
        self.assertIn("سکوت", str(caught.exception))

    def test_cutting_resets_timestamps(self):
        """Without this the output freezes for the length of what was removed —
        a bug that looks like a broken render, not like a bad edit."""
        plan = edl.EDL(
            source="x.mp4", duration=30.0, keep=[Span(0.0, 5.0), Span(10.0, 30.0)],
        )
        with patch("services.editing.edl._run", side_effect=self._write) as run:
            edl.render(plan, self.out)
        command = " ".join(run.call_args.args[0])
        self.assertIn("setpts=N/FRAME_RATE/TB", command)
        self.assertIn("asetpts=N/SR/TB", command)

    def test_one_pass_not_four(self):
        """Re-encoding once per correction costs four times the CPU and loses
        quality at every step."""
        plan = edl.EDL(
            source="x.mp4", duration=30.0, keep=[Span(0.0, 30.0)],
            video_filters=["eq=brightness=0.1", "eq=contrast=1.2", "deflicker=size=5"],
        )
        with patch("services.editing.edl._run", side_effect=self._write) as run:
            edl.render(plan, self.out)
        self.assertEqual(run.call_count, 1)

    def test_a_video_without_audio_gets_no_audio_flags(self):
        plan = edl.EDL(
            source="x.mp4", duration=30.0, keep=[Span(0.0, 30.0)], has_audio=False,
        )
        with patch("services.editing.edl._run", side_effect=self._write) as run:
            edl.render(plan, self.out)
        command = run.call_args.args[0]
        self.assertIn("-an", command)
        self.assertNotIn("-af", command)


# ------------------------------------------------------------- suggestions


class CodeOnlySuggestionTests(SimpleTestCase):
    """§8: most editing needs no model at all."""

    DARK = {
        "readable": True, "duration": 60, "has_audio": True, "brightness": 40,
        "brightness_swing": 4, "colour_cast": 2, "motion": 3,
        "silence_count": 0, "silence_seconds": 0, "clipped_pixels": 0,
    }

    def test_a_dark_video_is_offered_more_light(self):
        proposed = agent.suggest(self.DARK)
        self.assertEqual([p["tool"] for p in proposed], ["brightness"])
        self.assertGreater(proposed[0]["params"]["amount"], 0)

    def test_every_suggestion_says_why(self):
        """«۱۴ سکوت طولانی پیدا شد، حذف شود؟» is answerable;
        «بهینه‌سازی خودکار؟» is not."""
        for proposal in agent.suggest(self.DARK):
            self.assertTrue(proposal["reason"])

    def test_a_clean_video_is_left_alone(self):
        clean = {**self.DARK, "brightness": 128}
        self.assertEqual(agent.suggest(clean), [])

    def test_silences_are_offered_for_removal(self):
        noisy = {**self.DARK, "brightness": 128, "silence_count": 14,
                 "silence_seconds": 20}
        self.assertIn("trim_silence", [p["tool"] for p in agent.suggest(noisy)])

    def test_a_video_with_no_speech_is_never_offered_silence_removal(self):
        """On a video whose microphone failed, "remove the silence" means
        "remove the video"."""
        broken = {**self.DARK, "brightness": 128, "duration": 30,
                  "silence_count": 1, "silence_seconds": 29}
        self.assertNotIn("trim_silence", [p["tool"] for p in agent.suggest(broken)])

    def test_no_model_is_involved(self):
        with patch("services.editing.agent.ask_model") as model:
            agent.suggest(self.DARK)
        model.assert_not_called()


class ObviousProblemTests(SimpleTestCase):
    def test_an_unreadable_video_produces_no_findings(self):
        self.assertEqual(analysis.obvious_problems({"readable": False}), [])

    def test_a_mostly_silent_video_is_called_out_separately(self):
        found = analysis.obvious_problems({
            "readable": True, "duration": 30, "has_audio": True,
            "silence_count": 1, "silence_seconds": 29, "brightness": 128,
        })
        self.assertIn("no_speech", [f["what"] for f in found])


# ------------------------------------------------------------------ modes


class PlanningTests(SimpleTestCase):
    FACTS = {
        "readable": True, "duration": 60, "has_audio": True, "brightness": 40,
        "brightness_swing": 4, "colour_cast": 2, "motion": 3,
        "silence_count": 0, "silence_seconds": 0, "clipped_pixels": 0,
    }

    def _plan(self, **kwargs):
        with patch.object(analysis, "describe", return_value=self.FACTS), \
                patch.object(analysis, "silences", return_value=[]):
            return agent.plan("x.mp4", "work", **kwargs)

    def test_manual_mode_does_only_what_it_was_told(self):
        plan = self._plan(mode=agent.MANUAL, operations=[op("contrast", amount=1.2)])
        self.assertEqual([o.tool for o in plan.edl.operations], ["contrast"])

    def test_manual_mode_never_asks_the_model(self):
        """«دستی» means the shop decides. A system that adds its own edits there
        is not in manual mode."""
        self.assertFalse(self._plan(mode=agent.MANUAL, operations=[]).asked_model)

    def test_suggest_mode_proposes_from_measurements(self):
        self.assertTrue(self._plan(mode=agent.SUGGEST).edl.operations)

    def test_directed_mode_asks_the_model(self):
        with patch.object(agent, "ask_model", return_value=[]) as ask, \
                patch.object(analysis, "describe", return_value=self.FACTS), \
                patch.object(analysis, "silences", return_value=[]):
            agent.plan("x.mp4", "work", mode=agent.DIRECTED,
                       instruction="مثل یک یوتیوبر حرفه‌ای")
        ask.assert_called_once()

    def test_directed_mode_still_works_without_a_model(self):
        """Everything code could work out is already in the findings, so a
        missing model costs the direction, not the editing."""
        with patch.object(agent, "ask_model", return_value=[]):
            plan = self._plan(mode=agent.DIRECTED, instruction="ساده")
        self.assertTrue(plan.edl.operations)

    def test_the_model_cannot_smuggle_a_tool_past_validation(self):
        with patch.object(agent, "ask_model", return_value=[
            {"tool": "shell", "params": {"cmd": "rm -rf /"}},
            {"tool": "contrast", "params": {"amount": 1.2}},
        ]):
            plan = self._plan(mode=agent.DIRECTED, instruction="x")
        self.assertEqual([o.tool for o in plan.edl.operations], ["contrast"])
        self.assertTrue(plan.edl.refusals)

    def test_the_same_correction_is_not_stacked_twice(self):
        """Two brightness corrections do not average — they add, and the picture
        ends up further from right than it started."""
        plan = self._plan(
            mode=agent.MANUAL,
            operations=[op("brightness", amount=0.1), op("brightness", amount=0.2)],
        )
        self.assertEqual(len(plan.edl.operations), 1)

    def test_cuts_are_allowed_to_repeat(self):
        plan = self._plan(
            mode=agent.MANUAL,
            operations=[op("cut", start=1, end=2), op("cut", start=10, end=12)],
        )
        self.assertEqual(len(plan.edl.operations), 2)

    def test_an_unreadable_video_plans_nothing_and_says_why(self):
        with patch.object(analysis, "describe",
                          return_value={"readable": False, "reason": "فایل خراب است"}):
            plan = agent.plan("x.mp4", "work")
        self.assertTrue(plan.does_nothing)
        self.assertEqual(plan.edl.refusals, ["فایل خراب است"])


class RunTests(SimpleTestCase):
    FACTS = dict(PlanningTests.FACTS)

    def test_suggest_mode_renders_nothing(self):
        """The whole meaning of the mode is that a person sees the plan first.
        Rendering it would make the approval theatre."""
        with patch.object(analysis, "describe", return_value=self.FACTS), \
                patch.object(analysis, "silences", return_value=[]), \
                patch.object(edl, "render") as render:
            outcome = agent.run("x.mp4", "out.mp4", "work", mode=agent.SUGGEST)
        render.assert_not_called()
        self.assertIsNone(outcome.output)

    def test_an_edit_that_made_things_worse_is_not_handed_over(self):
        """«اگر خوب نشد» has to mean something, and the only way it can is if
        the second look can reject the result."""
        worse = {**self.FACTS, "brightness": 10, "colour_cast": 35}
        with patch.object(analysis, "describe", side_effect=[self.FACTS, worse]), \
                patch.object(analysis, "silences", return_value=[]), \
                patch.object(edl, "render"), \
                patch.object(analysis, "obvious_problems",
                             side_effect=analysis.obvious_problems):
            outcome = agent.run("x.mp4", "out.mp4", "work", mode=agent.AUTO)
        self.assertFalse(outcome.improved)
        self.assertIsNone(outcome.output)

    def test_a_clean_video_is_not_rendered_at_all(self):
        clean = {**self.FACTS, "brightness": 128}
        with patch.object(analysis, "describe", return_value=clean), \
                patch.object(analysis, "silences", return_value=[]), \
                patch.object(edl, "render") as render:
            outcome = agent.run("x.mp4", "out.mp4", "work", mode=agent.AUTO)
        render.assert_not_called()
        self.assertIn("پیدا نشد", outcome.note)

    def test_it_looks_again_after_rendering(self):
        """§9: «و بعد دوباره نگاه می‌کند: بهتر شد؟»"""
        fixed = {**self.FACTS, "brightness": 126}
        with patch.object(analysis, "describe", side_effect=[self.FACTS, fixed]) as look, \
                patch.object(analysis, "silences", return_value=[]), \
                patch.object(edl, "render"):
            agent.run("x.mp4", "out.mp4", "work", mode=agent.AUTO)
        self.assertEqual(look.call_count, 2)


# --------------------------------------------------------------- learning


class HabitTests(TestCase):
    def setUp(self):
        from apps.stores.models import Store

        owner = User.objects.create_user("edit-owner", password="x")
        self.store = Store.objects.create(owner=owner, name="فروشگاه تدوین")

    def _decide(self, tool, accepted, times=1, **params):
        for _ in range(times):
            preferences.record(
                self.store, tool=tool, params=params, accepted=accepted,
            )

    def test_defaults_apply_until_a_shop_teaches_us_otherwise(self):
        self.assertEqual(
            preferences.habits(self.store)["min_silence"],
            preferences.DEFAULTS["min_silence"],
        )

    def test_one_example_is_a_coincidence_not_a_habit(self):
        """A system that behaves differently every session for no visible
        reason is worse than one that does not learn."""
        self._decide("trim_silence", True, min_silence=1.5)
        self.assertEqual(preferences.learn(self.store)["min_silence"], 0.6)

    def test_a_repeated_choice_becomes_the_default(self):
        self._decide("trim_silence", True, times=5, min_silence=1.2, keep=0.15)
        self.assertEqual(preferences.learn(self.store)["min_silence"], 1.2)

    def test_a_repeatedly_refused_tool_stops_being_offered(self):
        """Turning something down four times is a person telling us plainly."""
        self._decide("stabilize", False, times=5)
        self.assertIn("stabilize", preferences.learn(self.store)["never"])

    def test_a_mixed_record_is_not_treated_as_a_refusal(self):
        self._decide("stabilize", False, times=2)
        self._decide("stabilize", True, times=3)
        self.assertNotIn("stabilize", preferences.learn(self.store)["never"])

    def test_one_extreme_edit_does_not_move_the_default(self):
        """A median carries no outlier forward; a mean does."""
        self._decide("trim_silence", True, times=4, min_silence=0.6)
        self._decide("trim_silence", True, min_silence=5.0)
        self.assertEqual(preferences.learn(self.store)["min_silence"], 0.6)

    def test_a_learned_value_still_has_to_pass_the_toolbox(self):
        """A preference table is data a user can edit, and must not become a way
        around the check that exists to stop bad parameters."""
        preferences.save(self.store, {**preferences.DEFAULTS, "min_silence": 99})
        learned = preferences._sanitise(dict(preferences.habits(self.store)))
        self.assertLessEqual(learned["min_silence"], 5.0)

    def test_a_never_tool_is_dropped_from_suggestions(self):
        self._decide("stabilize", False, times=5)
        preferences.refresh(self.store)
        shaky = {
            "readable": True, "duration": 60, "has_audio": True, "brightness": 128,
            "brightness_swing": 4, "colour_cast": 2, "motion": 20,
            "silence_count": 0, "silence_seconds": 0, "clipped_pixels": 0,
        }
        self.assertNotIn(
            "stabilize", [p["tool"] for p in agent.suggest(shaky, store=self.store)],
        )

    def test_saving_habits_keeps_other_ai_preferences(self):
        self.store.profile.ai_preferences = {"something_else": 1}
        self.store.profile.save()
        preferences.refresh(self.store)
        self.store.profile.refresh_from_db()
        self.assertEqual(self.store.profile.ai_preferences["something_else"], 1)

    def test_what_we_learned_is_said_out_loud(self):
        """A system that silently behaves differently for one customer is one
        they cannot correct."""
        self._decide("trim_silence", True, times=5, min_silence=1.2)
        preferences.refresh(self.store)
        self.assertTrue(preferences.explain(self.store))

    def test_a_tool_we_do_not_have_is_not_recorded(self):
        self.assertIsNone(preferences.record(self.store, tool="nope", params={},
                                             accepted=True))
