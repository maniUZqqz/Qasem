"""Continuity between segments.

The failure this prevents: the jacket is blue in segment one, the last frame
happens to show only a sleeve, and segment two invents a colour. A frame
carries one instant; the state carries what the scene *is*.
"""
from django.test import SimpleTestCase

from services.video import scene_state
from services.video.scene_state import SceneState


class FakeScene:
    """Just the attributes the builder reads."""

    def __init__(self, **kwargs):
        self.visual_prompt = kwargs.pop("visual_prompt", "")
        self.motion_prompt = kwargs.pop("motion_prompt", "")
        self.transition = kwargs.pop("transition", "CONTINUE")
        self.state = kwargs.pop("state", {})


class StateTests(SimpleTestCase):
    def test_an_empty_state_says_so(self):
        self.assertTrue(SceneState().is_empty)

    def test_round_trips_through_json(self):
        original = SceneState(
            characters=["a young woman"], location="sunlit kitchen",
            clothing=["blue denim jacket"], action="picks up the mug",
        )
        again = SceneState.from_dict(original.as_dict())
        self.assertEqual(again.as_dict(), original.as_dict())

    def test_unknown_keys_are_ignored(self):
        """Old rows and renamed fields must not break a resume of a half-done
        job."""
        state = SceneState.from_dict({"location": "kitchen", "weather": "rain"})
        self.assertEqual(state.location, "kitchen")
        self.assertFalse(hasattr(state, "weather"))

    def test_a_string_where_a_list_belongs_is_accepted(self):
        state = SceneState.from_dict({"clothing": "red coat"})
        self.assertEqual(state.clothing, ["red coat"])

    def test_carry_forward_keeps_everything_but_the_action(self):
        """The action is the one field that is meant to change. Everything else
        changing is drift."""
        state = SceneState(
            characters=["a man"], clothing=["grey suit"], action="opens the door",
        )
        nxt = state.carry_forward("walks to the desk")
        self.assertEqual(nxt.characters, ["a man"])
        self.assertEqual(nxt.clothing, ["grey suit"])
        self.assertEqual(nxt.action, "walks to the desk")

    def test_carry_forward_does_not_mutate_the_original(self):
        state = SceneState(characters=["a man"], action="opens the door")
        state.carry_forward("something else")
        self.assertEqual(state.action, "opens the door")


class ContinuityPromptTests(SimpleTestCase):
    def test_it_is_phrased_as_constraints_not_description(self):
        """A plain restatement reads to the model as a new subject to
        introduce, and it will happily add a second person in the same coat."""
        state = SceneState(characters=["a young woman"], clothing=["blue jacket"])
        prompt = state.continuity_prompt()
        self.assertIn("the same", prompt)
        self.assertIn("still wearing", prompt)

    def test_an_empty_state_produces_nothing(self):
        self.assertEqual(SceneState().continuity_prompt(), "")

    def test_every_axis_that_is_set_appears(self):
        state = SceneState(
            characters=["a man"], objects=["a leather bag"], location="cafe",
            lighting="warm afternoon light", camera="slow push in",
            clothing=["wool coat"], colors=["amber", "deep brown"],
        )
        prompt = state.continuity_prompt()
        for fragment in ("a man", "leather bag", "cafe", "warm afternoon",
                         "slow push in", "wool coat", "amber"):
            self.assertIn(fragment, prompt)


class InheritanceTests(SimpleTestCase):
    def test_silence_means_as_before_not_reset(self):
        """This is the whole bug. A scene that says nothing about clothing
        means "as before"; treating it as a reset is what makes video drift."""
        previous = SceneState(clothing=["blue denim jacket"], location="kitchen")
        scene = FakeScene(visual_prompt="she turns to the window")

        state = scene_state.from_scene(scene, previous)

        self.assertEqual(state.clothing, ["blue denim jacket"])
        self.assertEqual(state.location, "kitchen")

    def test_what_the_script_declares_wins(self):
        previous = SceneState(location="kitchen")
        scene = FakeScene(state={"location": "balcony"})

        state = scene_state.from_scene(scene, previous)

        self.assertEqual(state.location, "balcony")

    def test_a_new_scene_transition_carries_nothing_over(self):
        """A deliberate cut is not drift."""
        previous = SceneState(characters=["a man"], location="kitchen")
        scene = FakeScene(transition="NEW_SCENE", state={"location": "street"})

        state = scene_state.from_scene(scene, previous)

        self.assertEqual(state.location, "street")
        self.assertEqual(state.characters, [])

    def test_the_action_comes_from_the_motion_prompt_when_unstated(self):
        scene = FakeScene(motion_prompt="camera pans left")
        self.assertEqual(scene_state.from_scene(scene, None).action, "camera pans left")

    def test_the_first_segment_has_no_previous_state(self):
        scene = FakeScene(visual_prompt="a shoe on a table")
        state = scene_state.from_scene(scene, None)
        self.assertEqual(state.characters, [])


class BuildPromptTests(SimpleTestCase):
    def test_the_scene_text_and_the_continuity_are_both_present(self):
        scene = FakeScene(visual_prompt="she lifts the cup", motion_prompt="slow zoom")
        state = SceneState(clothing=["blue jacket"])

        prompt = scene_state.build_prompt(scene, state)

        self.assertIn("she lifts the cup", prompt)
        self.assertIn("slow zoom", prompt)
        self.assertIn("blue jacket", prompt)

    def test_a_deliberate_cut_gets_no_continuity_clause(self):
        scene = FakeScene(visual_prompt="a street at night", transition="NEW_SCENE")
        state = SceneState(clothing=["blue jacket"])

        prompt = scene_state.build_prompt(scene, state)

        self.assertIn("a street at night", prompt)
        self.assertNotIn("blue jacket", prompt)

    def test_no_state_still_produces_the_scene_prompt(self):
        scene = FakeScene(visual_prompt="a shoe")
        self.assertEqual(scene_state.build_prompt(scene, None), "a shoe")

    def test_an_empty_scene_with_only_motion_still_works(self):
        scene = FakeScene(motion_prompt="dolly in")
        self.assertIn("dolly in", scene_state.build_prompt(scene, SceneState()))
