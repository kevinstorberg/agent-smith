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
