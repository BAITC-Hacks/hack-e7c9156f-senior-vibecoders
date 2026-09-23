"""Шаг 8: конфликт интересов по правилам несовместимости функций (SoD)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel

from .functions import Func
from .llm import call_llm, load_prompt
from .schemas import Finding, Unit

MAX_FUNCS_PER_SIDE = 3


@lru_cache
def rules() -> list[dict]:
    path = Path(__file__).parent / "catalog" / "sod_rules.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))["rules"]


class LLMConflictDecision(BaseModel):
    cand_id: str
    is_conflict: bool
    explanation: str


class LLMConflicts(BaseModel):
    decisions: list[LLMConflictDecision]


def _fmt(funcs: list[Func]) -> str:
    return "\n".join(f"      - {f.text} (п. {f.evidence[0].clause_id}: «{f.evidence[0].quote}»)"
                     for f in funcs[:MAX_FUNCS_PER_SIDE])


def conflict_findings(after_funcs: list[Func], units: list[Unit]) -> list[Finding]:
    """Кандидат = единица «после», покрывающая обе категории правила; LLM подтверждает по тексту."""
    by_unit: dict[str, list[Func]] = {}
    for f in after_funcs:
        for u in f.unit_ids:
            by_unit.setdefault(u, []).append(f)

    cands: list[tuple[str, Unit, dict, list[Func], list[Func]]] = []
    for u in units:
        if u.side != "after":
            continue
        funcs = by_unit.get(u.id, [])
        for r in rules():
            a = [f for f in funcs if f.category_id == r["categories"][0]]
            b = [f for f in funcs if f.category_id == r["categories"][1]]
            if a and b:
                cands.append((f"c{len(cands)}", u, r, a, b))
    if not cands:
        return []

    blocks = [
        f"- cand_id={cid} | единица: {u.name}" + (f" ({u.abbr})" if u.abbr else "")
        + f"\n  правило {r['id']} «{r['name']}»: {r['rationale'].strip()}"
        + f"\n  функции категории «{r['categories'][0]}»:\n{_fmt(a)}"
        + f"\n  функции категории «{r['categories'][1]}»:\n{_fmt(b)}"
        for cid, u, r, a, b in cands
    ]
    res = call_llm(load_prompt("conflicts_verify"), "КАНДИДАТЫ:\n" + "\n".join(blocks), LLMConflicts, strong=True)
    ok = {d.cand_id: d for d in res.decisions if d.is_conflict}

    out: list[Finding] = []
    for cid, u, r, a, b in cands:
        if cid not in ok:
            continue
        name = u.abbr or u.name
        out.append(Finding(
            id=f"coi-{r['id']}-{name}", type="conflict_of_interest", severity=r["severity"],
            title=f"Конфликт интересов в {name}: {r['name'].lower()}",
            description=ok[cid].explanation,
            recommendation=f"Разделить функции «{a[0].text}» и «{b[0].text}» между разными исполнителями "
                           f"или предусмотреть независимую (внешнюю) оценку.",
            unit_ids=[u.id], evidence=[f.evidence[0] for f in a[:2] + b[:2]], rule_id=r["id"],
        ))
    return out
