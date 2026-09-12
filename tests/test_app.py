import json

from fastapi.testclient import TestClient

from app.config import SettingsManager, SetupInput, masked_settings
from app.main import _event, create_app
from app.news import Article, deduplicate_articles
from app.report import build_report_prompt


def test_setup_saves_keys_without_returning_them(tmp_path):
    manager = SettingsManager(tmp_path / ".env")
    settings = manager.save(
        SetupInput(
            newsapi_key="news-secret",
            llm_provider="cloud",
            llm_base_url="https://example.test/v1",
            llm_model="small-model",
            llm_api_key="llm-secret",
        )
    )

    public_settings = masked_settings(settings)
    assert settings.newsapi_key == "news-secret"
    assert "news-secret" not in public_settings.values()
    assert "llm-secret" not in public_settings.values()


def test_duplicate_articles_are_removed():
    articles = [
        Article(title="Same story", url="https://site.test/story", source="One"),
        Article(title="Same story!", url="https://other.test/story", source="Two"),
    ]

    assert len(deduplicate_articles(articles)) == 1


def test_report_prompt_uses_sources_but_not_urls():
    article = Article(
        title="Solar update",
        description="New capacity was announced.",
        url="https://site.test/solar",
        source="Example News",
    )

    prompt = build_report_prompt("solar energy", [article])
    assert "SOURCE [1]" in prompt
    assert "Solar update" in prompt
    assert article.url not in prompt


def test_progress_message_is_valid_json():
    message = json.loads(_event("status", "Searching news"))
    assert message == {"type": "status", "data": "Searching news"}


def test_research_requires_setup(tmp_path):
    client = TestClient(create_app(SettingsManager(tmp_path / ".env")))
    response = client.post(
        "/api/research",
        json={"topic": "artificial intelligence", "language": "en", "days": 7},
    )

    assert response.status_code == 400
