from dataclasses import dataclass


@dataclass(frozen=True)
class ResourceNames:
    singular: str
    plural: str
    class_name: str
    table_name: str
    router_name: str


def names_for(resource_name: str) -> ResourceNames:
    plural = _pluralize(resource_name)
    return ResourceNames(
        singular=resource_name,
        plural=plural,
        class_name=_class_name(resource_name),
        table_name=plural,
        router_name=plural,
    )


def _class_name(value: str) -> str:
    return "".join(part.capitalize() for part in value.split("_"))


def _pluralize(value: str) -> str:
    if value.endswith("y") and len(value) > 1 and value[-2] not in "aeiou":
        return f"{value[:-1]}ies"
    if value.endswith(("s", "x", "z", "ch", "sh")):
        return f"{value}es"
    return f"{value}s"
