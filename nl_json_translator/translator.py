from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from .domain.schemas import TransportRequestDraft
from .deepseek_client import ChatClient, ChatCompletion
from .json_utils import parse_json_object
from .prompts import build_messages


@dataclass(frozen=True)
class Translation:
    request: dict[str, Any]
    raw_response: str
    attempts: int
    response_id: str | None = None
    model: str | None = None
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None


class Translator:
    def __init__(self, client: ChatClient, *, retries: int = 1):
        self.client = client
        self.retries = retries

    def translate(self, text_command: str) -> Translation:
        command_text = text_command.strip()
        if not command_text:
            raise ValueError("text command cannot be empty")

        validation_error: str | None = None
        last_raw = ""
        completion = ChatCompletion("")

        for attempt in range(self.retries + 1):
            messages = build_messages(command_text, validation_error)
            completion = self.client.complete(messages)
            last_raw = completion.content
            try:
                parsed = parse_json_object(last_raw)
                request = TransportRequestDraft.model_validate(parsed).model_dump(mode="json")
                return Translation(
                    request=request,
                    raw_response=last_raw,
                    attempts=attempt + 1,
                    response_id=completion.response_id,
                    model=completion.model,
                    finish_reason=completion.finish_reason,
                    usage=completion.usage,
                )
            except (ValueError, ValidationError) as exc:
                validation_error = str(exc)

        raise ValueError(
            f"model response failed validation after {self.retries + 1} attempts: {validation_error}. "
            f"last raw response: {last_raw}"
        )
