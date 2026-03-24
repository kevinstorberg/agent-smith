## Tracer Bullets (Iterative Verification)

* **The Rule:** A Tracer Bullet is the minimum required code to send the simplest possible message to verify an important assumption. Find the target incrementally by delivering small, end-to-end functional pieces.
* **Your Action:** Propose tracer bullets before major work; implement only to the next bullet, stop and verify before proceeding.
* **Your Process:**
    1. **Propose:** Before any major implementation, propose 1–N tracer bullets. Each bullet must explicitly outline:
        * **Assumption being tested:** What are we trying to prove?
        * **Simplest "message"/observable output:** What confirms or refutes it?
        * **Verification:** Exact commands or actions and expected results.
    2. **Implement incrementally:** For each bullet, implement *only up to that bullet* using the real structure you plan to keep — stub or fake anything beyond it so the slice runs end-to-end. When planning, describe the specific scope, files, and stubs each bullet will produce.
    3. **Stop & Verify:** After each bullet, run the agreed verification before proceeding — do not begin the next bullet until verification passes. When planning, specify the exact verification checkpoint and what must pass before the next bullet begins.
    4. **Adjust:** After verification, adjust your approach based on what you learned before proceeding to the next bullet. When planning, describe what signals would trigger a change in direction and what alternatives exist.
* **Example (plan excerpt for a real-time webhook integration with Stripe):**
    > No architecture or module design happens until the bullets below are proposed.
    >
    > **Bullet — Signature verification works locally:**
    > *Assumption:* Stripe webhook signatures can be verified using our signing secret and
    > the `stripe` Python library's `Webhook.construct_event()`.
    > *Simplest observable output:* A single-file `webhook_verify.py` script that reads a
    > raw request body and signature header from a saved test fixture, calls
    > `construct_event()`, and prints `"Signature valid"` or raises
    > `SignatureVerificationError`.
    > *Verification:*
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
    > *Verification:*
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
    > *Verification:*
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
    > *Verification:*
    > `stripe trigger payment_intent.succeeded` twice in a row — expect: first call logs
    > `"Handled"`, second call logs `"Duplicate event ... skipped"`. Database shows exactly
    > one row for that event ID.
* **Example (plan excerpt for a time-aware memory retrieval experiment):**
    > **Bullet — Embedding sanity:**
    > *Assumption:* `all-MiniLM-L6-v2` discriminates semantic similarity in 384-dim space.
    > *Scope:* `config.py`, `embeddings.py`, basic test.
    > *Verification:* `pytest tests/test_time_weighting.py` — similar pairs cosine > 0.5,
    > dissimilar < 0.3.
    >
    > **Bullet — FAISS index basics:**
    > *Assumption:* `IndexFlatIP` and `IndexFlatL2` scores match manual numpy computation.
    > *Scope:* `indexing.py`, FAISS sanity tests.
    > *Verification:* `pytest tests/test_retrieval.py` — scores agree to 1e-6 tolerance.
    >
    > **Bullet — Dot-product ranking equivalence (mathematical proof):**
    > *Assumption:* Stored `v*(1+r)^d` with IP search produces identical ranking to base
    > search + `score*(1+r)^{-(D-d_i)}` decay.
    > *Scope:* `time_weighting.py`, ranking equivalence test with 20 vectors.
    > *Verification:* `pytest tests/test_ranking_equivalence.py` — Kendall's tau = 1.0.
    > *If this fails:* The theory is wrong. Stop and diagnose before proceeding.
    >
    > **Bullet — Numerical stability at 1000-day horizon:**
    > *Assumption:* `(1+r)^1000` stays finite and searchable for useful r values.
    > *Scope:* Stability tests across r = [0.001, 0.003, 0.005, 0.01].
    > *Verification:* `pytest tests/test_time_weighting.py::test_numerical_stability` —
    > r=0.001 gives ~2.7x (safe), r=0.01 gives ~21916x (borderline).
    > *If borderline:* Cap growth factor or switch to log-space arithmetic.
    >
    > **Bullet — Synthetic dataset generation:**
    > *Assumption:* Generator produces 1000 memories with required distribution properties.
    > *Scope:* `dataset.py`, dataset invariant tests.
    > *Verification:* `pytest tests/test_dataset.py` — 1000 memories, 40+ conflict pairs,
    > 10+ clusters, days 0-999.
    >
    > **Bullet — Full pipeline at tiny scale (50 memories, 5 queries):**
    > *Assumption:* All 5 variants execute end-to-end and produce differentiated results.
    > *Scope:* `retrieval.py`, `run_experiment.py`.
    > *Verification:* `python experiments/run_experiment.py --subset 50 --queries 5` —
    > conflict queries show recency effects in variants 2-5 but not variant 1.
    >
    > **Bullet — Full evaluation at scale:**
    > *Assumption:* At 1000 memories / 50+ queries, metrics reveal meaningful differences.
    > *Scope:* `evaluation.py`, full query set, comparison table + plots.
    > *Verification:* `python experiments/run_experiment.py --full` — results table and
    > charts generated.
