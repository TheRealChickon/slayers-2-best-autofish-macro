# Branch workflow

The owner requires branch-based development for all future work.

- `master`: stable release.
- `dev`: validated candidate for the next stable release.
- `dev-rolling`: integration branch.
- `feature/<name>`: all implementation work starts here, from `dev-rolling`.

Never implement directly on the long-lived branches. Commit and validate on a feature branch, then merge it into `dev-rolling` with a merge commit. Promote validated integration changes to `dev`; promote to `master` only as a deliberate release after validation. Tag the previous stable release before replacing it. Do not force-push or erase existing history. Keep local account settings, recordings, screenshots and logs out of Git.

Preserve the current run, its counters, and manual stop requests during deployment. A code rollback must not roll back or delete local run data.
