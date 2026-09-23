import json
import logging
from pathlib import Path
from typing import Callable

from app.config import BACKEND_DIR


def run_analysis(
    before_files: list[Path],
    after_files: list[Path],
    on_progress: Callable[[str, float], None],
    *,
    mock: bool,
) -> dict:
    if mock:
        on_progress("parsing", 0.2)
        result = json.loads((BACKEND_DIR / "mocks" / "result.json").read_text(encoding="utf-8"))
        on_progress("report", 0.95)
        return result

    from ai.pipeline import run_analysis as ai_run_analysis

    result = ai_run_analysis(before_files, after_files, on_progress)
    return result.model_dump(mode="json")


def rebuild_conclusion(result: dict, *, mock: bool) -> str:
    if not mock:
        try:
            from ai.report import rebuild_conclusion as ai_rebuild_conclusion
            from ai.schemas import AnalysisResult

            return ai_rebuild_conclusion(AnalysisResult.model_validate(result))
        except Exception:
            logging.exception("AI conclusion rebuild failed; using evidence-based fallback")

    findings = result.get("findings", []) + result.get("rejected_findings", [])
    included = []
    for finding in findings:
        review = finding.get("review") or {}
        critic = finding.get("critic") or {}
        if not any(e.get("verified") for e in finding.get("evidence", [])):
            continue
        if review.get("status") == "accepted" or (
            review.get("status") != "rejected" and critic.get("verdict") != "refuted"
        ):
            included.append(finding)
    lines = ["# Заключение по анализу", ""]
    lines.extend(f"- {finding['title']}: {finding['description']}" for finding in included)
    if not included:
        lines.append("Выводов для включения в заключение нет.")
    return "\n".join(lines)
