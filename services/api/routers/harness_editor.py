from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.exceptions import RequestValidationError
from psycopg2 import IntegrityError

from services.api.models.shared.harness import get_item_by_id
from services.api.routers.shared.base_controller import HarnessRoute
from services.harness.editor import decode, descriptors
from services.harness.editor_contracts import EditorDecode, EditorSave
from services.harness.editor_service import (
    EditorConflict,
    EditorNotFound,
    draft_content,
    save_editor,
)


class EditorRoute(HarnessRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def without_input_echo(request):
            try:
                return await handler(request)
            except RequestValidationError as error:
                details = [
                    {key: item[key] for key in ("loc", "msg", "type")}
                    for item in error.errors()
                ]
                raise HTTPException(422, details) from None

        return without_input_echo


router = APIRouter(route_class=EditorRoute)


def _run(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except EditorConflict as error:
        raise HTTPException(409, str(error)) from None
    except EditorNotFound as error:
        raise HTTPException(404, str(error)) from None
    except IntegrityError:
        raise HTTPException(
            409, "The item identity or version changed. Reload before saving."
        ) from None
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@router.get("/editor/descriptors")
def editor_descriptors():
    return descriptors()


@router.post("/editor/{kind}/decode")
def decode_editor(kind: str, request: EditorDecode):
    return _run(decode, kind, request.name, request.content)


@router.post("/editor/{kind}/preview")
def preview_editor(kind: str, request: EditorSave):
    source = (
        {
            "content": request.original_content,
            "name": request.source_name or request.common.name,
        }
        if request.original_content is not None
        else None
    )
    content = _run(draft_content, kind, request, source, preview=True)
    return {
        "content": content,
        "draft": _run(decode, kind, request.common.name, content),
    }


@router.get("/editor/{kind}/{item_id}")
def get_editor(kind: str, item_id: int):
    if kind not in descriptors()["types"]:
        raise HTTPException(404, "Unsupported editor type")
    item = get_item_by_id(kind, item_id)
    if item is None:
        raise HTTPException(404, "Harness item not found")
    return {"item": item, "draft": _run(decode, kind, item["name"], item["content"])}


@router.post("/editor/{kind}", status_code=201)
def create_editor(kind: str, request: EditorSave):
    return _run(save_editor, kind, request)


@router.put("/editor/{kind}/{item_id}")
def update_editor(kind: str, item_id: int, request: EditorSave):
    if request.expected_version is None or request.expected_updated_at is None:
        raise HTTPException(
            422, "expected_version and expected_updated_at are required for editing"
        )
    return _run(save_editor, kind, request, item_id=item_id)
