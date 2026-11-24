"""Protect filtered Action Item publication and scoped enrollment."""

from alembic import op
import sqlalchemy as sa

revision = "e4b7c9d2a6f1"
down_revision = "c8f3a2d1e6b9"
branch_labels = None
depends_on = None


def _quiescent() -> None:
    active = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT meeting_id FROM meeting_action_item_runs "
                "WHERE claim_until>clock_timestamp() LIMIT 1"
            )
        )
        .scalar()
    )
    if active is not None:
        raise RuntimeError(
            "Stop Action Item workers before changing the filtering protocol"
        )
    op.execute(
        "UPDATE meeting_action_item_runs SET claim_owner=NULL,claim_until=NULL "
        "WHERE claim_owner IS NOT NULL"
    )


def _lock() -> None:
    op.execute("SET LOCAL lock_timeout='5s'")
    op.execute(
        "LOCK TABLE meeting_sync_state,meeting_action_item_runs,"
        "action_item_proposals,action_item_proposal_payloads,"
        "action_item_proposal_receipts IN ACCESS EXCLUSIVE MODE"
    )
    _quiescent()


def upgrade() -> None:
    _lock()
    op.add_column(
        "meeting_sync_state",
        sa.Column(
            "action_items_activated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
    )
    op.execute(
        """UPDATE meeting_sync_state state SET action_items_activated_at=proof.activated_at
        FROM (SELECT source.provider,source.account_key,min(run.created_at) AS activated_at
              FROM meeting_action_item_runs run
              JOIN meeting_summaries source ON source.id=run.meeting_id
              GROUP BY source.provider,source.account_key) proof
        WHERE state.provider=proof.provider AND state.account_key=proof.account_key"""
    )
    op.add_column("action_item_proposals", sa.Column("superseded_by_id", sa.Integer()))
    op.create_foreign_key(
        "action_item_proposal_replacement",
        "action_item_proposals",
        "action_item_proposals",
        ["superseded_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_constraint("action_item_proposal_status", "action_item_proposals")
    op.create_check_constraint(
        "action_item_proposal_status",
        "action_item_proposals",
        "status IN ('pending','approved','rejected','superseded')",
    )
    op.create_check_constraint(
        "action_item_proposal_supersession",
        "action_item_proposals",
        "superseded_by_id IS NULL OR (status='superseded' AND superseded_by_id<>id)",
    )
    op.create_check_constraint(
        "meeting_action_item_protocol",
        "meeting_action_item_runs",
        "claim_owner IS NULL OR claim_owner ~ '^v2:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
    )
    op.execute(
        """CREATE FUNCTION validate_action_item_dismissal() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE current_status text; expected_key text;
        BEGIN
            IF NEW.proposal_id IS NULL THEN RETURN NEW; END IF;
            SELECT status INTO current_status FROM action_item_proposals
                WHERE id=NEW.proposal_id FOR UPDATE;
            SELECT decision_key INTO expected_key FROM action_item_proposal_payloads
                WHERE proposal_id=NEW.proposal_id;
            IF current_status IS NULL OR current_status NOT IN ('pending','rejected')
               OR expected_key IS DISTINCT FROM NEW.decision_key THEN
                RAISE EXCEPTION 'Dismissals require a pending or rejected Action Item proposal and its original decision key'
                    USING ERRCODE='23514', CONSTRAINT='action_item_dismissal_source';
            END IF;
            RETURN NEW;
        END $$"""
    )
    op.execute(
        """CREATE TRIGGER action_item_dismissal_source
        BEFORE INSERT OR UPDATE OF proposal_id,decision_key ON action_item_proposal_receipts
        FOR EACH ROW EXECUTE FUNCTION validate_action_item_dismissal()"""
    )
    op.execute(
        """CREATE FUNCTION validate_action_item_supersession() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.status='superseded' AND OLD.status<>'superseded' THEN
                IF OLD.status<>'pending' OR EXISTS(
                    SELECT 1 FROM action_item_proposal_receipts WHERE proposal_id=OLD.id
                ) THEN
                    RAISE EXCEPTION 'Only pending Action Item proposals without a dismissal can be superseded'
                        USING ERRCODE='23514', CONSTRAINT='action_item_supersession_source';
                END IF;
            END IF;
            RETURN NEW;
        END $$"""
    )
    op.execute(
        """CREATE TRIGGER action_item_supersession_source
        BEFORE UPDATE OF status ON action_item_proposals
        FOR EACH ROW EXECUTE FUNCTION validate_action_item_supersession()"""
    )


def downgrade() -> None:
    _lock()
    bind = op.get_bind()
    if bind.execute(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM action_item_proposals WHERE status='superseded') "
            "OR EXISTS(SELECT 1 FROM meeting_action_item_runs "
            "WHERE action_items_artifact->>'version'='2')"
        )
    ).scalar():
        raise RuntimeError(
            "Cannot downgrade filtered Action Item audit/checkpoints; forward-fix or restore a pre-upgrade backup"
        )
    op.execute("DROP TRIGGER action_item_supersession_source ON action_item_proposals")
    op.execute("DROP FUNCTION validate_action_item_supersession()")
    op.execute(
        "DROP TRIGGER action_item_dismissal_source ON action_item_proposal_receipts"
    )
    op.execute("DROP FUNCTION validate_action_item_dismissal()")
    op.drop_constraint("meeting_action_item_protocol", "meeting_action_item_runs")
    op.drop_constraint("action_item_proposal_supersession", "action_item_proposals")
    op.drop_constraint("action_item_proposal_replacement", "action_item_proposals")
    op.drop_column("action_item_proposals", "superseded_by_id")
    op.drop_constraint("action_item_proposal_status", "action_item_proposals")
    op.create_check_constraint(
        "action_item_proposal_status",
        "action_item_proposals",
        "status IN ('pending','approved','rejected')",
    )
    op.drop_column("meeting_sync_state", "action_items_activated_at")
