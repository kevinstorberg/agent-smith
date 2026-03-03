## No Broken Windows (Tech Debt & Code Rot)

* **The Rule:** Don't live with broken windows. Fix bad designs, wrong decisions, and poor code when you see them.
* **Your Action:** Fix broken code and poor patterns when encountered; leave code cleaner than you found it.
* **Your Process:**
    1. When you encounter broken code, poor naming, or deprecated patterns, fix it before moving on — don't build on top of a known bad foundation.
    2. If a full fix is out of scope for the current task, surface the issue explicitly to the user with a concrete description of the problem.
    3. Never add new code on top of code you know to be wrong without at minimum leaving a comment explaining why it is wrong and what the correct fix would be.
    4. Leave every file you touch in better shape than you found it.
