from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app.schemas import AnalysisStatus, AnalysisSummary, ClauseResponse, ReviewRequest
from app.services.analyses import DEMO_AFTER, DEMO_BEFORE, AnalysisStore, build_report
from app.services.documents import get_clause


router = APIRouter(prefix="/api/analyses", tags=["analyses"])
ALLOWED_EXTENSIONS = {".docx", ".pdf", ".xlsx"}
MAX_FILE_BYTES = 20 * 1024 * 1024


def store_for(request: Request) -> AnalysisStore:
    return request.app.state.store


def folder_for(store: AnalysisStore, analysis_id: str) -> Path:
    folder = store.directory(analysis_id)
    if folder is None:
        raise HTTPException(404, "Анализ не найден")
    return folder


async def read_uploads(uploads: list[UploadFile], side: str) -> list[tuple[str, str, bytes]]:
    if not uploads:
        label = "до" if side == "before" else "после"
        raise HTTPException(400, f"Загрузите хотя бы один файл «{label}»")
    files = []
    for upload in uploads:
        name = (upload.filename or "").replace("\\", "/").split("/")[-1]
        if not name or Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
            raise HTTPException(415, f"Файл «{name or 'без имени'}» не поддерживается: загрузите .docx, .pdf или .xlsx")
        content = await upload.read(MAX_FILE_BYTES + 1)
        if not content:
            raise HTTPException(400, f"Файл «{name}» пуст")
        if len(content) > MAX_FILE_BYTES:
            raise HTTPException(413, f"Файл «{name}» больше 20 МБ")
        files.append((side, name[:255], content))
    return files


@router.post("")
async def create_analysis(
    request: Request,
    background_tasks: BackgroundTasks,
    before: list[UploadFile] | None = File(None),
    after: list[UploadFile] | None = File(None),
) -> dict[str, str]:
    files = await read_uploads(before or [], "before") + await read_uploads(after or [], "after")
    store = store_for(request)
    analysis_id = store.create(files)
    background_tasks.add_task(store.run, analysis_id)
    return {"id": analysis_id}


@router.post("/demo")
def create_demo(request: Request, background_tasks: BackgroundTasks) -> dict[str, str]:
    store = store_for(request)
    analysis_id = store.create_demo()
    background_tasks.add_task(store.run, analysis_id)
    return {"id": analysis_id}


@router.get("", response_model=list[AnalysisSummary], response_model_exclude_none=True)
def list_analyses(request: Request) -> list[dict]:
    return store_for(request).history()


@router.get("/{analysis_id}", response_model=AnalysisStatus, response_model_exclude_none=True)
def get_status(analysis_id: str, request: Request) -> AnalysisStatus:
    store = store_for(request)
    return store.status(folder_for(store, analysis_id))


@router.get("/{analysis_id}/result")
def get_result(analysis_id: str, request: Request) -> dict:
    store = store_for(request)
    folder = folder_for(store, analysis_id)
    if store.status(folder).status != "done":
        raise HTTPException(409, "Анализ ещё не завершён")
    return store.result(folder)


@router.patch("/{analysis_id}/findings/{finding_id}")
def review_finding(analysis_id: str, finding_id: str, body: ReviewRequest, request: Request) -> dict:
    store = store_for(request)
    folder = folder_for(store, analysis_id)
    if store.status(folder).status != "done":
        raise HTTPException(409, "Анализ ещё не завершён")
    result = store.review(folder, finding_id, body.status, body.comment)
    if result is None:
        raise HTTPException(404, "Вывод не найден")
    return result


@router.get("/{analysis_id}/documents/{doc_id}/clauses/{clause_id}", response_model=ClauseResponse)
def get_document_clause(
    analysis_id: str, doc_id: str, clause_id: str, request: Request,
) -> ClauseResponse:
    store = store_for(request)
    folder = folder_for(store, analysis_id)
    if store.status(folder).status != "done":
        raise HTTPException(409, "Анализ ещё не завершён")
    result = store.result(folder)
    parsed_document = next((d for d in result.get("documents", []) if d["doc_id"] == doc_id), None)
    if parsed_document:
        clause = next((c for c in parsed_document["clauses"] if c["clause_id"] == clause_id), None)
        if clause:
            return ClauseResponse(clause_id=clause_id, text=clause["text"])
        raise HTTPException(404, "Пункт не найден")
    if result["meta"]["provider"] == "mock" and doc_id in {"before-1", "after-1"}:
        lines = DEMO_BEFORE if doc_id == "before-1" else DEMO_AFTER
        text = next((line for line in lines if line.startswith(f"{clause_id}.")), None)
        if text:
            return ClauseResponse(clause_id=clause_id, text=text)
        raise HTTPException(404, "Пункт не найден")
    documents = store.documents(folder)
    document = next((d for d in documents if d["doc_id"] == doc_id), None)
    if document is None:
        meta = next((d for d in result["meta"]["documents"] if d["doc_id"] == doc_id), None)
        if meta:
            document = next((d for d in documents if d["name"] == meta["name"] and d["side"] == meta["side"]), None)
    if document is None:
        raise HTTPException(404, "Документ не найден")
    try:
        text = get_clause(folder / document["path"], clause_id)
    except Exception:
        raise HTTPException(422, "Не удалось прочитать документ") from None
    if text is None:
        raise HTTPException(404, "Пункт не найден")
    return ClauseResponse(clause_id=clause_id, text=text)


@router.get("/{analysis_id}/report.docx")
def get_report(analysis_id: str, request: Request) -> FileResponse:
    store = store_for(request)
    folder = folder_for(store, analysis_id)
    if store.status(folder).status != "done":
        raise HTTPException(409, "Анализ ещё не завершён")
    report_path = folder / "report.docx"
    if not report_path.exists() or report_path.stat().st_mtime_ns < (folder / "result.json").stat().st_mtime_ns:
        build_report(store.result(folder), store.documents(folder), store.status(folder).created_at, report_path)
    return FileResponse(
        report_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"zaklyuchenie_{analysis_id}.docx",
    )
