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
* **Example (plan excerpt for a file sync daemon):**
    > **Step 1 — Preconditions at function boundaries:**
    > `SyncDaemon.__init__(config_path)` asserts the config file exists and is valid YAML
    > with required keys (`watch_dir`, `bucket`, `poll_interval`). `watch_dir` must be an
    > existing directory. `poll_interval` must be a positive integer. If any check fails,
    > the daemon crashes at startup: `ConfigError("watch_dir '/bad/path' does not exist")`.
    > It never falls back to defaults or guesses.
    >
    > **Step 2 — Validate inputs at system boundaries:**
    > The filesystem and S3 API are trust boundaries. `Scanner.scan(path)` validates that
    > each file is readable before computing its SHA-256 — if `open()` raises
    > `PermissionError`, the daemon crashes with
    > `SyncError(f"Cannot read {path}: permission denied")`. It does not skip the file and
    > continue. `Remote.upload(key, data, checksum)` validates the S3 response: if the
    > returned ETag does not match the expected MD5, the daemon crashes with
    > `UploadIntegrityError(f"ETag mismatch for {key}")`. Corrupt uploads are never silently
    > accepted.
    >
    > **Step 3 — Postconditions:**
    > After `Remote.upload()` returns, assert the response contains `ETag` and
    > `VersionId`. After `Manifest.save()` writes the local state file, assert the file
    > exists and is non-empty. A failed postcondition means something is fundamentally
    > wrong — crash immediately.
    >
    > **Step 4 — Fail fast with descriptive errors:**
    > If S3 returns an unexpected status (anything outside 200, 404), raise
    > `RemoteError(f"S3 returned {status} for {key}: {body}")` and let the daemon die.
    > Never retry silently or log a warning and continue — a dead daemon that gets
    > restarted after investigation does less damage than one that silently skips files.
    >
    > **Step 5 — Prefer crash over corrupt state:**
    > If a conflict is detected (local and remote both changed since last sync) and the
    > configured `conflict_strategy` is not one of the known values (`"local_wins"`,
    > `"remote_wins"`, `"abort"`), the daemon crashes:
    > `ConfigError(f"Unknown conflict_strategy: '{value}'")`. It never defaults to one
    > strategy when the config is ambiguous. The fix cycle: crash → investigate → fix
    > config → restart.
    >
    > **Step 6 — Specificity:**
    > Every boundary named: `daemon.py:SyncDaemon.__init__` (config validation),
    > `scanner.py:Scanner.scan` (filesystem trust boundary),
    > `remote.py:Remote.upload` (S3 trust boundary + postcondition),
    > `manifest.py:Manifest.save` (local state postcondition).
