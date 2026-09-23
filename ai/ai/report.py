"""Шаг 10: итоговое заключение — только из проверенных выводов."""

from __future__ import annotations

from .context import Ctx
from .llm import call_llm, load_prompt
from .schemas import AnalysisResult, Finding, Unit, UnitChange

_SEV = {"high": 0, "medium": 1, "low": 2}


def usable(f: Finding) -> bool:
    """В заключение идут выводы с проверенным источником. Решение сотрудника важнее критика:
    отклонённый человеком — исключается, принятый — включается, даже если критик его опроверг."""
    if not any(e.verified for e in f.evidence):
        return False
    if f.review:
        return f.review.status == "accepted"
    return not (f.critic and f.critic.verdict == "refuted")


def write_conclusion(ctx: Ctx, units: list[Unit], changes: list[UnitChange], findings: list[Finding]) -> str:
    by_id = {u.id: u for u in units}

    def label(ids: list[str]) -> str:
        return ", ".join(f"{by_id[i].name}" + (f" ({by_id[i].abbr})" if by_id[i].abbr else "") for i in ids if i in by_id)

    docs = "\n".join(f"- {d.doc_id}: {d.name} ({'до' if d.side == 'before' else 'после'})" for d in ctx.docs)
    ch = "\n".join(f"- {c.status}: {label(c.before_unit_ids) or '—'} → {label(c.after_unit_ids) or '—'}. {c.rationale}"
                   for c in changes)
    fs = []
    for f in sorted((f for f in findings if usable(f)), key=lambda f: _SEV[f.severity]):
        refs = "; ".join(f"{'до' if e.side == 'before' else 'после'}, п. {e.clause_id}" for e in f.evidence if e.verified)
        if f.review and f.review.status == "accepted":  # решение человека заменяет вердикт критика
            critic = " | ПОДТВЕРЖДЕНО СОТРУДНИКОМ" + (f": {f.review.comment}" if f.review.comment else "")
        else:
            critic = f" | критик: {f.critic.verdict} — {f.critic.argument}" if f.critic else ""
        fs.append(f"- [{f.type}, {f.severity}] {f.title}. {f.description} "
                  f"Рекомендация: {f.recommendation or '—'} | источники: {refs}{critic}")
    user = f"ДОКУМЕНТЫ:\n{docs}\n\nИЗМЕНЕНИЯ ЕДИНИЦ:\n{ch or '(нет)'}\n\nВЫВОДЫ:\n" + ("\n".join(fs) or "(нет)")
    return call_llm(load_prompt("report"), user, strong=True).strip()


def rebuild_conclusion(result: AnalysisResult) -> str:
    """Пересборка заключения после проверки выводов человеком (для PATCH …/findings/{id} бэкенда).
    Учитывает и rejected_findings: вывод, опровергнутый критиком, но принятый сотрудником, попадает в заключение."""
    ctx = Ctx(result.documents)
    return write_conclusion(ctx, result.units, result.unit_changes, result.findings + result.rejected_findings)
