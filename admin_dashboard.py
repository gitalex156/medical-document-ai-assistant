import json
import html
from pathlib import Path
from datetime import datetime
from collections import Counter

import streamlit as st


ANALYTICS_FILE = Path("data/analytics_events.jsonl")
SUPPORT_FILE = Path("data/support_messages.jsonl")


st.set_page_config(
    page_title="Admin Dashboard | Medical Report AI Reviewer",
    page_icon="📊",
    layout="wide",
)


st.markdown(
    """
<style>
    .stApp {
        background: linear-gradient(135deg, #e0f2fe 0%, #ecfdf5 100%);
    }

    .block-container {
        padding-top: 3rem;
        padding-bottom: 3rem;
        max-width: 1500px;
    }

    .admin-hero {
        padding: 28px 32px;
        border-radius: 28px;
        background: rgba(255, 255, 255, 0.88);
        border: 1px solid rgba(148, 163, 184, 0.35);
        box-shadow: 0 22px 60px rgba(15, 23, 42, 0.10);
        margin-bottom: 28px;
    }

    .admin-title {
        font-size: 38px;
        font-weight: 950;
        color: #0f172a;
        margin-bottom: 8px;
    }

    .admin-subtitle {
        color: #475569;
        font-size: 17px;
        line-height: 1.5;
    }

    .metric-card {
        padding: 22px 24px;
        border-radius: 24px;
        background: rgba(255, 255, 255, 0.92);
        border: 1px solid rgba(148, 163, 184, 0.35);
        box-shadow: 0 16px 40px rgba(15, 23, 42, 0.08);
        min-height: 132px;
        margin-bottom: 14px;
    }

    .metric-label {
        color: #64748b;
        font-size: 14px;
        font-weight: 800;
        margin-bottom: 12px;
    }

    .metric-value {
        color: #0f172a;
        font-size: 40px;
        font-weight: 950;
        line-height: 1;
    }

    .section-title {
        color: #0f172a;
        font-size: 25px;
        font-weight: 950;
        margin-top: 28px;
        margin-bottom: 16px;
    }

    .risk-row,
    .ticket-row {
        padding: 12px 14px;
        border-radius: 16px;
        background: rgba(248, 250, 252, 0.92);
        border: 1px solid #e2e8f0;
        margin-bottom: 9px;
        color: #1e293b;
        font-size: 14px;
        line-height: 1.35;
    }

    .risk-row b {
        color: #b91c1c;
    }

    .ticket-meta {
        color: #64748b;
        font-size: 13px;
        margin-top: 6px;
    }

    .status-new {
        display: inline-block;
        margin-top: 6px;
        color: #047857;
        font-weight: 900;
    }

    .empty {
        padding: 16px;
        border-radius: 16px;
        background: rgba(248, 250, 252, 0.92);
        border: 1px solid #e2e8f0;
        color: #64748b;
    }

    .ticket-title {
        font-size: 15px;
        font-weight: 900;
        color: #0f172a;
        margin-bottom: 4px;
    }

    .ticket-preview {
        font-size: 12px;
        color: #64748b;
        margin-bottom: 6px;
    }

    .status-new {
        display: inline-block;
        margin-top: 6px;
        padding: 4px 10px;
        border-radius: 999px;
        background: rgba(16, 185, 129, 0.12);
        color: #047857;
        font-size: 12px;
        font-weight: 900;
    }

</style>
""",
    unsafe_allow_html=True,
)


def read_jsonl(file_path: Path) -> list:
    if not file_path.exists():
        return []

    items = []
    with file_path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue

            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    return items


def safe_payload(item: dict) -> dict:
    payload = item.get("payload", {})
    return payload if isinstance(payload, dict) else {}


events = read_jsonl(ANALYTICS_FILE)
support_messages = read_jsonl(SUPPORT_FILE)

review_events = [
    item for item in events
    if item.get("event") == "review_completed"
]

error_events = [
    item for item in events
    if item.get("event") in ("backend_connection_error", "review_error")
]

today = datetime.now().strftime("%Y-%m-%d")

today_reviews = [
    item for item in review_events
    if str(item.get("timestamp", "")).startswith(today)
]

today_support = [
    item for item in support_messages
    if str(item.get("timestamp", "")).startswith(today)
]

scores = [
    safe_payload(item).get("quality_score")
    for item in review_events
    if isinstance(safe_payload(item).get("quality_score"), (int, float))
]

risks_counts = [
    safe_payload(item).get("risks_count", 0)
    for item in review_events
    if isinstance(safe_payload(item).get("risks_count", 0), (int, float))
]

processing_times = [
    safe_payload(item).get("processing_time_sec")
    for item in review_events
    if isinstance(safe_payload(item).get("processing_time_sec"), (int, float))
]

avg_score = round(sum(scores) / len(scores), 2) if scores else 0
avg_risks = round(sum(risks_counts) / len(risks_counts), 2) if risks_counts else 0
avg_processing = round(sum(processing_times) / len(processing_times), 2) if processing_times else 0


st.markdown(
    """
<div class="admin-hero">
    <div class="admin-title">📊 Admin Dashboard</div>
    <div class="admin-subtitle">
        Внутренняя панель разработчика для Medical Report AI Reviewer:
        проверки, обращения поддержки, частые риски и технические события.
    </div>
</div>
""",
    unsafe_allow_html=True,
)


m1, m2, m3, m4 = st.columns(4)

with m1:
    st.markdown(
        f"""
<div class="metric-card">
    <div class="metric-label">Проверок сегодня</div>
    <div class="metric-value">{len(today_reviews)}</div>
</div>
""",
        unsafe_allow_html=True,
    )

with m2:
    st.markdown(
        f"""
<div class="metric-card">
    <div class="metric-label">Всего проверок</div>
    <div class="metric-value">{len(review_events)}</div>
</div>
""",
        unsafe_allow_html=True,
    )

with m3:
    st.markdown(
        f"""
<div class="metric-card">
    <div class="metric-label">Средняя оценка</div>
    <div class="metric-value">{avg_score}</div>
</div>
""",
        unsafe_allow_html=True,
    )

with m4:
    st.markdown(
        f"""
<div class="metric-card">
    <div class="metric-label">Обращений сегодня</div>
    <div class="metric-value">{len(today_support)}</div>
</div>
""",
        unsafe_allow_html=True,
    )


m5, m6, m7, m8 = st.columns(4)

with m5:
    st.markdown(
        f"""
<div class="metric-card">
    <div class="metric-label">Всего обращений</div>
    <div class="metric-value">{len(support_messages)}</div>
</div>
""",
        unsafe_allow_html=True,
    )

with m6:
    st.markdown(
        f"""
<div class="metric-card">
    <div class="metric-label">Среднее число рисков</div>
    <div class="metric-value">{avg_risks}</div>
</div>
""",
        unsafe_allow_html=True,
    )

with m7:
    st.markdown(
        f"""
<div class="metric-card">
    <div class="metric-label">Среднее время, сек</div>
    <div class="metric-value">{avg_processing}</div>
</div>
""",
        unsafe_allow_html=True,
    )

with m8:
    st.markdown(
        f"""
<div class="metric-card">
    <div class="metric-label">Ошибки</div>
    <div class="metric-value">{len(error_events)}</div>
</div>
""",
        unsafe_allow_html=True,
    )


left, right = st.columns([1, 1])

with left:
    st.markdown('<div class="section-title">Частые риски</div>', unsafe_allow_html=True)

    all_risks = []
    for item in review_events:
        risks = safe_payload(item).get("risks", [])
        if isinstance(risks, list):
            all_risks.extend(risks)

    if all_risks:
        for risk, count in Counter(all_risks).most_common(10):
            st.markdown(
                f"""
<div class="risk-row">
    <b>{risk}</b><br>
    Количество: {count}
</div>
""",
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            '<div class="empty">Пока нет данных по рискам.</div>',
            unsafe_allow_html=True,
        )


with right:
    st.markdown('<div class="section-title">Последние обращения поддержки</div>', unsafe_allow_html=True)

    if support_messages:
        for item in list(reversed(support_messages[-5:])):
            raw_message = str(item.get("message", "")).strip()
            timestamp = str(item.get("timestamp", "")).strip()
            status = str(item.get("status", "new")).strip()

            if len(raw_message) < 5:
                title = "Тестовое обращение"
                preview = f"Исходный текст: {raw_message}"
            else:
                title = raw_message
                preview = ""

            if len(title) > 120:
                title = title[:120] + "..."

            status_label = {
                "new": "Новое",
                "in_progress": "В работе",
                "answered": "Отвечено",
            }.get(status, status)

            with st.container():
                st.markdown(f"**{title}**")
                if preview:
                    st.caption(preview)
                if timestamp:
                    st.caption(timestamp)
                st.markdown(f"🟢 **{status_label}**")
                st.divider()
    else:
        st.info("Обращений в поддержку пока нет.")


st.markdown('<div class="section-title">Последние проверки</div>', unsafe_allow_html=True)

if review_events:
    rows = []
    for item in list(reversed(review_events[-20:])):
        payload = safe_payload(item)

        rows.append(
            {
                "Время": item.get("timestamp", ""),
                "Оценка": payload.get("quality_score", ""),
                "Недостающие разделы": payload.get("missing_sections_count", ""),
                "Риски": payload.get("risks_count", ""),
                "Время обработки, сек": payload.get("processing_time_sec", ""),
                "Длина текста": payload.get("text_length", ""),
            }
        )

    st.dataframe(rows, use_container_width=True, hide_index=True)
else:
    st.markdown(
        '<div class="empty">Проверок пока нет.</div>',
        unsafe_allow_html=True,
    )


with st.expander("Технические события"):
    if events:
        st.json(events[-30:])
    else:
        st.caption("Технических событий пока нет.")


with st.expander("Служебные файлы"):
    st.write(f"Analytics file: `{ANALYTICS_FILE}`")
    st.write(f"Support file: `{SUPPORT_FILE}`")
