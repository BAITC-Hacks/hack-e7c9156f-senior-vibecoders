"""Оркестратор агента: run_analysis(before, after, on_progress) -> AnalysisResult."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

from .alignment import align
from .conflicts import conflict_findings
from .context import Ctx
from .critic import run_critic
from .evidence import verify_result
from .functions import analyze_functions, apply_rejected_losses, build_flows, categories
from .llm import model_name, provider
from .parsing import parse_documents
from .refcheck import sanitize_conclusion
from .report import write_conclusion
from .schemas import AnalysisResult, DocumentMeta, Meta
from .units import extract_all_units, match_units, structure_findings

log = logging.getLogger(__name__)

ProgressFn = Callable[[str, float], None]

# шаг → доля прогресса к его началу (совпадает с AnalysisStatus.step в shared/api.md)
STEPS = {"parsing": 0.0, "alignment": 0.05, "units": 0.1, "functions": 0.3, "conflicts": 0.6,
         "evidence": 0.7, "critic": 0.75, "report": 0.9}


def run_analysis(before_files: list[Path], after_files: list[Path],
                 on_progress: ProgressFn | None = None) -> AnalysisResult:
    started = time.monotonic()

    def step(name: str) -> None:
        log.info("step %s (%.0fs)", name, time.monotonic() - started)
        if on_progress:
            on_progress(name, STEPS[name])

    step("parsing")
    docs = parse_documents([Path(p) for p in before_files], [Path(p) for p in after_files])
    ctx = Ctx(docs)

    step("alignment")
    alignments = _align_documents(ctx)

    step("units")
    units = extract_all_units(ctx)
    changes = match_units(ctx, units)

    step("functions")
    fr = analyze_functions(ctx, units, changes)

    step("conflicts")
    findings = structure_findings(changes, units) + fr.findings + \
        conflict_findings([f for f in fr.funcs if f.side == "after"], units)

    step("evidence")
    draft = AnalysisResult(
        units=units, unit_changes=changes, function_mappings=fr.mappings, findings=findings,
        conclusion_md="", documents=docs, alignments=alignments, flows=fr.flows, categories=categories(),
        meta=Meta(model=model_name(strong=True), provider=provider(), duration_s=0,
                  documents=[DocumentMeta(doc_id=d.doc_id, name=d.name, side=d.side) for d in docs]),
    )
    draft = verify_result(draft)  # цитаты проверяет код; неверные ссылки исправляются или помечаются

    step("critic")
    kept, rejected = run_critic(ctx, draft.findings)

    mappings = apply_rejected_losses(draft.function_mappings, rejected, fr.funcs, changes)

    step("report")
    conclusion = write_conclusion(ctx, units, draft.unit_changes, kept)
    result = draft.model_copy(update={
        "findings": kept, "rejected_findings": rejected, "conclusion_md": conclusion,
        "function_mappings": mappings, "flows": build_flows(mappings),
        "meta": draft.meta.model_copy(update={"duration_s": round(time.monotonic() - started, 1)}),
    })
    result = verify_result(result)  # контр-цитаты критика тоже проверяются
    # ссылки внутри текста заключения тоже проверяет код: неподтверждённая помечается, а не остаётся молча
    result = result.model_copy(update={"conclusion_md": sanitize_conclusion(result)})
    if on_progress:
        on_progress("report", 1.0)
    return result


def _align_documents(ctx: Ctx):
    """Каждый документ «до» выравниваем с самым похожим по имени документом «после»."""
    from rapidfuzz import fuzz

    out = []
    for b in ctx.side("before"):
        best = max(ctx.side("after"), key=lambda a: fuzz.token_set_ratio(b.name, a.name), default=None)
        if best is not None:
            out += align(b, best)
    return out
