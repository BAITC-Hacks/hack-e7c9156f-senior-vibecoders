import json
from pathlib import Path
from typing import Callable

from app.config import BACKEND_DIR
from app.schemas import AnalysisResult


def run_analysis(
    before_files: list[Path],
    after_files: list[Path],
    on_progress: Callable[[str, float], None],
    *,
    mock: bool,
) -> AnalysisResult:
    if mock:
        on_progress("parsing", 0.2)
        result = json.loads((BACKEND_DIR / "mocks" / "result.json").read_text(encoding="utf-8"))
        on_progress("report", 0.95)
        return AnalysisResult.model_validate(result)

    from ai.pipeline import run_analysis as ai_run_analysis

    return AnalysisResult.model_validate(
        ai_run_analysis(before_files, after_files, on_progress)
    )
