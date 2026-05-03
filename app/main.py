from fastapi import FastAPI
from app.schemas import ReviewRequest, ReviewResponse
from app.agent import run_agent

app = FastAPI(title="Medical Report AI Reviewer")


@app.get("/")
def root():
    return {"message": "AI Reviewer is running"}


@app.post("/review", response_model=ReviewResponse)
def review(request: ReviewRequest):
    result = run_agent(request.report_text)
    return result


# --- Support endpoint for demo UI ---
from datetime import datetime as _support_datetime
from pathlib import Path as _SupportPath
import json as _support_json
from pydantic import BaseModel as _SupportBaseModel


class SupportRequest(_SupportBaseModel):
    message: str


@app.post("/support")
def support_endpoint(request: SupportRequest):
    data_dir = _SupportPath("data")
    data_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "created_at": _support_datetime.now().isoformat(timespec="seconds"),
        "message": request.message,
        "mode": "demo",
    }

    with (data_dir / "support_messages.jsonl").open("a", encoding="utf-8") as f:
        f.write(_support_json.dumps(payload, ensure_ascii=False) + "\n")

    return {
        "status": "ok",
        "mode": "demo",
        "answer": (
            "Спасибо за ваш вопрос!\n\n"
            "Сейчас сервис работает в **демо-режиме**.\n\n"
            "Ваше сообщение сохранено локально в `data/support_messages.jsonl`. "
            "В production такие обращения будут отправляться в поддержку, "
            "а команда сможет отвечать пользователям внутри сервиса."
        ),
    }
