from __future__ import annotations

import json
from pathlib import Path
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import SettingsManager, SetupInput, masked_settings
from app.llm import LLMClient, LLMError
from app.news import NewsSearchError, NewsSearcher
from app.report import NEWS_SYSTEM_PROMPT, build_report_prompt


STATIC_DIR = Path(__file__).resolve().parent / "static"


class ResearchInput(BaseModel):
    topic: str = Field(min_length=3, max_length=200)
    language: str = Field(default="en", pattern="^(en|de)$")
    days: int = Field(default=7, ge=1, le=30)


def create_app(settings_manager: SettingsManager | None = None) -> FastAPI:
    app = FastAPI(title="NewsBot", version="0.1.0")
    app.state.settings_manager = settings_manager or SettingsManager()
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def home() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/status")
    async def status() -> dict:
        manager = app.state.settings_manager
        settings = manager.load()
        return masked_settings(settings, manager.is_configured())

    @app.post("/api/setup")
    async def setup(data: SetupInput) -> dict:
        try:
            settings = app.state.settings_manager.save(data)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return masked_settings(settings, True)

    @app.post("/api/research")
    async def research(data: ResearchInput) -> dict:
        manager = app.state.settings_manager
        settings = manager.load()
        if not manager.is_configured():
            raise HTTPException(status_code=400, detail="Complete setup before researching")
        try:
            articles = await NewsSearcher(settings.newsapi_key).search(
                data.topic.strip(), data.language, data.days
            )
            prompt = build_report_prompt(data.topic.strip(), articles)
            report = await LLMClient(settings).generate(prompt, NEWS_SYSTEM_PROMPT)
        except (NewsSearchError, LLMError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {
            "topic": data.topic.strip(),
            "report": report,
            "sources": [article.model_dump() for article in articles],
        }

    @app.post("/api/research/stream")
    async def research_stream(data: ResearchInput) -> StreamingResponse:
        manager = app.state.settings_manager
        settings = manager.load()
        if not manager.is_configured():
            raise HTTPException(status_code=400, detail="Complete setup before researching")

        async def events() -> AsyncIterator[str]:
            try:
                providers = "Google News RSS"
                if settings.newsapi_key:
                    providers = "NewsAPI and Google News RSS"
                yield _event("status", f"Searching {providers} for “{data.topic.strip()}”…")

                articles = await NewsSearcher(settings.newsapi_key).search(
                    data.topic.strip(), data.language, data.days
                )
                yield _event(
                    "status",
                    f"Found {len(articles)} unique articles. Preparing their summaries…",
                )

                prompt = build_report_prompt(data.topic.strip(), articles)
                yield _event(
                    "status",
                    f"{settings.llm_model} is reading the sources and writing the report…",
                )
                report = await LLMClient(settings).generate(prompt, NEWS_SYSTEM_PROMPT)
                yield _event("status", "Report complete.")
                yield _event(
                    "result",
                    {
                        "topic": data.topic.strip(),
                        "report": report,
                        "sources": [article.model_dump() for article in articles],
                    },
                )
            except (NewsSearchError, LLMError) as exc:
                yield _event("error", str(exc))

        return StreamingResponse(events(), media_type="application/x-ndjson")

    return app


app = create_app()


def _event(event_type: str, data: object) -> str:
    return json.dumps({"type": event_type, "data": data}, ensure_ascii=False) + "\n"
