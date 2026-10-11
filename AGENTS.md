# Branch workflow

The owner requires branch-based development for all future work.

- `master`: stable release.
- `dev`: validated candidate for the next stable release.
- `dev-rolling`: integration branch.
- `feature/<name>`: all implementation work starts here, from `dev-rolling`.

Never implement directly on the long-lived branches. Commit and validate on a feature branch, then merge it into `dev-rolling` with a merge commit. Promote validated integration changes to `dev`; promote to `master` only as a deliberate release after validation. Tag the previous stable release before replacing it. Do not force-push or erase existing history. Keep local account settings, recordings, screenshots and logs out of Git.

Preserve the current run, its counters, and manual stop requests during deployment. A code rollback must not roll back or delete local run data.

Run logs use `current-run.json` and `runs/<id>/run.json`; lifetime counters in
`totals.json` deliberately remain separate. Preserve a log run across pause,
maintenance reload and worker recovery. Filter archived logs with both start and
end timestamps. Keep all completed-run records even when live views are bounded.

The optional overnight monitor only reads game state and emits errors through
the desktop MCP into the already-authorized chat. It must never clear manual
STOP/PAUSE/F8 requests or restart the farmer itself. Keep its chat ID/runtime
paths/expiry in ignored local data, and verify delivery before promising error
wakeups. A 30-minute app heartbeat does the periodic follow-up; neither monitor
nor heartbeat is permission to control unrelated applications. Roblox focus
guards and input release remain required. No code update changes spawn settings.

For explicitly authorized overnight runs, `--unattended-until` provides a bounded
focus restore after 120 seconds paused and 45 seconds of physical inactivity.
Do not enable it outside an authorized period or extend its expiry silently.
Physical activity telemetry is timestamps only. Never bypass the normal input
gate or restore focus while the user is active or a manual stop/pause is set.

Overnight defaults to on when no setting is saved, with no clock or night
condition. Preserve a saved Off. Off and explicit Stop disarm future idle activation; manual
Pause/F8 retain intent but block the restart guard until Continue. Optional idle
activation requires Player open and explicit autofocus/idle settings. All input
injection is tagged; only hardware activity counts as human input. Yield for the
configured grace after competing injected input instead of fighting other apps.

Farm here (`here`) uses the full worker with no startup rejoin or saved-scene
alignment. Local vision/focus/window/capture/pickup faults must not rejoin.
Positive disconnect/client-loss evidence may. A blank capture is unavailable
visual evidence, and capture_wait is not successful farming. Preserve the user's
monitor-off intent and never conceal a rendering/capture dependency.

Persistent all-white capture faults may refresh only the Player presentation
surface with a pair of F11 toggles, under enabled Overnight/autofocus, foreground ownership,
45 seconds of physical inactivity and no manual hold. Release fishing input,
replace owned capture resources and reacquire stable coordinates afterwards.
Limit to two refreshes per 90 minutes with 60 seconds between attempts. Never
use this repair to issue monitor power commands or restart/rejoin Farm here.

Catch predictions are read-only calculations from this run's logs. Deduplicate
stable catch/cycle IDs, merge overlapping worker activity, exclude recorded
pauses/recovery, and bound orphan intervals by their last event with a warning.
Do not produce forecasts when activity records are incomplete or samples are
small. Unknown prices stay unknown; distinguish NPC estimates from confirmed
sale proceeds. Never restart the farmer merely to expose the Predictions tab.
