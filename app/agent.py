from app.schemas import ReviewResponse, LLMReview
from app.tools import (
    detect_missing_sections,
    detect_risks,
    calculate_quality_score,
)
from app.rag import retrieve_relevant_chunks
from app.llm import is_llm_enabled, generate_llm_review


def generate_summary(report_text: str) -> str:
    return report_text[:200] + "..." if len(report_text) > 200 else report_text


def run_agent(report_text: str) -> ReviewResponse:
    sources = retrieve_relevant_chunks(report_text)

    missing_sections = detect_missing_sections(report_text)
    risks = detect_risks(report_text)
    score = calculate_quality_score(missing_sections, risks)

    summary = generate_summary(report_text)

    recommendations = []

    if missing_sections:
        recommendations.append("ADD_MISSING_SECTIONS:" + ",".join(missing_sections))

    recommendations.extend(risks)

    if sources:
        recommendations.append("RAG_GROUNDED")

    llm_review = None

    if is_llm_enabled():
        llm_data = generate_llm_review(
            report_text=report_text,
            missing_sections=missing_sections,
            risks=risks,
            quality_score=score,
            sources=sources,
        )
        llm_review = LLMReview(**llm_data)

    return ReviewResponse(
        summary=summary,
        quality_score=score,
        missing_sections=missing_sections,
        risks=risks,
        recommendations=recommendations,
        sources=sources,
        llm_review=llm_review,
    )
