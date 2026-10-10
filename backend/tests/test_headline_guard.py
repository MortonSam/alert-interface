"""The Discover headline guard (services/headline_guard): a headline beside a move must not contradict it."""
from datetime import datetime, timezone
from pathlib import Path

from app.services import headline_guard as G
from app.services import news as N


def test_a_verb_pointing_the_other_way_is_suppressed():
    assert G.check("Intel shares surge on foundry deal", -3.1).reason == "its verb says up on a down day"
    assert G.check("Coherent plunges after guidance cut", 4.0).reason.startswith("its verb says down")
    assert G.check("Intel rallies even as Nvidia falls", -1.0).reason is None          # both lists: not clear
    assert G.check("Intel announces new chip", -1.0).reason is None


def test_a_stated_percent_must_match_our_move_within_a_point_and_in_sign():
    assert G.check("Intel stock falls 4% after downgrade", -3.6).reason is None
    assert G.check("Intel stock falls 4% after downgrade", -2.1).reason.startswith("its stated move differs")
    assert G.check("Intel up 7.5% as chip stocks rally", -7.1).reason in ("its verb says up on a down day", "its stated move has the opposite sign")
    assert G.check("Intel shares +5% premarket", -1.0).reason == "its stated move has the opposite sign"
    assert G.stated_move("Coherent raises dividend 5%") is None                    # not a price move
    assert G.stated_move("Intel down 3.2% at the open") == -3.2
    assert G.check("Intel stock falls 4%", None).reason is None                      # no move of ours: nothing to contradict


def test_both_word_lists_live_in_one_file():
    root = Path(__file__).parents[1] / "app"
    for p in root.rglob("*.py"):
        if p.name == "headline_guard.py":
            continue
        src = p.read_text()
        assert "UP_VERBS =" not in src and "DOWN_VERBS =" not in src, p


def test_the_news_lists_apply_the_guard_and_record_both_numbers():
    t = datetime(2026, 10, 8, 18, tzinfo=timezone.utc)
    stories = [{"url": "u1", "headline": "Intel shares surge 9% on foundry deal", "source": "Reuters", "published_at": t, "related": ["INTC"]},
               {"url": "u2", "headline": "Intel stock falls 3% on chip glut worries", "source": "Reuters", "published_at": t, "related": ["INTC"]}]
    suppressed: dict = {}
    h = N.top_headline(stories, "INTC", "Intel Corporation", None, None, -3.4, suppressed)
    assert h["url"] == "u2"
    assert suppressed[("INTC", "u1")]["stated_pct"] == 9.0 and suppressed[("INTC", "u1")]["move_pct"] == -3.4
    ranked = N.in_the_news(stories, {"INTC": -3.4}, names={"INTC": "Intel Corporation"}, moves={"INTC": -3.4}, suppressed=suppressed)
    assert [r["url"] for r in ranked] == ["u2"]
    assert N.guard_share(1, 5) == 0.2 and N.guard_share(2, 5) > N.GUARD_WARN_SHARE and N.guard_share(1, 0) is None
