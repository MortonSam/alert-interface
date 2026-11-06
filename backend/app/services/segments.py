"""Revenue by segment from a company's latest 10-K, read from the filing's own XBRL instance (Ivy's walkthrough, step 1).

The company-facts API leaves out dimensional facts, and Intrinio's fundamentals carry the face statements only (no segments,
checked 2026-10-19 on MU's FY2026 10-K), so the instance document (<prefix>_htm.xml) is read directly. A split is used only when
it is trustworthy by its own arithmetic: on one axis (business segments first, then products and services), for the fiscal
year the 10-K reports, every member's revenue on the same tag as the company's total adds up to that total within
SUM_TOLERANCE (eliminations and corporate rows count toward the sum and are never shown as a segment). Anything else is
returned as an absence with its reason; a split is never estimated or normalised to fit.

A segment's name is its filed label (or its member's name), then written the way the 10-K's own text writes it (text_name):
among the label and its variants ("and" for "And", "&" for "and", the plural or singular of its last word), the one the
document's text uses most, and the label with a lower-case "and" when the text uses none of them.
"""
from __future__ import annotations

import re
from datetime import date
from io import BytesIO

from app.services.growth import revenue_tags

SEGMENTS_VERSION = 3                 # 2 (2026-10-19): names as the 10-K's text writes them (text_name)
                                     # 3 (2026-11-06): the other axis's split too, when it also adds up (`other`), so step 1 can follow the
                                     #   description's breakdown and say which one its figures use
SUM_TOLERANCE = 0.01                 # members must add up to the total within 1%
FY_DAYS = (350, 380)                 # the fiscal year's duration
MIN_SEGMENTS = 2                     # one member is the company itself, not a split
AXES = [("srt:ProductOrServiceAxis", "product or service"), ("us-gaap:StatementBusinessSegmentsAxis", "business segment")]   # what it sells first (iPhone, not Americas)
BUSINESS_AXIS = "us-gaap:StatementBusinessSegmentsAxis"
ACRONYM = re.compile(r"^[A-Z0-9&]{2,6}$")       # a label like "CMBU" names nothing a newcomer can read
ADJUSTMENT = re.compile(r"elimination|intersegment|intercompany|reconcil|corporate(?!.*segment)|consolidat|unallocated|nonsegment|non-segment", re.I)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _ns_prefix(nsmap: dict, uri: str) -> str | None:
    for p, u in nsmap.items():
        if u == uri:
            return p
    return None


def parse_instance(xml: bytes) -> dict:
    """Pure: {period_end (dei:DocumentPeriodEndDate), contexts: {id: (start, end, {axis: member})}, facts: [(qname, context id, value)]}
    from an XBRL instance. Only us-gaap facts with a numeric value are kept. Dimension and member QNames keep the prefixes the
    instance declares (us-gaap:, srt:, the company's own)."""
    from lxml import etree
    contexts: dict[str, tuple[date | None, date | None, dict[str, str]]] = {}
    facts: list[tuple[str, str, float]] = []
    period_end: date | None = None
    for _, el in etree.iterparse(BytesIO(xml), events=("end",), huge_tree=True):
        tag = el.tag if isinstance(el.tag, str) else ""
        name = _local(tag)
        if name == "context":
            start = end = None
            dims: dict[str, str] = {}
            for sub in el.iter():
                n = _local(sub.tag) if isinstance(sub.tag, str) else ""
                if n == "startDate":
                    start = _date(sub.text)
                elif n == "endDate":
                    end = _date(sub.text)
                elif n == "instant":
                    start = end = _date(sub.text)
                elif n == "explicitMember":
                    dims[(sub.get("dimension") or "").strip()] = (sub.text or "").strip()
            contexts[el.get("id")] = (start, end, dims)
            el.clear()
        elif el.get("contextRef") is not None:
            uri = tag[1:].split("}", 1)[0] if tag.startswith("{") else ""
            if name == "DocumentPeriodEndDate" and "dei" in uri:
                period_end = _date(el.text) or period_end
            elif "us-gaap" in uri:
                try:
                    facts.append((name, el.get("contextRef"), float((el.text or "").strip())))
                except ValueError:
                    pass
            el.clear()
    return {"period_end": period_end, "contexts": contexts, "facts": facts}


def _date(s: str | None) -> date | None:
    try:
        return date.fromisoformat((s or "").strip()[:10])
    except ValueError:
        return None


def parse_labels(xml: bytes | None) -> dict[str, str]:
    """Pure: {element id (e.g. "mu_ComputeAndNetworkingMember"): its standard label without " [Member]"} from a label linkbase."""
    if not xml:
        return {}
    from lxml import etree
    XL = "{http://www.w3.org/1999/xlink}"
    locs: dict[str, str] = {}
    arcs: list[tuple[str, str]] = []
    labels: dict[str, list[tuple[str, str]]] = {}
    for _, el in etree.iterparse(BytesIO(xml), events=("end",), huge_tree=True):
        n = _local(el.tag) if isinstance(el.tag, str) else ""
        if n == "loc":
            locs[el.get(XL + "label")] = (el.get(XL + "href") or "").split("#")[-1]
        elif n == "labelArc":
            arcs.append((el.get(XL + "from"), el.get(XL + "to")))
        elif n == "label":
            labels.setdefault(el.get(XL + "label"), []).append(((el.get(XL + "role") or "").rsplit("/", 1)[-1], (el.text or "").strip()))
    out: dict[str, str] = {}
    for frm, to in arcs:
        el_id = locs.get(frm)
        cands = labels.get(to) or []
        best = next((t for r, t in cands if r == "label"), None) or next((t for r, t in cands if r == "terseLabel"), None)
        if el_id and best and el_id not in out:
            out[el_id] = re.sub(r"\s*\[Member\]\s*$", "", best).strip()
    return out


def humanize(member: str) -> str:
    """Pure: "mu:ComputeAndNetworkingBusinessUnitMember" -> "Compute and Networking Business Unit" (when no label is filed)."""
    local = member.split(":", 1)[-1]
    local = re.sub(r"Member$", "", local)
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", local).split()
    small = {"And", "Of", "The", "For", "In", "On", "To", "Or"}
    return " ".join(w.lower() if i and w in small else w for i, w in enumerate(words))


def label_for(member: str, labels: dict[str, str]) -> str:
    """Pure: the filed label (else the humanized name), without a trailing "Segment" or "Reportable Segment"."""
    label = labels.get(member.replace(":", "_")) or humanize(member)
    return re.sub(r"\s+(?:reportable\s+)?(?:operating\s+)?segments?$", "", label, flags=re.I).strip() or label


def name_variants(label: str) -> list[str]:
    """Pure: the label tidied (a lower-case "and", no "[member]", no space before a comma) and its variants: "&" for "and", and the
    plural or singular of its last word. The tidied label comes first."""
    base = re.sub(r"\s*\[member\]\s*$", "", label, flags=re.I)
    base = re.sub(r"\s+,", ",", base)
    base = re.sub(r"(?<=\S) And (?=\S)", " and ", base).strip()
    out = [base]
    if " and " in base:
        out.append(base.replace(" and ", " & "))
    if " & " in base:
        out.append(base.replace(" & ", " and "))
    for v in list(out):
        head, _, last = v.rpartition(" ")
        word = last or v
        other = word[:-1] if word.endswith("s") and not word.endswith("ss") else word + "s"
        if word[:1].isalpha() and len(word) > 2:
            out.append(f"{head} {other}" if head else other)
    return list(dict.fromkeys(out))


def document_text(html: str | None) -> str:
    """Pure: a filing's visible text, entities decoded, white space collapsed."""
    import html as H
    if not html:
        return ""
    t = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", H.unescape(t)).replace("\u00a0", " ")


def text_name(label: str, text: str) -> str:
    """Pure: the variant of the label (name_variants) the 10-K's text uses most, case and word boundaries exact; the tidied label
    on a tie or when the text uses none."""
    variants = name_variants(label)
    counts = [len(re.findall(rf"(?<![\w&]){re.escape(v)}(?![\w&])", text)) if text else 0 for v in variants]
    best = max(range(len(variants)), key=lambda i: (counts[i], -i))
    return variants[best] if counts[best] > 0 else variants[0]


def fiscal_year(parsed: dict) -> tuple[date, date] | None:
    """Pure: (start, end) of the fiscal year the 10-K reports: a duration of FY_DAYS ending on the document period end (or, when the
    cover omits it, the latest such duration with no dimensions)."""
    ctx = parsed["contexts"]
    years = {(s, e) for s, e, d in ctx.values() if s and e and not d and FY_DAYS[0] <= (e - s).days <= FY_DAYS[1]}
    if not years:
        return None
    pe = parsed["period_end"]
    if pe:
        near = [y for y in years if abs((y[1] - pe).days) <= 7]
        if near:
            return max(near, key=lambda y: y[1])
    return max(years, key=lambda y: y[1])


SEGMENT_DIM = ("srt:ConsolidationItemsAxis", "us-gaap:OperatingSegmentsMember")    # a segment's own figure carries this second dimension (ASU 2023-07)
CONSOLIDATION_AXIS = "srt:ConsolidationItemsAxis"
EXTERNAL_DIM = ("srt:MajorCustomersAxis", "us-gaap:ExternalCustomersMember")
EXACT_TOLERANCE = 0.001              # a partition found among more members than the filing's own split must add up to the total within 0.1%
MAX_SEARCH_MEMBERS = 16              # beyond this many members only the whole set is tried
GENERIC_PREFIXES = ("us-gaap:", "srt:")
MIN_SHOWN_SHARE = 0.0005            # a member under 0.05% of sales rounds to 0.0% and is not shown


def _bare(qname: str) -> str:
    return qname.split(":", 1)[-1]


def _members(rows: list[tuple[tuple, float]], axis: str, external: bool) -> tuple[dict[str, float] | None, float]:
    """Pure: ({member: value} on `axis`, the sum of the consolidation rows: corporate, eliminations, reconciling items). A fact's
    only other dimensions may be the operating-segments marker and (in the external pass, required) the external-customers one.
    Axes and the standard members are matched by local name, whatever prefix the filing declares for them. None when one member
    carries two different values."""
    members: dict[str, float] = {}
    adjust = 0.0
    for dims, val in rows:
        d = {_bare(k): v for k, v in dict(dims).items()}
        has_ext = _bare(d.get(_bare(EXTERNAL_DIM[0]), "")) == _bare(EXTERNAL_DIM[1])
        if external != has_ext:
            continue
        d.pop(_bare(EXTERNAL_DIM[0]), None)
        if _bare(d.get(_bare(SEGMENT_DIM[0]), "")) == _bare(SEGMENT_DIM[1]):
            d.pop(_bare(SEGMENT_DIM[0]))
        if set(d) == {_bare(axis)}:
            m = d[_bare(axis)]
            if m in members and abs(members[m] - val) > 0.5:
                return None, 0.0
            members[m] = val
        elif set(d) == {_bare(CONSOLIDATION_AXIS)} and axis == BUSINESS_AXIS:
            adjust += val
    return members, adjust


def partition(members: dict[str, float], target: float) -> list[str] | None:
    """Pure: the finest set of members that adds up to `target`: every member when they do within SUM_TOLERANCE, else the subset
    with the most members (then the fewest generic us-gaap/srt members) within EXACT_TOLERANCE, which is how a filing that lists
    an aggregate beside its parts (Apple's Products and Services beside iPhone and Mac) is read. None when nothing adds up."""
    names = sorted(members)
    if target <= 0 or not names:
        return None
    if abs(sum(members.values()) - target) <= SUM_TOLERANCE * target:
        return names
    if len(names) > MAX_SEARCH_MEMBERS:
        return None
    best: tuple[int, int, list[str]] | None = None
    for mask in range(1, 1 << len(names)):
        chosen = [names[i] for i in range(len(names)) if mask >> i & 1]
        if abs(sum(members[n] for n in chosen) - target) > EXACT_TOLERANCE * target:
            continue
        key = (len(chosen), -sum(1 for n in chosen if n.startswith(GENERIC_PREFIXES)))
        if best is None or key > best[:2]:
            best = (key[0], key[1], chosen)
    return best[2] if best else None


def split_revenue(parsed: dict, sector: str | None, labels: dict[str, str] | None = None) -> dict:
    """Pure: the trustworthy split, or the reason there is none.

    Returns {ok: True, axis, axis_label, tag, start, end, total, segments: [{member, label, value, share}], adjustments, external,
    other} or {ok: False, reason}. For each revenue tag in the sector's order that carries one fiscal-year total, each axis in AXES is
    tried, first on sales to outside customers (when the filing tags them) and then on segment totals; the first whose members (with
    the corporate and elimination rows, when the axis is business segments) add up to the total wins (partition). `other` is the first
    readable split on the other axis when that one adds up too ({axis, axis_label, tag, total, segments}), else None."""
    labels = labels or {}
    fy = fiscal_year(parsed)
    if not fy:
        return {"ok": False, "reason": "the filing's XBRL has no full fiscal year"}
    ctx = parsed["contexts"]
    by_tag: dict[str, list[tuple[str, float]]] = {}
    for tag, cid, val in parsed["facts"]:
        by_tag.setdefault(tag, []).append((cid, val))
    tried: list[str] = []
    fallback: dict | None = None
    found: dict[str, dict] = {}                           # the first readable split on each axis
    for tag in revenue_tags(sector):
        rows = [(tuple(sorted(ctx[cid][2].items())), val) for cid, val in by_tag.get(tag) or [] if ctx.get(cid) and (ctx[cid][0], ctx[cid][1]) == fy]
        totals = {val for dims, val in rows if not dims}
        if len(totals) != 1 or next(iter(totals)) <= 0:
            continue
        total = next(iter(totals))
        for axis, axis_label in AXES:
            for external in (True, False):
                members, adjust = _members(rows, axis, external)
                if not members:
                    continue
                tried.append(f"{tag} by {axis_label}")
                candidates = {m: v for m, v in members.items() if not ADJUSTMENT.search(m)}
                adjust += sum(v for m, v in members.items() if ADJUSTMENT.search(m))
                chosen = partition(candidates, total - adjust) or (partition(candidates, total) if adjust else None)
                if not chosen:
                    continue
                shown = [m for m in chosen if candidates[m] / total >= MIN_SHOWN_SHARE]
                if len(shown) < MIN_SEGMENTS:
                    continue
                segs = sorted(({"member": m, "label": label_for(m, labels), "value": candidates[m], "share": round(candidates[m] / total * 100, 1)} for m in shown),
                              key=lambda s: -s["value"])
                if sum(s["share"] for s in segs) > 100 + SUM_TOLERANCE * 100:
                    continue                                  # shares over 100%: the segments count sales between themselves
                out = {"ok": True, "axis": axis, "axis_label": axis_label, "tag": tag, "start": fy[0], "end": fy[1], "total": total, "segments": segs,
                       "adjustments": round(adjust, 2), "external": external}
                if any(ACRONYM.match(g["label"]) for g in segs):
                    fallback = fallback or out                 # readable on another axis? keep looking, else use this one
                    continue
                found.setdefault(axis, out)
    if found:
        first, *rest = found.values()                      # the first found, as before; the other axis beside it
        return {**first, "other": ({k: rest[0][k] for k in ("axis", "axis_label", "tag", "total", "segments")} if rest else None)}
    if fallback:
        return fallback
    if tried:
        return {"ok": False, "reason": "the segments it files do not add up to its total sales (" + "; ".join(dict.fromkeys(tried)) + ")"}
    return {"ok": False, "reason": "its 10-K files no revenue split by segment or product"}


def latest_annual(submissions: dict) -> dict | None:
    """Pure: the latest 10-K (or 10-K405, 10-KT) in a submissions record: {accession, filed, report_date, primary_document, form}."""
    r = (submissions.get("filings") or {}).get("recent") or {}
    for i, form in enumerate(r.get("form") or []):
        if form in ("10-K", "10-KT", "10-K405"):
            return {"accession": r["accessionNumber"][i], "filed": _date(r["filingDate"][i]), "report_date": _date((r.get("reportDate") or [""] * (i + 1))[i]),
                    "primary_document": r["primaryDocument"][i], "form": form}
    return None


def instance_and_labels(names: list[str]) -> tuple[str | None, str | None]:
    """Pure: the XBRL instance (<prefix>_htm.xml) and the label linkbase (<prefix>_lab.xml) among a filing's file names."""
    inst = next((n for n in names if n.endswith("_htm.xml")), None)
    lab = next((n for n in names if n.endswith("_lab.xml")), None)
    return inst, lab


async def latest_annual_for(edgar, ciks: list[str]) -> tuple[str | None, dict | None]:
    """(cik, latest 10-K) across a company's CIKs, newest filing first (a re-domiciled company files its first 10-K under the new
    CIK only after a year: XOM's 2026 holding company)."""
    best: tuple[str | None, dict | None] = (None, None)
    for cik in ciks:
        k = latest_annual(await edgar.get_submissions(cik))
        if k and (best[1] is None or (k["filed"] or date.min) > (best[1]["filed"] or date.min)):
            best = (cik, k)
    return best


async def read_segments(edgar, ciks: list[str], sector: str | None) -> dict:
    """The latest 10-K's split (split_revenue) with the filing's receipt: {..., accession, filed, url}. Network: the submissions
    record (cached), the filing index, the instance and the label linkbase. Raises on a network failure (the caller records it)."""
    cik, k = await latest_annual_for(edgar, ciks)
    if not k:
        return {"ok": False, "reason": "no 10-K on file at the SEC"}
    acc = k["accession"].replace("-", "")
    base = f"/Archives/edgar/data/{int(cik)}/{acc}"
    resp = await edgar._paced_get(edgar._sec_client, f"{base}/index.json")
    resp.raise_for_status()
    names = [it.get("name", "") for it in (resp.json().get("directory") or {}).get("item", [])]
    inst, lab = instance_and_labels(names)
    receipt = {"accession": k["accession"], "filed": k["filed"], "form": k["form"], "url": f"https://www.sec.gov{base}/{k['primary_document']}"}
    if not inst:
        return {"ok": False, "reason": "the 10-K has no XBRL instance", **receipt}
    x = await edgar._paced_get(edgar._sec_client, f"{base}/{inst}")
    x.raise_for_status()
    labels = {}
    if lab:
        lx = await edgar._paced_get(edgar._sec_client, f"{base}/{lab}")
        if lx.status_code == 200:
            labels = parse_labels(lx.content)
    out = split_revenue(parse_instance(x.content), sector, labels)
    if out.get("ok"):
        text = document_text(await edgar.fetch_filing_html(cik, k["accession"], k["primary_document"]))
        for g in out["segments"] + ((out.get("other") or {}).get("segments") or []):
            g["label"] = text_name(g["label"], text)
    return {**out, **receipt}
