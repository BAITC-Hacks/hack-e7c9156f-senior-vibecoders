"""Deterministic, one-to-one clause alignment and lossless word redlines."""

from __future__ import annotations

from collections import defaultdict, deque
from difflib import SequenceMatcher
import re

from rapidfuzz import fuzz, process

from .evidence import normalize
from .schemas import ClauseAlignment, DiffOp, DocumentText


_LABEL = re.compile(r"^\s*(?:\d+(?:\.\d+)*(?:\.(?!\d)\s*|\s+)|[а-яёa-z][.)]\s+)", re.I)
_TOKENS = re.compile(r"\w+|\s+|[^\w\s]+")


def body(text: str) -> str:
    """Remove only the leading numeric/letter label; preserve the body verbatim."""
    return _LABEL.sub("", text, count=1)


def word_diff(a: str, b: str) -> list[DiffOp]:
    """Keep whitespace and punctuation so both inputs can be reconstructed."""
    left, right = _TOKENS.findall(a), _TOKENS.findall(b)
    result: list[DiffOp] = []

    def append(op: str, tokens: list[str]) -> None:
        text = "".join(tokens)
        if not text:
            return
        if result and result[-1].op == op:
            result[-1].text += text
        else:
            result.append(DiffOp(op=op, text=text))

    for tag, i, j, k, l in SequenceMatcher(None, left, right, autojunk=False).get_opcodes():
        if tag == "equal":
            append("equal", left[i:j])
        else:
            if tag in {"delete", "replace"}:
                append("delete", left[i:j])
            if tag in {"insert", "replace"}:
                append("insert", right[k:l])
    return result


def align(before: DocumentText, after: DocumentText) -> list[ClauseAlignment]:
    """Exact bodies first, then greedy fuzzy matches with small structural bonuses.

    Ratio penalizes omitted text; token_set_ratio incorrectly gives 100 to a
    heading wholly contained in a longer, substantively changed clause.
    Bonuses rank candidates only: similarity reports their raw text score.
    """
    left, right = before.clauses, after.clauses
    left_body, right_body = [body(c.text) for c in left], [body(c.text) for c in right]
    left_norm, right_norm = list(map(normalize, left_body)), list(map(normalize, right_body))
    available: dict[str, deque[int]] = defaultdict(deque)
    for j, text in enumerate(right_norm):
        available[text].append(j)
    pairs: dict[int, int] = {}
    rows: dict[int, ClauseAlignment] = {}
    for i, text in enumerate(left_norm):
        if available[text]:
            j = available[text].popleft()
            pairs[i] = j
            rows[j] = ClauseAlignment(
                before_clause_id=left[i].clause_id, after_clause_id=right[j].clause_id,
                status="unchanged" if left[i].clause_id == right[j].clause_id else "moved",
                similarity=1,
            )

    remaining_left = [i for i in range(len(left)) if i not in pairs]
    remaining_right = [j for j in range(len(right)) if j not in rows]
    if remaining_left and remaining_right:
        scores = process.cdist(
            [left_norm[i] for i in remaining_left], [right_norm[j] for j in remaining_right],
            scorer=fuzz.ratio, score_cutoff=60,
        )
        candidates = []
        for x, i in enumerate(remaining_left):
            for y, j in enumerate(remaining_right):
                score = float(scores[x, y])
                if score >= 60:
                    bonus = 2 * (left[i].clause_id == right[j].clause_id)
                    bonus += int(left[i].section == right[j].section)
                    candidates.append((-(score + bonus), -score, i, j))
        for _, negative_score, i, j in sorted(candidates):
            if i in pairs or j in rows:
                continue
            pairs[i] = j
            rows[j] = ClauseAlignment(
                before_clause_id=left[i].clause_id, after_clause_id=right[j].clause_id,
                status="modified", similarity=-negative_score / 100,
                diff=word_diff(left_body[i], right_body[j]),
            )

    # Each removed run follows its nearest preceding matched clause in BEFORE.
    # A leading removed run has no anchor and goes at the beginning.
    removed: dict[int | None, list[ClauseAlignment]] = defaultdict(list)
    anchor = None
    for i, clause in enumerate(left):
        if i in pairs:
            anchor = pairs[i]
        else:
            removed[anchor].append(ClauseAlignment(
                before_clause_id=clause.clause_id, status="removed", similarity=0,
            ))
    result = list(removed[None])
    for j, clause in enumerate(right):
        result.append(rows[j] if j in rows else ClauseAlignment(
            after_clause_id=clause.clause_id, status="added", similarity=0,
        ))
        result.extend(removed[j])
    return result
