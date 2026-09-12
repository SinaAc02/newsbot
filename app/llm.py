from __future__ import annotations

import httpx

from app.config import AppSettings


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, settings: AppSettings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.client = client

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient(timeout=300)
        try:
            if self.settings.llm_provider == "ollama":
                return await self._ollama(client, prompt, system_prompt)
            return await self._cloud(client, prompt, system_prompt)
        except httpx.TimeoutException as exc:
            raise LLMError(
                "The language model took too long to answer. Try again, or use the smaller gemma3:1b model."
            ) from exc
        except httpx.HTTPStatusError as exc:
            detail = _response_detail(exc.response)
            raise LLMError(
                f"The language model returned HTTP {exc.response.status_code}: {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMError(
                f"Could not connect to the language model ({type(exc).__name__})."
            ) from exc
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("The language model returned an unexpected response.") from exc
        finally:
            if owns_client:
                await client.aclose()

    async def _ollama(
        self, client: httpx.AsyncClient, prompt: str, system_prompt: str | None
    ) -> str:
        url = self.settings.llm_base_url.rstrip("/") + "/api/chat"
        response = await client.post(
            url,
            json={
                "model": self.settings.llm_model,
                "messages": _messages(prompt, system_prompt),
                "stream": False,
                "think": False,
            },
        )
        response.raise_for_status()
        content = response.json()["message"]["content"].strip()
        if not content:
            raise LLMError("The language model returned an empty answer")
        return content

    async def _cloud(
        self, client: httpx.AsyncClient, prompt: str, system_prompt: str | None
    ) -> str:
        base = self.settings.llm_base_url.rstrip("/")
        url = base if base.endswith("/chat/completions") else base + "/chat/completions"
        response = await client.post(
            url,
            headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
            json={
                "model": self.settings.llm_model,
                "messages": _messages(prompt, system_prompt),
                "temperature": 0.2,
            },
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"].strip()
        if not content:
            raise LLMError("The language model returned an empty answer")
        return content


def _response_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
        return payload.get("error") or payload.get("message") or "Request failed"
    except (ValueError, AttributeError):
        return response.text.strip() or "Request failed"



def _messages(prompt: str, system_prompt: str | None) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    return messages
