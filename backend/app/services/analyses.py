import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4

from docx import Document
from app.clients.ai import rebuild_conclusion, run_analysis
from app.config import Settings
from app.schemas import AnalysisStatus


DEMO_BEFORE = [
    "3.4. В БВА входят ДНМ, ДККМ и Директор направления внутреннего аудита.",
    "3.8. В ДККМ предусмотрены Директор по контролю качества аудита и методологии и Менеджер по аудиту.",
]
DEMO_AFTER = [
    "3.4. В БВА входят ДНМ, ДККМ, ДИТААД и ДОА.",
    "3.9. В ДККМ предусмотрены обновлённые должности.",
]


class AnalysisStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.storage_dir.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.review_lock = RLock()

    def directory(self, analysis_id: str) -> Path | None:
        if len(analysis_id) != 32 or any(c not in "0123456789abcdef" for c in analysis_id):
            return None
        path = self.root / analysis_id
        return path if path.is_dir() else None

    @staticmethod
    def _write_json(path: Path, value: object) -> None:
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)

    @staticmethod
    def _read_json(path: Path) -> object:
        return json.loads(path.read_text(encoding="utf-8"))

    def create(self, files: list[tuple[str, str, bytes]], *, demo: bool = False) -> str:
        analysis_id = uuid4().hex
        folder = self.root / analysis_id
        folder.mkdir()
        documents = []
        counts = {"before": 0, "after": 0}
        for side, name, content in files:
            counts[side] += 1
            doc_id = f"{side}-{counts[side]}"
            path = folder / f"{doc_id}{Path(name).suffix.lower()}"
            path.write_bytes(content)
            documents.append({"doc_id": doc_id, "name": name, "side": side, "path": path.name})
        self._write_json(folder / "documents.json", documents)
        created_at = datetime.now(timezone.utc).isoformat()
        self._write_json(folder / "status.json", AnalysisStatus(id=analysis_id, created_at=created_at, status="queued", progress=0).model_dump(exclude_none=True))
        if demo:
            (folder / "demo").touch()
        return analysis_id

    def create_demo(self) -> str:
        files = []
        for side, name, lines in [
            ("before", "demo_before.docx", DEMO_BEFORE),
            ("after", "demo_after.docx", DEMO_AFTER),
        ]:
            from io import BytesIO

            doc = Document()
            for line in lines:
                doc.add_paragraph(line)
            output = BytesIO()
            doc.save(output)
            files.append((side, name, output.getvalue()))
        return self.create(files, demo=True)

    def status(self, folder: Path) -> AnalysisStatus:
        path = folder / "status.json"
        status = AnalysisStatus.model_validate(self._read_json(path))
        if status.created_at is None:
            status.created_at = datetime.fromtimestamp((folder / "documents.json").stat().st_mtime, timezone.utc).isoformat()
        return status

    def documents(self, folder: Path) -> list[dict]:
        return self._read_json(folder / "documents.json")

    def result(self, folder: Path) -> dict:
        result = self._read_json(folder / "result.json")
        for key in ("rejected_findings", "documents", "alignments", "flows", "categories"):
            result.setdefault(key, [])
        return result

    def history(self) -> list[dict]:
        summaries = []
        for folder in self.root.iterdir():
            if not folder.is_dir() or self.directory(folder.name) is None:
                continue
            if not (folder / "status.json").is_file() or not (folder / "documents.json").is_file():
                continue
            status = self.status(folder)
            documents = [{"name": d["name"], "side": d["side"]} for d in self.documents(folder)]
            summary = {"id": status.id, "status": status.status, "created_at": status.created_at, "documents": documents}
            if status.status == "done":
                result = self.result(folder)
                findings = result.get("findings", [])
                rejected = result.get("rejected_findings", [])
                summary["counts"] = {
                    "findings": len(findings), "rejected": len(rejected),
                    "high": sum(f.get("severity") == "high" for f in findings),
                }
            summaries.append(summary)
        return sorted(summaries, key=lambda item: datetime.fromisoformat(item["created_at"]), reverse=True)

    def review(self, folder: Path, finding_id: str, status: str, comment: str | None) -> dict | None:
        with self.review_lock:
            result = self.result(folder)
            finding = next((f for f in result["findings"] + result["rejected_findings"] if f["id"] == finding_id), None)
            if finding is None:
                return None
            finding["review"] = {
                "status": status, "comment": comment,
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
            }
            result["conclusion_md"] = rebuild_conclusion(result, mock=result["meta"]["provider"] == "mock")
            self._write_json(folder / "result.json", result)
            return result

    def run(self, analysis_id: str) -> None:
        folder = self.directory(analysis_id)
        if folder is None:
            return
        previous = self.status(folder)
        self._write_json(folder / "status.json", previous.model_copy(update={"status": "running", "step": "parsing", "progress": 0.01}).model_dump(exclude_none=True))

        def progress(step: str, value: float) -> None:
            status = AnalysisStatus(id=analysis_id, created_at=previous.created_at, status="running", step=step, progress=value)
            self._write_json(folder / "status.json", status.model_dump(exclude_none=True))

        documents = self.documents(folder)
        before = [folder / d["path"] for d in documents if d["side"] == "before"]
        after = [folder / d["path"] for d in documents if d["side"] == "after"]
        try:
            result = run_analysis(before, after, progress, mock=self.settings.ai_mock)
        except Exception as exc:
            if (folder / "demo").exists() and not self.settings.ai_mock:
                try:
                    result = run_analysis(before, after, progress, mock=True)
                except Exception as fallback_exc:
                    self._fail(folder, analysis_id, fallback_exc)
                    return
            else:
                self._fail(folder, analysis_id, exc)
                return

        self._write_json(folder / "result.json", result)
        self._write_json(folder / "status.json", AnalysisStatus(id=analysis_id, created_at=previous.created_at, status="done", step="report", progress=1).model_dump(exclude_none=True))

    def _fail(self, folder: Path, analysis_id: str, exc: Exception) -> None:
        message = "Пакет ИИ недоступен" if isinstance(exc, ModuleNotFoundError) else "Не удалось выполнить анализ"
        self._write_json(folder / "status.json", AnalysisStatus(id=analysis_id, created_at=self.status(folder).created_at, status="failed", progress=0, error=message).model_dump(exclude_none=True))


def build_report(result: dict, documents: list[dict], created_at: str, path: Path) -> None:
    doc = Document()
    doc.add_heading("Служебная записка", 0)
    doc.add_paragraph(f"Дата: {datetime.fromisoformat(created_at).strftime('%d.%m.%Y')}")
    doc.add_heading("Документы", level=1)
    for item in documents:
        side = "До" if item["side"] == "before" else "После"
        doc.add_paragraph(f"{side}: {item['name']}", style="List Bullet")

    doc.add_heading("Заключение", level=1)
    for raw_line in result.get("conclusion_md", "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            doc.add_heading(line.lstrip("# "), level=min(len(line) - len(line.lstrip("#")) + 1, 3))
        elif line.startswith(("- ", "* ")):
            doc.add_paragraph(line[2:], style="List Bullet")
        elif line[0].isdigit() and ". " in line and line.split(". ", 1)[0].isdigit():
            doc.add_paragraph(line.split(". ", 1)[1], style="List Number")
        else:
            doc.add_paragraph(line)

    doc.add_heading("Выводы", level=1)
    table = doc.add_table(rows=1, cols=5)
    table.style = "Table Grid"
    for cell, label in zip(table.rows[0].cells, ("Тип", "Критичность", "Заголовок", "Источники", "Проверка")):
        cell.text = label
    for finding in result.get("findings", []) + result.get("rejected_findings", []):
        sources = "; ".join(
            f"{e['doc_name']}, п. {e['clause_id']} — «{e['quote']}»"
            for e in finding.get("evidence", [])
        )
        review = finding.get("review") or {}
        review_text = {"accepted": "Принято", "rejected": "Отклонено"}.get(review.get("status"), "Не проверено")
        if review.get("comment"):
            review_text += f": {review['comment']}"
        if finding in result.get("rejected_findings", []):
            review_text += "; опровергнуто критиком"
        row = table.add_row().cells
        for cell, value in zip(row, (finding["type"], finding["severity"], finding["title"], sources, review_text)):
            cell.text = value

    doc.add_paragraph(
        "Выводы носят рекомендательный характер и требуют проверки ответственным сотрудником."
    )
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        doc.save(temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
