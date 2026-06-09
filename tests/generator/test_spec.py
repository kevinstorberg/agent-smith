import pytest

from lib.cairn.generator.naming import names_for
from lib.cairn.generator.spec import parse_resource_spec


@pytest.mark.unit
def test_parse_resource_spec_accepts_supported_fields():
    spec = parse_resource_spec(
        "project",
        ["name:string", "description?:text", "status:enum[planned,active,done]", "owner_id:uuid"],
    )

    assert spec.name == "project"
    assert [field.name for field in spec.fields] == ["name", "description", "status", "owner_id"]
    assert spec.fields[1].optional is True
    assert spec.fields[2].kind == "enum"
    assert spec.fields[2].enum_values == ("planned", "active", "done")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("resource_name", "fields", "message"),
    [
        ("Project", ["name:string"], "Invalid resource name"),
        ("project", [], "At least one field is required"),
        ("project", ["name"], "name:type"),
        ("project", ["id:uuid"], "managed by Cairn"),
        ("project", ["name:string", "name:text"], "Duplicate fields"),
        ("project", ["status:enum[]"], "must define at least one value"),
        ("project", ["status:unknown"], "Unsupported field type"),
    ],
)
def test_parse_resource_spec_fails_before_writing_invalid_specs(resource_name, fields, message):
    with pytest.raises(ValueError, match=message):
        parse_resource_spec(resource_name, fields)


@pytest.mark.unit
def test_names_for_conventional_resource_names():
    names = names_for("category")

    assert names.singular == "category"
    assert names.plural == "categories"
    assert names.class_name == "Category"
    assert names.table_name == "categories"
    assert names.router_name == "categories"
