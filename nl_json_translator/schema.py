from __future__ import annotations

from typing import Any


class CommandValidationError(ValueError):
    """Raised when a translated JSON command does not match the supported schema."""


def validate_command(command: Any) -> dict[str, Any]:
    _validate_command(command, "$")
    return command


def _validate_command(command: Any, path: str) -> None:
    if not isinstance(command, dict):
        raise CommandValidationError(f"{path} must be an object")

    action = command.get("action")
    if not isinstance(action, str):
        raise CommandValidationError(f"{path}.action must be a string")

    allowed_actions = {"go_to_goal", "move", "rotate", "sequence", "stop"}
    if action not in allowed_actions:
        raise CommandValidationError(f"{path}.action must be one of {sorted(allowed_actions)}")

    if action == "go_to_goal":
        _validate_go_to_goal(command, path)
    elif action == "move":
        _validate_move(command, path)
    elif action == "rotate":
        _validate_rotate(command, path)
    elif action == "sequence":
        _validate_sequence(command, path)
    elif action == "stop":
        _validate_stop(command, path)


def _params(command: dict[str, Any], path: str) -> dict[str, Any]:
    params = command.get("params")
    if not isinstance(params, dict):
        raise CommandValidationError(f"{path}.params must be an object")
    return params


def _validate_go_to_goal(command: dict[str, Any], path: str) -> None:
    _expect_keys(command, {"action", "params"}, path)
    params = _params(command, path)
    _expect_keys(params, {"location"}, f"{path}.params")
    location = params["location"]
    if not isinstance(location, dict):
        raise CommandValidationError(f"{path}.params.location must be an object")
    _expect_keys(location, {"type", "value"}, f"{path}.params.location")
    if location["type"] != "str":
        raise CommandValidationError(f"{path}.params.location.type must be 'str'")
    if not isinstance(location["value"], str) or not location["value"].strip():
        raise CommandValidationError(f"{path}.params.location.value must be a non-empty string")


def _validate_move(command: dict[str, Any], path: str) -> None:
    _expect_keys(command, {"action", "params"}, path)
    params = _params(command, path)
    allowed = {"linear_speed", "distance", "duration", "is_forward", "unit"}
    _expect_subset(params, allowed, f"{path}.params")

    if "linear_speed" not in params:
        raise CommandValidationError(f"{path}.params.linear_speed is required")
    if not _is_number(params["linear_speed"]) or params["linear_speed"] < 0:
        raise CommandValidationError(f"{path}.params.linear_speed must be a non-negative number")

    has_distance = "distance" in params
    has_duration = "duration" in params
    if has_distance == has_duration:
        raise CommandValidationError(f"{path}.params must contain exactly one of distance or duration")

    if has_distance and (not _is_number(params["distance"]) or params["distance"] <= 0):
        raise CommandValidationError(f"{path}.params.distance must be a positive number")
    if has_duration and (not _is_number(params["duration"]) or params["duration"] <= 0):
        raise CommandValidationError(f"{path}.params.duration must be a positive number")

    if not isinstance(params.get("is_forward"), bool):
        raise CommandValidationError(f"{path}.params.is_forward must be a boolean")

    expected_unit = "meter" if has_distance else "second"
    if params.get("unit") != expected_unit:
        raise CommandValidationError(f"{path}.params.unit must be '{expected_unit}'")


def _validate_rotate(command: dict[str, Any], path: str) -> None:
    _expect_keys(command, {"action", "params"}, path)
    params = _params(command, path)
    _expect_keys(params, {"angular_velocity", "angle", "is_clockwise", "unit"}, f"{path}.params")

    if not _is_number(params["angular_velocity"]) or params["angular_velocity"] < 0:
        raise CommandValidationError(f"{path}.params.angular_velocity must be a non-negative number")
    if not _is_number(params["angle"]) or params["angle"] <= 0:
        raise CommandValidationError(f"{path}.params.angle must be a positive number")
    if not isinstance(params["is_clockwise"], bool):
        raise CommandValidationError(f"{path}.params.is_clockwise must be a boolean")
    if params["unit"] != "degrees":
        raise CommandValidationError(f"{path}.params.unit must be 'degrees'")


def _validate_sequence(command: dict[str, Any], path: str) -> None:
    _expect_keys(command, {"action", "params"}, path)
    params = command.get("params")
    if not isinstance(params, list):
        raise CommandValidationError(f"{path}.params must be a non-empty list")
    if not params:
        raise CommandValidationError(f"{path}.params must be a non-empty list")
    for index, step in enumerate(params):
        _validate_command(step, f"{path}.params[{index}]")


def _validate_stop(command: dict[str, Any], path: str) -> None:
    _expect_subset(command, {"action", "params"}, path)
    if "params" in command and command["params"] != {}:
        raise CommandValidationError(f"{path}.params for stop must be empty when provided")


def _expect_keys(obj: dict[str, Any], expected: set[str], path: str) -> None:
    actual = set(obj.keys())
    if actual != expected:
        raise CommandValidationError(f"{path} keys must be {sorted(expected)}, got {sorted(actual)}")


def _expect_subset(obj: dict[str, Any], allowed: set[str], path: str) -> None:
    extra = set(obj.keys()) - allowed
    if extra:
        raise CommandValidationError(f"{path} has unsupported keys: {sorted(extra)}")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)

