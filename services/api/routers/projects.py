from fastapi import APIRouter, Depends, HTTPException, Path, Request

from services.action_items import db
from services.action_items.contracts import (
    ProjectMetadataCreate,
    ProjectPatch,
    ProjectQuery,
)
from services.api.routers.shared.items import call_item

router = APIRouter()


def _query(
    request: Request,
    q: str | None = None,
    sort: str = "name_asc",
    limit: int = 10,
    offset: int = 0,
) -> ProjectQuery:
    unknown = set(request.query_params) - ProjectQuery.model_fields.keys()
    if unknown:
        raise HTTPException(
            422, f"Unknown project filters: {', '.join(sorted(unknown))}"
        )
    return call_item(
        ProjectQuery.model_validate,
        {"q": q, "sort": sort, "limit": limit, "offset": offset},
    )


@router.get("")
def list_projects(query: ProjectQuery = Depends(_query)):
    return call_item(db.list_project_details, query)


@router.post("", status_code=201)
def create_project(body: ProjectMetadataCreate):
    return call_item(db.create_project_details, body)


@router.get("/{project_id}")
def get_project(project_id: int = Path(gt=0)):
    return call_item(db.get_project_details, project_id)


@router.patch("/{project_id}")
def update_project(body: ProjectPatch, project_id: int = Path(gt=0)):
    return call_item(db.update_project_details, project_id, body)
