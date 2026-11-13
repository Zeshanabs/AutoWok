"""Condition validation and evaluation.

Conditions are a small JSON structure, never code::

    {"logic": "and", "rules": [
        {"field": "platform", "operator": "equals", "value": "facebook"},
        {"logic": "or", "rules": [
            {"field": "error_category", "operator": "equals", "value": "token_expired"},
            {"field": "attempt_count", "operator": "greater_than", "value": 2}
        ]}
    ]}

* ``logic`` is ``and`` or ``or``; an empty rule list always matches.
* Every ``field`` must exist in the trigger's payload schema, every ``operator``
  must be allowed for the field type, and ``value`` must match the type.
* Nesting depth and total rule count are bounded by settings.
* String comparisons are case-insensitive; list fields compare their items.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.core.config import get_settings
from app.services.automation.registry import (
    LIST_VALUE_OPERATORS,
    OPERATORS_BY_TYPE,
    VALUELESS_OPERATORS,
    FieldSpec,
    TriggerSpec,
)

LOGIC_VALUES = ("and", "or")
MAX_IN_VALUES = 20


class ConditionError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass
class RuleResult:
    path: str
    field: str | None
    operator: str | None
    expected: Any
    actual: Any
    passed: bool
    logic: str | None = None
    children: list[RuleResult] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"path": self.path, "passed": self.passed}
        if self.logic is not None:
            data["logic"] = self.logic
            data["children"] = [child.as_dict() for child in self.children]
        else:
            data.update({"field": self.field, "operator": self.operator, "expected": self.expected, "actual": self.actual})
        return data


# Validation -------------------------------------------------------------------


def _validate_scalar(field_spec: FieldSpec, value: Any, path: str, errors: list[str]) -> Any:
    kind = field_spec.type
    if kind == "list":
        kind = "string"
    if kind == "string":
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{path}: value must be a non-empty string.")
            return value
        if len(value) > 200:
            errors.append(f"{path}: value is too long (200 characters maximum).")
        if field_spec.choices and value not in field_spec.choices:
            errors.append(f"{path}: value must be one of {', '.join(field_spec.choices)}.")
        return value
    if kind == "uuid":
        try:
            return str(UUID(str(value)))
        except (TypeError, ValueError):
            errors.append(f"{path}: value must be a valid identifier.")
            return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"{path}: value must be a number.")
            return value
        if abs(value) > 1_000_000_000:
            errors.append(f"{path}: value is out of range.")
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            errors.append(f"{path}: value must be true or false.")
        return value
    errors.append(f"{path}: unsupported field type.")
    return value


def _validate_group(
    spec: TriggerSpec, node: Any, path: str, depth: int, counter: list[int], errors: list[str]
) -> dict[str, Any]:
    settings = get_settings()
    if not isinstance(node, dict):
        errors.append(f"{path}: a condition group must be an object.")
        return {"logic": "and", "rules": []}
    unknown = set(node) - {"logic", "rules"}
    if unknown:
        errors.append(f"{path}: unknown keys {sorted(unknown)}.")
    logic = node.get("logic", "and")
    if not isinstance(logic, str) or logic.lower() not in LOGIC_VALUES:
        errors.append(f"{path}: logic must be 'and' or 'or'.")
        logic = "and"
    rules = node.get("rules", [])
    if not isinstance(rules, list):
        errors.append(f"{path}: rules must be a list.")
        rules = []
    if depth > settings.automation_max_condition_depth:
        errors.append(f"{path}: conditions are nested too deeply (maximum depth {settings.automation_max_condition_depth}).")
        return {"logic": logic.lower(), "rules": []}
    normalized_rules: list[dict[str, Any]] = []
    fields = spec.field_map()
    for index, rule in enumerate(rules):
        rule_path = f"{path}.rules[{index}]"
        if not isinstance(rule, dict):
            errors.append(f"{rule_path}: a rule must be an object.")
            continue
        if "rules" in rule or "logic" in rule:
            normalized_rules.append(_validate_group(spec, rule, rule_path, depth + 1, counter, errors))
            continue
        counter[0] += 1
        if counter[0] > settings.automation_max_conditions:
            errors.append(f"Too many conditions (maximum {settings.automation_max_conditions}).")
            break
        unknown_keys = set(rule) - {"field", "operator", "value"}
        if unknown_keys:
            errors.append(f"{rule_path}: unknown keys {sorted(unknown_keys)}.")
        field_name = rule.get("field")
        operator = rule.get("operator")
        if not isinstance(field_name, str) or field_name not in fields:
            errors.append(f"{rule_path}: unknown field '{field_name}' for trigger {spec.type}.")
            continue
        field_spec = fields[field_name]
        allowed = OPERATORS_BY_TYPE[field_spec.type]
        if not isinstance(operator, str) or operator not in allowed:
            errors.append(f"{rule_path}: operator '{operator}' is not supported for {field_spec.type} field '{field_name}'.")
            continue
        value = rule.get("value")
        normalized: dict[str, Any] = {"field": field_name, "operator": operator}
        if operator in VALUELESS_OPERATORS:
            if value not in (None, ""):
                errors.append(f"{rule_path}: operator '{operator}' does not take a value.")
        elif operator in LIST_VALUE_OPERATORS:
            if not isinstance(value, list) or not value:
                errors.append(f"{rule_path}: operator '{operator}' needs a non-empty list of values.")
                continue
            if len(value) > MAX_IN_VALUES:
                errors.append(f"{rule_path}: at most {MAX_IN_VALUES} values are allowed.")
                continue
            normalized["value"] = [_validate_scalar(field_spec, item, f"{rule_path}.value[{position}]", errors) for position, item in enumerate(value)]
        else:
            if value is None:
                errors.append(f"{rule_path}: a value is required.")
                continue
            normalized["value"] = _validate_scalar(field_spec, value, f"{rule_path}.value", errors)
        normalized_rules.append(normalized)
    return {"logic": logic.lower(), "rules": normalized_rules}


def validate_conditions(spec: TriggerSpec, conditions: Any) -> dict[str, Any]:
    """Return the normalized condition tree or raise :class:`ConditionError`."""
    if conditions in (None, {}, []):
        return {"logic": "and", "rules": []}
    if isinstance(conditions, list):
        conditions = {"logic": "and", "rules": conditions}
    errors: list[str] = []
    normalized = _validate_group(spec, conditions, "conditions", 1, [0], errors)
    if errors:
        raise ConditionError(errors)
    return normalized


# Evaluation -------------------------------------------------------------------


def _fold(value: Any) -> Any:
    return value.casefold().strip() if isinstance(value, str) else value


def _is_empty(actual: Any) -> bool:
    return actual is None or actual == "" or actual == []


def _evaluate_rule(field_spec: FieldSpec, operator: str, expected: Any, actual: Any) -> bool:
    if operator == "is_empty":
        return _is_empty(actual)
    if operator == "is_not_empty":
        return not _is_empty(actual)
    if field_spec.type == "list":
        items = {_fold(item) for item in (actual or [])}
        if operator == "contains":
            return _fold(expected) in items
        if operator == "not_contains":
            return _fold(expected) not in items
        return False
    if field_spec.type == "number":
        if actual is None or isinstance(actual, bool) or not isinstance(actual, (int, float)):
            return False
        if operator == "equals":
            return actual == expected
        if operator == "not_equals":
            return actual != expected
        if operator == "greater_than":
            return actual > expected
        if operator == "greater_than_or_equal":
            return actual >= expected
        if operator == "less_than":
            return actual < expected
        if operator == "less_than_or_equal":
            return actual <= expected
        return False
    if field_spec.type == "boolean":
        return operator == "equals" and actual is not None and bool(actual) == bool(expected)
    # string and uuid
    folded_actual = _fold(actual) if actual is not None else None
    if operator == "equals":
        return folded_actual is not None and folded_actual == _fold(expected)
    if operator == "not_equals":
        return folded_actual != _fold(expected)
    if operator == "in":
        return folded_actual is not None and folded_actual in {_fold(item) for item in expected}
    if operator == "not_in":
        return folded_actual not in {_fold(item) for item in expected}
    if operator == "contains":
        return folded_actual is not None and _fold(expected) in folded_actual
    if operator == "not_contains":
        return folded_actual is None or _fold(expected) not in folded_actual
    return False


def _evaluate_group(spec: TriggerSpec, node: dict[str, Any], payload: dict[str, Any], path: str) -> RuleResult:
    logic = str(node.get("logic", "and")).lower()
    rules = node.get("rules") or []
    children: list[RuleResult] = []
    fields = spec.field_map()
    for index, rule in enumerate(rules):
        rule_path = f"{path}.rules[{index}]"
        if "rules" in rule or "logic" in rule:
            children.append(_evaluate_group(spec, rule, payload, rule_path))
            continue
        field_spec = fields.get(rule.get("field"))
        actual = payload.get(rule.get("field")) if field_spec is not None else None
        passed = False
        if field_spec is not None and rule.get("operator") in OPERATORS_BY_TYPE[field_spec.type]:
            passed = _evaluate_rule(field_spec, rule["operator"], rule.get("value"), actual)
        children.append(RuleResult(rule_path, rule.get("field"), rule.get("operator"), rule.get("value"), actual, passed))
    if not children:
        passed = True
    elif logic == "or":
        passed = any(child.passed for child in children)
    else:
        passed = all(child.passed for child in children)
    return RuleResult(path, None, None, None, None, passed, logic=logic, children=children)


def evaluate_conditions(spec: TriggerSpec, conditions: dict[str, Any] | None, payload: dict[str, Any]) -> RuleResult:
    """Evaluate a *validated* condition tree against a normalized payload."""
    if not conditions:
        return RuleResult("conditions", None, None, None, None, True, logic="and", children=[])
    return _evaluate_group(spec, conditions, payload, "conditions")
