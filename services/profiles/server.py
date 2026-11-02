from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from scripts.shared.paths import bootstrap
bootstrap()

from mcp.types import ToolAnnotations

from services.action_items import db
from services.action_items.contracts import Delete, ItemCreate, ItemPatch, ItemQuery, Move, PositiveInt
from services.mcp_contracts import ContractMCP
from services.meetings import profile_db
from services.profiles.contracts import (ProfileId, ProfileQuery, ProfileScope, TopicCreate, TopicDelete,
                                        TopicGet, TopicList, TopicMove, TopicUpdate)

_IDENTITY_FIELDS = ("id", "display_name", "email", "emails", "nicknames", "tags", "starred", "metadata",
                    "revision", "created_at", "updated_at")
_EMAIL_LIMIT = 20
_READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False)
_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False)


def _identity(profile: dict) -> dict:
    result = {key: profile[key] for key in _IDENTITY_FIELDS if key in profile}
    emails = result.get("emails", [])
    result.update(emails=emails[:_EMAIL_LIMIT], emails_omitted=max(0, len(emails) - _EMAIL_LIMIT))
    return result


def profile_list(q: str | None = None, limit: int = 10, offset: int = 0) -> dict[str, Any]:
    """Find canonical profiles by name, email, nickname, company, or role before managing discussion topics.

    Returns bounded identity/metadata summaries and total. Limit 1-100; offset nonnegative.
    Deleted profiles and merged aliases are excluded; aliases can still match the search.
    Alias emails are capped at 20 per result; emails_omitted reports the remaining count.
    Select the intended profile ID explicitly when names are ambiguous.
    """
    query = ProfileQuery.model_validate({"q": q, "limit": limit, "offset": offset})
    result = profile_db.list_profiles(query=query.q, limit=query.limit, offset=query.offset)
    return {**result, "items": [_identity(profile) for profile in result["items"]]}


def profile_get(profile_id: ProfileId) -> dict[str, Any]:
    """Read a canonical profile's identity and metadata, resolving a merged alias to its surviving ID.

    Does not return generated evidence/history. Alias emails are capped at 20, with emails_omitted.
    Discussion topics are read with profile_topic_list.
    """
    owner = ProfileScope.model_validate({"profile_id": profile_id})
    profile = profile_db.get_profile(owner.profile_id, include_evidence=False)
    if profile is None:
        raise db.NotFound("Profile not found or deleted")
    return _identity(profile)


def profile_topic_list(profile_id: ProfileId, q: str | None = None, status: str = "open",
                       tags: list[str] | None = None, sort: str | None = None,
                       limit: int = 10, offset: int = 0) -> dict[str, Any]:
    """List one person's discussion topics for meeting preparation; includes canonical profile_id even when empty.

    Search title/notes with q. Status: open, completed, all. All supplied tags must match.
    Sort: manual (open only), completed (completed only), newest, updated, title.
    Defaults: open/manual, completed/completed, all/newest. Limit 1-100, offset nonnegative.
    List rows omit full notes; use profile_topic_get before editing.
    """
    query = ItemQuery.model_validate({"q": q, "status": status, "tags": [] if tags is None else tags, "sort": sort,
                                     "limit": limit, "offset": offset})
    return db.profile_queue(profile_id).list_items(query.model_dump())


def profile_topic_get(profile_id: ProfileId, item_id: PositiveInt) -> dict[str, Any]:
    """Read a discussion topic's full Markdown notes and current revision within its profile's queue."""
    return db.profile_queue(profile_id).get(item_id)


def profile_topic_create(profile_id: ProfileId, title: str, description: str = "", tags: list[str] | None = None,
                         status: str = "open", request_id: str | None = None) -> dict[str, Any]:
    """Add an important topic to discuss with this person. description holds optional Markdown notes.

    Appends to this person's open priority queue. Optional UUID request_id makes an uncertain retry safe:
    reuse the original UUID/input; deleted UUIDs remain reserved. No model or persona analysis runs.
    """
    request = ItemCreate.model_validate({"title": title, "description": description, "tags": [] if tags is None else tags,
                                        "status": status, "request_id": request_id})
    return db.profile_queue(profile_id).create(request.model_dump())


def profile_topic_update(profile_id: ProfileId, item_id: PositiveInt, changes: ItemPatch) -> dict[str, Any]:
    """Edit a topic or explicitly complete/reopen it with changes.status (completed/open).

    Supply current changes.expected_revision. Omitted fields stay unchanged; description:null/empty and tags:[]
    clear notes/tags. On conflict, reread before resubmitting. The topic's profile cannot be changed.
    """
    patch = ItemPatch.model_validate(changes)
    return db.profile_queue(profile_id).update(item_id, patch.model_dump(exclude_unset=True))


def profile_topic_delete(profile_id: ProfileId, item_id: PositiveInt, expected_revision: PositiveInt) -> dict[str, Any]:
    """Delete a topic using its current item revision. Creation retries cannot restore a deleted topic."""
    return db.profile_queue(profile_id).delete(item_id, Delete(expected_revision=expected_revision))


def profile_topic_move(profile_id: ProfileId, item_id: PositiveInt, expected_revision: PositiveInt,
                       before_id: PositiveInt | None = None, after_id: PositiveInt | None = None) -> dict[str, Any]:
    """Prioritize an open topic before OR after another open topic belonging to the same person.

    Supply current item revision and exactly one neighbor. Page-bottom means after that page's neighbor,
    not the end of the full queue. Cross-profile/global anchors are rejected; conflicts require a reread.
    """
    return db.profile_queue(profile_id).move(item_id, Move(expected_revision=expected_revision,
                                                          before_id=before_id, after_id=after_id))


_INPUTS = {"profile_list": ProfileQuery, "profile_get": ProfileScope, "profile_topic_list": TopicList,
           "profile_topic_get": TopicGet, "profile_topic_create": TopicCreate, "profile_topic_update": TopicUpdate,
           "profile_topic_delete": TopicDelete, "profile_topic_move": TopicMove}


def create_server() -> ContractMCP:
    server = ContractMCP("profiles - find people and manage their discussion topics", _INPUTS)
    for function in (profile_list, profile_get, profile_topic_list, profile_topic_get, profile_topic_create,
                     profile_topic_update, profile_topic_delete, profile_topic_move):
        annotation = _READ if function in (profile_list, profile_get, profile_topic_list, profile_topic_get) else _WRITE
        if function is profile_topic_delete:
            annotation = ToolAnnotations(readOnlyHint=False, destructiveHint=True)
        server.add_tool(function, annotations=annotation)
    return server


mcp = create_server()


if __name__ == "__main__":
    mcp.run()
