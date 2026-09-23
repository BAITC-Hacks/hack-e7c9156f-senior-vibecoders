"""Чтение DOCX/PDF/XLSX и нарезка текста на пункты с clause_id. Без LLM.

clause_id:
  "3"      — заголовок раздела
  "3.4"    — нумерованный пункт
  "3.4.а"  — буквенный подпункт пункта 3.4
  "Лист1:12" — строка таблицы Excel
  "0"      — текст до первого пункта (шапка документа)
"""

from __future__ import annotations

import re
from pathlib import Path

from .schemas import Clause, DocumentText, Side

# "3.4. Текст", "3.10.Текст", "1. Общие положения"
_NUM_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s*(.*)$", re.S)
# "а. Текст", "б) Текст"
_LETTER_RE = re.compile(r"^([а-яё])[.)]\s+(.*)$", re.S | re.I)
# пункт, склеенный внутри абзаца: "...направления. 3.10.Рабочие места..."
_INLINE_NUM_RE = re.compile(r"(?<=[.;:])\s+(?=\d+\.\d+(?:\.\d+)*\.\s*[А-ЯЁA-Z])")
# строка оглавления: "3. СТРУКТУРА И ОРГАНИЗАЦИЯ РАБОТЫ ВНУТРЕННЕГО АУДИТА 8"
_TOC_RE = re.compile(r"^\d+\.\s+[А-ЯЁA-Z0-9\s,.«»\"()\-–]+\s\d+\s*$")
_SKIP_LINES = {"оглавление", "содержание", "приложения"}
# "Приложение 1. Кодекс этики …"
_APPENDIX_RE = re.compile(r"^Приложение\s+(\d+)\b", re.I)


def _docx_lines(path: Path) -> list[str]:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(str(path))
    lines: list[str] = []
    for el in d.element.body.iterchildren():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "p":
            lines.append(Paragraph(el, d).text)
        elif tag == "tbl":
            for row in Table(el, d).rows:
                cells: list[str] = []
                for c in row.cells:  # объединённые ячейки python-docx возвращает повторно
                    t = c.text.strip()
                    if t and (not cells or cells[-1] != t):
                        cells.append(t)
                if cells:
                    lines.append(" | ".join(cells))
    return lines


def _pdf_lines(path: Path) -> list[str]:
    import fitz  # pymupdf

    lines: list[str] = []
    with fitz.open(str(path)) as doc:
        for page in doc:
            lines.extend(page.get_text().splitlines())
    return lines


def _xlsx_clauses(path: Path) -> list[Clause]:
    import openpyxl

    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    clauses: list[Clause] = []
    for ws in wb.worksheets:
        for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
            cells = [str(v).strip() for v in row if v is not None and str(v).strip()]
            if cells:
                clauses.append(Clause(clause_id=f"{ws.title}:{i}", section=ws.title, text=" | ".join(cells)))
    return clauses


def _clean(text: str) -> str:
    text = text.replace("\xa0", " ").replace("\t", " ")
    return re.sub(r"[ ]{2,}", " ", text).strip()


def segment(lines: list[str]) -> list[Clause]:
    """Нарезка строк на пункты по текстовой нумерации."""
    clauses: list[Clause] = []
    seen: dict[str, int] = {}
    current_num: str | None = None  # последний нумерованный пункт — родитель для «а.», «б.»

    def add(cid: str, text: str) -> None:
        if cid in seen:  # повтор номера (ошибка в документе) — не теряем текст
            seen[cid] += 1
            cid = f"{cid}#{seen[cid]}"
        else:
            seen[cid] = 1
        section = "прил" if cid.startswith("прил.") else cid.split(".", 1)[0].split("#", 1)[0]
        clauses.append(Clause(clause_id=cid, section=section, text=text))

    for raw in lines:
        raw = _clean(raw)
        if not raw or _TOC_RE.match(raw) or raw.lower().rstrip(".:") in _SKIP_LINES:
            continue
        m = _APPENDIX_RE.match(raw)
        if m:
            current_num = None
            add(f"прил.{m.group(1)}", raw)
            continue
        for part in _INLINE_NUM_RE.split(raw):
            part = part.strip()
            if not part:
                continue
            m = _NUM_RE.match(part)
            if m and m.group(2):
                current_num = m.group(1)
                add(current_num, part)
                continue
            m = _LETTER_RE.match(part)
            if m and current_num:
                add(f"{current_num}.{m.group(1).lower()}", part)
                continue
            if clauses:  # продолжение предыдущего пункта (маркированный список, перенос строки)
                clauses[-1] = clauses[-1].model_copy(update={"text": f"{clauses[-1].text}\n{part}"})
            else:
                add("0", part)
    return clauses


def parse_document(path: str | Path, side: Side, doc_id: str) -> DocumentText:
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".docx":
        clauses = segment(_docx_lines(path))
    elif ext == ".pdf":
        clauses = segment(_pdf_lines(path))
    elif ext in (".xlsx", ".xlsm"):
        clauses = _xlsx_clauses(path)
    else:
        raise ValueError(f"Неподдерживаемый формат: {path.name} (нужен .docx, .pdf или .xlsx)")
    return DocumentText(doc_id=doc_id, name=path.name, side=side, clauses=clauses)


def parse_documents(before: list[Path], after: list[Path]) -> list[DocumentText]:
    docs = [parse_document(p, "before", f"b{i}") for i, p in enumerate(before, 1)]
    docs += [parse_document(p, "after", f"a{i}") for i, p in enumerate(after, 1)]
    return docs


def clause_text(doc: DocumentText, clause_id: str, with_children: bool = True) -> str | None:
    """Текст пункта; с подпунктами (3.4 → 3.4 + 3.4.а + 3.4.б …)."""
    parts = [
        c.text
        for c in doc.clauses
        if c.clause_id == clause_id or (with_children and c.clause_id.startswith(clause_id + "."))
    ]
    return "\n".join(parts) if parts else None


def render_for_prompt(doc: DocumentText, sections: set[str] | None = None) -> str:
    """Документ в виде «[clause_id] текст» — формат, в котором LLM видит и цитирует пункты."""
    rows = [f"[{c.clause_id}] {c.text}" for c in doc.clauses if sections is None or c.section in sections]
    return f"=== Документ {doc.doc_id}: {doc.name} ({'до' if doc.side == 'before' else 'после'}) ===\n" + "\n".join(rows)
