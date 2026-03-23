## Tracer Bullets (Iterative Verification)

* **The Rule:** A Tracer Bullet is the minimum required code to send the simplest possible message to verify an important assumption. Find the target incrementally by delivering small, end-to-end functional pieces.
* **Your Action:** Propose tracer bullets before major work; implement only to the next bullet, stop and verify before proceeding.
* **Your Process:**
    1. **Propose:** Before any major implementation, propose 1–N tracer bullets. Each bullet must explicitly outline:
        * **Assumption being tested:** What are we trying to prove?
        * **Simplest "message"/observable output:** What confirms or refutes it?
        * **User-run verification steps:** Exact commands and expected results.
    2. **Implement:** Write code *only up to the next bullet* using the real structure you plan to keep. Stub/fake anything missing so the slice still runs end-to-end (input → code → data → output).
    3. **Stop & Verify:** Halt execution. Ask the user to run the agreed verification steps and report the results back to you.
    4. **Adjust:** Based on the user's feedback, adjust your aim, refine the code, and proceed to the next bullet.
* **Example (plan excerpt for a real-time webhook integration with Stripe):**
    > No architecture or module design happens until the bullets below are proposed and the
    > user agrees to proceed.
    >
    > **Bullet — Signature verification works locally:**
    > *Assumption:* Stripe webhook signatures can be verified using our signing secret and
    > the `stripe` Python library's `Webhook.construct_event()`.
    > *Simplest observable output:* A single-file `webhook_verify.py` script that reads a
    > raw request body and signature header from a saved test fixture, calls
    > `construct_event()`, and prints `"Signature valid"` or raises
    > `SignatureVerificationError`.
    > *User-run verification:*
    > `python webhook_verify.py` — expect output: `Signature valid`
    > `python webhook_verify.py --tampered` (with a modified body) — expect:
    > `SignatureVerificationError`
    >
    > **Bullet — Flask receives raw body intact:**
    > *Assumption:* Our Flask app can receive a raw, unmodified request body (required for
    > signature verification — `request.get_data()` must return bytes before any JSON
    > parsing).
    > *Simplest observable output:* A minimal Flask route at `POST /webhooks/stripe` that
    > logs the raw body length and the verification result, returning HTTP 200 on success
    > and 400 on failure.
    > *User-run verification:*
    > `stripe trigger payment_intent.succeeded --webhook-endpoint
    > http://localhost:5000/webhooks/stripe` — expect: server log shows
    > `"Signature valid, body_length=<N>"`, HTTP 200 response.
    > Manually send a request with a bad signature via
    > `curl -X POST ... -H "Stripe-Signature: bad"` — expect HTTP 400.
    >
    > **Bullet — Event dispatch without growing if/elif:**
    > *Assumption:* We can dispatch different event types (`payment_intent.succeeded`,
    > `charge.refunded`) to separate handler functions without a growing if/elif chain.
    > *Simplest observable output:* A handler registry (dict mapping event type strings to
    > callables) that dispatches `payment_intent.succeeded` to a stub handler which logs
    > `"Handled: payment_intent.succeeded, id=<event_id>"`. Unknown event types log a
    > warning and return 200 (Stripe retries on non-2xx, so unknown events must not fail).
    > *User-run verification:*
    > `stripe trigger payment_intent.succeeded` — expect log:
    > `"Handled: payment_intent.succeeded, id=evt_..."`.
    > `stripe trigger charge.refunded` — expect log:
    > `"Unhandled event type: charge.refunded"`, HTTP 200.
    >
    > **Bullet — Idempotency prevents duplicate processing:**
    > *Assumption:* Processing the same event ID twice does not create duplicate side
    > effects (e.g., double-crediting an account).
    > *Simplest observable output:* An `event_log` table with a unique constraint on
    > `stripe_event_id`. The handler checks for existence before processing. Duplicate
    > delivery logs `"Duplicate event evt_... skipped"` and returns 200.
    > *User-run verification:*
    > `stripe trigger payment_intent.succeeded` twice in a row — expect: first call logs
    > `"Handled"`, second call logs `"Duplicate event ... skipped"`. Database shows exactly
    > one row for that event ID.
