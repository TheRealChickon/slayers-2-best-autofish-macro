# Claude instructions

Follow the branch workflow in `AGENTS.md`.

# Merging pull requests

When CI passes on a PR, merge it with `gh pr merge --squash` without asking. If the PR has a merge conflict, resolve it: bring the base branch into the PR branch, fix the conflicts, push, let CI rerun, then merge once it is green.
