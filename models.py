from datetime import datetime
from typing import Optional
from pydantic import BaseModel, HttpUrl


class AnalyzeRequest(BaseModel):
    url: str


class CategoryResult(BaseModel):
    name: str
    risk: str  # "low" | "medium" | "high"
    summary: str
    quote: Optional[str] = None


class CategoryChange(BaseModel):
    name: str
    previous_risk: str
    current_risk: str
    risk_changed: bool
    summary_changed: bool


class AnalysisResult(BaseModel):
    company: str
    url: str
    analyzed_at: datetime
    document_date: Optional[str] = None   # revision date stated inside the document
    overall_risk: str
    overall_summary: str
    categories: list[CategoryResult]
    privacy_score: Optional[int] = None   # 0-100 weighted risk score
    grade: Optional[str] = None           # A / B / C / D / F
    # populated when serving from cache
    from_cache: bool = False
    cached_at: Optional[datetime] = None
    version: Optional[int] = None
    changes_from_previous: Optional[list[CategoryChange]] = None
    is_pdf: bool = False


class PopularEntry(BaseModel):
    url: str
    company: str
    overall_risk: str
    overall_summary: str
    request_count: int
    analyzed_at: datetime
    document_date: Optional[str] = None
    is_pdf: bool = False
    has_newer_version: bool = False
    privacy_score: Optional[int] = None
    grade: Optional[str] = None


class PopularResponse(BaseModel):
    entries: list[PopularEntry]
    list_size: int


class AdminSettings(BaseModel):
    popular_list_size: int


class HealthResponse(BaseModel):
    status: str
