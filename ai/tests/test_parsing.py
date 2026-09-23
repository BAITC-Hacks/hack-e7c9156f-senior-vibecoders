from pathlib import Path

import pytest

from ai.parsing import clause_text, parse_document, segment

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def ids(clauses):
    return [c.clause_id for c in clauses]


def test_numbered_and_letter_items():
    cl = segment([
        "1. Общие положения",
        "3.4. БВА состоит из следующих структурных подразделений:",
        "а. Департамент ИТ-аудита (ДИТААД).",
        "б. Департамент операционного аудита (ДОА).",
        "- продолжение списка",
    ])
    assert ids(cl) == ["1", "3.4", "3.4.а", "3.4.б"]
    assert cl[1].section == "3"
    assert cl[-1].text.endswith("- продолжение списка")


def test_inline_clause_split():
    cl = segment(["3.9. Состав: б. Руководитель направления. 3.10.Рабочие места могут располагаться в филиалах."])
    assert ids(cl) == ["3.9", "3.10"]
    assert cl[1].text.startswith("3.10.Рабочие места")


def test_toc_and_appendix():
    cl = segment(["13.3. Последний пункт.", "Оглавление", "1. ОБЩИЕ ПОЛОЖЕНИЯ 1", "Приложение 1. Кодекс этики"])
    assert ids(cl) == ["13.3", "прил.1"]
    assert cl[0].text == "13.3. Последний пункт."


def test_duplicate_ids_kept():
    cl = segment(["9.3. Пункт", "а. один", "вводный текст", "а. другой"])
    assert ids(cl) == ["9.3", "9.3.а", "9.3.а#2"]


def test_clause_text_with_children():
    cl = segment(["3.4. Состав:", "а. ДИТААД", "3.40. Другой пункт"])
    from ai.schemas import DocumentText

    doc = DocumentText(doc_id="a1", name="x", side="after", clauses=cl)
    assert clause_text(doc, "3.4") == "3.4. Состав:\nа. ДИТААД"  # 3.40 не считается подпунктом 3.4


@pytest.mark.skipif(not (SAMPLES / "after").exists(), reason="нет samples/")
def test_real_document_r9():
    doc = parse_document(next((SAMPLES / "after").glob("*.docx")), "after", "a1")
    t = clause_text(doc, "3.4")
    assert "ДИТААД" in t and "ДОА" in t and "ДНМ" in t and "ДККМ" in t
    assert clause_text(doc, "3.10", with_children=False).startswith("3.10.Рабочие места")
    assert "3.11" in ids(doc.clauses)
