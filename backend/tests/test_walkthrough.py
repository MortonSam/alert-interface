

def test_step_one_reads_the_served_notes_own_description_word_for_word():
    """Sam, 2026-11-03: the research note's "what they do" is step 1's description; the vendor's only when there is no served note."""
    from datetime import date as _d
    from app.services import walkthrough as W
    note = {"text": "NVIDIA designs and sells accelerated computing platforms.", "written": _d(2026, 11, 2)}
    profile = {"short_description": "NVIDIA Corporation provides graphics and compute solutions.", "fetched_at": _d(2026, 10, 1)}
    s = W.step_business("NVIDIA", profile, None, None, None, "revenue", note)
    assert s["sentences"][0] == note["text"] and s["from_note"] and not s["described"]
    assert {"label": "Company description", "value": "Ivy's research note", "as_of": "Written Nov 2, 2026"} in s["deeper"]
    fallback = W.step_business("NVIDIA", profile, None, None, None, "revenue", None)
    assert fallback["described"] and not fallback["from_note"] and "graphics and compute" in fallback["sentences"][0]


def test_validate_reads_the_valuation_figure_the_way_the_step_words_it():
    """The first production night with walkthroughs (2026-11-12): the check read "$35" as a plain number and raised, so no
    walkthrough was checked. The figure comes from the step's own formatter here, so the two cannot drift apart again."""
    import asyncio
    import pytest
    from app.scripts import validate_data as V
    from app.services import walkthrough as W

    for x in (7.94, 10.0, 35.2, 98.4, 1234.0):
        assert V.walkthrough_valuation_figure(W.per_dollar(x)) == pytest.approx(x, abs=0.5)
    assert V.walkthrough_valuation_figure(W.num(11.4)) == 11.4

    def row(sym: str, kind: str, value: str):
        step = {"key": "valuation", "status": "ok", "numbers": [W._num(W.VALUATION_LABEL[kind], value, "Close of Nov 11, 2026")]}
        return (sym, {"steps": [step]}, None, None)

    class Session:
        async def execute(self, stmt):
            rows = [row("AAA", "pe", W.per_dollar(35.2)), row("OOO", "p_ffo", W.num(11.4)), row("ZZZ", "pe", W.per_dollar(140.0))]
            return type("R", (), {"all": lambda self: rows if "FROM ivy_walkthroughs" in str(stmt) else []})()

    result = asyncio.run(V.check_walkthrough_claims(Session()))
    assert result.level == V.ERROR and result.rows == ["ZZZ: Paid for each $1 of profit $140 outside 0 to 100"]
