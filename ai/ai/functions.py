"""Шаги 5–7: функции подразделений, сопоставление «до → после», потери, дубли, потоки для Sankey."""

from __future__ import annotations

import itertools
import re
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import numpy as np
import yaml
from pydantic import BaseModel
from rapidfuzz import fuzz

from .context import Ctx, LLMEvidence
from .llm import call_llm, embed, load_prompt
from .parsing import render_for_prompt
from .schemas import Category, DocumentText, Evidence, Finding, Flow, FunctionMapping, Side, Unit, UnitChange

TOP_K = 8
DUP_SIM = 0.82
MAX_DUP_PAIRS = 25
MAX_EVIDENCE = 6
# типовые обязанности любого руководителя — не предмет поиска дублей и потерь
GENERIC_CATEGORIES = {"management", "staff_development"}
_STUB_RE = re.compile(r"\bне (установлен|определен|указан|предусмотрен)", re.I)


# --- каталог ---

@lru_cache
def catalog() -> list[dict]:
    path = Path(__file__).parent / "catalog" / "functions.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))["categories"]


def categories() -> list[Category]:
    return [Category(id=c["id"], name=c["name"]) for c in catalog()]


def _cat_name(cid: str) -> str:
    return next((c["name"] for c in catalog() if c["id"] == cid), cid)


# --- схемы LLM ---

class LLMFunction(BaseModel):
    unit_ids: list[str]
    text: str
    category_id: str
    evidence: list[LLMEvidence]


class LLMFunctions(BaseModel):
    functions: list[LLMFunction]


class LLMMatchDecision(BaseModel):
    before_id: str
    relation: Literal["same", "modified", "none"]
    match_ids: list[str]
    explanation: str


class LLMMatches(BaseModel):
    decisions: list[LLMMatchDecision]


class LLMDupDecision(BaseModel):
    pair_id: str
    is_duplicate: bool
    explanation: str


class LLMDups(BaseModel):
    decisions: list[LLMDupDecision]


@dataclass
class Func:
    id: str
    side: Side
    unit_ids: list[str]
    text: str
    category_id: str
    evidence: list[Evidence]


@dataclass
class FunctionsResult:
    funcs: list[Func]
    mappings: list[FunctionMapping]
    findings: list[Finding]
    flows: list[Flow]


# --- извлечение ---

def extract_functions(ctx: Ctx, doc: DocumentText, units: list[Unit], start: int) -> list[Func]:
    side_units = [u for u in units if u.side == doc.side]
    if not side_units:
        return []
    cat_text = "\n".join(f"- {c['id']}: {c['name']} — {c['hint']}" for c in catalog())
    unit_text = "\n".join(f"- id={u.id} | {u.name}" + (f" ({u.abbr})" if u.abbr else "") for u in side_units)
    user = f"СТРУКТУРНЫЕ ЕДИНИЦЫ:\n{unit_text}\n\nКАТАЛОГ КАТЕГОРИЙ:\n{cat_text}\n\n{render_for_prompt(doc)}"
    res = call_llm(load_prompt("functions_extract"), user, LLMFunctions)

    valid_units = {u.id for u in side_units}
    valid_cats = {c["id"] for c in catalog()}
    out: list[Func] = []
    for f in res.functions:
        ev = ctx.evidence(f.evidence)
        by_uid = {u.id: u for u in side_units}
        # привязка к единице должна подтверждаться текстом пункта или заголовком родителя —
        # иначе это функция блока в целом, которую модель ошибочно приписала подразделению
        uids = [u for u in f.unit_ids if u in by_uid and any(_attributed(doc, e.clause_id, by_uid[u]) for e in ev)]
        for e in ev:  # «5.3. Директоры … ДИТААД и ДОА:» — подпункты относятся ко всем названным единицам
            uids += [u for u in _units_in_headings(doc, e.clause_id, side_units) if u not in uids]
        if not uids or not ev or _STUB_RE.search(f.text):  # без единицы, без источника или заглушка
            continue
        out.append(Func(id=f"f{doc.side[0]}{start + len(out) + 1}", side=doc.side, unit_ids=uids,
                        text=f.text.strip(), category_id=f.category_id if f.category_id in valid_cats else "other",
                        evidence=ev))
    return out


def _context_texts(doc: DocumentText, clause_id: str) -> list[str]:
    """Текст пункта и заголовки его родителей (без раздела верхнего уровня)."""
    texts = {c.clause_id: c.text for c in doc.clauses}
    parts = clause_id.split("#", 1)[0].split(".")
    out = [texts.get(clause_id, "")]
    out += [texts.get(".".join(parts[:d]), "").split("\n", 1)[0] for d in range(len(parts) - 1, 1, -1)]
    return [t for t in out if t]


def _attributed(doc: DocumentText, clause_id: str, unit: Unit) -> bool:
    for t in _context_texts(doc, clause_id):
        if unit.abbr and re.search(rf"(?<!\w){re.escape(unit.abbr)}(?!\w)", t):
            return True
        if fuzz.partial_ratio(unit.name.lower().replace("ё", "е"), t.lower().replace("ё", "е")) >= 85:
            return True
    return False


def _units_in_headings(doc: DocumentText, clause_id: str, units: list[Unit]) -> list[str]:
    """Единицы, названные в заголовках родительских пунктов (5.3.4.а → 5.3.4 → 5.3), по аббревиатуре."""
    texts = {c.clause_id: c.text for c in doc.clauses}
    parts = clause_id.split("#", 1)[0].split(".")
    found: list[str] = []
    for depth in range(len(parts) - 1, 1, -1):  # только родители, раздел целиком («5») не берём
        head = texts.get(".".join(parts[:depth]), "").split("\n", 1)[0]
        if not head.rstrip().endswith(":"):  # заголовок перечня: «…ДИТААД и ДОА:»
            continue
        for u in units:
            if u.abbr and re.search(rf"(?<!\w){re.escape(u.abbr)}(?!\w)", head) and u.id not in found:
                found.append(u.id)
    return found


# --- сопоставление ---

def _unit_mapping(changes: list[UnitChange]) -> dict[str, set[str]]:
    m: dict[str, set[str]] = defaultdict(set)
    for ch in changes:
        for b in ch.before_unit_ids:
            m[b].update(ch.after_unit_ids)
    return m


def _emb_text(f: Func) -> str:
    return f"{_cat_name(f.category_id)}: {f.text}"


def match_functions(before: list[Func], after: list[Func],
                    changes: list[UnitChange]) -> tuple[list[FunctionMapping], dict[str, str]]:
    """Возвращает сопоставления и пояснения LLM к потерянным функциям (mapping.id → текст)."""
    if not before:
        return [], {}
    if not after:
        sims = np.zeros((len(before), 0))
    else:
        eb, ea = embed([_emb_text(f) for f in before]), embed([_emb_text(f) for f in after])
        sims = eb @ ea.T

    cand: dict[str, list[Func]] = {}
    blocks = []
    for i, f in enumerate(before):
        idx = np.argsort(-sims[i])[:TOP_K] if after else []
        cand[f.id] = [after[j] for j in idx]
        lines = "\n".join(f"    - {a.id} [{', '.join(a.unit_ids)}] {a.text}  (цитата: «{a.evidence[0].quote}»)"
                          for a in cand[f.id])
        blocks.append(f"- {f.id} [{', '.join(f.unit_ids)}] {f.text}  (цитата: «{f.evidence[0].quote}»)\n"
                      f"  КАНДИДАТЫ:\n{lines or '    (нет)'}")
    res = call_llm(load_prompt("functions_match"), "ФУНКЦИИ ДО И КАНДИДАТЫ ПОСЛЕ:\n" + "\n".join(blocks),
                   LLMMatches, strong=True)
    decisions = {d.before_id: d for d in res.decisions}

    by_id = {a.id: a for a in after}
    umap = _unit_mapping(changes)
    mappings: list[FunctionMapping] = []
    loss_notes: dict[str, str] = {}
    for f in before:
        d = decisions.get(f.id)
        allowed = {a.id for a in cand[f.id]}
        matched = [by_id[i] for i in (d.match_ids if d else []) if i in allowed]
        relation = d.relation if d and matched else "none"
        after_units = sorted({u for a in matched for u in a.unit_ids})
        for u in f.unit_ids:
            if relation == "none":
                status, conf = "lost", 0.7
            elif set(after_units) <= umap.get(u, set()):
                status, conf = ("preserved", 0.9) if relation == "same" else ("modified", 0.75)
            else:
                status, conf = "moved", 0.8
            ev = f.evidence + [e for a in matched for e in a.evidence[:1]]
            mappings.append(FunctionMapping(id=f"fm{len(mappings) + 1}", function=f.text, category_id=f.category_id,
                                            before_unit_id=u, after_unit_ids=after_units, status=status,
                                            confidence=conf, evidence=ev))
            if d and relation == "none":
                loss_notes[mappings[-1].id] = d.explanation
    return mappings, loss_notes


# --- потери ---

def loss_findings(mappings: list[FunctionMapping], notes: dict[str, str], after: list[Func],
                  units: list[Unit]) -> list[Finding]:
    covered_after = {f.category_id for f in after}
    names = {u.id: u.abbr or u.name for u in units}
    out: list[Finding] = []
    for m in mappings:
        if m.status != "lost" or m.category_id in GENERIC_CATEGORIES:  # «прочие поручения» и т.п. — не потеря
            continue
        uncovered = m.category_id not in covered_after
        note = notes.get(m.id, "")
        out.append(Finding(
            id=f"loss-{m.id}", type="function_loss", severity="high" if uncovered else "medium",
            title=f"Возможная потеря функции: {m.function}",
            description=(f"Функция «{m.function}» была закреплена за {names.get(m.before_unit_id, m.before_unit_id)}, "
                         f"но в документах после реорганизации не найдена ни у одной единицы. {note}".strip()
                         + (f" Категория «{_cat_name(m.category_id)}» после реорганизации не покрыта никем."
                            if uncovered else "")),
            recommendation="Закрепить функцию за одной из единиц после реорганизации или зафиксировать сознательный отказ от неё.",
            unit_ids=[m.before_unit_id] if m.before_unit_id else [], evidence=m.evidence,
        ))
    return out


# --- дубли ---

def _related(a: Unit, b: Unit) -> bool:
    """Родитель и дочерняя единица (ДИТААД и его Центр анализа данных) — не дубли."""
    def names(u: Unit) -> set[str]:
        return {x.lower() for x in (u.name, u.abbr) if x}
    return bool((a.parent and a.parent.lower() in names(b)) or (b.parent and b.parent.lower() in names(a)))


def duplicate_findings(after: list[Func], units: list[Unit]) -> list[Finding]:
    by_uid = {u.id: u for u in units}
    after = [f for f in after if f.category_id not in GENERIC_CATEGORIES]
    pairs: list[tuple[str, str, Func, Func]] = []  # (unit1, unit2, func1, func2)

    # a) один пункт закрепляет функцию сразу за несколькими единицами
    for f in after:
        for u1, u2 in itertools.combinations(sorted(f.unit_ids), 2):
            if not _related(by_uid[u1], by_uid[u2]):
                pairs.append((u1, u2, f, f))
    # b) похожие функции разных единиц
    if len(after) > 1:
        e = embed([_emb_text(f) for f in after])
        sims = e @ e.T
        scored = []
        for i, j in itertools.combinations(range(len(after)), 2):
            fi, fj = after[i], after[j]
            if sims[i, j] < DUP_SIM or set(fi.unit_ids) & set(fj.unit_ids):
                continue
            for u1 in fi.unit_ids:
                for u2 in fj.unit_ids:
                    if not _related(by_uid[u1], by_uid[u2]):
                        scored.append((float(sims[i, j]), u1, u2, fi, fj))
        scored.sort(key=lambda x: -x[0])
        pairs += [(u1, u2, fi, fj) for _, u1, u2, fi, fj in scored[: MAX_DUP_PAIRS]]
    if not pairs:
        return []

    rows = []
    for n, (u1, u2, f1, f2) in enumerate(pairs[: MAX_DUP_PAIRS * 2]):
        rows.append(f"- pair_id=p{n}\n  {u1}: {f1.text} (п. {f1.evidence[0].clause_id}: «{f1.evidence[0].quote}»)\n"
                    f"  {u2}: {f2.text} (п. {f2.evidence[0].clause_id}: «{f2.evidence[0].quote}»)")
    res = call_llm(load_prompt("duplicates_verify"), "ПАРЫ:\n" + "\n".join(rows), LLMDups)
    ok = {d.pair_id: d for d in res.decisions if d.is_duplicate}

    grouped: dict[tuple[str, str], list[tuple[Func, Func, str]]] = defaultdict(list)
    for n, (u1, u2, f1, f2) in enumerate(pairs[: MAX_DUP_PAIRS * 2]):
        if f"p{n}" in ok:
            grouped[(u1, u2)].append((f1, f2, ok[f"p{n}"].explanation))

    out: list[Finding] = []
    for (u1, u2), items in grouped.items():
        n1, n2 = (by_uid[u].abbr or by_uid[u].name for u in (u1, u2))
        funcs = "; ".join(sorted({f1.text for f1, _, _ in items}))
        ev: list[Evidence] = []
        for f1, f2, _ in items:
            for e in f1.evidence[:1] + f2.evidence[:1]:
                if (e.doc_id, e.clause_id, e.quote) not in {(x.doc_id, x.clause_id, x.quote) for x in ev}:
                    ev.append(e)
        out.append(Finding(
            id=f"dup-{len(out) + 1}", type="duplication", severity="high" if len(items) >= 3 else "medium",
            title=f"Дублирование функций: {n1} и {n2}",
            description=f"{n1} и {n2} выполняют одинаковые функции без разграничения в тексте: {funcs}. "
                        + " ".join(sorted({x for _, _, x in items}))[:600],
            recommendation=f"Разграничить зоны ответственности {n1} и {n2} (по объектам/направлениям аудита) "
                           f"или закрепить функцию за одной единицей.",
            unit_ids=[u1, u2], evidence=ev[:MAX_EVIDENCE],
        ))
    return out


def apply_rejected_losses(mappings: list[FunctionMapping], rejected: list[Finding], funcs: list[Func],
                          changes: list[UnitChange]) -> list[FunctionMapping]:
    """Критик опроверг потерю → функция не «lost»: ищем, у какой единицы «после» она нашлась по контр-цитате."""
    by_clause: dict[tuple[str, str], set[str]] = defaultdict(set)
    for f in funcs:
        if f.side == "after":
            for e in f.evidence:
                by_clause[(e.doc_id, e.clause_id)].update(f.unit_ids)
    refuted = {f.id.removeprefix("loss-"): f for f in rejected if f.type == "function_loss" and f.critic}
    umap = _unit_mapping(changes)
    out = []
    for m in mappings:
        f = refuted.get(m.id)
        if m.status != "lost" or f is None:
            out.append(m)
            continue
        counter = [e for e in f.critic.counter_evidence if e.side == "after"]
        units = sorted({u for e in counter for u in by_clause.get((e.doc_id, e.clause_id), set())})
        status = "modified" if units and set(units) <= umap.get(m.before_unit_id or "", set()) else "moved"
        out.append(m.model_copy(update={"status": status, "after_unit_ids": units, "confidence": 0.6,
                                        "evidence": m.evidence + counter}))
    return out


# --- Sankey ---

def build_flows(mappings: list[FunctionMapping]) -> list[Flow]:
    agg: dict[tuple[str, str], list[str]] = defaultdict(list)
    for m in mappings:
        if not m.before_unit_id or (m.status == "lost" and m.category_id in GENERIC_CATEGORIES):
            continue  # типовые обязанности не считаем потерей (как и в loss_findings)
        # функция «не потеряна», но единица не определена (общие нормы блока) — поток в «БВА в целом» не рисуем
        targets = ["lost"] if m.status == "lost" else m.after_unit_ids
        for t in targets:
            agg[(m.before_unit_id, t)].append(m.id)
    return [Flow(source_unit_id=s, target_unit_id=t, function_ids=ids, value=len(ids)) for (s, t), ids in agg.items()]


# --- всё вместе ---

def analyze_functions(ctx: Ctx, units: list[Unit], changes: list[UnitChange]) -> FunctionsResult:
    funcs: list[Func] = []
    for doc in ctx.docs:
        funcs += extract_functions(ctx, doc, units, start=sum(1 for f in funcs if f.side == doc.side))
    before = [f for f in funcs if f.side == "before"]
    after = [f for f in funcs if f.side == "after"]
    mappings, notes = match_functions(before, after, changes)
    findings = loss_findings(mappings, notes, after, units) + duplicate_findings(after, units)
    return FunctionsResult(funcs=funcs, mappings=mappings, findings=findings, flows=build_flows(mappings))
