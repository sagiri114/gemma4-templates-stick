---
name: check
description: One-call verification after an edit. Compiles the changed Python files, runs the existing tests related to them, lists untracked scratch files in /workspace and shows the diff summary.
---

# check

Run it directly, without loading anything else first:

    run_skill_script(skill_name="check", file_path="scripts/check.py")

To run specific tests instead of the automatically chosen ones:

    run_skill_script(skill_name="check", file_path="scripts/check.py", args=["tests/test_file.py::test_name"])

Read the report:

- `SYNTAX ERROR`: fix that line, then run check again.
- `TESTS FAILED`: if the failure is caused by your change, fix it and run check again. Ignore failures unrelated to your change (some existing tests are broken).
- `UNTRACKED FILES`: delete scratch files before `submit_patch`, unless a file is an intended new source file.
- When the report looks right, call `submit_patch`.
