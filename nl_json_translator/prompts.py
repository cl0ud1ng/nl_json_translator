from __future__ import annotations

import json


SYSTEM_PROMPT = """You extract indoor cargo transport orders from natural language.

Return exactly one valid JSON object. Do not return markdown, comments, explanations,
database IDs, routes, vehicle assignments, or control commands.

Required shape:
{
  "intent": "create_transport_orders",
  "orders": [
    {
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
  ],
  "dispatch_constraints": {
    "distinct_vehicle_per_order": false
  }
}

Rules:
- intent must always be "create_transport_orders".
- Emit one orders item per explicit pickup-to-dropoff task, preserving input order.
- A request describing one task still uses an orders array with one item.
- Preserve pickup and dropoff text; never invent or normalize a database ID.
- quantity defaults to 1 and must be a positive integer.
- weight_kg and volume_m3 are positive numbers or null when absent.
- category is a short cargo category or null.
- required_capabilities contains only explicit requirements such as "cold_chain".
- vehicle_text preserves an explicitly requested vehicle name or is null.
- priority is one of low, normal, high, urgent and defaults to normal.
- distinct_vehicle_per_order is true only when the user requires separate vehicles,
  one vehicle per order, or an equivalent fleet-wide requirement.
- Never decide whether a location or vehicle exists.
- Never calculate capacity, assignment, path, timing, or collision avoidance.
"""


EXAMPLES = [
    (
        "从 A 取 3 箱零件送到 B",
        {
            "intent": "create_transport_orders",
            "orders": [
                {
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
                }
            ],
            "dispatch_constraints": {"distinct_vehicle_per_order": False},
        },
    ),
    (
        "创建三张独立运输订单：1）从 A 取 1 箱零件箱 A（25kg）送到 B；"
        "2）从 C 取 1 箱零件箱 B（30kg）送到 lab；3）从 A 取 1 箱零件箱 C"
        "（35kg）送到 lab。必须分配给 3 辆不同的车，每辆车只执行一张订单。",
        {
            "intent": "create_transport_orders",
            "orders": [
                {
                    "cargo": {"name": "零件箱 A", "quantity": 1, "weight_kg": 25},
                    "pickup_location_text": "A",
                    "dropoff_location_text": "B",
                },
                {
                    "cargo": {"name": "零件箱 B", "quantity": 1, "weight_kg": 30},
                    "pickup_location_text": "C",
                    "dropoff_location_text": "lab",
                },
                {
                    "cargo": {"name": "零件箱 C", "quantity": 1, "weight_kg": 35},
                    "pickup_location_text": "A",
                    "dropoff_location_text": "lab",
                },
            ],
            "dispatch_constraints": {"distinct_vehicle_per_order": True},
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
            "Extract all transport orders using the required JSON shape.",
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
