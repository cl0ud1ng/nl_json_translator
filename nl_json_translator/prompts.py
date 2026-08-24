from __future__ import annotations

import json


SYSTEM_PROMPT = """You are a natural-language-to-json translator for a high-level unmanned-car command interface.

Return one valid json object only. Do not return markdown, comments, explanations, or surrounding text.

You convert user commands into this ROSGPT-style ontology:

1. Go to a named goal:
{"action":"go_to_goal","params":{"location":{"type":"str","value":"B"}}}

2. Move by distance:
{"action":"move","params":{"linear_speed":1.0,"distance":1.0,"is_forward":true,"unit":"meter"}}

3. Move by duration:
{"action":"move","params":{"linear_speed":1.0,"duration":2.0,"is_forward":false,"unit":"second"}}

4. Rotate:
{"action":"rotate","params":{"angular_velocity":10.0,"angle":90.0,"is_clockwise":false,"unit":"degrees"}}

5. Stop:
{"action":"stop","params":{}}

6. Ordered sequence:
{"action":"sequence","params":[COMMAND_OBJECT,COMMAND_OBJECT]}

Rules:
- Preserve the user's order exactly. Words like "then", "after that", and "next" create a sequence.
- Treat "than" as a likely typo for "then" only when the sentence clearly describes ordered destinations or actions.
- Use go_to_goal for named places or symbolic points such as A, B, C, kitchen, lab, and charging station.
- Use rotate for "turn left", "turn right", "clockwise", and "counterclockwise".
- Left means counterclockwise, so is_clockwise is false.
- Right means clockwise, so is_clockwise is true.
- If speed is omitted for move, use linear_speed 1.0.
- If angular speed is omitted for rotate, use angular_velocity 10.0.
- Normalize distance unit to "meter".
- Normalize duration unit to "second".
- Normalize angle unit to "degrees".
- Ignore unrelated requests that are not robot-car commands.
- Do not create paths, trajectories, waypoints, steering angles, throttle values, brake values, or planning details.
- If no supported command remains after ignoring unrelated text, return {"action":"stop","params":{}}.
"""


EXAMPLES = [
    (
        "Move forward for 1 meter at a speed of 0.5 meters per second.",
        {
            "action": "move",
            "params": {
                "linear_speed": 0.5,
                "distance": 1,
                "is_forward": True,
                "unit": "meter",
            },
        },
    ),
    (
        "Rotate 60 degree in clockwise direction at 10 degrees per second and make pizza.",
        {
            "action": "rotate",
            "params": {
                "angular_velocity": 10,
                "angle": 60,
                "is_clockwise": True,
                "unit": "degrees",
            },
        },
    ),
    (
        "go to the bedroom, rotate 60 degrees and move 1 meter then stop",
        {
            "action": "sequence",
            "params": [
                {
                    "action": "go_to_goal",
                    "params": {
                        "location": {
                            "type": "str",
                            "value": "bedroom",
                        }
                    },
                },
                {
                    "action": "rotate",
                    "params": {
                        "angular_velocity": 10,
                        "angle": 60,
                        "is_clockwise": False,
                        "unit": "degrees",
                    },
                },
                {
                    "action": "move",
                    "params": {
                        "linear_speed": 1,
                        "distance": 1,
                        "is_forward": True,
                        "unit": "meter",
                    },
                },
                {
                    "action": "stop",
                    "params": {},
                },
            ],
        },
    ),
    (
        "go to B than A",
        {
            "action": "sequence",
            "params": [
                {
                    "action": "go_to_goal",
                    "params": {
                        "location": {
                            "type": "str",
                            "value": "B",
                        }
                    },
                },
                {
                    "action": "go_to_goal",
                    "params": {
                        "location": {
                            "type": "str",
                            "value": "A",
                        }
                    },
                },
            ],
        },
    ),
]


def build_messages(text_command: str, validation_error: str | None = None) -> list[dict[str, str]]:
    examples_text = []
    for prompt, output in EXAMPLES:
        examples_text.append(f"prompt: {prompt}\njson: {json.dumps(output, ensure_ascii=False)}")

    user_content = "\n\n".join(
        [
            "Use the rules and examples to translate the command.",
            *examples_text,
            f"prompt: {text_command}",
            "json:",
        ]
    )

    if validation_error:
        user_content = "\n\n".join(
            [
                user_content,
                "The previous response failed validation.",
                f"Validation error: {validation_error}",
                "Return corrected json only.",
            ]
        )

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

