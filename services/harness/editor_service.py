from __future__ import annotations

from psycopg2.extras import RealDictCursor

from services.api.models.shared import harness
from services.harness.editor import compose, compose_raw, raw_definition
from services.harness.editor_codecs import prepare_rule_clone


class EditorConflict(ValueError):
    pass


class EditorNotFound(ValueError):
    pass


def _draft_definition(kind, request, source=None, *, preview=False):
    if request.mode == "raw":
        prepared = source["content"] if source else None
        persisted_unchanged = (
            source is not None
            and request.raw == raw_definition(kind, source["name"], source["content"])
            and request.common.name == source["name"]
            and not request.dirty_paths
        )
        if request.dirty_paths or source is None:
            prepared = compose(
                kind,
                request.common.name,
                fields=request.fields,
                extensions=request.extensions,
                original_content=prepared,
                source_name=source["name"] if source else None,
                dirty_paths=request.dirty_paths,
                validate=False,
                clone_as_skill=request.common.clone_as_skill,
                agents=request.common.agents,
            )
        return compose_raw(
            kind,
            request.common.name,
            request.raw,
            prepared,
            allow_unchanged=persisted_unchanged,
            clone_as_skill=request.common.clone_as_skill,
            agents=request.common.agents,
        )
    return compose(
        kind,
        request.common.name,
        fields=request.fields,
        extensions=request.extensions,
        original_content=source["content"] if source else None,
        source_name=source["name"] if source else None,
        dirty_paths=request.dirty_paths,
        validate=not preview,
        clone_as_skill=request.common.clone_as_skill,
        agents=request.common.agents,
    )


def draft_content(kind, request, source=None, *, preview=False):
    content = _draft_definition(kind, request, source, preview=preview)
    if (
        not preview
        and kind == "rule"
        and request.common.clone_as_skill
        and (source is None or not source["clone_as_skill"])
    ):
        return prepare_rule_clone(request.common.name, content)
    return content


def save_editor(kind, request, *, item_id=None):
    if kind not in harness.VALID_TABLES:
        raise ValueError("item_type is unsupported")
    common = request.common
    if common.clone_as_skill and kind != "rule":
        raise ValueError("common.clone_as_skill is supported only for rules")
    with harness.harness_write(kind) as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            source = None
            if item_id is not None:
                cursor.execute(
                    f"SELECT * FROM {harness._table(kind)} WHERE id=%s FOR UPDATE",
                    (item_id,),
                )
                source = cursor.fetchone()
                if source is None:
                    raise EditorNotFound("Harness item not found")
                latest = harness._get_scoped_item(
                    cursor, kind, source["name"], source["project"], for_update=True
                )
                if (
                    latest is None
                    or latest["id"] != item_id
                    or source["version"] != request.expected_version
                    or source["updated_at"] != request.expected_updated_at
                ):
                    raise EditorConflict(
                        "This item changed. Reload its current version before saving the retained draft."
                    )
            destination = harness._get_scoped_item(
                cursor, kind, common.name, common.project, for_update=True
            )
            if destination is not None and (
                source is None or destination["id"] != source["id"]
            ):
                raise EditorConflict(
                    "common.name and common.project already identify another item"
                )
        content = draft_content(kind, request, source)
        fields = {
            key: getattr(common, key)
            for key in ("name", "project", "sort_key", "agents", "subagents", "enabled")
        }
        if kind == "rule":
            fields["clone_as_skill"] = common.clone_as_skill
        if source is not None and content == source["content"]:
            changes = {
                key: value for key, value in fields.items() if value != source[key]
            }
            if changes:
                harness._get_model(kind).dynamic_update(
                    item_id, changes, conn=connection
                )
            saved_id = item_id
        else:
            saved_id = harness._insert_version(
                connection,
                kind,
                {
                    **fields,
                    "content": content,
                    "version": source["version"] + 1 if source else 1,
                },
                source,
                device=common.device,
                repo=common.repo,
            )
    return harness.get_item_by_id(kind, saved_id)
