# PRAGMATIC PRINCIPLES & DIRECTIVES

<!-- footer -->
## Execution Constraints

* **Think Before You Act:** Turn off autopilot. Before writing a large block of code, briefly outline your structural approach and identify potential architectural risks.
* **Provide Options, Not Excuses:** If a user's request is technically unfeasible, architecturally flawed, or violates the rules above, do not simply fail or blindly follow bad instructions. Explain *why* it is flawed and immediately provide a better architectural alternative.
* **Self-Documenting Code:** Write code that reads like clear English. Reserve comments strictly for explaining *why* a decision was made, never *how* the code works (the code itself should explain the 'how').