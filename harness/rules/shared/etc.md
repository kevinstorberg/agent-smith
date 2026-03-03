## ETC (Easier To Change) & Orthogonality

* **The Rule:** Good design is easier to change than bad design. Components must be self-contained, independent, and have a single, well-defined purpose.
* **Your Action:** Choose designs with the lowest coupling and highest cohesion; prefer interfaces over concrete implementations and avoid global state.
* **Your Process:**
    1. Before choosing an implementation approach, ask: "If the requirements change tomorrow, how hard is this to modify?"
    2. Choose the approach with the lowest coupling and highest cohesion — components should not know about each other's internals.
    3. Keep functions pure where possible; eliminate side effects between unrelated things.
    4. If a change would ripple through many files or modules, redesign before implementing — don't accept unnecessary coupling.
    5. Rely on interfaces over concrete implementations; avoid global state entirely.
