## Testing as a First-Class Citizen

* **The Rule:** Coding ain't done 'til all the tests run. Test your software, or your users will.
* **Your Action:** Write tests alongside implementation; a feature is not complete without a passing test.
* **Your Process:**
    1. Write tests alongside implementation — not after. A feature is not complete until it has a test.
    2. A test must fail before the implementation makes it pass. If a test passes without any new code, it is not testing the right thing.
    3. Treat test code with the same quality standards as production code — no duplication, no magic values, no unclear assertions.
    4. Use Tracer Bullet tests to verify assumptions early: write the minimal test that confirms an assumption before building on it.
    5. Every bug fixed must have a regression test added so it cannot silently reappear.
    6. Name each test and what it asserts. "We will add tests" is not a test plan.
