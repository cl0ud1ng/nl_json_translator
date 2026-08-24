# NL JSON Translator Demo

Standalone local demo for translating natural-language unmanned-car commands into structured JSON.

This is a fast port of the NL-to-JSON idea from `../rosgpt/`, but without ROS, Flask, turtlesim, Nav2, or any lower-level robot control. It reuses the useful ROSGPT command style:

- `go_to_goal`
- `move`
- `rotate`
- `sequence`
- `stop`

The translator runs locally on macOS and calls the DeepSeek API for the LLM step.

## Quick Start

```bash
cd nl_json_translator
cp .env.example .env
# edit .env and set DEEPSEEK_API_KEY
python -m nl_json_translator.cli "go to B then A"
```

Expected shape:

```json
{
  "action": "sequence",
  "params": [
    {
      "action": "go_to_goal",
      "params": {
        "location": {
          "type": "str",
          "value": "B"
        }
      }
    },
    {
      "action": "go_to_goal",
      "params": {
        "location": {
          "type": "str",
          "value": "A"
        }
      }
    }
  ]
}
```

## Environment

```text
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro
```

If the exact DeepSeek V4 model id differs for your account, change `DEEPSEEK_MODEL` in `.env`.

## Commands

Interactive mode:

```bash
python -m nl_json_translator.cli
```

One-shot mode:

```bash
python -m nl_json_translator.cli "move forward for 1 meter"
```

Show the prompt without calling the API:

```bash
python -m nl_json_translator.cli --show-prompt "go to B then A"
```

Run tests:

```bash
python -m unittest discover -s tests
```

Run the full pipeline visualization UI:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-ui.txt
streamlit run app.py
```

## Design Notes

The LLM output is treated as untrusted. The CLI only prints a command after it parses as JSON and passes schema validation.

This demo does not calculate routes, trajectories, steering commands, throttle, braking, or motor signals. The unmanned car system is expected to consume the JSON and handle planning/control downstream.
