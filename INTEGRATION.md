# Local control interface · version 1

This interface prepares Fishing for a future Discord bot or another client. It is a one-shot local command, with no server, Discord dependency, token storage, or network listener. Existing interactive commands keep their current output.

Run it on the Windows PC that runs Roblox, using the installation's Python environment:

```powershell
.\.venv\Scripts\python.exe fishing_cli.py api status
.\.venv\Scripts\python.exe fishing_cli.py api events --limit 50
.\.venv\Scripts\python.exe fishing_cli.py api pause --request-id interaction-123
```

`fishing.cmd api ...` is convenient by hand. Programs should invoke Python directly with an argument list and `shell=False`.

## Commands

| Command | `data` on success |
| --- | --- |
| `status` | Current state, running/starting/paused/stop_requested flags, run start, counters, last item, presence and bait estimates |
| `items` | `started` and `items`, an array of `{item, quantity}` for the saved run |
| `events` | `started` and `events`, the latest 50 saved events by default; `--limit` accepts 1–200 |
| `pause` | `message` and a `status` snapshot after the request |
| `resume` | `message` and a `status` snapshot after the request |
| `stop` | `message` and a `status` snapshot after the request |

Read commands never start, focus, or stop Roblox. Controls call the same serialized handlers as the window and CLI, preserving duplicate-controller protection, counters, focus checks, and stop semantics. Explicit `resume` can clear a completed manual stop, focus Roblox, and start a rejoin. If pause/stop is still finishing, it reports that condition; it does not start a second controller.

The interface uses `config.local.json` and `FISHING_DATA_DIR` exactly like the app. Keep the installation directory and intended Windows user/session fixed in a future adapter.

`resume` uses the mode saved in Settings. In `assist` mode it starts only minigame tracking and never focuses, casts, collects or rejoins. Status includes `mode` (`full` or `assist`), `recent` (nullable recent rates and phase seconds) and `alignment` (the last local alignment result). Mode changes and reference calibration remain explicit local setup operations; there is no automatic remote calibration.

## Response contract

Valid API invocations produce one JSON object on stdout, with no ANSI escapes or progress text:

```json
{
  "api_version": 1,
  "ok": true,
  "command": "items",
  "request_id": "interaction-123",
  "at": 1790070000.0,
  "data": {"started": 1790000000.0, "items": [{"item": "Coral", "quantity": 4}]},
  "error": null
}
```

`request_id` echoes the supplied string or is null. It is for correlation, **not** deduplication or exactly-once delivery. Times are Unix seconds. Bait values may be null when stock or rate is unknown. `started` identifies the saved run, not an individual supervisor restart. Status `updated` is the saved totals timestamp; `at` is the API request time. Presence has its own freshness flag and can be unknown without a disconnect.

Exit codes:

- **0**: handler returned successfully, `ok: true`.
- **1**: handler failed, `ok: false`, `error: {code: "command_failed", message: "..."}`.
- **2**: invalid request. A valid API command with an out-of-range limit returns `invalid_request` JSON. CLI syntax errors (such as an unknown operation), `--help`, or failures before imports complete can use the normal CLI stdout/stderr format; check the exit code before parsing.

Successful control responses acknowledge the handler; they do not promise the game has finished pausing or rejoining. Poll `status` for the resulting state. A finishing stop can also leave `resume` waiting: inspect its `message` and `status.stop_requested`. If a subprocess times out or loses its reply, a control may already have taken effect. Read status before deciding whether to retry; never auto-resume a user-stopped run.

Consumers should check `api_version`, tolerate additional JSON fields, and not infer completion from a human-readable message. A breaking contract change will increment the API version.

## Events

Each event has `id`, `at`, `kind`, `group`, `level`, and `text`. IDs are stable across polls and distinguish equal events at separate log positions. Remember IDs already delivered to avoid sending repeated Discord notifications. Use `kind` for routing and `text` for display. Escape Discord mentions/formatting in the future adapter rather than treating OCR text as commands.

`events` returns a recent window, not a durable queue or cursor subscription. It excludes synthetic UI state changes and noisy OCR screen observations. Poll `status` for current state. A future notification adapter must choose its initial baseline, polling cadence, and delivery storage; a long offline gap can exceed the 200-entry response window. For full history, the existing `logs --json --all` and `logs --json --activity --all` commands and raw local logs remain available.

## Minimal caller for later use

This example runs **on the gaming PC**. It is not a Discord bot or a remote transport:

```python
import json
import subprocess
from pathlib import Path

INSTALL = Path(r"C:\Tools\Fishing")  # Your installed folder
ALLOWED = {"status", "items", "events", "pause", "resume", "stop"}

def fishing(command, request_id):
    if command not in ALLOWED:
        raise ValueError("Unsupported fishing command")
    result = subprocess.run(
        [str(INSTALL / ".venv/Scripts/python.exe"),
         str(INSTALL / "fishing_cli.py"), "api", command,
         "--request-id", str(request_id)],
        cwd=INSTALL, capture_output=True, text=True, encoding="utf-8",
        timeout=20, shell=False, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        response = json.loads(result.stdout)
    except ValueError as error:
        raise RuntimeError(result.stderr or "No JSON response") from error
    if response.get("api_version") != 1:
        raise RuntimeError("Unsupported Fishing API version")
    if result.returncode or not response.get("ok"):
        raise RuntimeError(response.get("error") or result.stderr)
    return response["data"]
```

A remotely hosted Discord bot will need an authenticated bridge to this function on the gaming PC. Keep that future transport separate from Fishing's game controller. Authorize the intended Discord owner/server and allowlisted operations there; do not expose arbitrary shell commands or the state directory. The PC must still be awake, unlocked, and able to foreground Roblox. None of that bridge is installed or enabled by this release.
## Fishing modes

The saved `mode` is `full`, `assist`, or `spot`. Resume uses that selection. The `spot` mode waits for a local F8 selection, pauses when Roblox loses focus, and resumes without recovery or reconnect actions. `selected_point` in status is the session's normalized client coordinate, or null. External integrations should leave spot selection to the local player.
