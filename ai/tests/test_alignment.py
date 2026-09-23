from collections import Counter
from pathlib import Path
from time import perf_counter

import pytest

from ai.alignment import align, body, word_diff
from ai.parsing import parse_documents, segment
from ai.schemas import DocumentText


def document(lines, side):
    return DocumentText(doc_id=side, name=side, side=side, clauses=segment(lines))


@pytest.mark.parametrize(("text", "expected"), [
    ("3.8. Текст", "Текст"), ("3.10.Текст", "Текст"),
    ("а. Текст", "Текст"), ("Б) Текст", "Текст"),
    ("12.3.4 Текст", "Текст"), ("Без номера\n  текст", "Без номера\n  текст"),
])
def test_body(text, expected):
    assert body(text) == expected


@pytest.mark.parametrize(("a", "b"), [
    ("", ""), ("", "Новый текст"), ("Удалённый текст", ""),
    ("Контроль  качества,\nаудит!", "Контроль качества;\tметодология!"),
    ("а " * 250 + "старое", "а " * 250 + "новое"),
])
def test_word_diff_is_lossless(a, b):
    diff = word_diff(a, b)
    assert "".join(x.text for x in diff if x.op != "insert") == a
    assert "".join(x.text for x in diff if x.op != "delete") == b
    assert all(x.text for x in diff)
    assert all(x.op != y.op for x, y in zip(diff, diff[1:]))


def test_exact_duplicate_bodies_match_in_order():
    before = document(["1. Ёлка «тест»", "2. Повтор", "3. Повтор"], "before")
    after = document(['1. Елка  "тест"', "4. Повтор", "5. Повтор"], "after")
    rows = align(before, after)
    assert [(r.before_clause_id, r.after_clause_id, r.status) for r in rows] == [
        ("1", "1", "unchanged"), ("2", "4", "moved"), ("3", "5", "moved"),
    ]
    assert all(r.similarity == 1 for r in rows)


def test_modified_and_unmatched():
    before = document(["1. Контроль качества аудита", "2. Яяяя"], "before")
    after = document(["1. Контроль качества методологии", "3. Zzzz"], "after")
    rows = align(before, after)
    assert [r.status for r in rows] == ["modified", "removed", "added"]
    assert 0.6 <= rows[0].similarity < 1
    assert rows[1].similarity == rows[2].similarity == 0
    assert "".join(x.text for x in rows[0].diff if x.op != "insert") == body(before.clauses[0].text)
    assert "".join(x.text for x in rows[0].diff if x.op != "delete") == body(after.clauses[0].text)


def test_removed_runs_follow_previous_before_clause_even_when_moved():
    before = document(["1. Яяяя", "2. AAAA", "3. Бббб", "4. Вввв", "5. ZZZZ", "6. Гггг"], "before")
    after = document(["7. ZZZZ", "8. AAAA"], "after")
    rows = align(before, after)
    assert [(r.before_clause_id, r.after_clause_id) for r in rows] == [
        ("1", None), ("5", "7"), ("6", None), ("2", "8"), ("3", None), ("4", None),
    ]


def test_empty_documents():
    empty = document([], "before")
    full = document(["1. Текст"], "after")
    assert align(empty, empty) == []
    assert align(empty, full)[0].status == "added"
    assert align(full, empty)[0].status == "removed"


def test_real_documents_alignment_and_performance():
    samples = Path(__file__).resolve().parents[2] / "samples"
    before, after = parse_documents(sorted((samples / "before").glob("*.docx")),
                                    sorted((samples / "after").glob("*.docx")))
    started = perf_counter()
    rows = align(before, after)
    assert perf_counter() - started < 3
    by_after = {r.after_clause_id: r for r in rows if r.after_clause_id is not None}
    for old, new in [("3.8", "3.9"), ("3.4.а", "3.4.в"), ("3.4.б", "3.4.г"),
                     ("3.9", "3.10"), ("5.4.4.а", "5.3.3.а"), ("5.4.4.б", "5.3.3.б")]:
        assert by_after[new].before_clause_id == old
        assert by_after[new].status == "moved"
    assert by_after["3.4.а"].status == by_after["3.4.б"].status == "added"
    assert Counter(r.before_clause_id for r in rows if r.before_clause_id is not None) == Counter(c.clause_id for c in before.clauses)
    assert Counter(r.after_clause_id for r in rows if r.after_clause_id is not None) == Counter(c.clause_id for c in after.clauses)
    assert [r.after_clause_id for r in rows if r.after_clause_id is not None] == [c.clause_id for c in after.clauses]
    left, right = {c.clause_id: c for c in before.clauses}, {c.clause_id: c for c in after.clauses}
    for row in rows:
        if row.status == "modified":
            assert "".join(x.text for x in row.diff if x.op != "insert") == body(left[row.before_clause_id].text)
            assert "".join(x.text for x in row.diff if x.op != "delete") == body(right[row.after_clause_id].text)
