"""Pydantic-схемы результата. Строго соответствуют shared/api.md — меняем только вместе с контрактом."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Side = Literal["before", "after"]


class Clause(BaseModel):
    clause_id: str  # "3.4", "2.4.7", "3.4.а"
    section: str  # номер раздела верхнего уровня: "3"
    text: str


class DocumentText(BaseModel):
    doc_id: str
    name: str
    side: Side
    clauses: list[Clause]


class Evidence(BaseModel):
    doc_id: str
    doc_name: str
    side: Side
    clause_id: str
    quote: str
    verified: bool = False


class Unit(BaseModel):
    id: str
    side: Side
    name: str
    abbr: str | None = None
    parent: str | None = None
    positions: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class UnitChange(BaseModel):
    before_unit_ids: list[str]
    after_unit_ids: list[str]
    status: Literal["preserved", "renamed", "created", "abolished", "merged", "split", "transformed"]
    rationale: str
    evidence: list[Evidence] = Field(default_factory=list)


class FunctionMapping(BaseModel):
    id: str
    function: str
    category_id: str
    before_unit_id: str | None = None
    after_unit_ids: list[str] = Field(default_factory=list)
    status: Literal["preserved", "moved", "modified", "lost"]
    confidence: float = Field(ge=0, le=1)
    evidence: list[Evidence] = Field(default_factory=list)


class CriticVerdict(BaseModel):
    verdict: Literal["upheld", "refuted", "uncertain"]
    argument: str
    counter_evidence: list[Evidence] = Field(default_factory=list)


class Finding(BaseModel):
    id: str
    type: Literal["function_loss", "duplication", "conflict_of_interest", "structure_change"]
    severity: Literal["high", "medium", "low"]
    title: str
    description: str
    recommendation: str | None = None
    unit_ids: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    rule_id: str | None = None
    critic: CriticVerdict | None = None


class DiffOp(BaseModel):
    op: Literal["equal", "insert", "delete"]
    text: str


class ClauseAlignment(BaseModel):
    before_clause_id: str | None = None
    after_clause_id: str | None = None
    status: Literal["unchanged", "modified", "added", "removed", "moved"]
    similarity: float = Field(ge=0, le=1)
    diff: list[DiffOp] | None = None


class Flow(BaseModel):
    source_unit_id: str
    target_unit_id: str  # id unit «после» или "lost"
    function_ids: list[str]
    value: int


class Category(BaseModel):
    id: str
    name: str


class DocumentMeta(BaseModel):
    doc_id: str
    name: str
    side: Side


class Meta(BaseModel):
    model: str
    provider: str
    duration_s: float
    documents: list[DocumentMeta]


class AnalysisResult(BaseModel):
    units: list[Unit]
    unit_changes: list[UnitChange]
    function_mappings: list[FunctionMapping]
    findings: list[Finding]
    rejected_findings: list[Finding] = Field(default_factory=list)
    conclusion_md: str
    documents: list[DocumentText]
    alignments: list[ClauseAlignment]
    flows: list[Flow]
    categories: list[Category]
    meta: Meta
