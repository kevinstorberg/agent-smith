## Design by Contract & Crash Early

* **The Rule:** A dead program normally does a lot less damage than a crippled one. Prove your assumptions.
* **Your Action:** Validate all external inputs, assert assumptions at function boundaries, and fail fast with descriptive errors.
* **Your Process:**
    1. At every function boundary, assert preconditions — what must be true on entry. Fail immediately if they are violated.
    2. Validate all inputs at system boundaries (user input, external APIs, config files). Never trust data that crosses a trust boundary.
    3. Assert postconditions where correctness is non-obvious — what must be true on exit.
    4. Fail fast with descriptive, actionable error messages. Never swallow exceptions or allow errors to cascade silently.
    5. Prefer crashing loudly over continuing in a corrupted or undefined state.
    6. Be specific. Name each boundary and its check; do not describe validation in general terms.
* **Example (plan excerpt for a REST API payment gateway):**
    > **Step 1 — Preconditions at function boundaries:**
    > `PaymentService.charge(amount, currency, card_token)` asserts on entry: `amount > 0`,
    > `currency` is a member of `SupportedCurrency` enum, and `card_token` matches the
    > format `^tok_[a-zA-Z0-9]{24}$`. If any precondition fails, raises `ValueError` with
    > the specific field name and why it was rejected (e.g.,
    > `"amount must be positive, got -5.00"`).
    >
    > **Step 2 — Validate inputs at system boundaries:**
    > The `POST /v1/charges` route handler is a trust boundary. Before calling any service
    > code, the controller validates: request Content-Type is `application/json`, the JSON
    > body contains exactly `amount`, `currency`, `card_token`, and `idempotency_key`, all
    > values match their expected types and formats, and `idempotency_key` is a valid UUID.
    > The Stripe callback webhook endpoint validates the `Stripe-Signature` header using
    > HMAC-SHA256 before parsing the payload. Any failure returns HTTP 400 with a structured
    > error body naming the offending field — the payload is never forwarded downstream.
    >
    > **Step 3 — Postconditions:**
    > After `PaymentService.charge()` returns, assert that the returned `ChargeResult` has a
    > non-empty `transaction_id` and a `status` in `{"succeeded", "pending", "failed"}`.
    > After persisting a charge record, assert the row count is exactly 1.
    >
    > **Step 4 — Fail fast with descriptive errors:**
    > If the Stripe API returns an unexpected status code (anything outside 200, 402, 429),
    > raise `PaymentGatewayError(f"Stripe returned unexpected {status}: {body}")` immediately.
    > Never fall through to a default branch or return a generic "something went wrong."
    >
    > **Step 5 — Prefer crash over corrupt state:**
    > If the database write succeeds but the Stripe confirmation callback indicates a
    > mismatch, raise `PaymentConsistencyError` and log the full context rather than silently
    > reconciling. A human must investigate payment discrepancies — the system never guesses.
    >
    > **Step 6 — Specificity:**
    > Every boundary above is named by module and function:
    > `routes/charges.py:create_charge`, `services/payment.py:PaymentService.charge`,
    > `webhooks/stripe.py:handle_event`. Each check names the exact field, format, and error.
