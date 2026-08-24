from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-pro"


@dataclass(frozen=True)
class DeepSeekConfig:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    temperature: float = 0.0
    max_tokens: int = 800


def load_env_file(path: str | Path) -> None:
    """Load KEY=VALUE pairs into the process environment if they are unset."""
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def config_from_env(
    *,
    model: str | None = None,
    base_url: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> DeepSeekConfig:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set. Create .env from .env.example or export it.")

    env_temperature = os.getenv("DEEPSEEK_TEMPERATURE", "0").strip()
    env_max_tokens = os.getenv("DEEPSEEK_MAX_TOKENS", "800").strip()

    return DeepSeekConfig(
        api_key=api_key,
        base_url=base_url or os.getenv("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL).strip(),
        model=model or os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL).strip(),
        temperature=temperature if temperature is not None else float(env_temperature),
        max_tokens=max_tokens if max_tokens is not None else int(env_max_tokens),
    )

