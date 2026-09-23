from typing import Literal

from pydantic import BaseModel, Field


class AnalysisStatus(BaseModel):
    id: str
    created_at: str | None = None
    status: Literal["queued", "running", "done", "failed"]
    step: str | None = None
    progress: float = Field(ge=0, le=1)
    error: str | None = None


class ReviewRequest(BaseModel):
    status: Literal["accepted", "rejected"]
    comment: str | None = None


class AnalysisSummary(BaseModel):
    id: str
    status: Literal["queued", "running", "done", "failed"]
    created_at: str
    documents: list[dict[str, str]]
    counts: dict[str, int] | None = None


class ClauseResponse(BaseModel):
    clause_id: str
    text: str
