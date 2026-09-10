"""Dependency-free validation for the JSON Schema subset used by this skill."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
JSON_TYPES = {
    "object",
    "array",
    "string",
    "integer",
    "number",
    "boolean",
    "null",
}


@dataclass(frozen=True)
class SchemaError:
    pointer: str
    message: str

    def __str__(self) -> str:
        return f"{self.pointer or '/'}: {self.message}"


def _pointer(parent: str, token: object) -> str:
    escaped = str(token).replace("~", "~0").replace("/", "~1")
    return f"{parent}/{escaped}"


def _type_matches(instance: object, expected: str) -> bool:
    if expected == "object":
        return isinstance(instance, dict)
    if expected == "array":
        return isinstance(instance, list)
    if expected == "string":
        return isinstance(instance, str)
    if expected == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if expected == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    if expected == "boolean":
        return isinstance(instance, bool)
    if expected == "null":
        return instance is None
    raise ValueError(f"unsupported JSON Schema type: {expected}")


def _resolve_ref(root: dict, reference: str) -> object:
    if not reference.startswith("#/"):
        raise ValueError(f"only local JSON Schema references are supported: {reference}")
    value: object = root
    for raw_token in reference[2:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or token not in value:
            raise ValueError(f"unresolved JSON Schema reference: {reference}")
        value = value[token]
    return value


def _validate(instance: object, schema: object, root: dict, pointer: str) -> list[SchemaError]:
    if schema is True:
        return []
    if schema is False:
        return [SchemaError(pointer, "value is not allowed")]
    if not isinstance(schema, dict):
        raise ValueError("JSON Schema nodes must be objects or booleans")

    if "$ref" in schema:
        referenced = _resolve_ref(root, schema["$ref"])
        errors = _validate(instance, referenced, root, pointer)
        siblings = {key: value for key, value in schema.items() if key != "$ref"}
        if siblings:
            errors.extend(_validate(instance, siblings, root, pointer))
        return errors

    errors: list[SchemaError] = []
    expected_type = schema.get("type")
    if expected_type is not None:
        choices = [expected_type] if isinstance(expected_type, str) else expected_type
        if not isinstance(choices, list) or not all(isinstance(item, str) for item in choices):
            raise ValueError("JSON Schema type must be a string or string array")
        if not any(_type_matches(instance, choice) for choice in choices):
            errors.append(SchemaError(pointer, f"must be of type {' or '.join(choices)}"))
            return errors

    if "const" in schema and instance != schema["const"]:
        errors.append(SchemaError(pointer, f"must equal {schema['const']!r}"))
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(SchemaError(pointer, f"must be one of {schema['enum']!r}"))

    for keyword in ("allOf", "anyOf", "oneOf"):
        if keyword not in schema:
            continue
        branches = schema[keyword]
        if not isinstance(branches, list):
            raise ValueError(f"JSON Schema {keyword} must be an array")
        branch_errors = [_validate(instance, branch, root, pointer) for branch in branches]
        matches = [result for result in branch_errors if not result]
        if keyword == "allOf":
            for result in branch_errors:
                errors.extend(result)
        elif keyword == "anyOf" and not matches:
            errors.extend(min(branch_errors, key=len, default=[]))
            errors.append(SchemaError(pointer, "must match at least one allowed shape"))
        elif keyword == "oneOf" and len(matches) != 1:
            if not matches:
                errors.extend(min(branch_errors, key=len, default=[]))
            errors.append(SchemaError(pointer, "must match exactly one allowed shape"))

    if "not" in schema and not _validate(instance, schema["not"], root, pointer):
        errors.append(SchemaError(pointer, "matches a forbidden shape"))
    if "if" in schema:
        condition_matches = not _validate(instance, schema["if"], root, pointer)
        selected = schema.get("then") if condition_matches else schema.get("else")
        if selected is not None:
            errors.extend(_validate(instance, selected, root, pointer))

    if isinstance(instance, dict):
        if "minProperties" in schema and len(instance) < schema["minProperties"]:
            errors.append(
                SchemaError(
                    pointer,
                    f"must contain at least {schema['minProperties']} properties",
                )
            )
        required = schema.get("required", [])
        if not isinstance(required, list):
            raise ValueError("JSON Schema required must be an array")
        for key in required:
            if key not in instance:
                errors.append(SchemaError(_pointer(pointer, key), "is required"))
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            raise ValueError("JSON Schema properties must be an object")
        for key, value in instance.items():
            if key in properties:
                errors.extend(_validate(value, properties[key], root, _pointer(pointer, key)))
            elif schema.get("additionalProperties") is False:
                errors.append(SchemaError(_pointer(pointer, key), "additional property is not allowed"))
            elif isinstance(schema.get("additionalProperties"), dict):
                errors.extend(
                    _validate(value, schema["additionalProperties"], root, _pointer(pointer, key))
                )

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(SchemaError(pointer, f"must contain at least {schema['minItems']} items"))
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(SchemaError(pointer, f"must contain at most {schema['maxItems']} items"))
        if schema.get("uniqueItems"):
            serialized = [json.dumps(item, sort_keys=True, ensure_ascii=False) for item in instance]
            if len(set(serialized)) != len(serialized):
                errors.append(SchemaError(pointer, "items must be unique"))
        if "items" in schema:
            for index, value in enumerate(instance):
                errors.extend(_validate(value, schema["items"], root, _pointer(pointer, index)))

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(SchemaError(pointer, f"must contain at least {schema['minLength']} characters"))
        if "pattern" in schema and re.search(schema["pattern"], instance) is None:
            errors.append(SchemaError(pointer, f"must match pattern {schema['pattern']!r}"))

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(SchemaError(pointer, f"must be at least {schema['minimum']}"))
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(SchemaError(pointer, f"must be at most {schema['maximum']}"))

    return errors


def validate(instance: object, schema: dict) -> list[SchemaError]:
    """Return deterministic validation errors for an instance."""
    if not isinstance(schema, dict):
        raise ValueError("JSON Schema root must be an object")
    return _validate(instance, schema, schema, "")


def validate_schema(schema: object) -> None:
    """Check the structure and local references of a bundled Draft 2020-12 schema."""
    if not isinstance(schema, dict):
        raise ValueError("JSON Schema root must be an object")
    if schema.get("$schema") != DRAFT_2020_12:
        raise ValueError("JSON Schema must declare Draft 2020-12")

    def visit(node: object, pointer: str) -> None:
        if isinstance(node, bool):
            return
        if not isinstance(node, dict):
            raise ValueError(f"JSON Schema node {pointer or '/'} must be an object or boolean")
        reference = node.get("$ref")
        if reference is not None:
            if not isinstance(reference, str):
                raise ValueError(f"JSON Schema $ref at {pointer or '/'} must be a string")
            _resolve_ref(schema, reference)
        expected = node.get("type")
        if expected is not None:
            choices = [expected] if isinstance(expected, str) else expected
            if (
                not isinstance(choices, list)
                or not choices
                or not all(isinstance(choice, str) and choice in JSON_TYPES for choice in choices)
            ):
                raise ValueError(f"JSON Schema type at {pointer or '/'} is invalid")
        required = node.get("required")
        if required is not None and (
            not isinstance(required, list)
            or not all(isinstance(key, str) for key in required)
            or len(set(required)) != len(required)
        ):
            raise ValueError(f"JSON Schema required at {pointer or '/'} is invalid")
        if "enum" in node and (not isinstance(node["enum"], list) or not node["enum"]):
            raise ValueError(f"JSON Schema enum at {pointer or '/'} must be a nonempty array")
        if "pattern" in node:
            if not isinstance(node["pattern"], str):
                raise ValueError(f"JSON Schema pattern at {pointer or '/'} must be a string")
            try:
                re.compile(node["pattern"])
            except re.error as exc:
                raise ValueError(f"invalid JSON Schema pattern at {pointer or '/'}: {exc}") from exc
        for keyword in ("minItems", "maxItems", "minLength", "minProperties"):
            if keyword in node and (
                isinstance(node[keyword], bool)
                or not isinstance(node[keyword], int)
                or node[keyword] < 0
            ):
                raise ValueError(f"JSON Schema {keyword} at {pointer or '/'} must be nonnegative")
        for keyword in ("properties", "$defs"):
            children = node.get(keyword, {})
            if not isinstance(children, dict):
                raise ValueError(f"JSON Schema {keyword} at {pointer or '/'} must be an object")
            for key, child in children.items():
                visit(child, _pointer(_pointer(pointer, keyword), key))
        for keyword in ("items", "additionalProperties", "not", "if", "then", "else"):
            if keyword in node:
                visit(node[keyword], _pointer(pointer, keyword))
        for keyword in ("allOf", "anyOf", "oneOf"):
            if keyword not in node:
                continue
            children = node[keyword]
            if not isinstance(children, list) or not children:
                raise ValueError(f"JSON Schema {keyword} at {pointer or '/'} must be nonempty")
            for index, child in enumerate(children):
                visit(child, _pointer(_pointer(pointer, keyword), index))

    visit(schema, "")


def load_and_validate(instance: object, schema_path: Path, label: str) -> None:
    """Load a bundled schema and raise a concise error for the first violation."""
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label} JSON Schema: {exc}") from exc
    try:
        validate_schema(schema)
    except ValueError as exc:
        raise ValueError(f"invalid {label} JSON Schema: {exc}") from exc
    errors = validate(instance, schema)
    if errors:
        raise ValueError(f"{label} does not match its JSON Schema at {errors[0]}")
