"""Шаг 10: итоговое заключение — только из проверенных выводов."""

from __future__ import annotations

from .context import Ctx
from .llm import call_llm, load_prompt
from .schemas import Finding, Unit, UnitChange

_SEV = {"high": 0, "medium": 1, "low": 2}


def usable(f: Finding) -> bool:
    """В заключение идут только выводы с проверенным источником и не опровергнутые критиком."""
    return any(e.verified for e in f.evidence) and not (f.critic and f.critic.verdict == "refuted")


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
        critic = f" | критик: {f.critic.verdict} — {f.critic.argument}" if f.critic else ""
        fs.append(f"- [{f.type}, {f.severity}] {f.title}. {f.description} "
                  f"Рекомендация: {f.recommendation or '—'} | источники: {refs}{critic}")
    user = f"ДОКУМЕНТЫ:\n{docs}\n\nИЗМЕНЕНИЯ ЕДИНИЦ:\n{ch or '(нет)'}\n\nВЫВОДЫ:\n" + ("\n".join(fs) or "(нет)")
    return call_llm(load_prompt("report"), user, strong=True).strip()
