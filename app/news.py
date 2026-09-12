from __future__ import annotations

import asyncio
import html
import re
from datetime import datetime
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree

import httpx
from pydantic import BaseModel


class Article(BaseModel):
    title: str
    description: str = ""
    url: str
    source: str
    published_at: str = ""


class NewsSearchError(RuntimeError):
    pass


class NewsSearcher:
    def __init__(self, newsapi_key: str, client: httpx.AsyncClient | None = None):
        self.newsapi_key = newsapi_key
        self.client = client

    async def search(self, topic: str, language: str, days: int) -> list[Article]:
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient(timeout=15, follow_redirects=True)
        try:
            jobs = [self._search_google_rss(client, topic, language)]
            if self.newsapi_key:
                jobs.append(self._search_newsapi(client, topic, language, days))
            results = await asyncio.gather(*jobs, return_exceptions=True)
        finally:
            if owns_client:
                await client.aclose()

        articles: list[Article] = []
        errors: list[str] = []
        for result in results:
            if isinstance(result, Exception):
                errors.append(str(result))
            else:
                articles.extend(result)

        cleaned = deduplicate_articles(articles)
        if not cleaned:
            detail = "; ".join(errors) or "No matching articles were returned"
            raise NewsSearchError(detail)
        return cleaned[:15]

    async def _search_newsapi(
        self, client: httpx.AsyncClient, topic: str, language: str, days: int
    ) -> list[Article]:
        from datetime import timedelta, timezone

        start_date = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
        response = await client.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": topic,
                "from": start_date,
                "language": language,
                "sortBy": "relevancy",
                "pageSize": 20,
            },
            headers={"X-Api-Key": self.newsapi_key},
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "ok":
            raise NewsSearchError(payload.get("message", "NewsAPI request failed"))
        return [
            Article(
                title=item.get("title") or "",
                description=item.get("description") or "",
                url=item.get("url") or "",
                source=(item.get("source") or {}).get("name") or "NewsAPI",
                published_at=item.get("publishedAt") or "",
            )
            for item in payload.get("articles", [])
            if item.get("title") and item.get("url")
        ]

    async def _search_google_rss(
        self, client: httpx.AsyncClient, topic: str, language: str
    ) -> list[Article]:
        locale = "de-DE" if language == "de" else "en-US"
        country = "DE" if language == "de" else "US"
        url = (
            "https://news.google.com/rss/search?"
            f"q={quote_plus(topic)}&hl={locale}&gl={country}&ceid={country}:{language}"
        )
        response = await client.get(url)
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)
        articles: list[Article] = []
        for item in root.findall(".//item"):
            title = _text(item, "title")
            link = _text(item, "link")
            source = _text(item, "source") or "Google News"
            if title and link:
                articles.append(
                    Article(
                        title=title,
                        description=_plain_text(_text(item, "description")),
                        url=link,
                        source=source,
                        published_at=_text(item, "pubDate"),
                    )
                )
        return articles


def deduplicate_articles(articles: list[Article]) -> list[Article]:
    unique: list[Article] = []
    urls: set[str] = set()
    titles: set[str] = set()
    for article in articles:
        title_key = re.sub(r"[^a-z0-9]+", " ", article.title.lower()).strip()
        url_key = _clean_url(article.url)
        if not title_key or not url_key or title_key in titles or url_key in urls:
            continue
        titles.add(title_key)
        urls.add(url_key)
        unique.append(article)
    return unique


def _clean_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        query = urlencode(
            [(key, value) for key, value in parse_qsl(parts.query) if not key.startswith("utm_")]
        )
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, query, ""))
    except ValueError:
        return url


def _text(element: ElementTree.Element, name: str) -> str:
    child = element.find(name)
    return (child.text or "").strip() if child is not None else ""


def _plain_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", html.unescape(value))
    return re.sub(r"\s+", " ", value).strip()
