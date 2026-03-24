## Testing as a First-Class Citizen

* **The Rule:** Coding ain't done 'til all the tests run. Test your software, or your users will.
* **Your Action:** Write tests alongside implementation; a feature is not complete without a passing test.
* **Your Process:**
    1. Write tests alongside implementation — not after. A feature is not complete until it has a test. When planning, specify which test files ship with each implementation step.
    2. A test must fail before the implementation makes it pass — if a test passes without new code, it is not testing the right thing. When planning, name at least one test per feature that will be written before its implementation and describe the expected failure.
    3. Treat test code with the same quality standards as production code — no duplication, no magic values, no unclear assertions.
    4. Use Tracer Bullet tests to verify assumptions early: write the minimal test that confirms an assumption before building on it.
    5. Every bug fixed must have a regression test added so it cannot silently reappear.
    6. Name each test and what it asserts — "We will add tests" is not a test plan. When planning, list every test by function name with a one-line description of what it asserts.
* **Example (plan excerpt for a Python SDK client library):**
    > **Step 1 — Tests alongside implementation:**
    > Each module gets its test file written in the same tracer bullet as the
    > implementation. `WidgetClient.list_widgets()` is not considered implemented until
    > `test_list_widgets_returns_paginated_results` passes. No "we will add tests later" —
    > every tracer bullet includes both source and test files.
    >
    > **Step 2 — Test must fail first:**
    > Before implementing `WidgetClient.create_widget()`, write
    > `test_create_widget_sends_post_with_serialized_body` — run it, confirm it fails with
    > `AttributeError: 'WidgetClient' has no attribute 'create_widget'`, then implement. If
    > a test passes before implementation, it is testing the wrong thing and must be
    > rewritten.
    >
    > **Step 3 — Test code quality equals production quality:**
    > All tests use a shared `make_widget(**overrides)` factory function instead of
    > duplicating widget dictionaries with magic values across test files. HTTP responses
    > are built with a `fake_response(status, body)` helper, not repeated
    > `Mock(status_code=200, json=...)`. Named constants replace magic numbers:
    > `RATE_LIMIT_STATUS = 429`, not bare `429`.
    >
    > **Step 4 — Tracer bullet tests verify assumptions early:**
    > The first tracer bullet writes `test_base_client_sends_auth_header` — a minimal test
    > that confirms the `httpx` client attaches the `Authorization: Bearer <token>` header
    > on every request. This validates the authentication assumption before building any
    > resource-specific endpoints on top of it.
    >
    > **Step 5 — Every bug fix gets a regression test:**
    > If during implementation we discover that the API returns `{"data": null}` instead of
    > `{"data": []}` for empty collections, the fix includes
    > `test_list_widgets_returns_empty_list_when_data_is_null` to ensure this edge case
    > never silently regresses.
    >
    > **Step 6 — Named tests with explicit assertions (23 tests total):**
    > `test_auth_header_attached_on_every_request`,
    > `test_create_widget_sends_post_with_body`,
    > `test_create_widget_raises_validation_error_on_missing_name`,
    > `test_list_widgets_paginates_through_all_pages`,
    > `test_list_widgets_returns_empty_list_when_data_is_null`,
    > `test_get_widget_raises_not_found_for_404`,
    > `test_retry_on_429_up_to_three_times`,
    > `test_retry_not_attempted_on_4xx_other_than_429`,
    > `test_timeout_raises_sdk_timeout_error`, and 14 more — each name states exactly
    > what it asserts. "We will add tests" never appears in this plan.
