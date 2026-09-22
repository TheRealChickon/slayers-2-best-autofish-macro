# Branches and rollback

`feature/* → dev-rolling → dev → master`

Work on feature branches. Merge each feature into `dev-rolling` with `--no-ff`, validate the integrated version, then promote to `dev`. `master` contains the stable release. The original `main` branch remains as a historical reference.

Before switching versions, pause Fishing and wait for **Paused**, then close its window and CLI so they reload from the intended checkout. The local data folder and ignored settings stay in place.

```powershell
git switch master
git pull --ff-only
.\fishing.cmd continue
```

To inspect the saved release before the inventory/resolution work:

```powershell
git switch --detach stable-before-inventory-resolution
```

To undo an integrated feature in shared history, create a rollback branch from `dev-rolling` and revert the feature's merge commit with `git revert -m 1 <merge-commit>`. Validate and merge that rollback branch normally. Avoid resetting shared branches or force-pushing.
