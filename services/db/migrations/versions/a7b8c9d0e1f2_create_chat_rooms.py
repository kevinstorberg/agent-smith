"""create Chat Rooms tables

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-09-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_rooms",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("topic", sa.Text, nullable=False),
        sa.Column("context", sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("length(btrim(topic)) BETWEEN 1 AND 200", name="ck_chat_rooms_topic"),
        sa.CheckConstraint("length(context) <= 20000", name="ck_chat_rooms_context"),
    )
    op.create_index("idx_chat_rooms_updated", "chat_rooms", [sa.text("updated_at DESC")])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "room_id",
            sa.Integer,
            sa.ForeignKey("chat_rooms.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("author", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "author IN ('user', 'claude', 'codex', 'gemini')",
            name="ck_chat_messages_author",
        ),
        sa.CheckConstraint("length(btrim(body)) BETWEEN 1 AND 8000", name="ck_chat_messages_body"),
    )
    op.create_index("idx_chat_messages_room_id", "chat_messages", ["room_id", "id"])


def downgrade() -> None:
    op.drop_table("chat_messages")
    op.drop_table("chat_rooms")
