## No Broken Windows (Tech Debt & Code Rot)

* **The Rule:** Don't live with broken windows. Fix bad designs, wrong decisions, and poor code when you see them.
* **Your Action:** Fix broken code and poor patterns when encountered; leave code cleaner than you found it.
* **Your Process:**
    1. When you encounter broken code, poor naming, or deprecated patterns, fix it before moving on — don't build on top of a known bad foundation. In greenfield projects, establish clean foundations from the start by defining naming conventions, error-handling patterns, and code-quality standards upfront.
    2. If a full fix is out of scope for the current task, surface the issue explicitly to the user with a concrete description of the problem. In greenfield projects, surface known limitations or design trade-offs (e.g., no concurrency safety, no file locking) rather than letting them become hidden debt.
    3. Never add new code on top of code you know to be wrong without at minimum leaving a comment explaining why it is wrong and what the correct fix would be. In greenfield projects, never accept a known-flawed design pattern without documenting the flaw and the intended fix.
    4. Leave every file you touch in better shape than you found it. In greenfield projects, apply this as a quality gate: every file must meet project standards (type annotations, consistent naming, no unused imports) before marking work complete.
    5. After completing new work, review it for rough edges and clean them up before finishing.
* **Example (plan excerpt for adding CSV export to an existing Flask app with tech debt):**
    > **Step 1 — Fix broken code before building on it:**
    > The existing `routes/reports.py` constructs SQL via string concatenation:
    > `f"SELECT * FROM orders WHERE status = '{status}'"`. This is a SQL injection
    > vulnerability. Before adding CSV export (which will reuse this query path), fix this
    > by converting all queries in `routes/reports.py` to parameterized queries using
    > SQLAlchemy's `text()` with bound parameters. The export feature must not be built on
    > an insecure foundation.
    >
    > **Step 2 — Surface issues that are out of scope:**
    > `models/order.py` uses a hand-rolled `to_dict()` method that silently drops `None`
    > fields and converts all datetimes to naive strings without timezone info. A full fix
    > (switching to Pydantic or marshmallow schemas) would touch 14 endpoints and is out of
    > scope for this task. Surfacing to user: "The `Order.to_dict()` serialization drops
    > null fields and strips timezone data. Recommend replacing with a Pydantic
    > `OrderSchema` in a dedicated follow-up. For now, the CSV export will use its own
    > explicit column mapping to avoid inheriting these bugs."
    >
    > **Step 3 — Never build on known-wrong code without a comment:**
    > The CSV export needs date formatting. Rather than calling the broken `to_dict()`, it
    > uses `order.created_at.isoformat()` directly. A comment is added above the `to_dict`
    > method: `# FIXME: drops None fields and strips timezone — replace with Pydantic
    > schema (see ticket PROJ-482)`.
    >
    > **Step 4 — Leave every file touched in better shape:**
    > While editing `routes/reports.py`, rename the ambiguous `get_data()` to
    > `get_filtered_orders()`, add type hints to the function signature, and remove two
    > unused imports (`import os`, `import sys`) that have been there since initial commit.
    >
    > **Step 5 — Final review pass:**
    > After completing the CSV export feature, review all touched files for: consistent
    > naming conventions, no leftover debug `print()` statements, no bare `except:` clauses,
    > and all new functions have type annotations. Clean up any rough edges before marking
    > the task as done.
