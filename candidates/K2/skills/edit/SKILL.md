---
name: edit
description: Install a fixed exact editor and a patch risk checker, then use run_command with literal SEARCH/REPLACE text.
---

# Fixed editor

Run run_skill_script(skill_name="edit", file_path="scripts/install.py") once.
It installs into task TMPDIR (or /tmp), locates the repository via git from cwd/PWD,
and records the fixed baseline in the git directory. Loading this skill is optional.

Use a workspace-relative path and one quoted-heredoc command:

    python3 /tmp/swe_edit.py edit module.py <<'SWE_EDIT_EOF'
    <<<<<<< SEARCH
    value = 1
    =======
    value = 2
    >>>>>>> REPLACE
    SWE_EDIT_EOF

Markers occupy whole lines. SEARCH is exact, nonempty and covers whole lines: a match
may not start or end inside a line. Only the first line's leading indentation may be
left out, and then REPLACE's first line must leave it out too. REPLACE may be empty.
The newline immediately before a marker is framing, not payload; use an additional
blank line to include a trailing payload newline. All blocks locate against one
original snapshot; nonunique, missing or overlapping targets refuse all writes.

Default is the common unnumbered format. On a full marker-line collision, retry
with --tag E0 and markers <<<<<<< SEARCH E0, ======= E0, >>>>>>> REPLACE E0.
Choose another E-number if those collide too. Choose a quoted outer heredoc
delimiter that never equals a payload line; shell truncation is not recoverable
inside the helper. Do not escape dollar signs, backticks or code quotes.

Supports UTF-8 with optional BOM, uniform LF/CRLF, preserved mode/final-newline
state. Unknown encoding, mixed/bare CR, invalid Python, outside/test/symlink paths
are refused. Config edits warn: the official grader may remove them from patches.
Unique matching and compilation do not prove correct function selection or logic.

Each edit result lists warnings for that edit when a function or class lost a return,
raise, yield, self, decorator or its definition; these are risks, not confirmed defects.
create PATH reads full stdin and refuses existing paths. check is optional: it reports
all staged/unstaged/untracked changes against the fixed baseline, without repairs or
test execution.
