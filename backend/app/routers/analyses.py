from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app.schemas import AnalysisResult, AnalysisStatus, ClauseResponse
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
        raise HTTPException(422, f"Нужен хотя бы один файл '{side}'")
    if len(uploads) > 10:
        raise HTTPException(413, "Не больше 10 файлов на одну сторону")
    files = []
    for upload in uploads:
        name = (upload.filename or "").replace("\\", "/").split("/")[-1]
        if not name or Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
            raise HTTPException(400, "Допустимы только DOCX, PDF и XLSX")
        content = await upload.read(MAX_FILE_BYTES + 1)
        if not content:
            raise HTTPException(400, f"Файл '{name}' пуст")
        if len(content) > MAX_FILE_BYTES:
            raise HTTPException(413, f"Файл '{name}' больше 20 МБ")
        files.append((side, name[:255], content))
    return files


@router.post("")
async def create_analysis(
    request: Request,
    background_tasks: BackgroundTasks,
    before: list[UploadFile] = File(...),
    after: list[UploadFile] = File(...),
) -> dict[str, str]:
    files = await read_uploads(before, "before") + await read_uploads(after, "after")
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


@router.get("/{analysis_id}", response_model=AnalysisStatus, response_model_exclude_none=True)
def get_status(analysis_id: str, request: Request) -> AnalysisStatus:
    store = store_for(request)
    return store.status(folder_for(store, analysis_id))


@router.get("/{analysis_id}/result", response_model=AnalysisResult, response_model_exclude_none=True)
def get_result(analysis_id: str, request: Request) -> AnalysisResult:
    store = store_for(request)
    folder = folder_for(store, analysis_id)
    if store.status(folder).status != "done":
        raise HTTPException(409, "Анализ ещё не завершён")
    return store.result(folder)


@router.get("/{analysis_id}/documents/{doc_id}/clauses/{clause_id}", response_model=ClauseResponse)
def get_document_clause(
    analysis_id: str, doc_id: str, clause_id: str, request: Request,
) -> ClauseResponse:
    store = store_for(request)
    folder = folder_for(store, analysis_id)
    if store.status(folder).status != "done":
        raise HTTPException(409, "Анализ ещё не завершён")
    result = store.result(folder)
    if result.meta.provider == "mock" and doc_id in {"before-1", "after-1"}:
        lines = DEMO_BEFORE if doc_id == "before-1" else DEMO_AFTER
        text = next((line for line in lines if line.startswith(f"{clause_id}.")), None)
        if text:
            return ClauseResponse(clause_id=clause_id, text=text)
        raise HTTPException(404, "Пункт не найден")
    documents = store.documents(folder)
    document = next((d for d in documents if d["doc_id"] == doc_id), None)
    if document is None:
        meta = next((d for d in result.meta.documents if d.doc_id == doc_id), None)
        if meta:
            document = next((d for d in documents if d["name"] == meta.name and d["side"] == meta.side), None)
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
    if not report_path.exists():
        build_report(store.result(folder), report_path)
    return FileResponse(
        report_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename="analysis-report.docx",
    )
