import re
from dataclasses import dataclass

SUPPORTED_TYPES = {"string", "text", "int", "float", "bool", "datetime", "date", "uuid"}
IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class FieldSpec:
    name: str
    kind: str
    optional: bool = False
    enum_values: tuple[str, ...] = ()

    @property
    def is_enum(self) -> bool:
        return self.kind == "enum"


@dataclass(frozen=True)
class ResourceSpec:
    name: str
    fields: tuple[FieldSpec, ...]


def parse_resource_spec(resource_name: str, field_specs: list[str]) -> ResourceSpec:
    _validate_identifier(resource_name, "resource name")
    if not field_specs:
        raise ValueError("At least one field is required")
    fields = tuple(_parse_field(spec) for spec in field_specs)
    names = [field.name for field in fields]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(f"Duplicate fields: {', '.join(duplicates)}")
    return ResourceSpec(name=resource_name, fields=fields)


def _parse_field(spec: str) -> FieldSpec:
    name_part, separator, type_part = spec.partition(":")
    if not separator:
        raise ValueError(f"Field spec must use name:type format: {spec!r}")

    optional = name_part.endswith("?")
    name = name_part[:-1] if optional else name_part
    _validate_identifier(name, "field name")
    if name in {"id", "created_at", "updated_at"}:
        raise ValueError(f"Field {name!r} is managed by Agent Smith base models")

    kind = type_part.strip()
    if kind.startswith("enum[") and kind.endswith("]"):
        values = tuple(value.strip() for value in kind[5:-1].split(",") if value.strip())
        if not values:
            raise ValueError(f"Enum field {name!r} must define at least one value")
        for value in values:
            _validate_identifier(value, "enum value")
        return FieldSpec(name=name, kind="enum", optional=optional, enum_values=values)

    if kind not in SUPPORTED_TYPES:
        supported = ", ".join(sorted(SUPPORTED_TYPES | {"enum[...]"}))
        raise ValueError(f"Unsupported field type {kind!r}. Supported: {supported}")
    return FieldSpec(name=name, kind=kind, optional=optional)


def _validate_identifier(value: str, label: str) -> None:
    if not IDENTIFIER_PATTERN.match(value):
        raise ValueError(f"Invalid {label} {value!r}; use snake_case starting with a letter")
