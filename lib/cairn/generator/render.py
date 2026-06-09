from datetime import datetime, timezone

from lib.cairn.generator.naming import ResourceNames, names_for
from lib.cairn.generator.spec import FieldSpec, ResourceSpec


def render_model(spec: ResourceSpec) -> str:
    names = names_for(spec.name)
    imports = "\n\n".join((_model_imports(spec), "from db.base import Base, TimestampMixin, UUIDMixin"))
    enum_classes = "\n\n".join(_enum_class(names, field) for field in spec.fields if field.is_enum)
    fields = "\n".join(_model_field(names, field) for field in spec.fields)
    sections = [
        imports,
        enum_classes,
        "def _enum_values(enum_cls):\n    return [member.value for member in enum_cls]" if enum_classes else "",
        f"""class {names.class_name}(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "{names.table_name}"

{fields}
""",
    ]
    return "\n\n\n".join(section for section in sections if section)


def render_repository(spec: ResourceSpec) -> str:
    names = names_for(spec.name)
    return f"""from db.models.{spec.name} import {names.class_name}
from db.repository import BaseRepository


class {names.class_name}Repository(BaseRepository[{names.class_name}]):
    model = {names.class_name}
"""


def render_schema(spec: ResourceSpec) -> str:
    names = names_for(spec.name)
    imports = _schema_imports(spec)
    create_fields = "\n".join(_schema_field(names, field, create=True) for field in spec.fields)
    update_fields = "\n".join(_schema_field(names, field, create=False) for field in spec.fields)
    read_fields = "\n".join(_schema_field(names, field, create=True) for field in spec.fields)
    return f"""{imports}


class {names.class_name}Create(BaseSchema):
{_indent_or_pass(create_fields)}


class {names.class_name}Update(BaseSchema):
{_indent_or_pass(update_fields)}


class {names.class_name}Read(BaseSchema):
    id: UUID
    created_at: datetime
    updated_at: datetime
{_indent_or_empty(read_fields)}
"""


def render_service(spec: ResourceSpec) -> str:
    names = names_for(spec.name)
    return f"""from uuid import UUID

from db.repositories.{spec.name} import {names.class_name}Repository
from db.unit_of_work import UnitOfWork
from src.models.{spec.name} import {names.class_name}Create, {names.class_name}Update
from src.services.application import ApplicationService


class {names.class_name}Service(ApplicationService):
    async def create(self, uow: UnitOfWork, data: {names.class_name}Create):
        repository = {names.class_name}Repository(uow.session)
        item = repository.add({names.class_name}Repository.model(**data.model_dump()))
        await uow.session.flush()
        return await repository.refresh(item)

    async def get(self, uow: UnitOfWork, item_id: UUID):
        return await {names.class_name}Repository(uow.session).get(item_id)

    async def list(self, uow: UnitOfWork, *, offset: int = 0, limit: int = 100):
        return await {names.class_name}Repository(uow.session).list(offset=offset, limit=limit)

    async def update(self, uow: UnitOfWork, item_id: UUID, data: {names.class_name}Update):
        repository = {names.class_name}Repository(uow.session)
        item = await repository.get(item_id)
        if item is None:
            return None
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(item, key, value)
        await uow.session.flush()
        return await repository.refresh(item)

    async def delete(self, uow: UnitOfWork, item_id: UUID) -> bool:
        repository = {names.class_name}Repository(uow.session)
        item = await repository.get(item_id)
        if item is None:
            return False
        await repository.delete(item)
        return True
"""


def render_router(spec: ResourceSpec) -> str:
    names = names_for(spec.name)
    return f"""from uuid import UUID

from fastapi import Depends, HTTPException, status

from db.unit_of_work import UnitOfWork, get_unit_of_work
from src.models.{spec.name} import {names.class_name}Create, {names.class_name}Read, {names.class_name}Update
from src.routers.base import create_router
from src.routers.registry import register_router
from src.services.{spec.name} import {names.class_name}Service

router = create_router(prefix="/{names.plural}", tags=["{names.plural}"])
service = {names.class_name}Service()


@router.post("", response_model={names.class_name}Read, status_code=status.HTTP_201_CREATED)
async def create_{spec.name}(payload: {names.class_name}Create, uow: UnitOfWork = Depends(get_unit_of_work)):
    return await service.create(uow, payload)


@router.get("", response_model=list[{names.class_name}Read])
async def list_{names.plural}(
    offset: int = 0,
    limit: int = 100,
    uow: UnitOfWork = Depends(get_unit_of_work),
):
    return await service.list(uow, offset=offset, limit=limit)


@router.get("/{{item_id}}", response_model={names.class_name}Read)
async def get_{spec.name}(item_id: UUID, uow: UnitOfWork = Depends(get_unit_of_work)):
    item = await service.get(uow, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="{names.class_name} not found")
    return item


@router.patch("/{{item_id}}", response_model={names.class_name}Read)
async def update_{spec.name}(
    item_id: UUID,
    payload: {names.class_name}Update,
    uow: UnitOfWork = Depends(get_unit_of_work),
):
    item = await service.update(uow, item_id, payload)
    if item is None:
        raise HTTPException(status_code=404, detail="{names.class_name} not found")
    return item


@router.delete("/{{item_id}}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_{spec.name}(item_id: UUID, uow: UnitOfWork = Depends(get_unit_of_work)):
    deleted = await service.delete(uow, item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="{names.class_name} not found")


register_router(router, name="{names.router_name}")
"""


def render_frontend_feature(spec: ResourceSpec) -> str:
    names = names_for(spec.name)
    fields = ",\n".join(_frontend_field(field) for field in spec.fields)
    return f"""import {{ ResourceCrudPage, type ResourceCrudConfig }} from "../resourceCrud";

const config: ResourceCrudConfig = {{
  endpoint: "/{names.plural}",
  fields: [
{fields}
  ],
  name: "{spec.name}",
  title: "{_label(names.plural)}",
}};

function {names.class_name}Feature() {{
  return <ResourceCrudPage config={{config}} />;
}}

export default {{
  Component: {names.class_name}Feature,
  label: "{_label(names.plural)}",
  name: "{names.router_name}",
  path: "/{names.plural}",
}};
"""


def render_migration(spec: ResourceSpec, *, revision: str, down_revision: str | None = None) -> str:
    names = names_for(spec.name)
    enum_fields = [field for field in spec.fields if field.is_enum]
    enum_definitions = "\n".join(_migration_enum_definition(names, field) for field in enum_fields)
    enum_create = "\n".join(
        f"    create_postgres_enum({_migration_enum_variable(names, field)})" for field in enum_fields
    )
    columns = "\n".join(_migration_column(names, field) for field in spec.fields)
    enum_drop = "\n".join(
        f"    drop_postgres_enum({_migration_enum_variable(names, field)})" for field in reversed(enum_fields)
    )
    down_revision_value = f'"{down_revision}"' if down_revision else "None"
    enum_definitions_block = f"\n{enum_definitions}\n" if enum_definitions else ""
    enum_create_block = f"{enum_create}\n" if enum_create else ""
    enum_drop_block = f"\n{enum_drop}" if enum_drop else ""
    helper_import = (
        "\nfrom db.migrations.utils import create_postgres_enum, drop_postgres_enum, postgres_enum"
        if enum_fields
        else ""
    )
    return f'''"""create {names.table_name}

Revision ID: {revision}
Revises: {down_revision or "None"}
Create Date: {datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
{helper_import}

revision = "{revision}"
down_revision = {down_revision_value}
branch_labels = None
depends_on = None
{enum_definitions_block}

def upgrade() -> None:
{enum_create_block}    op.create_table(
        "{names.table_name}",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
{columns}
    )


def downgrade() -> None:
    op.drop_table("{names.table_name}")
{enum_drop_block}
'''


def render_schema_test(spec: ResourceSpec) -> str:
    names = names_for(spec.name)
    payload = ", ".join(f"{field.name}={_test_value(field)}" for field in spec.fields if not field.optional)
    return f"""from src.models.{spec.name} import {names.class_name}Create


def test_{spec.name}_create_schema_accepts_required_fields():
    payload = {names.class_name}Create({payload})

    assert payload is not None
"""


def render_router_test(spec: ResourceSpec) -> str:
    names = names_for(spec.name)
    return f"""from fastapi import FastAPI

from src.routers.{spec.name} import router


def test_{spec.name}_router_registers_crud_routes():
    app = FastAPI()
    app.include_router(router)

    paths = {{route.path for route in app.routes}}

    assert "/{names.plural}" in paths
    assert "/{names.plural}/{{item_id}}" in paths
"""


def render_resource_doc(spec: ResourceSpec, *, frontend: bool = False) -> str:
    names = names_for(spec.name)
    field_lines = "\n".join(f"- `{field.name}`: `{_field_doc_type(field)}`" for field in spec.fields)
    frontend_line = f"- Frontend feature: `frontend/src/features/{spec.name}/feature.tsx`\n" if frontend else ""
    return f"""# {names.class_name} Resource

Generated Cairn resource scaffold.

Source of truth:

- DB model: `db/models/{spec.name}.py`
- API schemas: `src/models/{spec.name}.py`
- Repository: `db/repositories/{spec.name}.py`
- Service: `src/services/{spec.name}.py`
- Router: `src/routers/{spec.name}.py`
- Migration stub: `db/migrations/versions/`
{frontend_line}

Fields:

{field_lines}
"""


def _model_imports(spec: ResourceSpec) -> str:
    standard_imports: list[str] = []
    if any(field.is_enum for field in spec.fields):
        standard_imports.append("import enum")
    if any(field.kind == "uuid" for field in spec.fields):
        standard_imports.append("import uuid")
    datetime_types = []
    if any(field.kind == "date" for field in spec.fields):
        datetime_types.append("date")
    if any(field.kind == "datetime" for field in spec.fields):
        datetime_types.append("datetime")
    if datetime_types:
        standard_imports.append(f"from datetime import {', '.join(datetime_types)}")

    sqlalchemy_imports: list[str] = []
    sqlalchemy_types = sorted({_sqlalchemy_type(field) for field in spec.fields if _sqlalchemy_type(field)})
    if "Enum as SQLEnum" in sqlalchemy_types:
        sqlalchemy_imports.append("from sqlalchemy import Enum as SQLEnum")
        sqlalchemy_types.remove("Enum as SQLEnum")
    if sqlalchemy_types:
        sqlalchemy_imports.append(f"from sqlalchemy import {', '.join(sqlalchemy_types)}")
    if any(field.kind == "uuid" for field in spec.fields):
        sqlalchemy_imports.append("from sqlalchemy.dialects.postgresql import UUID")
    sqlalchemy_imports.append("from sqlalchemy.orm import Mapped, mapped_column")

    return "\n\n".join(section for section in ("\n".join(standard_imports), "\n".join(sqlalchemy_imports)) if section)


def _schema_imports(spec: ResourceSpec) -> str:
    datetime_types = ["datetime"]
    if any(field.kind == "date" for field in spec.fields):
        datetime_types.insert(0, "date")
    standard_imports = [f"from datetime import {', '.join(datetime_types)}", "from uuid import UUID"]

    local_imports = []
    enum_names = [_enum_name(names_for(spec.name), field) for field in spec.fields if field.is_enum]
    if enum_names:
        local_imports.append(f"from db.models.{spec.name} import {', '.join(enum_names)}")
    local_imports.append("from src.models.base import BaseSchema")
    return "\n\n".join(("\n".join(standard_imports), "\n".join(local_imports)))


def _enum_class(names: ResourceNames, field: FieldSpec) -> str:
    values = "\n".join(f'    {value.upper()} = "{value}"' for value in field.enum_values)
    return f"class {_enum_name(names, field)}(str, enum.Enum):\n{values}"


def _model_field(names: ResourceNames, field: FieldSpec) -> str:
    annotation = _python_type(names, field)
    if field.optional:
        annotation = f"{annotation} | None"
    column_type = _column_type(names, field)
    if field.is_enum:
        return f"""    {field.name}: Mapped[{annotation}] = mapped_column(
        {column_type}, nullable={field.optional}
    )"""
    return f"    {field.name}: Mapped[{annotation}] = mapped_column({column_type}, nullable={field.optional})"


def _schema_field(names: ResourceNames, field: FieldSpec, *, create: bool) -> str:
    annotation = _python_type(names, field, for_schema=True)
    if field.optional or not create:
        return f"{field.name}: {annotation} | None = None"
    return f"{field.name}: {annotation}"


def _migration_column(names: ResourceNames, field: FieldSpec) -> str:
    return f'        sa.Column("{field.name}", {_migration_type(names, field)}, nullable={field.optional}),'


def _sqlalchemy_type(field: FieldSpec) -> str | None:
    return {
        "string": "String",
        "text": "Text",
        "int": "Integer",
        "float": "Float",
        "bool": "Boolean",
        "datetime": "DateTime",
        "date": "Date",
        "enum": "Enum as SQLEnum",
    }.get(field.kind)


def _column_type(names: ResourceNames, field: FieldSpec) -> str:
    if field.kind == "string":
        return "String(255)"
    if field.kind == "text":
        return "Text()"
    if field.kind == "int":
        return "Integer()"
    if field.kind == "float":
        return "Float()"
    if field.kind == "bool":
        return "Boolean()"
    if field.kind == "datetime":
        return "DateTime(timezone=True)"
    if field.kind == "date":
        return "Date()"
    if field.kind == "uuid":
        return "UUID(as_uuid=True)"
    if field.is_enum:
        return (
            f'SQLEnum({_enum_name(names, field)}, values_callable=_enum_values, name="{names.singular}_{field.name}")'
        )
    raise ValueError(f"Unsupported field kind: {field.kind}")


def _migration_type(names: ResourceNames, field: FieldSpec) -> str:
    if field.kind == "string":
        return "sa.String(length=255)"
    if field.kind == "text":
        return "sa.Text()"
    if field.kind == "int":
        return "sa.Integer()"
    if field.kind == "float":
        return "sa.Float()"
    if field.kind == "bool":
        return "sa.Boolean()"
    if field.kind == "datetime":
        return "sa.DateTime(timezone=True)"
    if field.kind == "date":
        return "sa.Date()"
    if field.kind == "uuid":
        return "postgresql.UUID(as_uuid=True)"
    if field.is_enum:
        return _migration_enum_variable(names, field)
    raise ValueError(f"Unsupported field kind: {field.kind}")


def _python_type(names: ResourceNames, field: FieldSpec, *, for_schema: bool = False) -> str:
    if field.is_enum:
        return _enum_name(names, field)
    return {
        "string": "str",
        "text": "str",
        "int": "int",
        "float": "float",
        "bool": "bool",
        "datetime": "datetime",
        "date": "date",
        "uuid": "uuid.UUID" if not for_schema else "UUID",
    }[field.kind]


def _enum_name(names: ResourceNames, field: FieldSpec) -> str:
    return f"{names.class_name}{''.join(part.capitalize() for part in field.name.split('_'))}"


def _migration_enum_variable(names: ResourceNames, field: FieldSpec) -> str:
    return f"{names.singular}_{field.name}_enum"


def _migration_enum_definition(names: ResourceNames, field: FieldSpec) -> str:
    values = ", ".join(f'"{value}"' for value in field.enum_values)
    return f'{_migration_enum_variable(names, field)} = postgres_enum("{names.singular}_{field.name}", [{values}])'


def _indent_or_pass(lines: str) -> str:
    if not lines:
        return "    pass"
    return "\n".join(f"    {line}" for line in lines.splitlines())


def _indent_or_empty(lines: str) -> str:
    if not lines:
        return ""
    return "\n" + "\n".join(f"    {line}" for line in lines.splitlines())


def _test_value(field: FieldSpec) -> str:
    if field.is_enum:
        return f'"{field.enum_values[0]}"'
    return {
        "string": '"example"',
        "text": '"example"',
        "int": "1",
        "float": "1.0",
        "bool": "True",
        "datetime": '"2026-01-01T00:00:00Z"',
        "date": '"2026-01-01"',
        "uuid": '"00000000-0000-0000-0000-000000000001"',
    }[field.kind]


def _field_doc_type(field: FieldSpec) -> str:
    if field.is_enum:
        return f"enum[{', '.join(field.enum_values)}]"
    suffix = " optional" if field.optional else ""
    return f"{field.kind}{suffix}"


def _frontend_field(field: FieldSpec) -> str:
    enum_values = ""
    if field.is_enum:
        values = ", ".join(f'"{value}"' for value in field.enum_values)
        enum_values = f", enumValues: [{values}]"
    return (
        "    { "
        f'label: "{_label(field.name)}", name: "{field.name}", optional: {str(field.optional).lower()}, '
        f'type: "{field.kind}"{enum_values} '
        "}"
    )


def _label(value: str) -> str:
    return " ".join(part.capitalize() for part in value.split("_"))
