## ETC (Easier To Change) & Orthogonality

* **The Rule:** Good design is easier to change than bad design. Components must be self-contained, independent, and have a single, well-defined purpose.
* **Your Action:** Choose designs with the lowest coupling and highest cohesion; prefer interfaces over concrete implementations and avoid global state.
* **Your Process:**
    1. Before choosing an implementation approach, ask: "If the requirements change tomorrow, how hard is this to modify?"
    2. Choose the approach with the lowest coupling and highest cohesion — components should not know about each other's internals.
    3. Keep functions pure where possible; eliminate side effects between unrelated things.
    4. If a change would ripple through many files or modules, redesign before implementing — don't accept unnecessary coupling.
    5. Rely on interfaces over concrete implementations; avoid global state entirely.
* **Example (plan excerpt for a notification system supporting email, SMS, and push):**
    > **Step 1 — "How hard to modify if requirements change?":**
    > Tomorrow the product team could add Slack notifications, or swap Twilio for a
    > different SMS provider. The design must make adding a new channel a single-file
    > change and swapping a provider a config change — not a cross-cutting surgery.
    >
    > **Step 2 — Lowest coupling, highest cohesion:**
    > Three layers, each ignorant of the others' internals:
    > (a) `NotificationService` — accepts a `Notification(recipient, channel,
    > template_name, context)` and delegates to the appropriate sender. It knows nothing
    > about SMTP, Twilio, or Firebase.
    > (b) Channel senders (`EmailSender`, `SmsSender`, `PushSender`) — each implements a
    > `Sender` protocol with a single method: `send(recipient, rendered_body) ->
    > DeliveryResult`. Each sender owns its own retry logic and provider-specific config.
    > (c) `TemplateRenderer` — pure function that takes a template name and context dict,
    > returns a rendered string. No I/O, no knowledge of channels.
    >
    > **Step 3 — Pure functions, no side effects between unrelated things:**
    > `TemplateRenderer.render()` is pure: same inputs always produce the same output, no
    > network calls, no database access. Channel selection in `NotificationService` is a
    > pure dictionary lookup from channel name to sender instance — no conditional branching
    > that grows with each new channel.
    >
    > **Step 4 — No ripple effects:**
    > Adding a Slack channel means creating `SlackSender` implementing the `Sender` protocol
    > and registering it in the sender dictionary. Zero changes to `NotificationService`,
    > `TemplateRenderer`, or any existing sender. Swapping Twilio for Vonage means editing
    > only `SmsSender` internals — the protocol interface is unchanged.
    >
    > **Step 5 — Interfaces over concrete implementations, no global state:**
    > `NotificationService` depends on `Sender` (a `Protocol`), never on `SmsSender`
    > directly. Senders are injected at construction time via a `dict[str, Sender]`
    > parameter — no module-level singletons, no global sender registry. Tests inject
    > `FakeSender` instances with zero patching.
