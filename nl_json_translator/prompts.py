from __future__ import annotations

import json


SYSTEM_PROMPT = """You extract one indoor cargo transport intent from natural language.

Return exactly one valid JSON object. Do not return markdown, comments, explanations, database IDs, routes, vehicle assignments, or control commands.

Required shape:
{
  "intent": "create_transport_order",
  "cargo": {
    "name": "cargo name",
    "quantity": 1,
    "weight_kg": null,
    "volume_m3": null,
    "category": null,
    "required_capabilities": []
  },
  "pickup_location_text": "location exactly as the user described it",
  "dropoff_location_text": "location exactly as the user described it",
  "vehicle_text": null,
  "priority": "normal"
}

Rules:
- intent must always be "create_transport_order".
- Preserve pickup and dropoff location text; never invent or normalize a database ID.
- quantity must be a positive integer and defaults to 1.
- weight_kg and volume_m3 are positive numbers or null when absent.
- category is a short cargo category or null.
- required_capabilities contains explicit requirements such as "cold_chain" or "explosion_proof".
- vehicle_text preserves an explicitly requested vehicle name or is null.
- priority is one of low, normal, high, urgent and defaults to normal.
- Never decide whether a location or vehicle exists.
- Never calculate capacity, assignment, path, timing, or collision avoidance.
"""


EXAMPLES = [
    (
        "从 A 取 3 箱零件送到 B",
        {
            "intent": "create_transport_order",
            "cargo": {
                "name": "零件箱",
                "quantity": 3,
                "weight_kg": None,
                "volume_m3": None,
                "category": None,
                "required_capabilities": [],
            },
            "pickup_location_text": "A",
            "dropoff_location_text": "B",
            "vehicle_text": None,
            "priority": "normal",
        },
    ),
    (
        "Urgently move two 12 kg cold-chain medicine boxes from the lab to charging station using Demo Vehicle 01.",
        {
            "intent": "create_transport_order",
            "cargo": {
                "name": "medicine boxes",
                "quantity": 2,
                "weight_kg": 12,
                "volume_m3": None,
                "category": "medicine",
                "required_capabilities": ["cold_chain"],
            },
            "pickup_location_text": "lab",
            "dropoff_location_text": "charging station",
            "vehicle_text": "Demo Vehicle 01",
            "priority": "urgent",
        },
    ),
]


def build_messages(text_command: str, validation_error: str | None = None) -> list[dict[str, str]]:
    examples_text = [
        f"input: {prompt}\njson: {json.dumps(output, ensure_ascii=False)}"
        for prompt, output in EXAMPLES
    ]
    user_content = "\n\n".join(
        [
            "Extract the transport intent using the required shape.",
            *examples_text,
            f"input: {text_command}",
            "json:",
        ]
    )
    if validation_error:
        user_content = "\n\n".join(
            [
                user_content,
                "The previous response failed validation.",
                f"Validation error: {validation_error}",
                "Return corrected JSON only.",
            ]
        )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
