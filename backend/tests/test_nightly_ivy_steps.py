"""The nightly's two Ivy steps follow their switches (Sam, 2026-11-10): Auto-pick runs while the old Ivy shows, and the walkthrough
step calls no model until the stories are turned on."""
from app.config import Settings, settings
from app.scripts import refresh
from app.services import ai_pause


def test_the_walkthrough_step_runs_with_no_story_until_the_stories_are_on():
    assert Settings.model_fields["walkthrough_stories_enabled"].default is False
    off, on = refresh.walkthrough_cmd(False), refresh.walkthrough_cmd(True)
    assert off == ["python", "-m", "app.scripts.build_walkthroughs", "--write", "--no-story"]
    assert on == ["python", "-m", "app.scripts.build_walkthroughs", "--write"]
    assert dict(refresh.STEPS)["Ivy walkthroughs"] == refresh.walkthrough_cmd(settings.walkthrough_stories_enabled)
    # with no story the step calls no model, so an AI pause leaves it running; with stories it is skipped like the notes
    assert ai_pause.WALKTHROUGH_STEP not in ai_pause.ai_only_steps(False)
    assert ai_pause.WALKTHROUGH_STEP in ai_pause.ai_only_steps(True)
    assert ai_pause.AI_ONLY_STEPS == ai_pause.ai_only_steps(settings.walkthrough_stories_enabled)


def test_auto_pick_runs_while_the_old_ivy_shows_and_stops_with_the_walkthrough():
    assert refresh.auto_pick_steps(False) == [("Auto-pick", ["python", "-m", "app.scripts.auto_pick"])]
    assert refresh.auto_pick_steps(True) == []
    labels = [label for label, _ in refresh.STEPS]
    assert ("Auto-pick" in labels) is (not settings.ivy_walkthrough_enabled)
    if "Auto-pick" in labels:                # where production runs it today: after the features it reads, before the shadow eval
        assert labels.index("Build earnings features") < labels.index("Auto-pick") < labels.index("Shadow eval")
    assert refresh.STEP_TIMEOUTS["Auto-pick"] == 600
