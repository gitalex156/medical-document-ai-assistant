from typing import List


REQUIRED_SECTIONS = [
    "complaint",
    "medical_history",
    "objective_findings",
    "diagnosis",
    "treatment_plan",
    "recommendations",
    "follow_up_plan",
]


SECTION_KEYWORDS = {
    "complaint": ["жалоб", "жалуется", "complaint", "complaints", "беспокоит"],
    "medical_history": ["анамнез", "history", "medical history"],
    "objective_findings": ["осмотр", "объективно", "findings", "objective findings"],
    "diagnosis": ["диагноз", "diagnosis"],
    "treatment_plan": ["лечение", "назначено", "treatment", "treatment plan"],
    "recommendations": ["рекомендац", "recommendations"],
    "follow_up_plan": ["контроль", "повторный", "наблюдение", "follow-up", "follow up"],
}


def detect_missing_sections(report_text: str) -> List[str]:
    text = report_text.lower()
    missing = []

    for section, keywords in SECTION_KEYWORDS.items():
        if not any(keyword in text for keyword in keywords):
            missing.append(section)

    return missing


def detect_risks(report_text: str) -> List[str]:
    text = report_text.lower()
    risks = []

    if "противопоказ" not in text and "contraindication" not in text:
        risks.append("Не указаны противопоказания")

    if "аллерг" not in text and "allergy" not in text:
        risks.append("Не указана информация об аллергиях")

    if len(report_text) < 300:
        risks.append("Заключение слишком короткое для полноценной проверки")

    return risks


def calculate_quality_score(missing_sections: List[str], risks: List[str]) -> float:
    score = 1.0
    score -= 0.08 * len(missing_sections)
    score -= 0.05 * len(risks)
    return max(0.0, round(score, 2))
