from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import config_from_env, load_env_file
from .deepseek_client import DeepSeekClient
from .prompts import build_messages
from .translator import Translator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Translate natural-language commands to ROSGPT-style JSON.")
    parser.add_argument("command", nargs="*", help="Command text. If omitted, interactive mode starts.")
    parser.add_argument("--env-file", default=".env", help="Optional env file to load before reading config.")
    parser.add_argument("--model", help="DeepSeek model id. Overrides DEEPSEEK_MODEL.")
    parser.add_argument("--base-url", help="DeepSeek-compatible base URL. Overrides DEEPSEEK_BASE_URL.")
    parser.add_argument("--temperature", type=float, help="Sampling temperature. Overrides DEEPSEEK_TEMPERATURE.")
    parser.add_argument("--max-tokens", type=int, help="Max output tokens. Overrides DEEPSEEK_MAX_TOKENS.")
    parser.add_argument("--raw", action="store_true", help="Also print the raw model response to stderr.")
    parser.add_argument("--show-prompt", action="store_true", help="Print the built messages without calling the API.")
    args = parser.parse_args(argv)

    load_env_file(Path(args.env_file))
    text = " ".join(args.command).strip()

    if args.show_prompt:
        if not text:
            print("--show-prompt requires a command argument", file=sys.stderr)
            return 2
        print(json.dumps(build_messages(text), ensure_ascii=False, indent=2))
        return 0

    try:
        config = config_from_env(
            model=args.model,
            base_url=args.base_url,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
        translator = Translator(DeepSeekClient(config))

        if text:
            return _translate_once(translator, text, raw=args.raw)

        return _interactive(translator, raw=args.raw)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _translate_once(translator: Translator, text: str, *, raw: bool) -> int:
    result = translator.translate(text)
    if raw:
        print(result.raw_response, file=sys.stderr)
    print(json.dumps(result.command, ensure_ascii=False, indent=2))
    return 0


def _interactive(translator: Translator, *, raw: bool) -> int:
    print("Enter natural-language commands. Press Ctrl-D to exit.")
    while True:
        try:
            text = input("Command> ").strip()
        except EOFError:
            print()
            return 0

        if not text:
            continue
        try:
            _translate_once(translator, text, raw=raw)
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())

