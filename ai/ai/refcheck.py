"""Check conclusion citations against verified evidence, without model calls.

This checks reference provenance, not the truth of the surrounding assertion.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

from .schemas import AnalysisResult


@dataclass
class Ref:
    side: Literal["before", "after"] | None
    clause_id: str
    # Half-open slice covering the marker and ID, or just the ID in a list.
    # An explicit side is outside the slice and survives sanitization.
    span: tuple[int, int]


_ID = (
    r"(?:[^\W\d][\w-]*:\d+|(?:абз\.|прил\.)\d+|т\d+(?:\.\d+)*"
    r"|\d+(?:\.(?:\d+|[а-яёa-z]))*)(?:#\d+)?(?![\w#]|\.[\w])"
)
_TOKEN = re.compile(
    rf"(?P<open>\()|(?P<close>\))|"
    rf"(?<!\w)(?:(?P<side>до|после)\s*,\s*)?"
    rf"(?P<reference>(?:пп?\.|пункт(?:а|ы|ов|е|у|ам|ами|ах)?\b)"
    rf"\s*(?P<id>{_ID}))",
    re.IGNORECASE,
)
_NEXT = re.compile(rf"\s*(?:,|\bи\b)\s*(?P<id>{_ID})", re.IGNORECASE)
_SIDES = {"до": "before", "после": "after"}


def extract_refs(md: str) -> list[Ref]:
    """Extract marked references; side inheritance is local to each parenthesis."""
    refs: list[Ref] = []
    scopes: list[Literal["before", "after"] | None] = []
    cursor = 0
    while match := _TOKEN.search(md, cursor):
        cursor = match.end()
        if match.group("open"):
            scopes.append(None)
            continue
        if match.group("close"):
            if scopes:
                scopes.pop()
            continue
        side = _SIDES[match.group("side").lower()] if match.group("side") else (
            scopes[-1] if scopes else None
        )
        if scopes:
            scopes[-1] = side
        refs.append(Ref(side, match.group("id"), match.span("reference")))
        while following := _NEXT.match(md, cursor):
            refs.append(Ref(side, following.group("id"), following.span("id")))
            cursor = following.end()
    return refs


def allowed_refs(result: AnalysisResult) -> set[tuple[str, str]]:
    """Collect verified sources of changes and all findings, including critics.

    Rejected findings are included because a human may accept them on review.
    Sources on units/mappings alone do not qualify as finding evidence.
    """
    evidence = [e for change in result.unit_changes for e in change.evidence]
    for finding in result.findings + result.rejected_findings:
        evidence.extend(finding.evidence)
        if finding.critic:
            evidence.extend(finding.critic.counter_evidence)
    return {(e.side, e.clause_id) for e in evidence if e.verified}


def _related(left: str, right: str) -> bool:
    # Dot boundaries prevent 3.4 from matching 3.40. Duplicate IDs (#2)
    # remain distinct; only actual dot-separated descendants qualify.
    return left == right or left.startswith(right + ".") or right.startswith(left + ".")


def check_conclusion(result: AnalysisResult) -> list[Ref]:
    """Return unsupported citations in text order, preserving repeated mentions."""
    allowed = allowed_refs(result)
    return [ref for ref in extract_refs(result.conclusion_md) if not any(
        (ref.side is None or ref.side == side) and _related(ref.clause_id, clause_id)
        for side, clause_id in allowed
    )]


def sanitize_conclusion(result: AnalysisResult) -> str:
    """Return marked text without mutating the result or removing assertions."""
    md = result.conclusion_md
    for ref in reversed(check_conclusion(result)):
        start, end = ref.span
        md = md[:start] + f"п. {ref.clause_id} — ⚠ ссылка не подтверждена" + md[end:]
    return md
