# Browser regressions

Run `npm ci`, `npx playwright install chromium`, then `npm run test:browser` from
`services/client`. The test command builds the current source, checks browser-test
types, and runs bundled Chromium at widths 1440, 1024, 390, and 320 pixels.

Playwright owns one preview process on an available loopback port. Workers inherit
that port; an existing server is never reused. The preview disables API proxying.
Each browser context blocks service workers, external requests, WebSockets,
unregistered APIs, and writes. Register exact GET paths through `fixtureAPI.get`.
The rejection proving case explicitly exercises blocked requests; other unexpected
traffic fails teardown. The guard stays installed until its context closes.

Import existing typed fixtures when a family has them, including `profileFixture`
and `actionItem`. Add only the contract needed by a case. Keep fixture omissions
separate from product failures, and use locator assertions or observed requests to
wait for readiness instead of fixed delays.

`geometry.ts` provides named checks for document/main width, horizontal control
containment, hidden-overflow clipping, accessible labels, and dialog bounds. These
are distinct contracts: a document-width check alone cannot detect a clipped grid.
Later responsive-flow cases should add vertical hit testing and real composer/action
interaction where required.

Every case attaches geometry and network evidence. Playwright adds a screenshot and
trace on failure; CI uploads the report and test artifacts. The Memory baseline also
records checkbox dimensions without treating its current stretched shape as correct.
The square-checkbox regression belongs with the following selector fix.

See `audit-coverage.json` for the broader local audit and remaining CI coverage gaps.
The initial CI cases prove the harness using Memory interaction, long Plans/Harness
content, a real topic dialog, and rejected network traffic. They do not assert that
known clipped tables or inaccessible mobile Chat behavior are desirable.
