"""Шаги 3–4: извлечение структурных единиц и сопоставление «до ↔ после»."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel
from rapidfuzz import fuzz

from .context import Ctx, LLMEvidence
from .llm import call_llm, load_prompt
from .parsing import render_for_prompt
from .schemas import DocumentText, Finding, Side, Unit, UnitChange


# --- схемы ответов LLM (без значений по умолчанию — для strict structured output) ---

class LLMUnit(BaseModel):
    name: str
    abbr: str | None
    parent: str | None
    head: str | None
    positions: list[str]
    evidence: list[LLMEvidence]


class LLMUnits(BaseModel):
    units: list[LLMUnit]


class LLMChange(BaseModel):
    before_ids: list[str]
    after_ids: list[str]
    status: Literal["renamed", "transformed", "merged", "split", "abolished", "created"]
    rationale: str
    evidence: list[LLMEvidence]


class LLMChanges(BaseModel):
    changes: list[LLMChange]


# --- извлечение ---

def _norm(s: str | None) -> str:
    s = (s or "").lower().replace("ё", "е")
    s = re.sub(r"[«»\"'()]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _unit_id(side: Side, u: LLMUnit) -> str:
    return f"{'b' if side == 'before' else 'a'}:{(u.abbr or u.name).strip()}"


# «Директору направления внутреннего аудита подчиняются работники …» — признак единицы с подчинёнными
_SUBORD_RE = re.compile(r"(?:Директору|Руководителю|Начальнику|Заместителю)\s+(.{3,120}?)\s+подчиняются", re.I)


def subordination_hints(doc: DocumentText) -> list[tuple[str, str]]:
    """(clause_id, руководитель) для всех пунктов о подчинении — найдено кодом, без LLM."""
    out = []
    for c in doc.clauses:
        m = _SUBORD_RE.search(c.text)
        if m:
            out.append((c.clause_id, m.group(1).strip()))
    return out


def _covered(head: str, units: list[LLMUnit]) -> bool:
    h = _norm(head)
    for u in units:
        for k in (u.name, u.abbr, u.head):
            k = _norm(k)
            if k and (k in h or h in k or fuzz.token_set_ratio(k, h) >= 85):
                return True
    return False


def extract_units(ctx: Ctx, doc: DocumentText) -> list[Unit]:
    hints = subordination_hints(doc)
    hint_text = "\n".join(f"- [{cid}] {head}" for cid, head in hints)
    user = render_for_prompt(doc)
    if hints:
        user += ("\n\nПОДСКАЗКА ПАРСЕРА — пункты о подчинении работников (каждый руководитель из списка возглавляет "
                 f"структурную единицу, её нужно выписать, если это не весь блок/организация):\n{hint_text}")
    res = call_llm(load_prompt("units_extract"), user, LLMUnits)

    # самопроверка полноты: руководитель с подчинёнными есть, а его единицы в ответе нет → второй проход
    missing = [(cid, head) for cid, head in hints if not _covered(head, res.units)]
    if missing:
        extra = "\n".join(f"- [{cid}] {head}" for cid, head in missing)
        found = "\n".join(f"- {u.name}" + (f" ({u.abbr})" if u.abbr else "") for u in res.units)
        res2 = call_llm(
            load_prompt("units_extract"),
            f"{user}\n\nУЖЕ ИЗВЛЕЧЕНО:\n{found}\n\nПРОПУЩЕНО — у этих руководителей есть подчинённые, но их единиц нет "
            f"в списке. Верни ТОЛЬКО недостающие единицы (для направления назови его «Направление …»):\n{extra}",
            LLMUnits,
        )
        res = LLMUnits(units=res.units + res2.units)

    units: dict[str, Unit] = {}
    for u in res.units:
        uid = _unit_id(doc.side, u)
        ev = ctx.evidence(u.evidence)
        if uid in units:  # одна и та же единица в нескольких документах одной стороны
            units[uid].evidence.extend(ev)
            continue
        units[uid] = Unit(id=uid, side=doc.side, name=u.name.strip(), abbr=(u.abbr or None),
                          parent=u.parent, positions=u.positions, evidence=ev)
    return list(units.values())


def extract_all_units(ctx: Ctx) -> list[Unit]:
    merged: dict[str, Unit] = {}
    for doc in ctx.docs:
        for u in extract_units(ctx, doc):
            if u.id in merged:
                merged[u.id].evidence.extend(u.evidence)
            else:
                merged[u.id] = u
    all_units = list(merged.values())
    return [u for u in all_units if _is_org_unit(u) and not _is_root(u, all_units)]


_ORG_WORDS = ("департамент", "управлени", "отдел", "служб", "центр", "направлени", "групп", "сектор",
              "дирекци", "подразделени", "бюро", "лаборатори", "филиал", "блок")


def _is_org_unit(u: Unit) -> bool:
    """Отсекает документы/процессы, которые модель ошибочно приняла за единицу (напр. «Программа …»)."""
    return any(w in _norm(u.name) for w in _ORG_WORDS)


def _is_root(u: Unit, units: list[Unit]) -> bool:
    """Весь блок/организация, в который входят остальные, — не единица для сравнения."""
    names = {_norm(u.name), _norm(u.abbr)} - {""}
    children = [o for o in units if o.side == u.side and o is not u and o.parent
                and any(n == _norm(o.parent) or fuzz.partial_ratio(n, _norm(o.parent)) >= 95 for n in names if len(n) >= 3)]
    return len(children) >= 2


# --- сопоставление ---

def _same_unit(a: Unit, b: Unit) -> Literal["preserved", "renamed"] | None:
    if a.abbr and b.abbr and _norm(a.abbr) == _norm(b.abbr):
        return "preserved" if fuzz.ratio(_norm(a.name), _norm(b.name)) >= 90 else "renamed"
    if fuzz.ratio(_norm(a.name), _norm(b.name)) >= 95:
        return "preserved"
    return None


def _relevant_clauses(ctx: Ctx, units: list[Unit]) -> str:
    """Пункты, где упоминаются единицы (по названию/аббревиатуре) или на которые они ссылаются."""
    keys = {_norm(k) for u in units for k in (u.abbr, u.name) if k and len(k) >= 3}
    cited = {(e.doc_id, e.clause_id) for u in units for e in u.evidence}
    blocks: list[str] = []
    for doc in ctx.docs:
        rows = [f"[{c.clause_id}] {c.text}" for c in doc.clauses
                if (doc.doc_id, c.clause_id) in cited or any(k in _norm(c.text) for k in keys)]
        if rows:
            blocks.append(f"=== Документ {doc.doc_id}: {doc.name} ({'до' if doc.side == 'before' else 'после'}) ===\n"
                          + "\n".join(rows))
    return "\n\n".join(blocks)


def _describe(units: list[Unit]) -> str:
    return "\n".join(
        f"- id={u.id} | {u.name}" + (f" ({u.abbr})" if u.abbr else "")
        + (f" | подчинение: {u.parent}" if u.parent else "")
        + (f" | должности: {'; '.join(u.positions)}" if u.positions else "")
        for u in units
    )


def match_units(ctx: Ctx, units: list[Unit]) -> list[UnitChange]:
    before = [u for u in units if u.side == "before"]
    after = [u for u in units if u.side == "after"]
    changes: list[UnitChange] = []
    used_b: set[str] = set()
    used_a: set[str] = set()

    # 1. точные совпадения — без LLM
    for b in before:
        for a in after:
            if a.id in used_a:
                continue
            status = _same_unit(b, a)
            if status:
                used_b.add(b.id)
                used_a.add(a.id)
                why = "Единица присутствует в обеих редакциях" if status == "preserved" else \
                      f"Аббревиатура совпадает, название изменено: «{b.name}» → «{a.name}»"
                if status == "preserved" and b.positions != a.positions:
                    why += "; состав должностей изменён"
                changes.append(UnitChange(before_unit_ids=[b.id], after_unit_ids=[a.id], status=status,
                                          rationale=why, evidence=b.evidence[:1] + a.evidence[:1]))
                break

    rest_b = [u for u in before if u.id not in used_b]
    rest_a = [u for u in after if u.id not in used_a]
    if not rest_b and not rest_a:
        return changes

    # 2. остальное решает LLM
    user = (f"ЕДИНИЦЫ ДО:\n{_describe(rest_b) or '(нет)'}\n\nЕДИНИЦЫ ПОСЛЕ:\n{_describe(rest_a) or '(нет)'}\n\n"
            f"СОПОСТАВЛЕННЫЕ БЕЗ ИЗМЕНЕНИЙ (для контекста):\n{_describe([u for u in units if u.id in used_b | used_a]) or '(нет)'}\n\n"
            f"ПУНКТЫ ДОКУМЕНТОВ:\n{_relevant_clauses(ctx, units)}")
    res = call_llm(load_prompt("units_match"), user, LLMChanges, strong=True)

    ids_b = {u.id for u in rest_b}
    ids_a = {u.id for u in rest_a}
    by_id = {u.id: u for u in units}
    for ch in res.changes:
        bs = [i for i in ch.before_ids if i in ids_b and i not in used_b]
        as_ = [i for i in ch.after_ids if i in ids_a and i not in used_a]
        if not bs and not as_:
            continue
        status = ch.status
        if status != "created" and not bs:
            status = "created"
        if status != "abolished" and not as_:
            status = "abolished"
        used_b.update(bs)
        used_a.update(as_)
        changes.append(UnitChange(before_unit_ids=bs, after_unit_ids=as_, status=status,
                                  rationale=ch.rationale, evidence=ctx.evidence(ch.evidence)))

    # 3. всё, что LLM пропустил, — по умолчанию упразднено/создано
    for i in ids_b - used_b:
        changes.append(UnitChange(before_unit_ids=[i], after_unit_ids=[], status="abolished",
                                  rationale="Единица не найдена в документах после реорганизации",
                                  evidence=by_id[i].evidence[:1]))
    for i in ids_a - used_a:
        changes.append(UnitChange(before_unit_ids=[], after_unit_ids=[i], status="created",
                                  rationale="Единица отсутствовала в документах до реорганизации",
                                  evidence=by_id[i].evidence[:1]))
    return changes


_STATUS_TITLE = {
    "created": "Создана единица", "abolished": "Упразднена единица", "renamed": "Переименована единица",
    "transformed": "Преобразована единица", "merged": "Объединены единицы", "split": "Разделена единица",
}


def structure_findings(changes: list[UnitChange], units: list[Unit]) -> list[Finding]:
    """Выводы об изменениях структуры — без LLM, из результатов сопоставления."""
    by_id = {u.id: u for u in units}

    def label(ids: list[str]) -> str:
        return ", ".join(by_id[i].abbr or by_id[i].name for i in ids if i in by_id)

    out: list[Finding] = []
    for n, ch in enumerate(changes, 1):
        if ch.status == "preserved":
            b, a = by_id[ch.before_unit_ids[0]], by_id[ch.after_unit_ids[0]]
            removed = [p for p in b.positions if _norm(p) not in {_norm(x) for x in a.positions}]
            added = [p for p in a.positions if _norm(p) not in {_norm(x) for x in b.positions}]
            if not removed and not added:
                continue
            out.append(Finding(
                id=f"struct-{n}", type="structure_change", severity="medium" if removed else "low",
                title=f"Изменён состав должностей {a.abbr or a.name}",
                description=(f"Подразделение сохранено, но состав должностей изменён."
                             + (f" Исключены: {'; '.join(removed)}." if removed else "")
                             + (f" Добавлены: {'; '.join(added)}." if added else "")),
                recommendation="Проверить, за кем закреплены функции исключённых должностей." if removed else None,
                unit_ids=ch.before_unit_ids + ch.after_unit_ids, evidence=b.evidence[:2] + a.evidence[:2],
            ))
            continue
        if ch.status not in _STATUS_TITLE:
            continue
        subj = label(ch.before_unit_ids) or label(ch.after_unit_ids)
        arrow = (f"{label(ch.before_unit_ids)} → {label(ch.after_unit_ids)}"
                 if ch.before_unit_ids and ch.after_unit_ids else subj)
        # к обоснованию изменения добавляем, где каждая единица названа в структуре (напр. п. 3.4.а)
        ev = list(ch.evidence)
        for uid in ch.before_unit_ids + ch.after_unit_ids:
            for e in by_id[uid].evidence[:1] if uid in by_id else []:
                if (e.doc_id, e.clause_id) not in {(x.doc_id, x.clause_id) for x in ev}:
                    ev.append(e)
        out.append(Finding(
            id=f"struct-{n}", type="structure_change",
            severity="medium" if ch.status in ("abolished", "split", "merged", "transformed") else "low",
            title=f"{_STATUS_TITLE[ch.status]}: {arrow}", description=ch.rationale,
            unit_ids=ch.before_unit_ids + ch.after_unit_ids, evidence=ev,
        ))
    return out
