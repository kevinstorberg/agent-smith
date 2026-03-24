## DRY (Don't Repeat Yourself)

* **The Rule:** Every piece of knowledge must have a single, unambiguous, authoritative representation within a system.
* **Your Action:** Never duplicate logic; abstract repeated patterns into reusable modules.
* **Your Process:**
    1. Before writing new code, search for existing implementations of the same functionality that could be reused or extended — name each project evaluated, explain why it was or was not suitable, and justify building from scratch if none fit.
    2. If one exists, extend or reuse it — never duplicate it.
    3. When similar logic appears in two or more places, abstract it before adding a third instance.
    4. Do not generate boilerplate when a clean abstraction already exists or can be made.
* **Example (plan excerpt for adding search to a web app with an existing query builder):**
    > **Step 1 — Search existing codebase and open source:**
    > The codebase already has `lib/query_builder.py`, which constructs parameterized SQL
    > queries for the product listing page. It supports `filter_by()`, `sort_by()`, and
    > `paginate()` methods. Searched PyPI for full-text search libraries: Whoosh (pure
    > Python, unmaintained since 2015), django-haystack (Django-specific, this project is
    > Flask), SQLAlchemy full-text search extensions (compatible, but only PostgreSQL
    > `tsvector`). Since the app already uses PostgreSQL and SQLAlchemy, the `tsvector`
    > approach integrates with the existing query builder rather than introducing a new
    > search engine dependency.
    >
    > **Step 2 — Extend, do not duplicate:**
    > Rather than writing a separate `search_products()` function with its own SQL
    > construction, extend `QueryBuilder` with a new `.full_text_search(columns,
    > query_string)` method that appends a `tsvector @@ tsquery` clause to the existing
    > chain. The search endpoint reuses the same `filter_by()`, `sort_by()`, and
    > `paginate()` methods that the listing page uses. No parallel query-building code
    > path is created.
    >
    > **Step 3 — Abstract before the third instance:**
    > Both the product listing endpoint and the new search endpoint need to serialize
    > results into the same JSON shape with pagination metadata (`total`, `page`,
    > `per_page`, `items`). Rather than duplicating the pagination-response formatting in
    > both route handlers, extract a `paginated_response(query, page, per_page)` helper in
    > `lib/responses.py` that both endpoints call. This prevents a third instance when the
    > upcoming "browse by category" endpoint ships next sprint.
    >
    > **Step 4 — No boilerplate when abstraction exists:**
    > The existing `QueryBuilder` already handles parameterization and SQL injection
    > prevention. The search method delegates to it — no hand-rolled SQL string
    > concatenation, no duplicate parameter binding logic. The migration for the GIN index
    > on the `tsvector` column uses Alembic's `op.create_index` rather than raw DDL.
* **Example (greenfield — searching before building from scratch):**
    > **Step 1 — Search for existing implementations:**
    > No existing codebase. Before building a CLI URL shortener from scratch, searched PyPI
    > and GitHub for existing Python URL shortener implementations (not general web
    > frameworks): `pyshorteners` (wrapper around third-party services like bit.ly — requires
    > external API keys, not self-hosted), `polr` (PHP, not Python), `yourls` (PHP), `shlink`
    > (PHP with a Python SDK, but the SDK is a thin API client, not a standalone shortener).
    > None provide a self-contained Python CLI shortener with local storage. Decision: build
    > from stdlib using `hashlib` for slug generation and SQLite for persistence, adopting the
    > base62 encoding convention used by bit.ly since it is compact and URL-safe.
    > **Step 2:** N/A — no existing Python implementation to extend.
    > **Step 3:** `create` and `lookup` both need slug-to-URL resolution + fail-if-missing —
    > that's two call sites already, so extract `_resolve_slug(db, slug)` now to prevent a
    > third copy when future commands (e.g., `stats`, `delete`) need the same lookup.
    > **Step 4:** `argparse` handles subcommand routing and type coercion. `sqlite3` module
    > handles persistence. No hand-rolled SQL string concatenation or custom serialization.
