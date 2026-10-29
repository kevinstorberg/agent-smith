"""Keep directed relationship analysis ownership and proof beside its text."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "8a3b0d7e9f21"
down_revision = "7f2a9c6d8e10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("profile_relationships", sa.Column("analysis_evidence", JSONB, nullable=False,
                                                    server_default=sa.text("jsonb_build_object('version',1,'human',false)")))
    op.execute("UPDATE profile_relationships SET analysis_evidence=jsonb_build_object('version',1,'human',human_confirmed)")
    op.create_check_constraint("relationship_analysis_object", "profile_relationships", "jsonb_typeof(analysis_evidence)='object'")


def downgrade() -> None:
    unsafe = op.get_bind().execute(sa.text("""SELECT EXISTS (
        SELECT 1 FROM profile_relationships WHERE notes<>'' AND analysis_evidence->>'human'='false'
        UNION ALL SELECT 1 FROM profile_relationships WHERE jsonb_path_exists(history,
            '$.** ? (@.analysis_evidence.human == false && @.notes != "")')
        UNION ALL SELECT 1 FROM profile_revisions WHERE jsonb_path_exists(changes,
            '$.** ? (@.analysis_evidence.human == false && @.notes != "")'))""")).scalar()
    if unsafe:
        raise RuntimeError("Cannot downgrade relationship analysis while generated current or historical notes require source protection")
    op.drop_constraint("relationship_analysis_object", "profile_relationships", type_="check")
    op.drop_column("profile_relationships", "analysis_evidence")
