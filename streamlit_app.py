import requests
import re
import json
import time
from datetime import datetime
from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components


API_URL = "http://127.0.0.1:8000/review"
ANALYTICS_FILE = Path("data/analytics_events.jsonl")
SUPPORT_FILE = Path("data/support_messages.jsonl")

SECTION_LABELS = {
    "complaint": "Жалобы пациента",
    "medical_history": "Анамнез",
    "objective_findings": "Объективный осмотр",
    "diagnosis": "Диагноз",
    "treatment_plan": "План лечения",
    "recommendations": "Что уточнить у врача",
    "follow_up_plan": "План наблюдения / контроль",
}

TEXT_REPLACEMENTS = {
    "диагностирован/head diagnosed:": "указан диагноз:",
    "diagnosed/head diagnosed:": "указан диагноз:",
    "head diagnosed": "указан диагноз",
    "objective_findings": "объективный осмотр",
    "medical_history": "анамнез",
    "treatment_plan": "план лечения",
    "follow_up_plan": "план наблюдения / контроль",
    "symptoms": "симптомах",
}


def humanize_section(section: str) -> str:
    return SECTION_LABELS.get(section, section)


def normalize_generated_text(text_value: str) -> str:
    """
    Финальная нормализация AI-текста перед выводом:
    - убирает английские служебные слова;
    - исправляет заглавные буквы после запятых;
    - исправляет фразы про клинические рекомендации;
    - не трогает технические термины AI, RAG, LLM, JSON, API.
    """
    if not text_value:
        return ""

    text_value = str(text_value).strip()

    replacements = [
        (r"\bPatient\s+complaining\s+of\b", "Пациент жалуется на"),
        (r"\bPatient\s+complains\s+of\b", "Пациент жалуется на"),
        (r"\bPatient\s+complaining\b", "Пациент жалуется"),
        (r"\bPatient\s+complains\b", "Пациент жалуется"),
        (r"\bcomplaining\s+of\b", "жалуется на"),
        (r"\bcomplains\s+of\b", "жалуется на"),
        (r"\bcomplaining\b", "жалуется"),
        (r"\bcomplains\b", "жалуется"),

        (r"\bcomplaints\b", "жалобы пациента"),
        (r"\bcomplaint\b", "жалобы пациента"),
        (r"\banamnesis\b", "анамнез"),
        (r"\banamnes\b", "анамнез"),
        (r"\bdiagnosis\b", "диагноз"),
        (r"\brecommendations\b", "рекомендации"),
        (r"\brecommendation\b", "рекомендация"),

        (r"\bmissing\s+sections\b", "недостающие разделы"),
        (r"\bquality\s+score\b", "оценка качества"),
        (r"\brisks\b", "риски"),
        (r"\brisk\b", "риск"),

        (r"\bNo\s+guideline[- ]?sources\b", "Нет клинических рекомендаций"),
        (r"\bNo\s+guidelines\b", "Нет клинических рекомендаций"),
        (r"\bguideline[- ]?sources\b", "клинические рекомендации"),
        (r"\bguidelines\b", "клинические рекомендации"),
        (r"\bguideline\b", "клиническая рекомендация"),

        (r"\bConduct\b", "провести"),
        (r"\bconduct\b", "провести"),
        (r"\bPerform\b", "провести"),
        (r"\bperform\b", "провести"),
        (r"\bAssess\b", "оценить"),
        (r"\bassess\b", "оценить"),
        (r"\bReview\b", "проверить"),
        (r"\breview\b", "проверить"),
        (r"\bCheck\b", "проверить"),
        (r"\bcheck\b", "проверить"),
        (r"\bDocument\b", "описать"),
        (r"\bdocument\b", "описать"),
    ]

    for pattern, replacement in replacements:
        text_value = re.sub(pattern, replacement, text_value, flags=re.IGNORECASE)

    # Чиним кривые варианты про "источники клинических рекомендаций"
    bad_guideline_patterns = [
        r"Нет\s+клиническ\w*\s+рекомендаци\w*[-\s]*источников",
        r"Нет\s+клинической\s+рекомендации\s+источников",
        r"Нет\s+клиническая\s+рекомендация[-\s]*источников",
        r"Нет\s+клинические\s+рекомендации[-\s]*источников",
        r"клиническая\s+рекомендация[-\s]*источников",
        r"клинической\s+рекомендации\s+источников",
        r"клинические\s+рекомендации[-\s]*источников",
    ]

    for pattern in bad_guideline_patterns:
        text_value = re.sub(
            pattern,
            "Нет клинических рекомендаций",
            text_value,
            flags=re.IGNORECASE,
        )

    # После "Риски:" делаем список аккуратным:
    # Риски: Не указаны..., Не указана... -> Риски: не указаны...; не указана...
    def polish_risks(match):
        prefix = match.group(1)
        body = match.group(2).strip()

        parts = [part.strip() for part in re.split(r"[,;]", body) if part.strip()]

        if len(parts) <= 1:
            return match.group(0)

        normalized = []
        for part in parts:
            if part and re.match(r"[А-ЯЁ]", part[0]):
                part = part[0].lower() + part[1:]
            normalized.append(part)

        return prefix + "; ".join(normalized)

    text_value = re.sub(
        r"(Риски:\s*)([^.]+)",
        polish_risks,
        text_value,
        flags=re.IGNORECASE,
    )

    # После запятой/точки с запятой внутри предложения — строчная буква
    text_value = re.sub(
        r"([,;]\s+)([А-ЯЁ])",
        lambda m: m.group(1) + m.group(2).lower(),
        text_value,
    )

    # Оставшиеся английские слова удаляем, но сохраняем технические термины
    allowed = {"AI", "RAG", "LLM", "JSON", "API", "FastAPI", "Streamlit", "Ollama"}

    def remove_latin(match):
        token = match.group(0)
        if token in allowed or token.upper() in allowed:
            return token
        return ""

    if re.search(r"[А-Яа-яЁё]", text_value):
        text_value = re.sub(r"\b[A-Za-z][A-Za-z\-]*\b", remove_latin, text_value)

    # Чистим пробелы
    text_value = re.sub(r"\s+([,.!?;:])", r"\1", text_value)
    text_value = re.sub(r"\s{2,}", " ", text_value)

    return text_value.strip()

def clean_text(text: str) -> str:
    if not text:
        return ""

    for old, new in TEXT_REPLACEMENTS.items():
        text = text.replace(old, new)

    fixes = {
        "Не указать информацию об аллергиях": "Не указана информация об аллергиях",
        "Не указать противопоказания": "Не указаны противопоказания",
        "Не указать": "Не указаны",
        "Заключить более длинное заключение": "Заключение слишком короткое для полноценной проверки",
    }

    for old, new in fixes.items():
        text = text.replace(old, new)

    text = text.replace("['", "").replace("']", "")
    text = text.replace("', '", ", ")
    text = text.replace("[", "").replace("]", "")

    while "  " in text:
        text = text.replace("  ", " ")

    return normalize_generated_text(text.strip())


def build_document_improvements_from_result(result):
    """
    Формирует безопасный список доработок документа.
    Не использует LLM-рекомендации по лечению.
    """
    missing_sections = result.get("missing_sections", []) or []
    risks = result.get("risks", []) or []

    items = []

    for section in missing_sections:
        section_label = humanize_section(str(section))
        items.append(f"Добавить или уточнить раздел «{section_label}» в медицинском документе.")

    for risk in risks:
        risk_text = str(risk).lower()

        if "аллерг" in risk_text:
            items.append("Добавить сведения об аллергиях или явно указать, что аллергии не выявлены.")
        elif "противопоказ" in risk_text:
            items.append("Добавить сведения о противопоказаниях или явно указать их отсутствие.")
        elif "коротк" in risk_text:
            items.append("Расширить документ: добавить анамнез, объективный осмотр, обоснование диагноза и план наблюдения.")
        else:
            items.append(f"Уточнить пункт: {risk}")

    if not items:
        items.append("Проверить полноту документа и убедиться, что ключевые разделы заполнены.")

    # Убираем дубли, сохраняя порядок
    unique_items = []
    seen = set()

    for item in items:
        if item not in seen:
            unique_items.append(item)
            seen.add(item)

    return unique_items[:6]


def build_doctor_questions_from_result(result):
    """
    Формирует вопросы для обсуждения с врачом.
    Не даёт медицинских назначений.
    """
    missing_sections = result.get("missing_sections", []) or []
    risks = result.get("risks", []) or []

    questions = []

    missing_lower = [str(item).lower() for item in missing_sections]
    risks_lower = [str(item).lower() for item in risks]

    if any("objective" in item or "объектив" in item for item in missing_lower):
        questions.append("Нужно ли добавить в документ раздел «Объективный осмотр»?")

    if any("history" in item or "анамнез" in item for item in missing_lower):
        questions.append("Нужно ли подробнее описать анамнез в документе?")

    if any("diagnosis" in item or "диагноз" in item for item in missing_lower):
        questions.append("Нужно ли уточнить или подробнее обосновать диагноз?")

    if any("recommend" in item or "рекомендац" in item for item in missing_lower):
        questions.append("Какие рекомендации должны быть добавлены в документ?")

    if any("follow" in item or "наблюден" in item or "контроль" in item for item in missing_lower):
        questions.append("Нужно ли добавить план наблюдения или контрольного обращения?")

    if any("противопоказ" in item for item in risks_lower):
        questions.append("Есть ли противопоказания, которые нужно явно указать в документе?")

    if any("аллерг" in item for item in risks_lower):
        questions.append("Есть ли сведения об аллергиях, которые нужно добавить в документ?")

    if any("коротк" in item for item in risks_lower):
        questions.append("Какие разделы стоит расширить, чтобы документ был достаточно полным?")

    if not questions:
        questions.append("Что ещё стоит уточнить у врача по этому документу?")

    # Убираем дубли, сохраняя порядок
    unique_questions = []
    seen = set()

    for question in questions:
        if question not in seen:
            unique_questions.append(question)
            seen.add(question)

    return unique_questions[:6]

def render_recommendation(rec: str) -> str:
    if rec.startswith("ADD_MISSING_SECTIONS:"):
        raw = rec.replace("ADD_MISSING_SECTIONS:", "").strip()
        sections = [humanize_section(x.strip()) for x in raw.split(",") if x.strip()]
        return "Уточнить или добавить разделы в документе: " + ", ".join(sections)

    if rec == "RAG_GROUNDED":
        return "Разбор выполнен с использованием чек-листа полноты документа."

    return clean_text(rec)


def score_status(score: float):
    if score >= 0.85:
        return "Документ выглядит полным", "🟢", "#10b981", "#ecfdf5", "#6ee7b7", "Документ выглядит достаточно полным для обсуждения с врачом."
    if score >= 0.65:
        return "Есть что уточнить", "🟡", "#f59e0b", "#fffbeb", "#fbbf24", "В документе есть разделы, которые стоит уточнить перед обсуждением с врачом."
    return "Документ неполный", "🔴", "#ef4444", "#fef2f2", "#fca5a5", "Документ выглядит неполным: стоит уточнить ключевые разделы у врача."


def save_support_message(message: str) -> None:
    SUPPORT_FILE.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "message": message.strip(),
        "status": "new",
    }

    with SUPPORT_FILE.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False) + "\n")

def append_jsonl(file_path: Path, payload: dict) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)

    with file_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def track_event(event_name: str, payload=None) -> None:
    event = {
        "event": event_name,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "payload": payload or {},
    }

    append_jsonl(ANALYTICS_FILE, event)

def fix_mixed_cyrillic_text(value):
    """
    Исправляет случайные латинские буквы внутри русских слов.
    Например: аллерgия -> аллергия, aллергия -> аллергия.
    Английские слова типа RAG, LLM, JSON не трогает.
    """
    if not isinstance(value, str):
        return value

    latin_to_cyrillic = {
        # похожие по написанию
        "a": "а", "A": "А",
        "e": "е", "E": "Е",
        "o": "о", "O": "О",
        "p": "р", "P": "Р",
        "c": "с", "C": "С",
        "x": "х", "X": "Х",
        "y": "у", "Y": "У",
        "k": "к", "K": "К",
        "m": "м", "M": "М",
        "h": "н", "H": "Н",
        "t": "т", "T": "Т",

        # частые случайные подмешивания/транслит внутри русских слов
        "g": "г", "G": "Г",
        "r": "р", "R": "Р",
        "n": "н", "N": "Н",
        "u": "и", "U": "И",
        "i": "и", "I": "И",
        "l": "л", "L": "Л",
        "d": "д", "D": "Д",
        "v": "в", "V": "В",
        "s": "с", "S": "С",
        "z": "з", "Z": "З",
        "f": "ф", "F": "Ф",
    }

    cyrillic_re = re.compile(r"[А-Яа-яЁё]")
    latin_re = re.compile(r"[A-Za-z]")
    word_re = re.compile(r"[A-Za-zА-Яа-яЁё]+")

    def fix_word(match):
        word = match.group(0)

        # Исправляем только смешанные слова, где есть и кириллица, и латиница.
        # Это защищает RAG, LLM, FastAPI, JSON и другие английские термины.
        if cyrillic_re.search(word) and latin_re.search(word):
            return "".join(latin_to_cyrillic.get(ch, ch) for ch in word)

        return word

    return word_re.sub(fix_word, value)


def fix_mixed_cyrillic_payload(payload):
    """
    Рекурсивно чистит строки внутри dict/list результата AI.
    """
    if isinstance(payload, dict):
        return {
            key: fix_mixed_cyrillic_payload(value)
            for key, value in payload.items()
        }

    if isinstance(payload, list):
        return [fix_mixed_cyrillic_payload(item) for item in payload]

    if isinstance(payload, str):
        return fix_mixed_cyrillic_text(payload)

    return payload

def normalize_ai_russian_text(value):
    """
    Переводит служебные английские термины, которые иногда проскакивают в AI-ответе.
    Например: complains, complaint, anamnes, diagnosis, recommendations, guideline-sources.
    """
    if not isinstance(value, str):
        return value

    replacements = [
        (r"\bPatient\s+complains\s+of\b", "Пациент жалуется на"),
        (r"\bPatient\s+complains\b", "Пациент жалуется"),
        (r"\bcomplains\s+of\b", "жалуется на"),
        (r"\bcomplains\b", "жалуется"),

        (r"\bcomplaint\b", "жалобы пациента"),
        (r"\bcomplaints\b", "жалобы пациента"),
        (r"\banamnesis\b", "анамнез"),
        (r"\banamnes\b", "анамнез"),
        (r"\bdiagnosis\b", "диагноз"),
        (r"\brecommendations\b", "рекомендации"),
        (r"\brecommendation\b", "рекомендация"),

        (r"\btreatment\s+plan\b", "план лечения"),
        (r"\bplan\s+of\s+treatment\b", "план лечения"),
        (r"\bmonitoring\s+plan\b", "план наблюдения"),
        (r"\bfollow[- ]?up\s+plan\b", "план наблюдения"),
        (r"\bcontrol\s+plan\b", "план контроля"),

        (r"\bmissing\s+sections\b", "недостающие разделы"),
        (r"\brisks\b", "риски"),
        (r"\brisk\b", "риск"),
        (r"\bquality\s+score\b", "оценка качества"),

        (r"\bguideline[- ]sources\b", "источников клинических рекомендаций"),
        (r"\bguideline\s+sources\b", "источников клинических рекомендаций"),
        (r"\bguidelines\b", "клинические рекомендации"),
        (r"\bguideline\b", "клиническая рекомендация"),

        (r"\bNo\s+guideline[- ]sources\b", "Нет источников клинических рекомендаций"),
        (r"\bNo\s+guidelines\b", "Нет клинических рекомендаций"),
        (r"\bNo\s+sources\b", "Нет источников"),

        (r"\bobjective\s+examination\b", "объективный осмотр"),
        (r"\bphysical\s+examination\b", "объективный осмотр"),
        (r"\bcontraindications\b", "противопоказания"),
        (r"\ballergies\b", "аллергии"),
        (r"\ballergy\b", "аллергия"),
    ]

    for pattern, replacement in replacements:
        value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)

    return value


def normalize_ai_russian_payload(payload):
    """
    Рекурсивно нормализует строки внутри dict/list результата AI.
    """
    if isinstance(payload, dict):
        return {
            key: normalize_ai_russian_payload(value)
            for key, value in payload.items()
        }

    if isinstance(payload, list):
        return [normalize_ai_russian_payload(item) for item in payload]

    if isinstance(payload, str):
        return normalize_ai_russian_text(payload)

    return payload

def final_polish_ai_text(value):
    """
    Финальная чистка текста перед выводом:
    - исправляет фразы про клинические рекомендации;
    - приводит список после "Что требует внимания:" к нормальному виду;
    - убирает заглавные буквы после запятой/точки с запятой внутри списков.
    """
    if not isinstance(value, str):
        return value

    value = value.strip()

    # Исправляем кривые варианты про guideline / sources
    guideline_patterns = [
        r"Нет\s+клиническ\w*\s+рекомендаци\w*[-\s]*источников",
        r"Нет\s+клинической\s+рекомендации\s+источников",
        r"Нет\s+клиническая\s+рекомендация[-\s]*источников",
        r"Нет\s+клинические\s+рекомендации[-\s]*источников",
        r"Нет\s+источников\s+клинических\s+рекомендаций",
        r"Нет\s+guideline[-\s]*sources",
        r"No\s+guideline[-\s]*sources",
        r"No\s+guidelines",
        r"guideline[-\s]*sources",
    ]

    for pattern in guideline_patterns:
        value = re.sub(
            pattern,
            "нет клинических рекомендаций",
            value,
            flags=re.IGNORECASE,
        )

    # Если фраза стоит в начале предложения — делаем первую букву заглавной
    value = re.sub(
        r"(^|[.!?]\s+)нет клинических рекомендаций",
        lambda m: m.group(1) + "Нет клинических рекомендаций",
        value,
        flags=re.IGNORECASE,
    )

    # После "Что требует внимания:" делаем список аккуратным:
    # Что требует внимания: Не указаны противопоказания, Не указана информация...
    # -> Что требует внимания: не указаны противопоказания; не указана информация...
    def polish_risks(match):
        prefix = match.group(1)
        body = match.group(2).strip()

        # не захватываем следующие смысловые блоки
        stop_words = [
            "Полнота документа",
            "Каких разделов не хватает",
            "Что уточнить у врача",
            "Что уточнить у врача",
        ]

        tail = ""
        for stop in stop_words:
            pos = body.find(stop)
            if pos != -1:
                tail = " " + body[pos:]
                body = body[:pos].strip()
                break

        parts = [p.strip() for p in re.split(r"[,;]", body) if p.strip()]

        normalized = []
        for part in parts:
            if part and re.match(r"[А-ЯЁ]", part[0]):
                part = part[0].lower() + part[1:]
            normalized.append(part)

        return prefix + "; ".join(normalized) + tail

    value = re.sub(
        r"(Что требует внимания:\s*)([^.]+)",
        polish_risks,
        value,
        flags=re.IGNORECASE,
    )

    # После запятой/точки с запятой внутри фразы убираем лишнюю заглавную букву:
    # ", Не указана" -> ", не указана"
    value = re.sub(
        r"([,;]\s+)([А-ЯЁ])",
        lambda m: m.group(1) + m.group(2).lower(),
        value,
    )

    # Исправляем частые остатки
    value = value.replace("клиническая рекомендация-источников", "клинических рекомендаций")
    value = value.replace("клинической рекомендации источников", "клинических рекомендаций")
    value = value.replace("клинические рекомендации-источников", "клинических рекомендаций")

    # Чистим пробелы перед пунктуацией и двойные пробелы
    value = re.sub(r"\s+([,.!?;:])", r"\1", value)
    value = re.sub(r"\s{2,}", " ", value)

    return value.strip()


def final_polish_ai_payload(payload):
    if isinstance(payload, dict):
        return {key: final_polish_ai_payload(value) for key, value in payload.items()}

    if isinstance(payload, list):
        return [final_polish_ai_payload(item) for item in payload]

    if isinstance(payload, str):
        return final_polish_ai_text(payload)

    return payload

def enforce_documentation_only_payload(result, report_text=""):
    """
    Финальный защитный слой:
    - убирает английские служебные слова из русского ответа;
    - запрещает лечебные назначения и дозировки;
    - превращает рекомендации в советы по доработке документации.
    """
    if not isinstance(result, dict):
        return result

    def clean_text(value):
        if not isinstance(value, str):
            return value

        text_value = value.strip()

        replacements = [
            (r"\bPatient\s+complaining\s+of\b", "Пациент жалуется на"),
            (r"\bPatient\s+complains\s+of\b", "Пациент жалуется на"),
            (r"\bPatient\s+complaining\b", "Пациент жалуется"),
            (r"\bPatient\s+complains\b", "Пациент жалуется"),
            (r"\bcomplaining\s+of\b", "жалуется на"),
            (r"\bcomplains\s+of\b", "жалуется на"),
            (r"\bcomplaining\b", "жалуется"),
            (r"\bcomplains\b", "жалуется"),
            (r"\bcomplaint\b", "жалобы пациента"),
            (r"\bcomplaints\b", "жалобы пациента"),
            (r"\banamnesis\b", "анамнез"),
            (r"\banamnes\b", "анамнез"),
            (r"\bdiagnosis\b", "диагноз"),
            (r"\brecommendations\b", "рекомендации"),
            (r"\brecommendation\b", "рекомендация"),
            (r"\bguideline[-\s]*sources\b", "клинических рекомендаций"),
            (r"\bNo\s+guideline[-\s]*sources\b", "Нет клинических рекомендаций"),
            (r"\bNo\s+guidelines\b", "Нет клинических рекомендаций"),
            (r"\brisks\b", "риски"),
            (r"\brisk\b", "риск"),
        ]

        for pattern, replacement in replacements:
            text_value = re.sub(pattern, replacement, text_value, flags=re.IGNORECASE)

        # Исправляем кривые варианты фразы про клинические рекомендации
        guideline_patterns = [
            r"Нет\s+клиническ\w*\s+рекомендаци\w*[-\s]*источников",
            r"Нет\s+клинической\s+рекомендации\s+источников",
            r"Нет\s+клиническая\s+рекомендация[-\s]*источников",
            r"Нет\s+клинические\s+рекомендации[-\s]*источников",
            r"клиническая\s+рекомендация[-\s]*источников",
            r"клинической\s+рекомендации\s+источников",
        ]

        for pattern in guideline_patterns:
            text_value = re.sub(
                pattern,
                "Нет клинических рекомендаций",
                text_value,
                flags=re.IGNORECASE,
            )

        # Запрещаем лечебные назначения, дозировки и бытовые советы от модели
        unsafe_patterns = [
            r"(?:Рекомендуется|Рекомендуем|Пациенту необходимо|Пациенту следует|Следует|Нужно|Принимайте|Принять|Пейте|Выпить|Назначить|Назначьте)[^.]*?(?:таблет|капсул|мг|мл|дозировк|раза?\s+в\s+день|нимесулид|активированн\w+\s+уг\w+|алкогол|обед|ед[ауы]|диет|физическ\w+\s+активност)[^.]*\.?",
            r"(?:до|после)\s+(?:еды|обеда|при[её]ма пищи)[^.]*\.?",
            r"\b\d+\s*[-–]\s*\d+\s*(?:таблет|капсул)[^.]*\.?",
        ]

        for pattern in unsafe_patterns:
            text_value = re.sub(
                pattern,
                "Уточнить назначения, дозировки, противопоказания и ограничения в тексте заключения; сервис не назначает лечение.",
                text_value,
                flags=re.IGNORECASE,
            )

        # После "Что требует внимания:" делаем список аккуратным
        def polish_risks(match):
            prefix = match.group(1)
            body = match.group(2).strip()
            parts = [p.strip() for p in re.split(r"[,;]", body) if p.strip()]

            if len(parts) <= 1:
                return match.group(0)

            normalized = []
            for part in parts:
                if part and re.match(r"[А-ЯЁ]", part[0]):
                    part = part[0].lower() + part[1:]
                normalized.append(part)

            return prefix + "; ".join(normalized)

        text_value = re.sub(
            r"(Что требует внимания:\s*)([^.]+)",
            polish_risks,
            text_value,
            flags=re.IGNORECASE,
        )

        text_value = re.sub(r"([,;]\s+)([А-ЯЁ])", lambda m: m.group(1) + m.group(2).lower(), text_value)
        text_value = re.sub(r"\s+([,.!?;:])", r"\1", text_value)
        text_value = re.sub(r"\s{2,}", " ", text_value)

        return text_value.strip()

    def clean_recursive(value):
        if isinstance(value, dict):
            return {key: clean_recursive(item) for key, item in value.items()}
        if isinstance(value, list):
            return [clean_recursive(item) for item in value]
        if isinstance(value, str):
            return clean_text(value)
        return value

    result = clean_recursive(result)

    missing_sections = result.get("missing_sections", [])
    risks = result.get("risks", [])

    if not isinstance(missing_sections, list):
        missing_sections = []

    if not isinstance(risks, list):
        risks = []

    missing_clean = [str(item).strip().lower() for item in missing_sections if str(item).strip()]
    risks_clean = [str(item).strip() for item in risks if str(item).strip()]

    safe_recommendations = []

    if missing_clean:
        safe_recommendations.append(
            "Добавить недостающие разделы заключения: " + ", ".join(missing_clean) + "."
        )

    for risk in risks_clean:
        risk_lower = risk.lower()

        if "аллерг" in risk_lower:
            safe_recommendations.append(
                "Указать сведения об аллергиях или явно отметить, что аллергии не выявлены."
            )
        elif "противопоказ" in risk_lower:
            safe_recommendations.append(
                "Указать противопоказания или явно отметить их отсутствие."
            )
        elif "коротк" in risk_lower:
            safe_recommendations.append(
                "Расширить заключение: добавить анамнез, объективный осмотр, обоснование диагноза и план наблюдения."
            )

    if not safe_recommendations:
        safe_recommendations.append(
            "Проверить полноту заключения и убедиться, что все обязательные разделы заполнены."
        )

    # Делаем краткое резюме безопасным: без назначений и дозировок
    summary = "Заключение требует проверки полноты и структуры."

    if risks_clean:
        risks_text = "; ".join(
            risk[0].lower() + risk[1:] if risk and re.match(r"[А-ЯЁ]", risk[0]) else risk
            for risk in risks_clean
        )
        summary += " Что требует внимания: " + risks_text + "."

    if missing_clean:
        summary += " Каких разделов не хватает: " + ", ".join(missing_clean) + "."

    summary += " Сервис оценивает качество документации и не назначает лечение."

    summary_keys = [
        "summary",
        "short_summary",
        "brief_summary",
        "ai_summary",
        "llm_summary",
    ]

    for key in summary_keys:
        if key in result:
            result[key] = summary

    recommendation_keys = [
        "recommendations",
        "recommendations_for_improvement",
        "what_to_improve",
        "improvements",
        "improvement_recommendations",
        "next_steps",
    ]

    for key in recommendation_keys:
        if key in result:
            result[key] = safe_recommendations

    hint_keys = [
        "doctor_hint",
        "physician_hint",
        "clinical_hint",
        "hint_for_doctor",
    ]

    doctor_hint = (
        "Проверьте полноту заключения: добавьте недостающие разделы, уточните противопоказания, "
        "аллергии и план наблюдения. Сервис не формирует назначения лечения."
    )

    for key in hint_keys:
        if key in result:
            result[key] = doctor_hint

    return result

def strict_russian_document_text(value, field_name=""):
    """
    Универсальный финальный фильтр AI-ответа:
    - заменяет частые английские медицинские/служебные слова;
    - удаляет оставшиеся латинские слова из русских предложений;
    - если фраза похожа на лечебное назначение, переписывает её как доработку документации;
    - не трогает разрешённые технические термины: AI, RAG, LLM, JSON, API.
    """
    if not isinstance(value, str):
        return value

    text_value = value.strip()

    allowed_latin = {
        "AI", "RAG", "LLM", "JSON", "API", "FastAPI", "Streamlit", "Ollama"
    }

    replacements = [
        # Частые английские фразы от LLM
        (r"\bPatient\s+complaining\s+of\b", "Пациент жалуется на"),
        (r"\bPatient\s+complains\s+of\b", "Пациент жалуется на"),
        (r"\bPatient\s+complaining\b", "Пациент жалуется"),
        (r"\bPatient\s+complains\b", "Пациент жалуется"),
        (r"\bcomplaining\s+of\b", "жалуется на"),
        (r"\bcomplains\s+of\b", "жалуется на"),
        (r"\bcomplaining\b", "жалуется"),
        (r"\bcomplains\b", "жалуется"),

        # Разделы медицинского заключения
        (r"\bcomplaints\b", "жалобы пациента"),
        (r"\bcomplaint\b", "жалобы пациента"),
        (r"\banamnesis\b", "анамнез"),
        (r"\banamnes\b", "анамнез"),
        (r"\bdiagnosis\b", "диагноз"),
        (r"\bobjective\s+examination\b", "объективный осмотр"),
        (r"\bphysical\s+examination\b", "объективный осмотр"),
        (r"\btreatment\s+plan\b", "план лечения"),
        (r"\bmonitoring\s+plan\b", "план наблюдения"),
        (r"\bfollow[- ]?up\s+plan\b", "план наблюдения"),
        (r"\brecommendations\b", "рекомендации"),
        (r"\brecommendation\b", "рекомендация"),

        # Служебные термины
        (r"\bmissing\s+sections\b", "недостающие разделы"),
        (r"\bquality\s+score\b", "оценка качества"),
        (r"\brisks\b", "риски"),
        (r"\brisk\b", "риск"),

        # Клинические рекомендации
        (r"\bNo\s+guideline[- ]?sources\b", "Нет клинических рекомендаций"),
        (r"\bNo\s+guidelines\b", "Нет клинических рекомендаций"),
        (r"\bguideline[- ]?sources\b", "клинические рекомендации"),
        (r"\bguidelines\b", "клинические рекомендации"),
        (r"\bguideline\b", "клиническая рекомендация"),

        # Частые глаголы, которые всплывают в рекомендациях
        (r"\bConduct\b", "провести"),
        (r"\bconduct\b", "провести"),
        (r"\bPerform\b", "провести"),
        (r"\bperform\b", "провести"),
        (r"\bAssess\b", "оценить"),
        (r"\bassess\b", "оценить"),
        (r"\bReview\b", "проверить"),
        (r"\breview\b", "проверить"),
        (r"\bCheck\b", "проверить"),
        (r"\bcheck\b", "проверить"),
        (r"\bDocument\b", "описать"),
        (r"\bdocument\b", "описать"),
    ]

    for pattern, replacement in replacements:
        text_value = re.sub(pattern, replacement, text_value, flags=re.IGNORECASE)

    # Чиним кривые варианты про рекомендации
    guideline_bad_patterns = [
        r"Нет\s+клиническ\w*\s+рекомендаци\w*[-\s]*источников",
        r"Нет\s+клинической\s+рекомендации\s+источников",
        r"Нет\s+клиническая\s+рекомендация[-\s]*источников",
        r"Нет\s+клинические\s+рекомендации[-\s]*источников",
        r"клиническая\s+рекомендация[-\s]*источников",
        r"клинической\s+рекомендации\s+источников",
        r"клинические\s+рекомендации[-\s]*источников",
    ]

    for pattern in guideline_bad_patterns:
        text_value = re.sub(
            pattern,
            "Нет клинических рекомендаций",
            text_value,
            flags=re.IGNORECASE,
        )

    # Переписываем любые назначения/дозировки как доработку документации
    unsafe_medical_patterns = [
        r"(?:принимайте|примите|пейте|выпейте|назначить|назначьте|рекомендуется принять|пациенту следует принять|пациенту необходимо принять)[^.]*\.?",
        r"(?:\d+\s*[-–]\s*\d+|\d+)\s*(?:таблетк\w*|капсул\w*|мг|мл)[^.]*\.?",
        r"(?:до|после)\s+(?:еды|обеда|при[её]ма пищи)[^.]*\.?",
        r"(?:провести|нужно провести|следует провести)\s+более\s+детальное\s+медицинское\s+обследование[^.]*\.?",
    ]

    for pattern in unsafe_medical_patterns:
        text_value = re.sub(
            pattern,
            "Уточнить и описать в заключении данные обследования, противопоказания, аллергии, обоснование диагноза и план наблюдения.",
            text_value,
            flags=re.IGNORECASE,
        )

    # Если в русском предложении всё ещё остались латинские слова — удаляем их,
    # кроме разрешённых технических терминов.
    def remove_bad_latin(match):
        token = match.group(0)
        if token in allowed_latin or token.upper() in allowed_latin:
            return token
        return ""

    # Удаляем только если строка содержит кириллицу.
    if re.search(r"[А-Яа-яЁё]", text_value):
        text_value = re.sub(r"\b[A-Za-z][A-Za-z\-]*\b", remove_bad_latin, text_value)

    # После "Что требует внимания:" делаем список аккуратным
    def polish_risks(match):
        prefix = match.group(1)
        body = match.group(2).strip()

        parts = [p.strip() for p in re.split(r"[,;]", body) if p.strip()]
        if len(parts) <= 1:
            return match.group(0)

        clean_parts = []
        for part in parts:
            if part and re.match(r"[А-ЯЁ]", part[0]):
                part = part[0].lower() + part[1:]
            clean_parts.append(part)

        return prefix + "; ".join(clean_parts)

    text_value = re.sub(
        r"(Что требует внимания:\s*)([^.]+)",
        polish_risks,
        text_value,
        flags=re.IGNORECASE,
    )

    # Убираем заглавные буквы после запятой/точки с запятой внутри списков
    text_value = re.sub(
        r"([,;]\s+)([А-ЯЁ])",
        lambda m: m.group(1) + m.group(2).lower(),
        text_value,
    )

    # Чистим пробелы
    text_value = re.sub(r"\s+([,.!?;:])", r"\1", text_value)
    text_value = re.sub(r"\s{2,}", " ", text_value)
    text_value = text_value.replace(" ,", ",").replace(" .", ".")

    # Если после удаления английских слов фраза стала пустой или странной
    if len(text_value.strip()) < 3:
        return "Уточнить и дополнить соответствующий раздел медицинского заключения."

    return text_value.strip()


def strict_russian_document_payload(payload, field_name=""):
    """
    Рекурсивно чистит весь JSON-ответ AI.
    """
    if isinstance(payload, dict):
        return {
            key: strict_russian_document_payload(value, key)
            for key, value in payload.items()
        }

    if isinstance(payload, list):
        return [
            strict_russian_document_payload(item, field_name)
            for item in payload
        ]

    if isinstance(payload, str):
        return strict_russian_document_text(payload, field_name)

    return payload

def has_document_issues(result):
    missing_sections = result.get("missing_sections", []) or []
    risks = result.get("risks", []) or []

    return bool(missing_sections or risks)


def build_safe_document_summary(result):
    missing_sections = result.get("missing_sections", []) or []
    risks = result.get("risks", []) or []

    if not missing_sections and not risks:
        return (
            "Документ выглядит достаточно полным для информационного разбора. "
            "Существенных недостающих разделов или явных замечаний по чек-листу не обнаружено."
        )

    parts = ["Документ содержит медицинские сведения, но требует уточнения перед обсуждением с врачом."]

    if missing_sections:
        readable_sections = [humanize_section(str(item)) for item in missing_sections]
        parts.append("Не хватает разделов: " + ", ".join(readable_sections) + ".")

    if risks:
        readable_risks = [clean_text(str(item)) for item in risks]
        parts.append("Что требует внимания: " + "; ".join(readable_risks) + ".")

    return " ".join(parts)


def build_safe_attention_reason(result):
    missing_sections = result.get("missing_sections", []) or []
    risks = result.get("risks", []) or []

    reasons = []

    if missing_sections:
        readable_sections = [humanize_section(str(item)) for item in missing_sections]
        reasons.append(
            "в документе отсутствуют или требуют уточнения разделы: "
            + ", ".join(readable_sections)
        )

    if risks:
        readable_risks = [clean_text(str(item)) for item in risks]
        reasons.append(
            "есть пункты, которые стоит проверить перед обсуждением с врачом: "
            + "; ".join(readable_risks)
        )

    if not reasons:
        return "По чек-листу полноты существенных замечаний не обнаружено."

    text_value = "Стоит обратить внимание, потому что " + "; ".join(reasons) + "."

    text_value = re.sub(
        r"([,;]\s+)([А-ЯЁ])",
        lambda m: m.group(1) + m.group(2).lower(),
        text_value,
    )

    return text_value


def build_document_improvements_from_result(result):
    missing_sections = result.get("missing_sections", []) or []
    risks = result.get("risks", []) or []

    items = []

    for section in missing_sections:
        section_label = humanize_section(str(section))
        items.append(f"Добавить или уточнить раздел «{section_label}» в медицинском документе.")

    for risk in risks:
        risk_text = str(risk).lower()

        if "аллерг" in risk_text:
            items.append("Указать сведения об аллергиях или явно отметить, что аллергии не выявлены.")
        elif "противопоказ" in risk_text:
            items.append("Указать противопоказания или явно отметить их отсутствие.")
        elif "коротк" in risk_text:
            items.append("Расширить документ: добавить анамнез, объективный осмотр, обоснование диагноза и план наблюдения.")
        else:
            items.append(f"Уточнить пункт: {clean_text(str(risk))}")

    unique_items = []
    seen = set()

    for item in items:
        if item not in seen:
            unique_items.append(item)
            seen.add(item)

    return unique_items[:6]


def build_doctor_questions_from_result(result):
    missing_sections = result.get("missing_sections", []) or []
    risks = result.get("risks", []) or []

    questions = []

    missing_lower = [str(item).lower() for item in missing_sections]
    risks_lower = [str(item).lower() for item in risks]

    if any("objective" in item or "объектив" in item for item in missing_lower):
        questions.append("Нужно ли добавить в документ раздел «Объективный осмотр»?")

    if any("history" in item or "анамнез" in item for item in missing_lower):
        questions.append("Нужно ли подробнее описать анамнез в документе?")

    if any("diagnosis" in item or "диагноз" in item for item in missing_lower):
        questions.append("Нужно ли уточнить или подробнее обосновать диагноз?")

    if any("recommend" in item or "рекомендац" in item for item in missing_lower):
        questions.append("Какие рекомендации должны быть добавлены в документ?")

    if any("follow" in item or "наблюден" in item or "контроль" in item for item in missing_lower):
        questions.append("Нужно ли добавить план наблюдения или контрольного обращения?")

    if any("противопоказ" in item for item in risks_lower):
        questions.append("Есть ли противопоказания, которые нужно явно указать в документе?")

    if any("аллерг" in item for item in risks_lower):
        questions.append("Есть ли сведения об аллергиях, которые нужно добавить в документ?")

    if any("коротк" in item for item in risks_lower):
        questions.append("Какие разделы стоит расширить, чтобы документ был достаточно полным?")

    unique_questions = []
    seen = set()

    for question in questions:
        if question not in seen:
            unique_questions.append(question)
            seen.add(question)

    return unique_questions[:6]

st.set_page_config(
    page_title="AI-помощник по медицинским документам",
    page_icon="🩺",
    layout="wide",
)


components.html(
    """
    <script>
    (function () {
        if (window.parent.location.hash) {
            window.parent.history.replaceState(
                null,
                "",
                window.parent.location.pathname + window.parent.location.search
            );
        }
    })();
    </script>
    """,
    height=0,
)

st.markdown(
    """
    <style>
    #MainMenu, footer, header, [data-testid="stToolbar"] {
        visibility: hidden;
        height: 0%;
    }

    .stApp {
        background:
            radial-gradient(circle at 8% 10%, rgba(14,165,233,0.25), transparent 26%),
            radial-gradient(circle at 90% 12%, rgba(16,185,129,0.26), transparent 28%),
            linear-gradient(135deg, #dff4ff 0%, #f7fbff 46%, #e8fff7 100%);
    }

    .block-container {
        padding-top: 1.1rem;
        padding-bottom: 3rem;
        max-width: 1180px;
    }

    @keyframes fadeInUp {
        from { opacity: 0; transform: translateY(14px); }
        to { opacity: 1; transform: translateY(0); }
    }

    @keyframes pulseBlue {
        0% { box-shadow: 0 0 0 0 rgba(14,165,233,0.42); }
        70% { box-shadow: 0 0 0 16px rgba(14,165,233,0); }
        100% { box-shadow: 0 0 0 0 rgba(14,165,233,0); }
    }

    .support-row {
        display: flex;
        justify-content: flex-end;
        margin-bottom: 12px;
    }

    .hero {
        display: grid;
        grid-template-columns: 1.45fr 0.75fr;
        gap: 28px;
        padding: 38px 42px;
        border-radius: 34px;
        background: rgba(255,255,255,0.96);
        border: 1px solid #bae6fd;
        box-shadow: 0 28px 70px rgba(14,165,233,0.16);
        margin-bottom: 34px;
        animation: fadeInUp 0.65s ease;
        overflow: hidden;
    }

    .main-title {
        font-size: 50px;
        font-weight: 950;
        letter-spacing: -1.5px;
        color: #0f172a;
        margin-bottom: 14px;
        line-height: 1.05;
    }

    .subtitle {
        font-size: 18px;
        color: #475569;
        line-height: 1.65;
        max-width: 820px;
    }

    .stack-label {
        font-size: 14px;
        color: #475569;
        margin-top: 20px;
        margin-bottom: 8px;
        font-weight: 800;
    }

    .tag {
        display: inline-block;
        padding: 9px 16px;
        margin: 8px 8px 0 0;
        border-radius: 999px;
        background: rgba(255,255,255,0.95);
        border: 1px solid #cbd5e1;
        color: #334155;
        box-shadow: 0 10px 24px rgba(15,23,42,0.08);
        font-weight: 800;
    }

    .ai-card {
        min-height: 230px;
        border-radius: 30px;
        padding: 26px;
        background:
            radial-gradient(circle at top right, rgba(16,185,129,0.22), transparent 34%),
            linear-gradient(135deg, #ecfeff 0%, #eff6ff 100%);
        border: 1px solid #bae6fd;
        box-shadow: inset 0 0 0 1px rgba(255,255,255,0.7), 0 18px 42px rgba(14,165,233,0.14);
        display: flex;
        flex-direction: column;
        justify-content: space-between;
    }

    .ai-card-icon {
        font-size: 46px;
        margin-bottom: 10px;
    }

    .ai-card-title {
        font-size: 24px;
        font-weight: 950;
        color: #0f172a;
        margin-bottom: 8px;
    }

    .ai-card-text {
        color: #475569;
        font-size: 15px;
        line-height: 1.55;
    }

    .ai-card-mini {
        margin-top: 18px;
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
    }

    .mini-pill {
        padding: 7px 10px;
        border-radius: 999px;
        background: rgba(255,255,255,0.9);
        border: 1px solid #bfdbfe;
        color: #0369a1;
        font-weight: 800;
        font-size: 13px;
    }

    .metric-card {
        padding: 24px;
        border-radius: 26px;
        background: rgba(255,255,255,0.98);
        border: 1px solid #dbe4f0;
        box-shadow: 0 16px 36px rgba(15,23,42,0.09);
    }

    .metric-label {
        color: #64748b;
        font-size: 14px;
        font-weight: 700;
        margin-bottom: 8px;
    }

    .metric-value {
        font-size: 42px;
        font-weight: 950;
        color: #0f172a;
    }

    .quality-bar-bg {
        width: 100%;
        height: 16px;
        background: #dbe4f0;
        border-radius: 999px;
        overflow: hidden;
        margin: 20px 0 10px 0;
    }

    .quality-bar-fill {
        height: 16px;
        border-radius: 999px;
    }

    .status-card {
        padding: 24px;
        border-radius: 26px;
        margin: 24px 0;
        box-shadow: 0 14px 32px rgba(15,23,42,0.08);
    }

    .status-title {
        font-size: 25px;
        font-weight: 950;
        margin-bottom: 8px;
    }

    .ai-box {
        padding: 28px;
        border-radius: 30px;
        background: linear-gradient(135deg, rgba(240,249,255,0.98) 0%, rgba(238,242,255,0.98) 100%);
        border: 1px solid #93c5fd;
        margin: 28px 0;
        box-shadow: 0 24px 56px rgba(59,130,246,0.16);
    }

    .ai-active {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 9px 16px;
        border-radius: 999px;
        background: #e0f2fe;
        border: 1px solid #38bdf8;
        color: #075985;
        font-weight: 900;
        animation: pulseBlue 2.2s infinite;
        margin-bottom: 14px;
    }

    .soft-blue, .soft-yellow, .soft-green, .soft-red, .soft-purple {
        padding: 18px;
        border-radius: 20px;
        margin-bottom: 12px;
        font-weight: 650;
    }

    .soft-blue { background: #eff6ff; border: 1px solid #93c5fd; color: #1d4ed8; }
    .soft-yellow { background: #fffbeb; border: 1px solid #fbbf24; color: #92400e; }
    .soft-green { background: #ecfdf5; border: 1px solid #6ee7b7; color: #047857; }
    .soft-red { background: #fef2f2; border: 1px solid #fca5a5; color: #b91c1c; }
    .soft-purple { background: #f5f3ff; border: 1px solid #c4b5fd; color: #5b21b6; }

    .section-title {
        font-size: 30px;
        font-weight: 950;
        margin-top: 28px;
        margin-bottom: 16px;
        color: #0f172a;
    }

    .stButton button {
        background: linear-gradient(135deg, #0ea5e9, #10b981);
        color: white;
        border-radius: 18px;
        border: none;
        min-height: 52px;
        font-weight: 900;
        box-shadow: 0 16px 36px rgba(14,165,233,0.30);
    }

    textarea {
        border-radius: 22px !important;
        background: #ffffff !important;
        border: 2px solid #7dd3fc !important;
        box-shadow: 0 18px 40px rgba(14,165,233,0.14) !important;
        font-size: 16px !important;
        line-height: 1.55 !important;
    }

    textarea:focus {
        border: 2px solid #0ea5e9 !important;
        box-shadow: 0 0 0 4px rgba(14,165,233,0.18), 0 18px 40px rgba(14,165,233,0.16) !important;
        outline: none !important;
    }

    [data-testid="stPopover"] button {
        border-radius: 999px !important;
        font-weight: 800 !important;
        border: 1px solid #cbd5e1 !important;
        background: rgba(255,255,255,0.9) !important;
        box-shadow: 0 8px 24px rgba(15,23,42,0.08) !important;
    }

    @media (max-width: 900px) {
        .hero {
            grid-template-columns: 1fr;
        }
        .main-title {
            font-size: 38px;
        }
    }
    
    /* Финальная доводка textarea: убираем серые уголки и системные рамки */
    div[data-baseweb="textarea"] {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        outline: none !important;
    }

    div[data-baseweb="textarea"] > div {
        background: #ffffff !important;
        border: 2px solid #7dd3fc !important;
        border-radius: 24px !important;
        box-shadow: 0 18px 40px rgba(14,165,233,0.14) !important;
        overflow: hidden !important;
        outline: none !important;
    }

    div[data-baseweb="textarea"]:focus-within > div {
        border: 2px solid #0ea5e9 !important;
        box-shadow: 0 0 0 4px rgba(14,165,233,0.18), 0 18px 40px rgba(14,165,233,0.16) !important;
        outline: none !important;
    }

    textarea {
        background: #ffffff !important;
        border: none !important;
        outline: none !important;
        box-shadow: none !important;
        resize: none !important;
    }

    textarea:focus,
    textarea:focus-visible,
    textarea:active {
        border: none !important;
        outline: none !important;
        box-shadow: none !important;
    }

    /* Убираем оранжевую/красную обводку у кнопок и поддержки */
    button:focus,
    button:focus-visible,
    button:active,
    [data-testid="stPopover"] button:focus,
    [data-testid="stPopover"] button:focus-visible,
    [data-testid="stPopover"] button:active {
        outline: none !important;
        border-color: #7dd3fc !important;
        box-shadow: 0 0 0 3px rgba(14,165,233,0.16) !important;
    }

    /* Поддержка: поле без красной рамки */
    [data-testid="stPopover"] div[data-baseweb="textarea"] > div {
        border: 2px solid #7dd3fc !important;
        box-shadow: none !important;
    }

    [data-testid="InputInstructions"] {
        display: none !important;
        visibility: hidden !important;
        height: 0 !important;
    }

    /* Добавляем воздуха под кнопкой проверки */
    div[data-testid="stButton"] {
        margin-bottom: 28px !important;
    }

    
    /* Убираем серые уголки именно в поле поддержки */
    [data-testid="stPopover"] div[data-baseweb="textarea"],
    [data-testid="stPopover"] div[data-baseweb="textarea"] > div,
    [data-testid="stPopover"] div[data-baseweb="base-input"],
    [data-testid="stPopover"] div[data-baseweb="base-input"] > div {
        background: #ffffff !important;
        border-radius: 24px !important;
        overflow: hidden !important;
    }

    [data-testid="stPopover"] textarea {
        background: #ffffff !important;
        border-radius: 24px !important;
    }

    [data-testid="stPopover"] div[data-baseweb="textarea"] {
        box-shadow: none !important;
        border: none !important;
    }

    
    /* УБИВАЕМ ВСЕ СЕРЫЕ УГЛЫ НАВСЕГДА */
    div[data-baseweb="textarea"],
    div[data-baseweb="textarea"] > div,
    div[data-baseweb="base-input"],
    div[data-baseweb="base-input"] > div {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
    }

    div[data-baseweb="textarea"] > div {
        background: #ffffff !important;
        border-radius: 24px !important;
        overflow: hidden !important;
    }

    textarea {
        background: #ffffff !important;
        border-radius: 24px !important;
    }

    /* Главное поле заключения — заметная medtech-рамка */
    div[data-testid="stTextArea"] div[data-baseweb="textarea"] > div {
        background: linear-gradient(135deg, #ffffff 0%, #f8fcff 100%) !important;
        border: 2px solid #38bdf8 !important;
        border-radius: 26px !important;
        box-shadow:
            0 0 0 4px rgba(14,165,233,0.08),
            0 20px 48px rgba(14,165,233,0.18) !important;
    }

    div[data-testid="stTextArea"] textarea {
        background: transparent !important;
    }

    /* самое главное — обрезаем артефакты */
    div[data-baseweb="textarea"]::before,
    div[data-baseweb="textarea"]::after {
        display: none !important;
    }


    /* ПОДНИМАЕМ ЛОАДЕР ПОД КНОПКУ */
    div[data-testid="stSpinner"] {
        margin-top: -10px !important;
        margin-bottom: 10px !important;
    }


    /* Support textarea — убираем серые углы BaseWeb */
    [data-testid="stPopover"] div[data-testid="stTextArea"] {
        background: #ffffff !important;
        border-radius: 26px !important;
        overflow: hidden !important;
    }

    [data-testid="stPopover"] div[data-baseweb="textarea"] {
        background: #ffffff !important;
        border-radius: 26px !important;
        overflow: hidden !important;
        padding: 0 !important;
        box-shadow: none !important;
    }

    [data-testid="stPopover"] div[data-baseweb="textarea"] > div {
        background: #ffffff !important;
        border-radius: 26px !important;
        border: 2px solid #0ea5e9 !important;
        overflow: hidden !important;
        box-shadow: none !important;
    }

    [data-testid="stPopover"] textarea {
        background: #ffffff !important;
        border-radius: 26px !important;
        border: none !important;
        outline: none !important;
        box-shadow: none !important;
    }

    [data-testid="stPopover"] div[data-baseweb="textarea"]::before,
    [data-testid="stPopover"] div[data-baseweb="textarea"]::after,
    [data-testid="stPopover"] div[data-baseweb="textarea"] > div::before,
    [data-testid="stPopover"] div[data-baseweb="textarea"] > div::after {
        display: none !important;
        content: none !important;
    }


    /* Финально убираем серые углы вокруг textarea */
    div[data-testid="stTextArea"],
    div[data-testid="stTextArea"] > div,
    div[data-testid="stTextArea"] div[data-baseweb="textarea"],
    div[data-testid="stTextArea"] div[data-baseweb="textarea"] > div {
        background: transparent !important;
        box-shadow: none !important;
    }

    div[data-testid="stTextArea"] div[data-baseweb="textarea"] > div {
        background: #ffffff !important;
        border: 2px solid #38bdf8 !important;
        border-radius: 24px !important;
        overflow: hidden !important;
    }

    div[data-testid="stTextArea"] textarea {
        background: #ffffff !important;
        border: none !important;
        box-shadow: none !important;
        outline: none !important;
        resize: none !important;
    }

    /* Support textarea тоже без серых углов */
    [data-testid="stPopover"] div[data-testid="stTextArea"],
    [data-testid="stPopover"] div[data-testid="stTextArea"] > div,
    [data-testid="stPopover"] div[data-baseweb="textarea"],
    [data-testid="stPopover"] div[data-baseweb="textarea"] > div {
        background: transparent !important;
        box-shadow: none !important;
    }

    [data-testid="stPopover"] div[data-baseweb="textarea"] > div {
        background: #ffffff !important;
        border: 2px solid #0ea5e9 !important;
        border-radius: 24px !important;
        overflow: hidden !important;
    }

    /* Красивый индикатор анализа справа от кнопки */
    @keyframes aiThinkingPulse {
        0% { opacity: 0.65; transform: scale(1); }
        50% { opacity: 1; transform: scale(1.02); }
        100% { opacity: 0.65; transform: scale(1); }
    }

    .thinking-card {
        min-height: 52px;
        border-radius: 18px;
        background: linear-gradient(135deg, #e0f2fe, #ecfdf5);
        border: 1px solid #67e8f9;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 900;
        color: #0369a1;
        animation: aiThinkingPulse 1.2s ease-in-out infinite;
        box-shadow: 0 14px 32px rgba(14,165,233,0.18);
    }


    /* Кнопка поддержки: одна строка, аккуратная таблетка */
    [data-testid="stPopover"] button {
        min-width: 156px !important;
        max-width: 190px !important;
        height: 48px !important;
        padding: 0 16px !important;
        border-radius: 999px !important;
        white-space: nowrap !important;
        overflow: visible !important;
    }

    [data-testid="stPopover"] button * {
        white-space: nowrap !important;
        overflow: visible !important;
        text-overflow: clip !important;
        line-height: 1.1 !important;
    }

    [data-testid="stPopover"] button p {
        white-space: nowrap !important;
        font-size: 15px !important;
        line-height: 1.1 !important;
    }

    [data-testid="stPopover"] button svg {
        flex-shrink: 0 !important;
    }



    /* compact-ui-fix */
    .main .block-container {
        padding-top: 0.9rem !important;
        padding-bottom: 2rem !important;
        max-width: 1180px !important;
    }

    h1, h2, h3 {
        margin-top: 0.15rem !important;
        margin-bottom: 0.65rem !important;
        line-height: 1.08 !important;
    }

    .stTextArea textarea {
        min-height: 165px !important;
    }

    .stButton > button {
        margin-top: 0 !important;
    }

    .element-container {
        margin-bottom: 0.35rem !important;
    }

    .stMarkdown p {
        margin-bottom: 0.45rem !important;
    }


    /* compact-safe-layout-final */
    .block-container {
        padding-top: 0.4rem !important;
        padding-bottom: 2rem !important;
        max-width: 1180px !important;
    }

    .hero {
        padding: 24px 34px !important;
        margin-bottom: 22px !important;
        gap: 22px !important;
    }

    .main-title {
        font-size: 42px !important;
        line-height: 1.05 !important;
        margin-bottom: 10px !important;
    }

    .subtitle {
        font-size: 16px !important;
        line-height: 1.45 !important;
        max-width: 780px !important;
    }

    .stack-label {
        margin-top: 14px !important;
        margin-bottom: 6px !important;
    }

    .tag {
        padding: 7px 13px !important;
        margin: 6px 6px 0 0 !important;
        font-size: 13px !important;
    }

    .ai-card {
        min-height: 190px !important;
        padding: 22px !important;
    }

    .ai-card-icon {
        font-size: 36px !important;
        margin-bottom: 6px !important;
    }

    .ai-card-title {
        font-size: 21px !important;
        margin-bottom: 6px !important;
    }

    .ai-card-text {
        font-size: 14px !important;
        line-height: 1.4 !important;
    }

    .mini-pill {
        padding: 6px 9px !important;
        font-size: 12px !important;
    }

    h3 {
        margin-top: 0.25rem !important;
        margin-bottom: 0.5rem !important;
    }

    div[data-testid="stTextArea"] textarea {
        min-height: 165px !important;
    }

    div[data-testid="stButton"] {
        margin-bottom: 8px !important;
    }

    .stButton button {
        min-height: 48px !important;
    }

    .stCaptionContainer, .stCaption {
        font-size: 13px !important;
        line-height: 1.35 !important;
    }


    /* loader-pill-fix */
    .thinking-card {
        min-height: 52px !important;
        padding: 10px 14px !important;
        border-radius: 18px !important;
        background: linear-gradient(135deg, #e0f2fe, #ecfdf5) !important;
        border: 1px solid #67e8f9 !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        font-weight: 900 !important;
        color: #0369a1 !important;
        line-height: 1.25 !important;
        text-align: center !important;
        white-space: normal !important;
        word-break: keep-all !important;
        overflow-wrap: normal !important;
        box-sizing: border-box !important;
        width: 100% !important;
    }


    /* support-submit-button-fix */
    [data-testid="stPopover"] div[data-testid="stFormSubmitButton"] button {
        background: linear-gradient(135deg, #0ea5e9, #10b981) !important;
        color: white !important;
        border: none !important;
        border-radius: 18px !important;
        min-height: 46px !important;
        padding: 0 18px !important;
        font-weight: 900 !important;
        box-shadow: 0 14px 28px rgba(14,165,233,0.28) !important;
        transition: all 0.18s ease !important;
    }

    [data-testid="stPopover"] div[data-testid="stFormSubmitButton"] button:hover {
        transform: translateY(-1px) !important;
        box-shadow: 0 18px 36px rgba(16,185,129,0.34) !important;
        color: white !important;
    }

    [data-testid="stPopover"] div[data-testid="stFormSubmitButton"] button p {
        color: white !important;
        font-weight: 900 !important;
    }


    /* support-submit-green-final */
    div[data-testid="stPopoverBody"] div[data-testid="stFormSubmitButton"] button,
    div[data-testid="stPopover"] div[data-testid="stFormSubmitButton"] button,
    div[data-testid="stFormSubmitButton"] button[kind="primary"],
    div[data-testid="stFormSubmitButton"] button {
        background: linear-gradient(135deg, #0ea5e9, #10b981) !important;
        color: #ffffff !important;
        border: none !important;
        border-radius: 18px !important;
        min-height: 46px !important;
        padding: 0 20px !important;
        font-weight: 900 !important;
        box-shadow: 0 14px 30px rgba(14,165,233,0.28) !important;
    }

    div[data-testid="stPopoverBody"] div[data-testid="stFormSubmitButton"] button:hover,
    div[data-testid="stPopover"] div[data-testid="stFormSubmitButton"] button:hover,
    div[data-testid="stFormSubmitButton"] button:hover {
        background: linear-gradient(135deg, #0284c7, #059669) !important;
        color: #ffffff !important;
        transform: translateY(-1px) !important;
        box-shadow: 0 18px 38px rgba(16,185,129,0.34) !important;
    }

    div[data-testid="stFormSubmitButton"] button p,
    div[data-testid="stFormSubmitButton"] button span,
    div[data-testid="stFormSubmitButton"] button div {
        color: #ffffff !important;
        font-weight: 900 !important;
    }


    /* support-button-font-match */
    div[data-testid="stFormSubmitButton"] button,
    div[data-testid="stFormSubmitButton"] button[kind="primary"] {
        font-size: 16px !important;
        font-weight: 900 !important;
        letter-spacing: 0 !important;
        line-height: 1.1 !important;
        font-family: inherit !important;
        color: #ffffff !important;
        text-align: center !important;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
    }

    div[data-testid="stFormSubmitButton"] button p,
    div[data-testid="stFormSubmitButton"] button span,
    div[data-testid="stFormSubmitButton"] button div {
        font-size: 16px !important;
        font-weight: 900 !important;
        letter-spacing: 0 !important;
        line-height: 1.1 !important;
        font-family: inherit !important;
        color: #ffffff !important;
        text-align: center !important;
    }


    /* support-button-font-soft-final */
    div[data-testid="stFormSubmitButton"] button,
    div[data-testid="stFormSubmitButton"] button[kind="primary"] {
        font-size: 15px !important;
        font-weight: 600 !important;
        letter-spacing: 0 !important;
        line-height: 1.2 !important;
        font-family: inherit !important;
        color: #ffffff !important;
        text-align: center !important;
    }

    div[data-testid="stFormSubmitButton"] button p,
    div[data-testid="stFormSubmitButton"] button span,
    div[data-testid="stFormSubmitButton"] button div {
        font-size: 15px !important;
        font-weight: 600 !important;
        letter-spacing: 0 !important;
        line-height: 1.2 !important;
        font-family: inherit !important;
        color: #ffffff !important;
        text-align: center !important;
    }

</style>
    """,
    unsafe_allow_html=True,
)

top_left, top_right = st.columns([5.7, 1.3])

with top_right:
    with st.popover("🛟 Поддержка"):
        st.markdown("### Задать вопрос")

        with st.form("support_form", clear_on_submit=True):
            support_question = st.text_area(
                "Опишите вопрос или проблему",
                placeholder="Например: как добавить новый медицинский стандарт?",
                height=120,
                key="support_question_input",
            )

            submitted = st.form_submit_button("Отправить вопрос", type="primary")

        if submitted:
            if support_question.strip():
                try:
                    if "save_support_message" in globals():
                        save_support_message(support_question)
                    if "track_event" in globals():
                        track_event("support_message_sent", {"message_length": len(support_question.strip())})
                except Exception:
                    pass

                st.toast("Спасибо, сообщение отправлено в поддержку")
            else:
                st.warning("Введите текст вопроса.")
st.markdown(
    """
    <div class="hero">
        <div>
            <div class="main-title">🩺 AI-помощник по медицинским документам</div>
            <div class="subtitle">
                AI-сервис помогает понять медицинский документ, проверить полноту и подготовить вопросы врачу.
                Пользователь вставляет текст заключения, а система оценивает его полноту,
                риски и соответствие медицинским рекомендациям.
            </div>
            <div class="stack-label">Технологический стек:</div>
            <div>
                <span class="tag">⚙️ FastAPI</span>
                <span class="tag">🖥️ Streamlit</span>
                <span class="tag">📚 RAG</span>
                <span class="tag">🧠 Ollama LLM</span>
                <span class="tag">🔗 Structured JSON</span>
            </div>
        </div>
        <div class="ai-card">
            <div>
                <div class="ai-card-icon">🧠🩺</div>
                <div class="ai-card-title">Разбор медицинского документа</div>
                <div class="ai-card-text">
                    Проверка медицинского заключения через правила качества,
                    внутренние рекомендации и локальную LLM.
                </div>
            </div>
            <div class="ai-card-mini">
                <span class="mini-pill">Полнота документа</span>
                <span class="mini-pill">Что требует внимания</span>
                <span class="mini-pill">Чек-лист документа</span>
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

left, right = st.columns([1.25, 1])

with left:
    st.subheader("Текст медицинского документа")

    default_text = (
        "Пациент жалуется на головную боль. "
        "Анамнез без особенностей. "
        "Диагноз: головная боль напряжения. "
        "Назначено лечение. "
        "Что уточнить у врача: отдых, контроль состояния."
    )

    report_text = st.text_area(
        "Вставьте текст заключения",
        value=default_text,
        height=170,
        label_visibility="collapsed",
    )

    button_col, loader_col = st.columns([3, 1])

    with button_col:
        analyze = st.button("Разобрать документ", type="primary", use_container_width=True)

    with loader_col:
        ai_loader = st.empty()

    st.markdown(
        """
""",
        unsafe_allow_html=True,
    )

with right:
    st.subheader("Что делает сервис")
    st.markdown(
        """
        - помогает проверить полноту документа  
        - выделяет, что требует внимания  
        - показывает недостающие разделы  
        - формирует вопросы для врача  
        - использует чек-лист полноты документа через RAG  
        - даёт информационный разбор через локальную LLM  
        """
    )
    st.caption("Информационный сервис: не ставит диагноз, не назначает и не отменяет лечение.")


if analyze:
    if len(report_text.strip()) < 20:
        st.error("Текст слишком короткий. Введите минимум 20 символов.")
    else:
        try:
            ai_loader.markdown(
                '<div class="thinking-card">🤖 AI разбирает документ...</div>',
                unsafe_allow_html=True,
            )

            request_started_at = time.time()
            response = requests.post(API_URL, json={"report_text": report_text}, timeout=180)
            response.raise_for_status()
            result = response.json()
            result = fix_mixed_cyrillic_payload(result)
            result = normalize_ai_russian_payload(result)
            result = final_polish_ai_payload(result)
            result = enforce_documentation_only_payload(result, report_text)
            result = strict_russian_document_payload(result)

            track_event(
                "review_completed",
                {
                    "quality_score": result.get("quality_score"),
                    "missing_sections_count": len(result.get("missing_sections", [])),
                    "risks_count": len(result.get("risks", [])),
                    "risks": result.get("risks", []),
                    "processing_time_sec": round(time.time() - request_started_at, 2),
                    "text_length": len(report_text),
                },
            )

            ai_loader.markdown(
                '<div class="thinking-card">✅ Разбор готов</div>',
                unsafe_allow_html=True,
            )

            st.markdown('<div id="results-anchor"></div>', unsafe_allow_html=True)

            components.html(
                """
                <script>
                setTimeout(() => {
                    const el = window.parent.document.querySelector('[id="results-anchor"]');
                    if (el) el.scrollIntoView({behavior: "smooth", block: "start"});
                }, 300);
                </script>
                """,
                height=0,
            )

            st.divider()
            st.markdown('<div class="section-title">Результаты разбора</div>', unsafe_allow_html=True)

            score = result["quality_score"]
            label, emoji, color, bg, border, status_text = score_status(score)
            score_percent = int(score * 100)

            col1, col2, col3 = st.columns(3)

            with col1:
                st.markdown(
                    f'<div class="metric-card"><div class="metric-label">Полнота документа</div><div class="metric-value">{score:.2f}</div></div>',
                    unsafe_allow_html=True,
                )

            with col2:
                st.markdown(
                    f'<div class="metric-card"><div class="metric-label">Каких разделов не хватает</div><div class="metric-value">{len(result["missing_sections"])}</div></div>',
                    unsafe_allow_html=True,
                )

            with col3:
                st.markdown(
                    f'<div class="metric-card"><div class="metric-label">Что требует внимания</div><div class="metric-value">{len(result["risks"])}</div></div>',
                    unsafe_allow_html=True,
                )

            st.markdown(
                f'<div class="quality-bar-bg"><div class="quality-bar-fill" style="width:{score_percent}%;background:{color};"></div></div>',
                unsafe_allow_html=True,
            )

            st.markdown(
                f'<div class="status-card" style="background:{bg};border:1px solid {border};">'
                f'<div class="status-title" style="color:{color};">{emoji} {label}</div>'
                f'<div style="font-size:16px;color:#334155;">{status_text}</div></div>',
                unsafe_allow_html=True,
            )

            llm = result.get("llm_review")

            st.markdown('<div class="ai-box">', unsafe_allow_html=True)
            st.markdown('<div class="ai-active">● Информационный разбор активен</div>', unsafe_allow_html=True)
            st.markdown('<div class="section-title">🤖 Информационный разбор документа</div>', unsafe_allow_html=True)

            st.markdown("#### Краткое объяснение документа")
            st.markdown(
                f'<div class="soft-purple">{clean_text(build_safe_document_summary(result))}</div>',
                unsafe_allow_html=True,
            )

            attention_title = "Почему стоит обратить внимание" if has_document_issues(result) else "Итог разбора"
            st.markdown(f"#### {attention_title}")
            st.markdown(
                f'<div class="soft-blue">{clean_text(build_safe_attention_reason(result))}</div>',
                unsafe_allow_html=True,
            )

            improvements = build_document_improvements_from_result(result)
            if improvements:
                st.markdown("#### Что нужно доработать")
                for item in improvements:
                    st.markdown(
                        f'<div class="soft-yellow">{clean_text(item)}</div>',
                        unsafe_allow_html=True,
                    )

            doctor_questions = build_doctor_questions_from_result(result)
            if doctor_questions:
                st.markdown("#### Что уточнить у врача")
                for question in doctor_questions:
                    st.markdown(
                        f'<div class="soft-green">{clean_text(question)}</div>',
                        unsafe_allow_html=True,
                    )

            st.markdown("</div>", unsafe_allow_html=True)

            col_a, col_b = st.columns(2)

            with col_a:
                st.markdown("### Каких разделов не хватает")
                if result["missing_sections"]:
                    for item in result["missing_sections"]:
                        st.markdown(
                            f'<div class="soft-yellow">{humanize_section(item)}</div>',
                            unsafe_allow_html=True,
                        )
                else:
                    st.markdown('<div class="soft-green">Не обнаружено.</div>', unsafe_allow_html=True)

            with col_b:
                st.markdown("### Что требует внимания")
                if result["risks"]:
                    for risk in result["risks"]:
                        st.markdown(
                            f'<div class="soft-red">{clean_text(risk)}</div>',
                            unsafe_allow_html=True,
                        )
                else:
                    st.markdown('<div class="soft-green">Не обнаружено.</div>', unsafe_allow_html=True)

            st.markdown("### Чек-лист полноты документа")
            if result["sources"]:
                with st.expander("📄 Обязательные разделы медицинского документа"):
                    st.write(result["sources"][0]["text"] if len(result["sources"]) > 0 else "")

                with st.expander("📄 Критерии полноты медицинского документа"):
                    st.write(result["sources"][1]["text"] if len(result["sources"]) > 1 else "")

            with st.expander("Для разработчиков: raw JSON"):
                st.json(result)

        except requests.exceptions.ConnectionError:
            st.error("FastAPI backend не запущен. Запустите: python3 -m uvicorn app.main:app --reload")
        except Exception as exc:
            st.error(f"Ошибка: {exc}")
