

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
