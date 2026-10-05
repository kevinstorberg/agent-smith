"""relax chat message author check for configurable AI participants

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-09-10
"""
from typing import Sequence, Union

from alembic import op


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # AI chat participants are configured via CHAT_MODEL_NAMES, so the author
    # column can no longer enumerate identities. Enumerated-identity
    # enforcement lives in services/chat/service.py's posting functions; the
    # database keeps a sanity bound only.
    op.drop_constraint("ck_chat_messages_author", "chat_messages", type_="check")
    op.create_check_constraint(
        "ck_chat_messages_author",
        "chat_messages",
        "length(btrim(author)) BETWEEN 1 AND 64",
    )


def downgrade() -> None:
    # Destructive by necessity: rows authored by configured AI participants
    # violate the original fixed list. Dev-only path.
    op.execute(
        "DELETE FROM chat_messages WHERE author NOT IN ('user', 'claude', 'codex', 'gemini')"
    )
    op.drop_constraint("ck_chat_messages_author", "chat_messages", type_="check")
    op.create_check_constraint(
        "ck_chat_messages_author",
        "chat_messages",
        "author IN ('user', 'claude', 'codex', 'gemini')",
    )
