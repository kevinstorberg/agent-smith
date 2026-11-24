"""Order global Action Items and one-level Epics in one authoritative queue."""
from alembic import op

revision = "f7a2d8c4b9e3"
down_revision = "e4b7c9d2a6f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE action_items IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        CREATE TABLE action_item_epics (
          id SERIAL PRIMARY KEY,
          title TEXT NOT NULL CHECK(char_length(title) BETWEEN 1 AND 200 AND title ~ '[^[:space:]]'),
          revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>0),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          deleted_at TIMESTAMPTZ,
          request_id UUID NOT NULL UNIQUE,
          create_payload JSONB NOT NULL CHECK(jsonb_typeof(create_payload)='object')
        );
        CREATE TABLE action_item_queue_entries (
          id SERIAL PRIMARY KEY,
          action_item_id INTEGER UNIQUE REFERENCES action_items(id) ON DELETE RESTRICT,
          epic_id INTEGER UNIQUE REFERENCES action_item_epics(id) ON DELETE RESTRICT,
          parent_epic_id INTEGER REFERENCES action_item_epics(id) ON DELETE RESTRICT,
          sort_key INTEGER CHECK(sort_key>0),
          sibling_scope TEXT GENERATED ALWAYS AS (coalesce('epic:' || parent_epic_id::text,'root')) STORED NOT NULL,
          CONSTRAINT action_item_queue_entity CHECK((action_item_id IS NULL) <> (epic_id IS NULL)),
          CONSTRAINT action_item_queue_flat CHECK(epic_id IS NULL OR parent_epic_id IS NULL),
          CONSTRAINT action_item_queue_order UNIQUE(sibling_scope,sort_key) DEFERRABLE INITIALLY DEFERRED
        );
        CREATE INDEX action_item_queue_parent ON action_item_queue_entries(parent_epic_id);
        INSERT INTO action_item_queue_entries(action_item_id,sort_key)
          SELECT id,sort_key FROM action_items WHERE profile_id IS NULL ORDER BY id;
        ALTER TABLE action_items DROP CONSTRAINT action_item_position;
        UPDATE action_items SET sort_key=NULL WHERE profile_id IS NULL;
        ALTER TABLE action_items ADD CONSTRAINT action_item_position CHECK(
          CASE WHEN profile_id IS NULL THEN sort_key IS NULL
          WHEN deleted_at IS NULL AND status='open' THEN sort_key>0 AND sort_key IS NOT NULL
          ELSE sort_key IS NULL END);
        CREATE VIEW action_item_ordered_items AS
          SELECT item.*,
            CASE WHEN item.profile_id IS NOT NULL THEN item.sort_key
                 WHEN item.deleted_at IS NULL AND item.status='open' THEN
                   row_number() OVER(PARTITION BY item.profile_id,(item.deleted_at IS NULL AND item.status='open')
                     ORDER BY coalesce(parent.sort_key,child.sort_key),child.sort_key,item.id)::integer
                 ELSE NULL END AS queue_priority
          FROM action_items item
          LEFT JOIN action_item_queue_entries child ON child.action_item_id=item.id
          LEFT JOIN action_item_queue_entries parent ON parent.epic_id=child.parent_epic_id;
        CREATE VIEW action_item_global_positions AS
          SELECT id AS action_item_id,queue_priority AS priority FROM action_item_ordered_items
          WHERE profile_id IS NULL AND queue_priority IS NOT NULL;
        DO $$ BEGIN
          IF (SELECT count(*) FROM action_items WHERE profile_id IS NULL) <>
             (SELECT count(*) FROM action_item_queue_entries WHERE action_item_id IS NOT NULL) THEN
            RAISE EXCEPTION 'Epic migration did not preserve every global task';
          END IF;
          IF EXISTS(SELECT 1 FROM action_item_queue_entries q
             JOIN action_item_global_positions p ON p.action_item_id=q.action_item_id
             WHERE q.sort_key<>p.priority) OR
             (SELECT count(*) FROM action_item_global_positions) <>
             (SELECT count(*) FROM action_items WHERE profile_id IS NULL AND status='open' AND deleted_at IS NULL) THEN
            RAISE EXCEPTION 'Epic migration did not preserve dense global ordering';
          END IF;
        END $$;
        CREATE FUNCTION action_item_queue_check_item(item_id INTEGER) RETURNS VOID LANGUAGE plpgsql AS $$
        DECLARE task action_items; entry action_item_queue_entries;
        BEGIN
          SELECT * INTO task FROM action_items WHERE id=item_id;
          IF NOT FOUND THEN RETURN; END IF;
          SELECT * INTO entry FROM action_item_queue_entries WHERE action_item_id=item_id;
          IF task.profile_id IS NOT NULL THEN
            IF FOUND THEN RAISE EXCEPTION 'Profile topics cannot have global queue entries' USING ERRCODE='23514'; END IF;
            RETURN;
          END IF;
          IF NOT FOUND THEN RAISE EXCEPTION 'Global task requires one queue entry' USING ERRCODE='23514'; END IF;
          IF (entry.sort_key IS NOT NULL) <> (task.deleted_at IS NULL AND task.status='open') THEN
            RAISE EXCEPTION 'Task queue activity differs from task state' USING ERRCODE='23514';
          END IF;
          IF entry.parent_epic_id IS NOT NULL AND NOT EXISTS(
            SELECT 1 FROM action_item_epics WHERE id=entry.parent_epic_id AND deleted_at IS NULL) THEN
            RAISE EXCEPTION 'Task requires a live parent Epic' USING ERRCODE='23514';
          END IF;
        END $$;
        CREATE FUNCTION action_item_queue_check_epic(epic INTEGER) RETURNS VOID LANGUAGE plpgsql AS $$
        DECLARE owner action_item_epics; entry action_item_queue_entries;
        BEGIN
          SELECT * INTO owner FROM action_item_epics WHERE id=epic;
          IF NOT FOUND THEN RETURN; END IF;
          SELECT * INTO entry FROM action_item_queue_entries WHERE epic_id=epic;
          IF NOT FOUND THEN RAISE EXCEPTION 'Epic requires one root queue entry' USING ERRCODE='23514'; END IF;
          IF (entry.sort_key IS NOT NULL) <> (owner.deleted_at IS NULL) THEN
            RAISE EXCEPTION 'Epic queue activity differs from Epic state' USING ERRCODE='23514';
          END IF;
          IF owner.deleted_at IS NOT NULL AND EXISTS(
            SELECT 1 FROM action_item_queue_entries WHERE parent_epic_id=epic) THEN
            RAISE EXCEPTION 'Removed Epic still has members' USING ERRCODE='23514';
          END IF;
        END $$;
        CREATE FUNCTION action_item_queue_validate() RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_TABLE_NAME='action_items' THEN
            PERFORM action_item_queue_check_item(coalesce(NEW.id,OLD.id));
          ELSIF TG_TABLE_NAME='action_item_epics' THEN
            PERFORM action_item_queue_check_epic(coalesce(NEW.id,OLD.id));
          ELSE
            IF TG_OP<>'DELETE' THEN
              PERFORM action_item_queue_check_item(NEW.action_item_id);
              PERFORM action_item_queue_check_epic(NEW.epic_id);
            END IF;
            IF TG_OP<>'INSERT' THEN
              PERFORM action_item_queue_check_item(OLD.action_item_id);
              PERFORM action_item_queue_check_epic(OLD.epic_id);
            END IF;
          END IF;
          RETURN NULL;
        END $$;
        CREATE CONSTRAINT TRIGGER action_item_queue_task_check AFTER INSERT OR UPDATE OR DELETE ON action_items
          DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION action_item_queue_validate();
        CREATE CONSTRAINT TRIGGER action_item_queue_epic_check AFTER INSERT OR UPDATE OR DELETE ON action_item_epics
          DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION action_item_queue_validate();
        CREATE CONSTRAINT TRIGGER action_item_queue_entry_check AFTER INSERT OR UPDATE OR DELETE ON action_item_queue_entries
          DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION action_item_queue_validate();
    """)


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
    connection.exec_driver_sql("LOCK TABLE action_items,action_item_epics,action_item_queue_entries IN ACCESS EXCLUSIVE MODE")
    if connection.exec_driver_sql("SELECT EXISTS(SELECT 1 FROM action_item_epics)").scalar():
        raise RuntimeError("Cannot remove Epic history; restore from a backup to roll back Epics")
    op.execute("""
        DROP TRIGGER action_item_queue_task_check ON action_items;
        DROP TRIGGER action_item_queue_epic_check ON action_item_epics;
        DROP TRIGGER action_item_queue_entry_check ON action_item_queue_entries;
        ALTER TABLE action_items DROP CONSTRAINT action_item_position;
        UPDATE action_items item SET sort_key=position.priority FROM action_item_global_positions position
          WHERE position.action_item_id=item.id;
        DROP VIEW action_item_global_positions;
        DROP VIEW action_item_ordered_items;
        DROP FUNCTION action_item_queue_validate();
        DROP FUNCTION action_item_queue_check_item(INTEGER);
        DROP FUNCTION action_item_queue_check_epic(INTEGER);
        DROP TABLE action_item_queue_entries;
        DROP TABLE action_item_epics;
        ALTER TABLE action_items ADD CONSTRAINT action_item_position CHECK(
          CASE WHEN deleted_at IS NULL AND status='open' THEN sort_key>0 AND sort_key IS NOT NULL
          ELSE sort_key IS NULL END);
    """)
