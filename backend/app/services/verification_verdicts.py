"""One final verdict per claim. The verifier returns, for each claim, a verdict (supported, unsupported, contradicted) and a
one-sentence reason, never its deliberation; a reason that corrects itself ("re-evaluating", "actually", a verdict that changes
inside the text) sends the claim back once, and a second such answer counts as unsupported. The summary is never the model's: it is
counted from the claims' verdicts, at store and at read, so the badges and the totals can only agree.

Stored notes from before 2026-10-12 carry {status, evidence} per claim and a model-written summary; normalize_verification() reads
them as verdicts and recounts, so one field per claim is the truth everywhere.
"""
from __future__ import annotations

import re

VERDICTS = ("supported", "unsupported", "contradicted")
FALLBACK = "unsupported"
SELF_CORRECTION = re.compile(r"\bre-?evaluat\w*|\bactually\b|\bon reflection\b|\bcorrection\b|\bon second thought\b|\bwait,|\bi (?:was|am) wrong\b|\bupon (?:re-?)?review\b", re.I)
UNSETTLED_REASON = "The checker did not settle on one verdict for this claim, so it counts as unsupported."


def self_corrected(reason: str | None, verdict: str | None = None) -> bool:
    """Pure: the reason reads as deliberation rather than a settled verdict: a correction cue, or two different verdict words."""
    text = reason or ""
    if SELF_CORRECTION.search(text):
        return True
    words = {v for v in VERDICTS if re.search(rf"\b{v}\b", text, re.I)}
    return len(words) >= 2


_CLAIM_START = re.compile(r'"claim"\s*:\s*"')
_NEXT_KEY = re.compile(r'"\s*,\s*"(?:verdict|status|reason|evidence)"\s*:')
_VERDICT = re.compile(r'"(?:verdict|status)"\s*:\s*"([a-z]+)"', re.I)
_REASON = re.compile(r'"(?:reason|evidence)"\s*:\s*"(.*)"\s*\}', re.S)


def parse_claims(content: str | None) -> list[dict]:
    """The verifier's {"claims": [{claim, verdict, reason}]} as normalized claims. A row whose text carries the note's or the filing's
    own quotation marks unescaped (AVY and CARR on 2026-10-28: "Expecting ',' delimiter") is read by its keys instead, as the report-date
    reader's parse_model_json does: the claim runs to the next key, the reason to the row's closing brace. Raises ValueError when no
    claim can be read at all, so a reply that is not a verification never passes for one."""
    import json
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    body = m.group(0) if m else text
    try:
        rows = json.loads(body).get("claims") or []
        return [normalize_claim(c) for c in rows if isinstance(c, dict)]
    except (ValueError, AttributeError):
        pass
    starts = [x.end() for x in _CLAIM_START.finditer(body)]
    out = []
    for i, start in enumerate(starts):
        chunk = body[start:(starts[i + 1] if i + 1 < len(starts) else len(body))]
        end = _NEXT_KEY.search(chunk)
        claim = chunk[:end.start()] if end else ""
        verdict = _VERDICT.search(chunk)
        reason = _REASON.search(chunk)
        if claim:
            out.append(normalize_claim({"claim": claim.replace('\\"', '"'), "verdict": verdict.group(1) if verdict else None,
                                        "reason": (reason.group(1) if reason else "").replace('\\"', '"')}))
    if not out:
        raise ValueError("the verifier's reply holds no claim that can be read")
    return out


def normalize_claim(raw: dict) -> dict:
    """Pure: {claim, verdict, reason} from a model row in either shape (verdict/reason, or the older status/evidence)."""
    verdict = str(raw.get("verdict") or raw.get("status") or "").strip().lower()
    reason = str(raw.get("reason") if raw.get("reason") is not None else raw.get("evidence") or "").strip()
    if verdict not in VERDICTS:
        verdict = FALLBACK
    return {"claim": str(raw.get("claim") or "").strip(), "verdict": verdict, "reason": reason}


def summary_of(claims: list[dict]) -> dict:
    """Pure: the totals counted from the claims' verdicts."""
    return {v: sum(1 for c in claims if c.get("verdict") == v) for v in VERDICTS}


def normalize_verification(raw: dict | None) -> dict | None:
    """Pure: the stored verification as the API serves it: claims with one verdict each, the summary recounted from them, and the
    older field names mirrored (status, evidence) for readers that still use them."""
    if not raw or not isinstance(raw.get("claims"), list):
        return None
    claims = [normalize_claim(c) for c in raw["claims"] if isinstance(c, dict)]
    return {"claims": [{**c, "status": c["verdict"], "evidence": c["reason"]} for c in claims], "summary": summary_of(claims)}


def problems(raw: dict | None) -> list[str]:
    """Pure: why a stored verification is not self-consistent: an unknown verdict, a self-correcting reason, or a stored summary
    that differs from the claims' count."""
    out: list[str] = []
    if not raw or not isinstance(raw.get("claims"), list):
        return ["no claims"]
    claims = [c for c in raw["claims"] if isinstance(c, dict)]
    for i, c in enumerate(claims):
        v = str(c.get("verdict") or c.get("status") or "").lower()
        if v not in VERDICTS:
            out.append(f"claim {i + 1}: verdict {v!r}")
        if self_corrected(c.get("reason") if c.get("reason") is not None else c.get("evidence"), v):
            out.append(f"claim {i + 1}: the reason corrects itself")
    counted = summary_of([normalize_claim(c) for c in claims])
    stored = raw.get("summary") or {}
    for v in VERDICTS:
        if stored.get(v) is not None and int(stored.get(v)) != counted[v]:
            out.append(f"summary says {v} {stored.get(v)}, the claims count {counted[v]}")
    return out
