"""A served note states only what its check confirmed (Sam, 2026-10-28).

The verifier splits a note into claims and gives each a verdict. A visitor used to see the whole note as fact, with the unsupported and
contradicted claims listed only in a collapsed bar under it (BNY: "⚠ 2 unsupported · 17 claims", both in What they do). Now each claim
is located in the sentence of the note it came from, and the served note drops every sentence holding an unsupported or contradicted
claim; a point whose text is all dropped, or whose lead holds one, goes whole. The verification served beside it lists the supported
claims that remain, so the bar names no unsupported claim.

The verifier copies each claim's sentence from the note ("sentence"); older verifications have none, and the claim is found by its
words instead (a claim is usually a span of its sentence). A claim that cannot be found in the note is counted as unlocated: its
sentence cannot be dropped, so it counts against the note like a lost sentence (lost()).

A note that would lose more than MAX_LOST sentences is regenerated once; if it still would, it is held and the digest names it
(research_note_service.run_research_note_background).
"""
from __future__ import annotations

import re

NOTE_CHECK_VERSION = 2          # 2 (2026-10-28): Item 1 of the 10-K as evidence, each claim's sentence, unconfirmed sentences dropped
MAX_LOST = 3                    # more lost sentences than this and the note is regenerated once, then held
MATCH_SHARE = 0.5               # else, the sentence holding the largest share of its words, at least this share
SECTIONS = ("highlights", "watch", "risks")
PROSE = ("what_they_do", "bottom_line")
DROP = ("unsupported", "contradicted")

_SPLIT = re.compile(r"(?<=[.!?])(?<!\b[A-Z]\.)(?<!\b[A-Z][a-z]\.)\s+(?=[A-Z\"'(])")   # never after an initial ("U.S.") or "Inc."/"Co."
_WORD = re.compile(r"[a-z0-9$%]+(?:[.,][0-9]+)*")


def sentences(text: str | None) -> list[str]:
    """Pure: the text's sentences."""
    return [s.strip() for s in _SPLIT.split((text or "").strip()) if s.strip()]


def words(text: str | None) -> list[str]:
    t = (text or "").lower().replace("’", "'").replace("“", '"').replace("”", '"')
    return _WORD.findall(t)


def units(structured: dict | None) -> list[dict]:
    """Pure: the note's sentences in reading order, {where, text}: where is ("what_they_do"|"bottom_line", None, i) for prose,
    (section, point, "lead") for a point's lead and (section, point, i) for the i-th sentence of its detail."""
    s = structured or {}
    out = []
    for key in PROSE:
        out += [{"where": (key, None, i), "text": t} for i, t in enumerate(sentences(s.get(key)))]
    for sec in SECTIONS:
        for j, p in enumerate(s.get(sec) or []):
            if not isinstance(p, dict):
                continue
            if (p.get("lead") or "").strip():
                out.append({"where": (sec, j, "lead"), "text": p["lead"].strip()})
            out += [{"where": (sec, j, i), "text": t} for i, t in enumerate(sentences(p.get("detail")))]
    return out


META = re.compile(r"most recent quarter|^\s*#|rating:", re.I)   # the serialized note's heading and its "Most recent quarter: date" line


def is_meta(claim: dict) -> bool:
    """Pure: a claim about the serialized note's own heading or date line, never a sentence of the note (the verifier read
    "Most recent quarter: 2026-07-21" as a claim on 25 notes before 2026-10-28): neither dropped nor counted."""
    return bool(META.search(str(claim.get("claim") or ""))) and len(words(claim.get("claim"))) <= 12


def locate(claim: dict, us: list[dict]) -> int | None:
    """Pure: the index in `us` of the sentence a claim came from: the verifier's copied sentence when it is the note's, else the
    sentence holding the claim's words (all of them in order, else at least MATCH_SHARE of them); None when no sentence does."""
    copied = " ".join(words(claim.get("sentence")))
    if copied:
        for i, u in enumerate(us):
            if " ".join(words(u["text"])) == copied:
                return i
    cw = words(claim.get("claim"))
    if not cw:
        return None
    joined = " ".join(cw)
    holding = [i for i, u in enumerate(us) if joined in " ".join(words(u["text"]))]
    if holding:
        return min(holding, key=lambda i: len(us[i]["text"]))
    best, score = None, 0.0
    for i, u in enumerate(us):
        sw = set(words(u["text"]))
        share = sum(1 for w in cw if w in sw) / len(cw)
        if share > score:
            best, score = i, share
    return best if score >= MATCH_SHARE else None


def _verdict(c: dict) -> str:
    return str(c.get("verdict") or c.get("status") or "").lower()


def review(structured: dict | None, verification: dict | None) -> dict:
    """Pure: {drop: set of unit indexes, lost: [sentences dropped], unlocated: [claims not found], keep_claims: [claims served]}."""
    us = units(structured)
    claims = [c for c in ((verification or {}).get("claims") or []) if isinstance(c, dict)]
    at = [locate(c, us) for c in claims]
    drop = {i for c, i in zip(claims, at) if i is not None and _verdict(c) in DROP}
    points: dict[tuple, list[int]] = {}
    for k, u in enumerate(us):
        if u["where"][1] is not None:
            points.setdefault(u["where"][:2], []).append(k)
    for ks in points.values():              # a point goes whole when its lead holds a dropped claim or its text is all dropped
        lead = [k for k in ks if us[k]["where"][2] == "lead"]
        body = [k for k in ks if us[k]["where"][2] != "lead"]
        if any(k in drop for k in lead) or (body and all(k in drop for k in body)):
            drop |= set(ks)
    lost = [us[i]["text"] for i in sorted(drop) if us[i]["where"][2] != "lead"]
    unlocated = [c.get("claim") for c, i in zip(claims, at) if i is None and _verdict(c) in DROP and not is_meta(c)]
    keep = [c for c, i in zip(claims, at) if _verdict(c) == "supported" and (i is None or i not in drop) and not is_meta(c)]
    return {"drop": drop, "lost": lost, "unlocated": unlocated, "keep_claims": keep, "units": us}


def lost(structured: dict | None, verification: dict | None) -> int:
    """Pure: how many sentences the served note loses to its check, an unlocated unsupported or contradicted claim counting as one."""
    r = review(structured, verification)
    return len(r["lost"]) + len(r["unlocated"])


def served(structured: dict | None, verification: dict | None, content: str | None) -> tuple[dict | None, dict | None, str | None]:
    """Pure: (structured, verification, content) with every sentence that holds an unsupported or contradicted claim removed, and the
    verification's claims cut to the supported ones still shown."""
    if not verification or not isinstance(verification.get("claims"), list):
        return structured, verification, content
    r = review(structured, verification)
    us, drop = r["units"], r["drop"]
    if structured:
        s = dict(structured)
        for key in PROSE:
            if s.get(key) is not None:
                s[key] = " ".join(u["text"] for k, u in enumerate(us) if u["where"][0] == key and k not in drop)
        for sec in SECTIONS:
            pts = []
            for j, p in enumerate(s.get(sec) or []):
                if not isinstance(p, dict):
                    continue
                mine = [k for k, u in enumerate(us) if u["where"][:2] == (sec, j)]
                if mine and all(k in drop for k in mine):
                    continue                                  # review() drops a point whole or keeps its lead
                if any(k in drop for k in mine):
                    p = {**p, "detail": " ".join(us[k]["text"] for k in mine if us[k]["where"][2] != "lead" and k not in drop)}
                pts.append(p)
            s[sec] = pts
        structured = s
    if content:
        for k in sorted(drop):
            if us[k]["where"][2] != "lead":
                content = content.replace(us[k]["text"], "")
        content = re.sub(r"[ \t]{2,}", " ", content)
    return structured, {**verification, "claims": r["keep_claims"]}, content
