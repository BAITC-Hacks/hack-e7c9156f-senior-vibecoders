"""Build the offline r8/r9 demo: python ai/scripts/build_mock.py (from any cwd).

Interpretations are hand-authored below; quotations and positions are copied
from explicitly selected source clauses. No model or network calls are made.
The `lost` mapping describes missing explicit ownership, not proven loss of work.
"""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import sys

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ai"))

from ai.alignment import align, body
from ai.evidence import verify_result
from ai.parsing import clause_text, parse_documents
from ai.schemas import AnalysisResult, Evidence, Flow, FunctionMapping, Unit


def all_evidence(value):
    """Include every evidence location, especially critic counter-evidence."""
    if isinstance(value, Evidence):
        yield value
    elif isinstance(value, BaseModel):
        for name in type(value).model_fields:
            yield from all_evidence(getattr(value, name))
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from all_evidence(item)


def validate_mock(result: AnalysisResult) -> None:
    evidence = list(all_evidence(result))
    assert evidence and all(e.verified for e in evidence), "Unverified evidence in mock"
    docs = {d.doc_id: d for d in result.documents}
    for ev in evidence:
        doc = docs[ev.doc_id]
        assert (ev.doc_name, ev.side) == (doc.name, doc.side)
        assert ev.quote in clause_text(doc, ev.clause_id), "Mock quotes must be exact"
    units = {u.id: u for u in result.units}
    functions = {f.id: f for f in result.function_mappings}
    categories = {c.id for c in result.categories}
    assert len(units) == len(result.units) == 7
    assert len(functions) == len(result.function_mappings)
    assert 8 <= len(functions) <= 12 and 6 <= len(categories) <= 8
    expected = defaultdict(list)
    for f in result.function_mappings:
        assert f.category_id in categories
        assert units[f.before_unit_id].side == "before"
        assert (f.status == "lost") == (not f.after_unit_ids)
        for target in f.after_unit_ids or ["lost"]:
            assert target == "lost" or units[target].side == "after"
            expected[f.before_unit_id, target].append(f.id)
    actual = {}
    for flow in result.flows:
        key = (flow.source_unit_id, flow.target_unit_id)
        assert key not in actual
        assert flow.value == len(flow.function_ids)
        actual[key] = flow.function_ids
    assert actual == dict(expected)
    for change in result.unit_changes:
        assert all(units[u].side == "before" for u in change.before_unit_ids)
        assert all(units[u].side == "after" for u in change.after_unit_ids)
    for finding in result.findings + result.rejected_findings:
        assert finding.critic is not None
        assert all(u in units for u in finding.unit_ids)
        assert finding.evidence
    assert all(f.critic.verdict != "refuted" for f in result.findings)
    assert all(f.critic.verdict == "refuted" and f.critic.counter_evidence
               for f in result.rejected_findings)


def build_mock() -> AnalysisResult:
    before_files = sorted((ROOT / "samples" / "before").glob("*.docx"))
    after_files = sorted((ROOT / "samples" / "after").glob("*.docx"))
    assert len(before_files) == len(after_files) == 1, "Expected the r8/r9 sample pair"
    documents = parse_documents(before_files, after_files)
    before, after = documents
    docs = {d.side: d for d in documents}
    clauses = {d.side: {c.clause_id: c for c in d.clauses} for d in documents}

    def ev(side, cid, children=False):
        doc = docs[side]
        assert cid in clauses[side], (side, cid)
        return Evidence(doc_id=doc.doc_id, doc_name=doc.name, side=side,
                        clause_id=cid, quote=clause_text(doc, cid, with_children=children))

    def unit(uid, side, name, abbr, definition, positions):
        children = [c for c in docs[side].clauses if c.clause_id.startswith(positions + ".")]
        assert children
        return Unit(id=uid, side=side, name=name, abbr=abbr, parent="Главный аудитор",
                    positions=[body(c.text).rstrip(".") for c in children],
                    evidence=[ev(side, definition), ev(side, positions, True)])

    units = [
        unit("b_dnm", "before", "Департамент непрерывного мониторинга системы внутреннего контроля", "ДНМ", "3.4.а", "3.7"),
        unit("b_dkkm", "before", "Департамент контроля качества аудита и методологии", "ДККМ", "3.4.б", "3.8"),
        unit("b_va", "before", "Директор направления внутреннего аудита", "Направление ВА", "3.5.а", "3.6"),
        unit("a_ita", "after", "Департамент ИТ-аудита и анализа данных", "ДИТААД", "3.4.а", "3.6"),
        unit("a_oa", "after", "Департамент операционного аудита", "ДОА", "3.4.б", "3.7"),
        unit("a_dnm", "after", "Департамент непрерывного мониторинга системы внутреннего контроля", "ДНМ", "3.4.в", "3.8"),
        unit("a_dkkm", "after", "Департамент контроля качества аудита и методологии", "ДККМ", "3.4.г", "3.9"),
    ]
    changes = [
        dict(before_unit_ids=[], after_unit_ids=["a_ita"], status="created",
             rationale="ДИТААД впервые включён в перечень подразделений БВА; в ред. 8 перечень содержит ДНМ и ДККМ.",
             evidence=[ev("before", "3.4", True), ev("after", "3.4.а")]),
        dict(before_unit_ids=[], after_unit_ids=["a_oa"], status="created",
             rationale="ДОА впервые включён в перечень подразделений БВА.",
             evidence=[ev("before", "3.4", True), ev("after", "3.4.б")]),
        dict(before_unit_ids=["b_dnm"], after_unit_ids=["a_dnm"], status="preserved",
             rationale="Название ДНМ сохранено, подпункт перенумерован с а на в; состав должностей изменён.",
             evidence=[ev("before", "3.4.а"), ev("after", "3.4.в")]),
        dict(before_unit_ids=["b_dkkm"], after_unit_ids=["a_dkkm"], status="preserved",
             rationale="Название ДККМ сохранено, подпункт перенумерован с б на г; это не означает неизменность всех функций.",
             evidence=[ev("before", "3.4.б"), ev("after", "3.4.г")]),
        dict(before_unit_ids=["b_va"], after_unit_ids=["a_ita", "a_oa"], status="transformed",
             rationale="Функциональное направление представлено как условная организационная единица: обязанности прежнего директора направления теперь описаны для руководителей ДИТААД/ДОА; формальное правопреемство требует подтверждения.",
             evidence=[ev("before", "3.6", True), ev("before", "5.3"), ev("after", "5.3"),
                       ev("before", "5.3.2"), ev("after", "5.3.3")]),
    ]
    categories = [dict(id=cid, name=name) for cid, name in [
        ("planning", "Планирование аудита"), ("audits", "Проведение проверок"),
        ("it", "ИТ-аудит и анализ данных"), ("quality", "Контроль качества"),
        ("methodology", "Методология"), ("monitoring", "Непрерывный мониторинг СВК"),
        ("consulting", "Консультирование"),
    ]]

    def mapping(fid, name, cat, source, targets, status, confidence, refs):
        return FunctionMapping(id=fid, function=name, category_id=cat,
                               before_unit_id=source, after_unit_ids=targets,
                               status=status, confidence=confidence,
                               evidence=[ev(side, cid) for side, cid in refs])

    mappings = [
        mapping("f_plan", "Подготовка предложений в план работ БВА", "planning", "b_va", ["a_ita", "a_oa"], "moved", .96,
                [("before", "5.3"), ("before", "5.3.2"), ("after", "5.3"), ("after", "5.3.3")]),
        mapping("f_audit", "Проведение проверок: выделение операционного аудита", "audits", "b_va", ["a_oa"], "modified", .85,
                [("before", "5.3.4"), ("after", "5.3.2.б"), ("after", "5.3.5")]),
        mapping("f_it", "Специализация проверок на ИТ-аудите и анализе данных", "it", "b_va", ["a_ita"], "modified", .8,
                [("before", "5.3.3"), ("after", "5.3.2.а")]),
        mapping("f_quality", "Мониторинг и периодические оценки качества внутреннего аудита", "quality", "b_dkkm", ["a_dkkm"], "preserved", 1,
                [("before", "5.5.2"), ("after", "5.5.2")]),
        mapping("f_method", "Разработка методологии и актуализация ВНД внутреннего аудита", "methodology", "b_dkkm", ["a_dkkm"], "preserved", 1,
                [("before", "5.5.6"), ("after", "5.5.4")]),
        mapping("f_monitor", "Анализ результатов непрерывного аудита директором ДНМ", "monitoring", "b_dnm", ["a_dnm"], "preserved", 1,
                [("before", "5.4.6"), ("after", "5.4.5")]),
        mapping("f_consult", "Консультирование по совершенствованию СУР, ВК и КУ", "consulting", "b_dnm", ["a_dnm"], "preserved", 1,
                [("before", "5.4.5"), ("after", "5.4.4")]),
        mapping("f_coverage", "Выявление рисков с недостаточным или дублирующим покрытием в Карте гарантий", "monitoring", "b_dnm", ["a_ita", "a_oa"], "moved", 1,
                [("before", "5.4"), ("before", "5.4.4.б"), ("after", "5.3"), ("after", "5.3.3.б")]),
        mapping("f_remediation_quality", "Контроль качества устранения недостатков и нарушений", "quality", "b_dkkm", ["a_dkkm"], "preserved", 1,
                [("before", "5.5.7"), ("after", "5.5.5")]),
        mapping("f_consolidate", "Консолидация предложений и формирование плана работ БВА", "planning", "b_dkkm", ["a_dkkm"], "preserved", 1,
                [("before", "5.5.11"), ("after", "5.5.7")]),
        mapping("f_owner_gap", "Возможная потеря явного закрепления анализа непрерывного аудита за директором ДККМ", "monitoring", "b_dkkm", [], "lost", .55,
                [("before", "5.5.4"), ("after", "5.5"), ("after", "5.4.5"), ("after", "5.3.8")]),
        mapping("f_followup", "Контроль устранения нарушений и развитие мониторинга корректирующих мер", "audits", "b_va", ["a_ita", "a_oa"], "modified", .96,
                [("before", "5.3.6"), ("after", "5.3"), ("after", "5.3.7")]),
    ]
    # Missing ownership is assessed against the entire current duty list, not
    # merely its heading. Its survival elsewhere is included as counter-context.
    mappings[10].evidence[1] = ev("after", "5.5", True)

    findings = [
        dict(id="structure", type="structure_change", severity="low",
             title="Созданы ДИТААД и ДОА в структуре БВА",
             description="В перечне подразделений вместо двух департаментов указаны четыре: добавлены ДИТААД и ДОА, ДНМ и ДККМ сохранены.",
             recommendation="Согласовать границы ответственности новых департаментов и обновить организационную схему.",
             unit_ids=["a_ita", "a_oa", "a_dnm", "a_dkkm"],
             evidence=[ev("before", "3.4", True), ev("after", "3.4", True)],
             critic=dict(verdict="upheld", argument="Оба новых названия отсутствуют в перечне ред. 8 и прямо перечислены в ред. 9; вывод относится к тексту положения.", counter_evidence=[])),
        dict(id="owner_gap", type="function_loss", severity="medium",
             title="Возможная потеря явного закрепления функции за ДККМ",
             description="Из перечня обязанностей директора ДККМ исчезло отдельное указание на анализ результатов непрерывного аудита (ранее 5.5.4); также изменён состав должностей 3.8 → 3.9. Это возможный пробел закрепления ответственности, а не доказанная потеря функции во всём БВА: она сохранена у ДНМ и руководителей ДИТААД/ДОА.",
             recommendation="Уточнить у владельца процесса роль ДККМ и сопоставить информационные листы должностей; подтвердить необходимость отдельного закрепления функции.",
             unit_ids=["b_dkkm", "a_dkkm"],
             evidence=[ev("before", "5.5.4"), ev("after", "5.5", True), ev("before", "3.8", True), ev("after", "3.9", True)],
             critic=dict(verdict="uncertain", argument="Изменение штатных названий не доказывает потерю работ; анализ непрерывного аудита явно сохранён у других руководителей, поэтому статус lost в моке означает только возможный пробел прежнего владельца.",
                         counter_evidence=[ev("after", "5.4.5"), ev("after", "5.3.8")])),
        dict(id="overlap", type="duplication", severity="medium",
             title="Общие обязанности ДИТААД и ДОА требуют разграничения",
             description="Пункт 5.3 устанавливает общие обязанности по планированию, организации проверок и контролю для руководителей обоих департаментов. Возможное дублирование возникает при пересечении объектов проверок; сам общий текст ещё не доказывает двойное исполнение.",
             recommendation="Зафиксировать владельцев проверок на стыке ИТ и операционных процессов и порядок совместной работы.",
             unit_ids=["a_ita", "a_oa"],
             evidence=[ev("after", "5.3"), ev("after", "5.3.3"), ev("after", "5.3.4"), ev("after", "5.3.5")],
             critic=dict(verdict="uncertain", argument="Подпункты 5.3.2.а/б разделяют предметные области; общая формулировка обязанностей может быть обоснованной, а не дублированием.",
                         counter_evidence=[ev("after", "5.3.2.а"), ev("after", "5.3.2.б")])),
        dict(id="sod", type="conflict_of_interest", severity="medium",
             title="ДККМ совмещает методологию и контроль качества",
             description="Один департамент разрабатывает методические материалы и организует оценки качества внутреннего аудита. Это потенциальный риск самооценки собственной методологии, а не установленное нарушение; сочетание существовало и в ред. 8.",
             recommendation="Проверить независимость оценщиков и участие внешних экспертов при оценке методологии ДККМ.",
             unit_ids=["a_dkkm"], rule_id="SOD_METHOD_AUTHOR_QUALITY_REVIEW",
             evidence=[ev("after", "5.5.2"), ev("after", "5.5.4"), ev("before", "5.5.2"), ev("before", "5.5.6")],
             critic=dict(verdict="uncertain", argument="Правило SOD_METHOD_AUTHOR_QUALITY_REVIEW — демонстрационная проверка независимости автора методологии и её оценщика; внешние оценки прямо предусмотрены и могут снижать риск, сведений о фактическом составе оценщиков нет.",
                         counter_evidence=[ev("after", "5.5.2"), ev("after", "5.1.10")])),
    ]
    rejected = [dict(
        id="rejected_coverage_loss", type="function_loss", severity="medium",
        title="Опровергнуто: утрачено выявление пробелов покрытия рисков",
        description="Первоначальная гипотеза: удаление подпункта 5.4.4.б у ДНМ означает потерю функции в БВА.",
        recommendation="Показать перенос к ДИТААД/ДОА вместо потери функции.",
        unit_ids=["b_dnm", "a_ita", "a_oa"], evidence=[ev("before", "5.4.4.б")],
        critic=dict(verdict="refuted", argument="Та же формулировка дословно присутствует в ред. 9, п. 5.3.3.б, в обязанностях руководителей ДИТААД и ДОА.",
                    counter_evidence=[ev("after", "5.3"), ev("after", "5.3.3.б")]),
    )]
    flow_ids = defaultdict(list)
    for f in mappings:
        for target in f.after_unit_ids or ["lost"]:
            flow_ids[f.before_unit_id, target].append(f.id)
    flows = [Flow(source_unit_id=source, target_unit_id=target, function_ids=ids, value=len(ids))
             for (source, target), ids in flow_ids.items()]
    conclusion = "\n".join([
        "# Сравнение положения о внутреннем аудите: редакции 8 и 9",
        "Это демонстрационный результат, составленный вручную по документам; вызовы LLM не использовались.",
        "## Организационные изменения",
        "- В перечень подразделений включены ДИТААД и ДОА (ред. 9, п. 3.4).",
        "- ДНМ и ДККМ сохранены; их позиции в перечне перенумерованы (ред. 8, п. 3.4; ред. 9, п. 3.4).",
        "- Направление ВА условно показано как предшественник ДИТААД/ДОА по преемственности обязанностей; формальное правопреемство не установлено (ред. 8, п. 5.3; ред. 9, п. 5.3).",
        "## Функции и риски",
        "- Выявление пробелов покрытия рисков перенесено от ДНМ к руководителям ДИТААД/ДОА, а не утрачено (ред. 8, п. 5.4.4.б; ред. 9, п. 5.3.3.б).",
        "- Контроль качества и разработка методологии сохранены за ДККМ (ред. 9, п. 5.5.2; ред. 9, п. 5.5.4).",
        "- Общие обязанности ДИТААД/ДОА создают гипотезу дублирования; предметные области разделены и требуют проверки на практике (ред. 9, п. 5.3).",
        "- Сочетание методологии и контроля качества в ДККМ — потенциальный риск самооценки, существовавший до изменений; предусмотрены внешние оценки (ред. 8, п. 5.5.2; ред. 8, п. 5.5.6; ред. 9, п. 5.5.2).",
        "- Статус lost означает возможную потерю явного закрепления анализа непрерывного аудита за ДККМ, не потерю функции во всём БВА (ред. 8, п. 5.5.4; ред. 9, п. 5.5; ред. 9, п. 5.4.5).",
        "- Изменение названий должностей ДККМ само по себе не подтверждает утрату обязанностей (ред. 8, п. 3.8; ред. 9, п. 3.9).",
        "## Рекомендация",
        "Уточнить владельцев функций, границы совместных проверок и независимость оценки методологии; значения Sankey считают назначения функций, одна функция может иметь двух получателей.",
        "**Выводы носят рекомендательный характер и требуют проверки ответственным сотрудником.**",
    ])
    result = verify_result(AnalysisResult(
        units=units, unit_changes=changes, function_mappings=mappings,
        findings=findings, rejected_findings=rejected, conclusion_md=conclusion,
        documents=documents, alignments=align(before, after), flows=flows, categories=categories,
        meta=dict(model="mock", provider="offline", duration_s=0,
                  documents=[dict(doc_id=d.doc_id, name=d.name, side=d.side) for d in documents]),
    ))
    validate_mock(result)
    return AnalysisResult.model_validate(result.model_dump())


def main() -> None:
    result = build_mock()
    destination = ROOT / "mocks" / "result.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    loaded = AnalysisResult.model_validate_json(destination.read_text(encoding="utf-8"))
    validate_mock(loaded)
    print(f"Wrote {destination}: {len(loaded.units)} units, {len(loaded.function_mappings)} mappings, "
          f"{len(loaded.alignments)} alignments, {len(list(all_evidence(loaded)))} verified quotes")


if __name__ == "__main__":
    main()
