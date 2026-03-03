## DRY (Don't Repeat Yourself)

* **The Rule:** Every piece of knowledge must have a single, unambiguous, authoritative representation within a system.
* **Your Action:** Never duplicate logic; abstract repeated patterns into reusable modules.
* **Your Process:**
    1. Before writing new code, search the codebase for an existing implementation that solves the same problem.
    2. If one exists, extend or reuse it — never duplicate it.
    3. When similar logic appears in two or more places, abstract it before adding a third instance.
    4. Do not generate boilerplate when a clean abstraction already exists or can be made.
