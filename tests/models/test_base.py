from src.models.base import BaseSchema


class ObjectBackedSchema(BaseSchema):
    name: str


class SourceObject:
    name = "from-attributes"


def test_base_schema_supports_from_attributes():
    schema = ObjectBackedSchema.model_validate(SourceObject())

    assert schema.name == "from-attributes"
