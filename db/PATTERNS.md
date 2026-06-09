# Database Patterns

This file documents SQLAlchemy pitfalls that are easy to forget and not obvious
from the template source. Authoritative implementations live in `db/` and
`tests/conftest.py`.

## PostgreSQL ARRAY Types

Use SQLAlchemy types inside PostgreSQL `ARRAY()`, not Python primitives.

```python
from sqlalchemy import Float
from sqlalchemy.dialects.postgresql import ARRAY

embedding: Mapped[list[float]] = mapped_column(ARRAY(Float))
```

`ARRAY(float)` fails because Python `float` is not a SQLAlchemy type object.

## Self-Referential Relationships

Self-referential relationships need explicit `foreign_keys` and `remote_side`.

```python
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship


class Node(Base):
    __tablename__ = "nodes"

    id: Mapped[str] = mapped_column(primary_key=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("nodes.id"))

    children: Mapped[list["Node"]] = relationship(
        "Node",
        back_populates="parent",
        foreign_keys="[Node.parent_id]",
    )
    parent: Mapped["Node | None"] = relationship(
        "Node",
        back_populates="children",
        remote_side="[Node.id]",
    )
```

Without those hints, SQLAlchemy cannot infer which side of the relationship is
the parent.

## Enum Values

If your Python enum inherits from `str`, store enum values rather than enum names:

```python
from enum import Enum
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column


class Status(str, Enum):
    PENDING = "pending"
    DONE = "done"


status: Mapped[Status] = mapped_column(
    SQLEnum(Status, values_callable=lambda values: [item.value for item in values]),
    nullable=False,
    default=Status.PENDING,
)
```

Without `values_callable`, SQLAlchemy stores names such as `PENDING`, which can
surprise application code expecting `pending`.

## Async Relationship Loading

Do not trigger lazy relationship loading in async SQLAlchemy. Eager load the
relationship in the original query.

```python
from sqlalchemy import select
from sqlalchemy.orm import selectinload


result = await session.execute(
    select(Node)
    .where(Node.id == node_id)
    .options(selectinload(Node.children))
)
node = result.scalar_one()
children = node.children
```

Lazy loading outside the query can raise greenlet errors in async code.

## Mixins

Use the existing mixins in `db/base.py`:

- `TimestampMixin`
- `UUIDMixin`

Do not redefine timestamp or UUID columns in each model unless the app has a
specific schema requirement that differs from the template.

## Test Engines

Use the fixtures in `tests/conftest.py`. They resolve the test database through
`Settings.database_url_for("test")` and use `NullPool` to avoid shared connection
state between tests.

Do not hard-code test database URLs in individual test modules.

## Further Reading

- [SQLAlchemy Async Documentation](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [PostgreSQL ARRAY Types](https://www.postgresql.org/docs/current/arrays.html)
- [Self-Referential Relationships](https://docs.sqlalchemy.org/en/20/orm/self_referential.html)
