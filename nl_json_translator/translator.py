from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .deepseek_client import ChatClient
from .json_utils import parse_json_object
from .prompts import build_messages
from .schema import CommandValidationError, validate_command


@dataclass(frozen=True)
class Translation:
    command: dict[str, Any]
    raw_response: str
    attempts: int


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

        for attempt in range(self.retries + 1):
            messages = build_messages(command_text, validation_error)
            last_raw = self.client.complete(messages)
            try:
                parsed = parse_json_object(last_raw)
                command = validate_command(parsed)
                return Translation(command=command, raw_response=last_raw, attempts=attempt + 1)
            except (ValueError, CommandValidationError) as exc:
                validation_error = str(exc)

        raise CommandValidationError(
            f"model response failed validation after {self.retries + 1} attempts: {validation_error}. "
            f"last raw response: {last_raw}"
        )

