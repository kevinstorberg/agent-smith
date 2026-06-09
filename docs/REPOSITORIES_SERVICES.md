# Repositories And Services

Cairn separates database-backed application code into three layers:

| Layer | Owns | Does not own |
| --- | --- | --- |
| Router | HTTP validation, auth dependencies, response shape | Business rules, SQL queries, commits |
| Service | Use-case flow, business rules, transaction boundary | HTTP details, SQL construction |
| Repository | SQLAlchemy queries for one aggregate/model area | Commits, rollbacks, request handling |

## Repository Convention

Subclass `BaseRepository` for app-specific query methods:

```python
from db.repository import BaseRepository
from db.models.project import Project


class ProjectRepository(BaseRepository[Project]):
    model = Project
```

Repositories receive an `AsyncSession`, call SQLAlchemy, and never commit or
roll back. This keeps transaction ownership in one place.

## Unit Of Work Convention

Use `get_unit_of_work()` in FastAPI routes that perform writes:

```python
from fastapi import Depends

from db.unit_of_work import UnitOfWork, get_unit_of_work


async def create_project(uow: UnitOfWork = Depends(get_unit_of_work)):
    ...
```

Use `unit_of_work()` in scripts, jobs, tools, and graph nodes. Successful blocks
commit once; exceptions roll back and re-raise.

## Service Convention

Application services inherit `ApplicationService` when they need a standard
unit-of-work factory:

```python
from src.services.application import ApplicationService


class ProjectService(ApplicationService):
    async def create_project(self, data):
        async with self.create_unit_of_work() as uow:
            ...
```

Keep these services separate from `src.services.base`, which is for
lifecycle-managed infrastructure services such as embeddings.
