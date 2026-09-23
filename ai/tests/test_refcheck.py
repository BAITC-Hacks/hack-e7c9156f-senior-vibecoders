from pathlib import Path

import pytest

from ai.refcheck import allowed_refs, check_conclusion, extract_refs, sanitize_conclusion
from ai.schemas import AnalysisResult, Evidence, Finding, UnitChange


def evidence(clause_id, side="after", verified=True):
    return Evidence(doc_id="doc", doc_name="doc", side=side, clause_id=clause_id,
                    quote="source", verified=verified)


def finding(*sources, **kwargs):
    return Finding(id="f", type="structure_change", severity="low", title="x",
                   description="x", evidence=list(sources), **kwargs)


def result(md="", *sources, **kwargs):
    fields = dict(units=[], unit_changes=[], function_mappings=[],
                  findings=[finding(*sources)], conclusion_md=md, documents=[],
                  alignments=[], flows=[], categories=[],
                  meta=dict(model="mock", provider="none", duration_s=0, documents=[]))
    fields.update(kwargs)
    return AnalysisResult(**fields)


@pytest.mark.parametrize("clause_id", [
    "3.4", "2.4.7", "3.4.а", "9.3.а#2", "т1.2", "абз.5", "прил.1", "Оргструктура:3",
])
def test_clause_formats_and_spans(clause_id):
    md = f"Источник (до, п. {clause_id})."
    refs = extract_refs(md)
    assert len(refs) == 1
    ref = refs[0]
    assert (ref.side, ref.clause_id) == ("before", clause_id)
    assert md[slice(*ref.span)] == f"п. {clause_id}"


@pytest.mark.parametrize("md, expected", [
    ("(до, п. 5.3.3)", [("before", "5.3.3")]),
    ("(после, п. 3.4; после, п. 3.4.а)", [("after", "3.4"), ("after", "3.4.а")]),
    ("(до, п. 3.4.а; п. 3.7)", [("before", "3.4.а"), ("before", "3.7")]),
    ("п. 3.4, 3.5", [(None, "3.4"), (None, "3.5")]),
    ("пп. 4.3.1 и 4.3.3", [(None, "4.3.1"), (None, "4.3.3")]),
    ("пункт 3.4; пункты 3.5 и 3.6", [(None, "3.4"), (None, "3.5"), (None, "3.6")]),
    ("(ДО, П.\u00a03.4, 3.5 и 3.6)", [("before", "3.4"), ("before", "3.5"), ("before", "3.6")]),
    ("(до, п. 3.4; после, п. 3.5; п. 3.6)", [("before", "3.4"), ("after", "3.5"), ("after", "3.6")]),
    ("(до, п. 3.4) (п. 3.5) п. 3.6", [("before", "3.4"), (None, "3.5"), (None, "3.6")]),
    ("до, п. 3.4; п. 3.5", [("before", "3.4"), (None, "3.5")]),
    ("(до, п. 3.4 (после, п. 3.5); п. 3.6)", [("before", "3.4"), ("after", "3.5"), ("before", "3.6")]),
])
def test_reference_lists_and_side_scope(md, expected):
    refs = extract_refs(md)
    assert [(r.side, r.clause_id) for r in refs] == expected
    assert all(md[slice(*r.span)].endswith(r.clause_id) for r in refs)
    assert all(a.span[1] <= b.span[0] for a, b in zip(refs, refs[1:]))


def test_numbers_without_reference_context_are_ignored():
    assert extract_refs("Выявлено 6 рисков, ред. 9; 3.4, 3.5 и 4.3.3 (до, 5.3).") == []
    assert extract_refs("этап. 3.4; пунктуация 3.5; п. 3.4wrong") == []
    assert extract_refs("") == []


def test_allowed_sources_and_verified_flags():
    r = result(
        findings=[finding(evidence("1"), evidence("2", verified=False), critic=dict(
            verdict="uncertain", argument="x",
            counter_evidence=[evidence("3", "before"), evidence("4", verified=False)]))],
        rejected_findings=[finding(evidence("5"), critic=dict(
            verdict="refuted", argument="x", counter_evidence=[evidence("6")]))],
        unit_changes=[UnitChange(before_unit_ids=[], after_unit_ids=[], status="created",
                                 rationale="x", evidence=[evidence("7"), evidence("8", verified=False)])],
        units=[dict(id="u", side="after", name="x", evidence=[evidence("9")])],
        function_mappings=[dict(id="m", function="x", category_id="c", status="lost",
                                confidence=1, evidence=[evidence("10")])],
    )
    assert allowed_refs(r) == {("after", "1"), ("before", "3"), ("after", "5"),
                               ("after", "6"), ("after", "7")}


@pytest.mark.parametrize("cited, allowed, supported", [
    ("3.4", "3.4", True), ("3.4", "3.4.а", True), ("3.4.а", "3.4", True),
    ("3.4.а.1", "3.4", True), ("3.40", "3.4", False), ("3.4", "3.40", False),
    ("3.4.б", "3.4.а", False), ("9.3.а#2", "9.3.а#2", True),
    ("9.3.а#2", "9.3.а", False), ("Оргструктура:30", "Оргструктура:3", False),
])
def test_exact_and_hierarchical_support(cited, allowed, supported):
    r = result(f"(после, п. {cited})", evidence(allowed))
    assert (check_conclusion(r) == []) is supported


def test_sides_and_unverified_sources():
    r = result("(до, п. 3.4) (после, п. 3.4) п. 3.4; п. 8.1",
               evidence("3.4.а"), evidence("8.1", verified=False))
    assert [(ref.side, ref.clause_id) for ref in check_conclusion(r)] == [
        ("before", "3.4"), (None, "8.1"),
    ]


def test_sanitization_preserves_prose_verified_refs_and_original():
    md = "**Вывод** (до, п. 3.4; после, п. 8.1, 8.2 и 8.3). Повтор: п. 8.1!"
    r = result(md, evidence("3.4", "before"), evidence("8.2"))
    original = r.model_dump()
    assert sanitize_conclusion(r) == (
        "**Вывод** (до, п. 3.4; после, п. 8.1 — ⚠ ссылка не подтверждена, "
        "8.2 и п. 8.3 — ⚠ ссылка не подтверждена). "
        "Повтор: п. 8.1 — ⚠ ссылка не подтверждена!"
    )
    assert r.model_dump() == original
    assert len(check_conclusion(r)) == 3


def test_no_changes_when_supported_or_no_references():
    for md in ("", "Выявлено 6 рисков", "(после, п. 3.4)"):
        r = result(md, evidence("3.4"))
        assert check_conclusion(r) == []
        assert sanitize_conclusion(r) == md


def test_real_mock_conclusion():
    path = Path(__file__).resolve().parents[2] / "mocks/result.json"
    r = AnalysisResult.model_validate_json(path.read_text(encoding="utf-8"))
    assert len(extract_refs(r.conclusion_md)) == 18
    assert check_conclusion(r) == []
    assert sanitize_conclusion(r) == r.conclusion_md
