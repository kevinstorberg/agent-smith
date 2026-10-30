"""Record explicit, bounded requests to revisit saved meeting analysis."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "a2c5e8f1b4d7"
down_revision = "91b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("meeting_analysis_requests",
        sa.Column("request_id", UUID(as_uuid=False), primary_key=True),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("result", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("jsonb_typeof(payload)='object' AND octet_length(payload::text)<=50000", name="analysis_request_payload"),
        sa.CheckConstraint("jsonb_typeof(result)='object' AND octet_length(result::text)<=100000", name="analysis_request_result"),
    )
    op.add_column("meeting_digestions", sa.Column("manual_analysis", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.create_check_constraint("manual_analysis_control", "meeting_digestions",
        "jsonb_typeof(manual_analysis)='object' AND octet_length(manual_analysis::text)<=10000")


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM meeting_digestions WHERE manual_analysis<>'{}'::jsonb)")).scalar():
        raise RuntimeError("Cannot downgrade while manual analysis request controls exist")
    op.drop_constraint("manual_analysis_control", "meeting_digestions", type_="check")
    op.drop_column("meeting_digestions", "manual_analysis")
    op.drop_table("meeting_analysis_requests")
