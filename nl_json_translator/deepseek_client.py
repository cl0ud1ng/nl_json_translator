from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

from .config import DeepSeekConfig


@dataclass(frozen=True)
class ChatCompletion:
    content: str
    response_id: str | None = None
    model: str | None = None
    finish_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)


class ChatClient(Protocol):
    def complete(self, messages: list[dict[str, str]]) -> ChatCompletion:
        ...


class DeepSeekClient:
    def __init__(self, config: DeepSeekConfig):
        self.config = config

    def complete(self, messages: list[dict[str, str]]) -> ChatCompletion:
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
        }
        body = json.dumps(payload).encode("utf-8")

        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"DeepSeek API HTTP {exc.code}: {details}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"DeepSeek API request failed: {exc.reason}") from exc

        data = json.loads(raw)
        try:
            choice = data["choices"][0]
            return ChatCompletion(
                content=choice["message"]["content"],
                response_id=data.get("id"),
                model=data.get("model"),
                finish_reason=choice.get("finish_reason"),
                usage=dict(data.get("usage") or {}),
            )
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected DeepSeek API response: {raw}") from exc
