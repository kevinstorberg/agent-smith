from __future__ import annotations

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Query as QueryParam,
    Request,
)

from services.action_items import db, queue_db
from services.action_items.queue_contracts import (
    EpicCreate,
    EpicPatch,
    EpicRemove,
    Membership,
    QueueMove,
    QueueKind,
    QueueQuery,
)
from services.action_items.contracts import (
    Create,
    Delete,
    Move,
    MAX_DUE_WINDOW_HOURS,
    Patch,
    ProjectCreate,
    Query,
)
from services.api.routers.shared.items import call_item as _call

router = APIRouter()


def _query_fields(
    request: Request,
    q: str | None = None,
    status: str = "open",
    project: str | None = None,
    tags: list[str] = QueryParam(default=[]),
    sort: str | None = None,
    limit: int = 10,
    offset: int = 0,
    unassigned: bool = False,
    priority_only: bool = False,
    due_within_hours: int | None = None,
) -> dict:
    for field in ("unassigned", "priority_only"):
        if field in request.query_params and request.query_params[field] not in {
            "true",
            "false",
        }:
            raise HTTPException(422, f"{field} must be true or false")
    if "due_within_hours" in request.query_params:
        hours = request.query_params["due_within_hours"]
        if not hours.isascii() or not hours.isdecimal():
            raise HTTPException(
                422,
                f"due_within_hours must be an integer from 1 through {MAX_DUE_WINDOW_HOURS}",
            )
    return {
        "q": q,
        "status": status,
        "project": project,
        "tags": tags,
        "sort": sort,
        "limit": limit,
        "offset": offset,
        "unassigned": unassigned,
        "priority_only": priority_only,
        "due_within_hours": due_within_hours,
    }


def _validated_query(request: Request, fields: dict, model: type[Query]) -> Query:
    unknown = set(request.query_params) - model.model_fields.keys()
    if unknown:
        raise HTTPException(
            422, f"Unknown action item filters: {', '.join(sorted(unknown))}"
        )
    return _call(model.model_validate, fields)


def _query(request: Request, fields: dict = Depends(_query_fields)) -> Query:
    return _validated_query(request, fields, Query)


def _queue_query(
    request: Request,
    kind: QueueKind = "all",
    fields: dict = Depends(_query_fields),
) -> QueueQuery:
    return _validated_query(request, {**fields, "kind": kind}, QueueQuery)


@router.get("")
def list_all(query: Query = Depends(_query)):
    return _call(db.list_items, query)


@router.post("", status_code=201)
def create(body: Create):
    return _call(db.create, body)


@router.get("/queue")
def grouped_queue(query: QueueQuery = Depends(_queue_query)):
    return _call(queue_db.list_queue, query)


@router.post("/queue/move")
def move_queue(body: QueueMove):
    return _call(queue_db.move, body)


@router.get("/epics")
def list_epics():
    return _call(queue_db.list_epics)


@router.post("/epics", status_code=201)
def create_epic(body: EpicCreate):
    return _call(queue_db.create_epic, body)


@router.patch("/epics/{epic_id}")
def rename_epic(body: EpicPatch, epic_id: int = Path(gt=0)):
    return _call(queue_db.rename_epic, epic_id, body)


@router.delete("/epics/{epic_id}")
def remove_epic(body: EpicRemove, epic_id: int = Path(gt=0)):
    return _call(queue_db.remove_epic, epic_id, body)


@router.post("/{item_id}/epic")
def set_epic(body: Membership, item_id: int = Path(gt=0)):
    return _call(queue_db.set_membership, item_id, body)


@router.get("/projects")
def list_projects():
    return _call(db.list_projects)


@router.post("/projects", status_code=201)
def create_project(body: ProjectCreate):
    return _call(db.create_project, body)


@router.delete("/projects/{project_id}")
def delete_project(project_id: int = Path(gt=0)):
    return _call(db.delete_project, project_id)


@router.get("/{item_id}")
def get_one(item_id: int = Path(gt=0)):
    return _call(db.get, item_id)


@router.patch("/{item_id}")
def update(body: Patch, item_id: int = Path(gt=0)):
    return _call(db.update, item_id, body)


@router.delete("/{item_id}")
def delete(body: Delete, item_id: int = Path(gt=0)):
    return _call(db.delete, item_id, body)


@router.post("/{item_id}/move")
def move(body: Move, item_id: int = Path(gt=0)):
    return _call(db.move, item_id, body)
