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
