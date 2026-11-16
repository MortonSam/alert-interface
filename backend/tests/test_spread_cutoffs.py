"""One set of IV-RV spread cutoffs everywhere (Sam's item 7, 2026-11-16): the ticker page's "Options look pricey / cheap" row and
Ivy's Read, the vol regime chip on Discover and Build a Trade, the draft rules, the API's label-and-rule fields and the nightly
same_number_same_answer check all word a spread by thresholds.SPREAD_RICH_PP / SPREAD_CHEAP_PP. This fails if any surface words a
spread differently, or if a second copy of the cutoffs appears in the code."""
import re
from pathlib import Path

import pytest

from app import thresholds as T
from app.services.draft_rules import structure_for
from app.services.ivy_read_plain import spread_word

BACKEND_APP = Path(__file__).resolve().parents[1] / "app"
FRONTEND_SRC = Path(__file__).resolve().parents[2] / "frontend" / "src"
PROBES = sorted({T.SPREAD_CHEAP_PP + d for d in (-0.1, 0, 0.1)} | {T.SPREAD_RICH_PP + d for d in (-0.1, 0, 0.1)}
                | {-50, -12, -10, -9.9, -7, -4, 0, 4, 8, 9, 9.9, 10, 12, 50})


def word_of_key(key):
    return {"iv_rich": "rich", "iv_cheap": "cheap", "iv_fair": "neither", None: None}[key]


def word_of_label(label, empty="neither"):
    if label is None:
        return empty
    return "neither" if label.label == "in line" else label.label.split()[-1]


@pytest.mark.parametrize("x", PROBES)
def test_every_surface_words_a_spread_alike(x):
    key = word_of_key(T.vol_regime_key(x))                                    # the draft rules' regime (thesis) and Discover's chip
    assert word_of_label(T.spread_label(x)) == key                             # the ticker page's spread_labeled
    assert word_of_label(T.vol_regime_label(x)) == key                         # the chip's label (validate's second reading)
    assert {"pricey": "rich", "cheap": "cheap", "about the same": "neither"}[spread_word(x)] == key   # Ivy's Read, line E


def test_the_cutoffs_are_the_draft_rules():
    assert (T.SPREAD_RICH_PP, T.SPREAD_CHEAP_PP) == (8, -4)
    assert structure_for("moderate", T.vol_regime_key(T.SPREAD_RICH_PP + 0.1)) == "spread"     # rich: a debit spread
    assert structure_for("conservative", T.vol_regime_key(T.SPREAD_CHEAP_PP - 0.1)) == "long"  # cheap: the option outright
    assert T.vol_regime_key(None) is None


def test_the_label_rules_name_the_cutoffs():
    for x in (T.SPREAD_RICH_PP + 1, T.SPREAD_CHEAP_PP - 1, 0):
        rule = T.spread_label(x).rule
        assert any(str(abs(c)) in rule for c in (T.SPREAD_RICH_PP, T.SPREAD_CHEAP_PP))
        assert "10" not in rule


# an IV-RV spread (iv_rv_spread_pp, spread_pp, spreadPts) compared with a literal other than zero (the sign test is not a cutoff)
_SPREAD = r"(?:iv_rv\w*|\w*spread_pp\w*|spreadPts|ivRv\w*)"
_COMPARE = re.compile(rf"{_SPREAD}\s*[<>]=?\s*-?(?!0\b)\d|(?<![\w.])-?(?!0\b)\d[\d.]*\s*[<>]=?\s*{_SPREAD}", re.I)


def _sources(root: Path, exts):
    return [p for ext in exts for p in root.rglob(f"*{ext}") if "node_modules" not in p.parts and "__tests__" not in p.parts]


def test_no_surface_compares_a_spread_with_its_own_number():
    hits = []
    for p in _sources(BACKEND_APP, (".py",)) + (_sources(FRONTEND_SRC, (".ts", ".tsx")) if FRONTEND_SRC.exists() else []):
        for n, line in enumerate(p.read_text(errors="ignore").splitlines(), 1):
            if _COMPARE.search(line) and "TAPE_OPTIONS_BAND_PP" not in line:
                hits.append(f"{p}:{n}: {line.strip()}")
    assert hits == []


def test_no_second_copy_of_the_cutoffs():
    defined = re.compile(r"\b(\w*(?:IV_RICH|IV_CHEAP|SPREAD_RICH|SPREAD_CHEAP)\w*)\s*(?::[^=]+)?=\s*-?\d")
    found = []
    for p in _sources(BACKEND_APP, (".py",)) + (_sources(FRONTEND_SRC, (".ts", ".tsx")) if FRONTEND_SRC.exists() else []):
        for m in defined.finditer(p.read_text(errors="ignore")):
            found.append((p.name, m.group(1)))
    want = [("thresholds.py", "SPREAD_CHEAP_PP"), ("thresholds.py", "SPREAD_RICH_PP")]
    if FRONTEND_SRC.exists():
        want += [("thresholds.ts", "SPREAD_CHEAP_PP"), ("thresholds.ts", "SPREAD_RICH_PP")]
    assert sorted(found) == want


def test_frontend_reads_the_cutoffs_only_from_thresholds():
    if not FRONTEND_SRC.exists():
        pytest.skip("frontend not mounted")
    for rel in ("lib/optionsRows.ts", "lib/encodings/volRegime.ts"):
        src = (FRONTEND_SRC / rel).read_text()
        assert re.search(r'import \{[^}]*SPREAD_CHEAP_PP[^}]*SPREAD_RICH_PP[^}]*\} from "@/lib/thresholds"', src), rel
