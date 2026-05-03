from pydantic import BaseModel, Field
from typing import List, Optional


class ReviewRequest(BaseModel):
    report_text: str = Field(
        ...,
        min_length=20,
        description="Medical report text to be reviewed",
    )


class SourceChunk(BaseModel):
    source: str
    text: str


class LLMReview(BaseModel):
    llm_summary: str = ""
    quality_explanation: str = ""
    improved_recommendations: List[str] = []
    doctor_copilot_hint: str = ""


class ReviewResponse(BaseModel):
    summary: str
    quality_score: float = Field(..., ge=0.0, le=1.0)
    missing_sections: List[str]
    risks: List[str]
    recommendations: List[str]
    sources: List[SourceChunk] = []
    llm_review: Optional[LLMReview] = None
