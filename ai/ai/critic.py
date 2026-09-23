"""Шаг 9: агент-критик пытается опровергнуть каждый вывод по тексту документов."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Literal

import numpy as np
from pydantic import BaseModel

from .context import Ctx, LLMEvidence
from .functions import moved_clauses
from .llm import call_llm, embed, load_prompt
from .schemas import ClauseAlignment, CriticVerdict, Finding

TOP_CLAUSES = 14
MAX_CLAUSE_CHARS = 1500
WORKERS = 4
CRITICIZED = {"function_loss", "duplication", "conflict_of_interest"}


class LLMVerdict(BaseModel):
    verdict: Literal["upheld", "refuted", "uncertain"]
    argument: str
    counter_evidence: list[LLMEvidence]


class _Index:
    """Эмбеддинги всех пунктов — поиск контр-аргументов по смыслу."""

    def __init__(self, ctx: Ctx):
        self.items = [(d, c) for d in ctx.docs for c in d.clauses]
        self.emb = embed([c.text[:MAX_CLAUSE_CHARS] for _, c in self.items])

    def search(self, query: str, k: int) -> list[int]:
        q = embed([query])[0]
        return list(np.argsort(-(self.emb @ q))[:k])


def _moved_rows(ctx: Ctx, f: Finding, moved: dict[str, str]) -> list[str]:
    """Для «потери»: текст пунктов «после», куда по выравниванию переехали исходные пункты."""
    rows = []
    for e in f.evidence:
        target = moved.get(e.clause_id) if e.side == "before" else None
        for d in ctx.side("after"):
            c = next((c for c in d.clauses if c.clause_id == target), None)
            if c is not None:
                rows.append(f"[{d.doc_id} | после | {c.clause_id}] (сюда переехал пункт {e.clause_id} документа «до») "
                            f"{c.text[:MAX_CLAUSE_CHARS]}")
    return rows


def _criticize(ctx: Ctx, idx: _Index, f: Finding, moved: dict[str, str]) -> CriticVerdict:
    cited = {(e.doc_id, e.clause_id) for e in f.evidence}
    hits = idx.search(f"{f.title}. {f.description}", TOP_CLAUSES)
    rows = _moved_rows(ctx, f, moved) if f.type == "function_loss" else []
    for i in hits:
        d, c = idx.items[i]
        if (d.doc_id, c.clause_id) not in cited:
            rows.append(f"[{d.doc_id} | {'до' if d.side == 'before' else 'после'} | {c.clause_id}] {c.text[:MAX_CLAUSE_CHARS]}")
    ev = "\n".join(f"- {e.doc_id} ({'до' if e.side == 'before' else 'после'}), п. {e.clause_id}: «{e.quote}»"
                   for e in f.evidence)
    user = (f"ВЫВОД ({f.type}, критичность {f.severity}):\n{f.title}\n{f.description}\n\n"
            f"ИСТОЧНИКИ ВЫВОДА:\n{ev}\n\nДРУГИЕ ПУНКТЫ ДОКУМЕНТОВ, БЛИЗКИЕ ПО СМЫСЛУ:\n" + "\n".join(rows))
    res = call_llm(load_prompt("critic"), user, LLMVerdict, strong=True)
    counter = ctx.evidence(res.counter_evidence)
    verdict = res.verdict
    if verdict == "refuted" and not counter:  # опровержение без источника не принимаем
        verdict = "uncertain"
    return CriticVerdict(verdict=verdict, argument=res.argument, counter_evidence=counter)


def run_critic(ctx: Ctx, findings: list[Finding],
               alignments: list[ClauseAlignment] | None = None) -> tuple[list[Finding], list[Finding]]:
    """Возвращает (подтверждённые/спорные, опровергнутые)."""
    targets = [f for f in findings if f.type in CRITICIZED]
    if not targets:
        return findings, []
    idx = _Index(ctx)
    moved = moved_clauses(alignments or [])
    with ThreadPoolExecutor(WORKERS) as pool:
        verdicts = dict(zip((f.id for f in targets), pool.map(lambda f: _criticize(ctx, idx, f, moved), targets)))
    kept, rejected = [], []
    for f in findings:
        v = verdicts.get(f.id)
        f = f.model_copy(update={"critic": v}) if v else f
        (rejected if v and v.verdict == "refuted" else kept).append(f)
    return kept, rejected
