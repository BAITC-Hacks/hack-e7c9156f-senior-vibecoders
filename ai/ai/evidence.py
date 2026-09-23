"""Deterministic quote verification and correction of clause references."""

from __future__ import annotations

import re

from pydantic import BaseModel
from rapidfuzz import fuzz

from .parsing import clause_text
from .schemas import AnalysisResult, DocumentText, Evidence


def normalize(text: str) -> str:
    text = text.lower().replace("ё", "е").replace("\u00ad", "")
    text = text.translate(str.maketrans({c: '"' for c in '«»“”„"'}))
    text = text.translate(str.maketrans({"–": "-", "—": "-"}))
    text = re.sub(r"\bno\b", "№", text)
    text = re.sub(r"(?<=\w)-\s+(?=\w)", "-", text)
    return re.sub(r"\s+", " ", text).strip()


def verify_quote(
    doc: DocumentText, clause_id: str, quote: str, fuzzy_threshold: int = 90
) -> bool:
    quote = normalize(quote)
    if not quote or not any(c.clause_id == clause_id for c in doc.clauses):
        return False
    text = normalize(clause_text(doc, clause_id, with_children=True) or "")
    return quote in text or (
        len(quote) >= 20
        and fuzz.partial_ratio(quote, text, score_cutoff=fuzzy_threshold) >= fuzzy_threshold
    )


def locate_quote(doc: DocumentText, quote: str) -> str | None:
    """Prefer exact matches, then fuzzy matches; deepest/shortest wins ties."""
    quote = normalize(quote)
    if not quote:
        return None
    candidates = [
        (c, normalize(clause_text(doc, c.clause_id, with_children=True) or ""))
        for c in doc.clauses
    ]
    candidates.sort(key=lambda item: (-item[0].clause_id.count("."), len(item[1])))
    for c, text in candidates:
        if quote in text:
            return c.clause_id
    if len(quote) >= 20:
        for c, text in candidates:
            if fuzz.partial_ratio(quote, text, score_cutoff=90) >= 90:
                return c.clause_id
    return None


def verify_evidence(ev: Evidence, docs: dict[str, DocumentText]) -> Evidence:
    doc = docs.get(ev.doc_id)
    if doc is None:
        return ev.model_copy(update={"verified": False})
    if verify_quote(doc, ev.clause_id, ev.quote):
        return ev.model_copy(update={"verified": True})
    found = locate_quote(doc, ev.quote)
    return ev.model_copy(update={
        "clause_id": found if found is not None else ev.clause_id,
        "verified": found is not None,
    })


def verify_result(result: AnalysisResult) -> AnalysisResult:
    """Copy the entire model tree, including critics, verifying every Evidence."""
    docs = {doc.doc_id: doc for doc in result.documents}

    def visit(value):
        if isinstance(value, Evidence):
            return verify_evidence(value, docs)
        if isinstance(value, BaseModel):
            return value.model_copy(update={
                name: visit(getattr(value, name)) for name in type(value).model_fields
            })
        if isinstance(value, list):
            return [visit(item) for item in value]
        if isinstance(value, dict):
            return {key: visit(item) for key, item in value.items()}
        return value

    return visit(result)
