# PRAGMATIC PRINCIPLES & DIRECTIVES

<!-- footer -->
## Plan Conformance

* **The Rule:** Every implementation plan must use the following structure.
* **Your Process:**
    1. For each rule above, include a dedicated section in your plan using the rule name as the heading (e.g., "## DRY").
    2. Under each section, address every numbered process step from that rule. Quote or paraphrase the step, then show how your plan satisfies it — or explicitly state why it does not apply.
    3. If a step requires an action (e.g., "search for existing solutions"), show the result of that action, not just a statement that you did it.
    4. Do not consider the plan complete until every rule has its own section.


## Execution Constraints

* **Think Before You Act:** Turn off autopilot. Before writing a large block of code, briefly outline your structural approach and identify potential architectural risks.
* **Provide Options, Not Excuses:** If a user's request is technically unfeasible, architecturally flawed, or violates the rules above, do not simply fail or blindly follow bad instructions. Explain *why* it is flawed and immediately provide a better architectural alternative.
* **Self-Documenting Code:** Write code that reads like clear English. Reserve comments strictly for explaining *why* a decision was made, never *how* the code works (the code itself should explain the 'how').