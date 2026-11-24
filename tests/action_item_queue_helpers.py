from collections import defaultdict

from services.db import get_connection


def clear_action_items(cursor=None, *, include_projects=False):
    if cursor is None:
        with get_connection() as connection, connection.cursor() as owned:
            clear_action_items(owned, include_projects=include_projects)
        return
    cursor.execute("TRUNCATE action_item_queue_entries,action_item_epics,action_items,action_item_projects" if include_projects else "TRUNCATE action_item_queue_entries,action_item_epics,action_items")


def assert_action_item_queue():
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT sibling_scope,sort_key FROM action_item_queue_entries WHERE sort_key IS NOT NULL ORDER BY sibling_scope,sort_key")
        scopes = defaultdict(list)
        for scope, position in cursor.fetchall():
            scopes[scope].append(position)
        assert all(positions == list(range(1, len(positions)+1)) for positions in scopes.values())
        cursor.execute("""SELECT a.profile_id,a.status,a.deleted_at,q.id,q.sort_key,q.parent_epic_id,e.deleted_at
          FROM action_items a LEFT JOIN action_item_queue_entries q ON q.action_item_id=a.id
          LEFT JOIN action_item_epics e ON e.id=q.parent_epic_id""")
        for profile, status, deleted, entry, position, parent, parent_deleted in cursor.fetchall():
            if profile is not None:
                assert entry is None
            else:
                assert entry is not None
                assert (position is not None) == (status == "open" and deleted is None)
                assert parent is None or parent_deleted is None
        cursor.execute("""SELECT e.deleted_at,q.id,q.sort_key,
          EXISTS(SELECT 1 FROM action_item_queue_entries child WHERE child.parent_epic_id=e.id)
          FROM action_item_epics e LEFT JOIN action_item_queue_entries q ON q.epic_id=e.id""")
        for deleted, entry, position, has_members in cursor.fetchall():
            assert entry is not None
            assert (position is not None) == (deleted is None)
            assert deleted is None or not has_members
        cursor.execute("SELECT priority FROM action_item_global_positions ORDER BY priority")
        priorities = [row[0] for row in cursor.fetchall()]
        assert priorities == list(range(1, len(priorities)+1))


def legacy_task_snapshots(cursor, *, exclude_fields=()):
    cursor.execute("""SELECT (to_jsonb(a)-%s::text[]-'sort_key') || jsonb_build_object('sort_key',coalesce(a.sort_key,p.priority))
      FROM action_items a LEFT JOIN action_item_global_positions p ON p.action_item_id=a.id ORDER BY a.id""", (list(exclude_fields),))
    return [row[0] for row in cursor.fetchall()]
