# Screen preferences

Jobs, Plans, the five Harness lists, Audit, Proposals, Eval suites, Action items, Profiles, Chat and Results share the typed codec in `services/client/src/utils/viewPreferences.ts` and the browser/router adapter `useViewPreferences`.
Further screens should extend that registry and reuse the adapter, rather than adding cookies or persistence effects.

The host-only `agent-smith.ui.v1` cookie uses `Path=/`, `SameSite=Lax`, a 30-day lifetime and `Secure` on HTTPS.
Its entire encoded assignment, including the name and attributes, is limited to 3,000 bytes and 12 view entries.
Only nondefault fields are stored, in most-recent-first order; older entries are evicted until both bounds hold.
An oversized current view removes its previous saved entry without truncating the live query or changing other valid views.
The API still receives the live query and enforces its own input contracts.

The secure-cookie byte worksheet below includes a project filter, page size 50, offset 100 and distinct numeric scopes.

| Query in each of 12 requested entries | Encoded query bytes | Retained entries | Complete cookie bytes |
| --- | ---: | ---: | ---: |
| `plain search and tags` | 27 | 12 | 2493 |
| 100 copies of `é` | 600 | 3 | 2421 |
| 45 copies of `漢字🙂` | 1350 | 1 | 1625 |

Writes re-read the current cookie before merging a view.
The browser has no atomic compare-and-swap for `document.cookie`: simultaneous cross-tab writes remain best-effort, last-writer-wins.
Cookie denial or eviction does not disable live controls.
These are view preferences, not durable application data; drafts, selected records and mutation receipts are excluded.

Explicit URL parameter presence wins, including empty clears.
Invalid external values resolve to validated defaults rather than resurrecting a saved value.
A URL criteria override without an offset starts at page zero, and offsets align to the validated page size.
Unrelated query parameters survive control changes; Back/Forward and external navigation restore the URL's effective view.
Hidden or unmatched views never write preferences.

The adapter initializes synchronously before the first list request and supplies controlled pagination.
User criteria/page-size changes reset the page atomically; pending debounced criteria pause reads.
Stale offsets clamp only inside `usePagination`'s accepted response gate using that request's criteria, limit and offset.
Older totals, failed requests and stale responses cannot change a newer view's page.

Action item status and its default sort change atomically; incompatible sorts normalize before fetching and during live updates.
Queue controls, including Reset view, remain frozen during reordering.
Profile creation drafts, selected chat rooms, room edits, unsent messages, and result chart modes remain local.
Result category and subcategory changes clear dependent filters in one update.
