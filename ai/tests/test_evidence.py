from pathlib import Path

import pytest

from ai.evidence import locate_quote, normalize, verify_evidence, verify_quote, verify_result
from ai.parsing import parse_document, segment
from ai.schemas import AnalysisResult, DocumentText, Evidence


@pytest.fixture(scope="module")
def real_doc():
    samples = Path(__file__).resolve().parents[2] / "samples" / "after"
    return parse_document(next(samples.glob("*.docx")), "after", "a1")


def evidence(doc, clause_id, quote):
    return Evidence(doc_id=doc.doc_id, doc_name=doc.name, side=doc.side,
                    clause_id=clause_id, quote=quote)


def test_normalize():
    assert normalize('  Ёлка «тест» “да” „нет" – No 2\t№ 3\nИТ- аудит\u00ad  ') == (
        'елка "тест" "да" "нет" - № 2 № 3 ит-аудит'
    )
    assert normalize("Nobody knows") == "nobody knows"


def test_real_quote_and_children(real_doc):
    quote = "Департамент ИТ-аудита и анализа данных (ДИТААД)"
    assert verify_quote(real_doc, "3.4", quote)
    assert verify_quote(real_doc, "3.4.а", quote)
    assert locate_quote(real_doc, quote) == "3.4.а"
    assert not verify_quote(real_doc, "3.4", "Разведение пингвинов на Марсе")
    assert not verify_quote(real_doc, "missing", quote)
    assert not verify_quote(real_doc, "3.4", " \n ")
    assert locate_quote(real_doc, " \n ") is None


def test_real_typography(real_doc):
    clause = next(c for c in real_doc.clauses if "е" in c.text and "«" in c.text)
    quote = clause.text.replace("е", "ё").replace("«", '"').replace("»", '"').replace(" ", "  ")
    assert verify_quote(real_doc, clause.clause_id, quote, fuzzy_threshold=100)


def test_correction_is_a_copy(real_doc):
    ev = evidence(real_doc, "missing", "Департамент ИТ-аудита и анализа данных (ДИТААД)")
    checked = verify_evidence(ev, {real_doc.doc_id: real_doc})
    assert checked.verified and checked.clause_id == "3.4.а"
    assert not ev.verified and ev.clause_id == "missing"
    unknown = ev.model_copy(update={"verified": True})
    assert not verify_evidence(unknown, {}).verified


def test_fuzzy_and_short_quotes():
    doc = DocumentText(doc_id="x", name="x", side="before", clauses=segment([
        "1. Контроль качества аудита и методологии", "1.1. Ёлка «аудит»"
    ]))
    assert verify_quote(doc, "1", "Контроль качества аудита и методолагии")
    assert not verify_quote(doc, "1", "Контроль качества аудита и методолагии", 100)
    assert not verify_quote(doc, "1", "аудет")
    assert locate_quote(doc, 'Елка  “аудит”') == "1.1"
    # A prefix without an actual parent clause must not count as an existing clause.
    orphan = doc.model_copy(update={"clauses": doc.clauses[1:]})
    assert not verify_quote(orphan, "1", "Ёлка")


def test_locate_prefers_exact_then_deepest_shortest():
    doc = DocumentText(doc_id="x", name="x", side="after", clauses=segment([
        "1. Контроль качества аудита и методологии",
        "1.1. Контроль качества аудита и методолагии",
        "2. Контроль качества аудита и методологии",
        "2.1. Длинное описание: контроль качества аудита и методологии",
        "2.2. Контроль качества аудита и методологии",
    ]))
    assert locate_quote(doc, "Контроль качества аудита и методологии") == "2.2"
    ev = evidence(doc, "1", "Разведение пингвинов на Марсе")
    assert not verify_evidence(ev, {"x": doc}).verified
    assert locate_quote(doc, ev.quote) is None


def test_verify_result_all_locations(real_doc):
    ev = evidence(real_doc, "missing", "Департамент ИТ-аудита и анализа данных (ДИТААД)")
    finding = dict(id="risk", type="structure_change", severity="low", title="x",
                   description="x", evidence=[ev], critic=dict(
                       verdict="uncertain", argument="x", counter_evidence=[ev]))
    result = AnalysisResult(
        units=[dict(id="u", side="after", name="x", evidence=[ev])],
        unit_changes=[dict(before_unit_ids=[], after_unit_ids=["u"], status="created",
                           rationale="x", evidence=[ev])],
        function_mappings=[dict(id="f", function="x", category_id="c", status="moved",
                                confidence=1, evidence=[ev])],
        findings=[finding], rejected_findings=[dict(finding, id="rejected")],
        conclusion_md="", documents=[real_doc], alignments=[], flows=[], categories=[],
        meta=dict(model="mock", provider="none", duration_s=0, documents=[]),
    )
    original = result.model_dump()
    checked = verify_result(result)
    all_ev = [checked.units[0].evidence[0], checked.unit_changes[0].evidence[0],
              checked.function_mappings[0].evidence[0]]
    for f in checked.findings + checked.rejected_findings:
        all_ev.extend(f.evidence + f.critic.counter_evidence)
    assert len(all_ev) == 7
    assert all(e.verified and e.clause_id == "3.4.а" for e in all_ev)
    assert result.model_dump() == original
    checked.documents[0].clauses.clear()
    assert result.documents[0].clauses


def test_offline_mock_is_reproducible_and_matches_golden():
    import json
    import runpy

    root = Path(__file__).resolve().parents[2]
    builder = runpy.run_path(str(root / "ai/scripts/build_mock.py"))
    result = builder["build_mock"]()
    checked = AnalysisResult.model_validate_json((root / "mocks/result.json").read_text(encoding="utf-8"))
    assert result.model_dump() == checked.model_dump()
    builder["validate_mock"](checked)
    assert checked.meta.model == "mock"
    assert 10 <= len(checked.conclusion_md.splitlines()) <= 20
    golden = json.loads((root / "ai/evals/golden_r8_r9.json").read_text(encoding="utf-8"))
    units = {u.id: u for u in checked.units}
    for fact in golden["unit_changes"]:
        assert any(
            change.status == fact["status"]
            and any(units[uid].abbr == fact["after_abbr"] for uid in change.after_unit_ids)
            and any(ev.side == fact["evidence"]["side"] and ev.clause_id == fact["evidence"]["clause_id"]
                    for ev in change.evidence)
            for change in checked.unit_changes
        ), fact
    for fact in golden["alignments"]:
        assert any(all(getattr(row, key) == value for key, value in fact.items())
                   for row in checked.alignments), fact
    for fact in golden["findings"]:
        assert any(
            finding.type == fact["type"]
            and set(fact["unit_abbrs"]) <= {units[uid].abbr for uid in finding.unit_ids}
            and set(fact["evidence_clause_ids"]) <= {ev.clause_id for ev in finding.evidence}
            for finding in checked.findings
        ), fact
