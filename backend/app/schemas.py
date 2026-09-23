from typing import Literal

from pydantic import BaseModel, Field


Side = Literal["before", "after"]
Step = Literal[
    "parsing", "units", "unit_matching", "functions", "function_matching",
    "duplicates", "conflicts", "evidence", "report",
]


class AnalysisStatus(BaseModel):
    id: str
    status: Literal["queued", "running", "done", "failed"]
    step: Step | None = None
    progress: float = Field(ge=0, le=1)
    error: str | None = None


class Evidence(BaseModel):
    doc_id: str
    doc_name: str
    side: Side
    clause_id: str
    quote: str
    verified: bool


class Unit(BaseModel):
    id: str
    side: Side
    name: str
    abbr: str | None = None
    parent: str | None = None
    positions: list[str]
    evidence: list[Evidence]


class UnitChange(BaseModel):
    before_unit_ids: list[str]
    after_unit_ids: list[str]
    status: Literal["preserved", "renamed", "created", "abolished", "merged", "split", "transformed"]
    rationale: str
    evidence: list[Evidence]


class FunctionMapping(BaseModel):
    function: str
    before_unit_id: str | None = None
    after_unit_ids: list[str]
    status: Literal["preserved", "moved", "modified", "lost"]
    confidence: float = Field(ge=0, le=1)
    evidence: list[Evidence]


class Finding(BaseModel):
    id: str
    type: Literal["function_loss", "duplication", "conflict_of_interest", "structure_change"]
    severity: Literal["high", "medium", "low"]
    title: str
    description: str
    recommendation: str | None = None
    unit_ids: list[str]
    evidence: list[Evidence]


class DocumentMeta(BaseModel):
    doc_id: str
    name: str
    side: Side


class ResultMeta(BaseModel):
    model: str
    provider: str
    duration_s: float = Field(ge=0)
    documents: list[DocumentMeta]


class AnalysisResult(BaseModel):
    units: list[Unit]
    unit_changes: list[UnitChange]
    function_mappings: list[FunctionMapping]
    findings: list[Finding]
    conclusion_md: str
    meta: ResultMeta


class ClauseResponse(BaseModel):
    clause_id: str
    text: str
