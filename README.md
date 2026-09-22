# Fishing

A Windows fishing assistant for the Project Slayers 2 / Ouwland fishing minigame. Includes a game-inspired inventory window, a keyboard terminal app, item history, live events, bait estimates, and reconnect recovery.

## Launch it

**First time:** extract the repository, install Python 3.12 x64, and double-click **Setup.cmd**. Then open **Fishing** on the desktop, set your Roblox username and rod slot in Settings, prepare the game as described below, and click **Continue**.

**After setup:**

- **Fishing** on the desktop opens the window. Continue starts/resumes; Pause and Stop release game input.
- **Fishing CLI** opens the terminal dashboard. Press **C** to continue, **P** to pause, **S** to stop, and **Q** to close only the dashboard.
- **Start Fishing** resumes the saved run directly.
- Without desktop shortcuts, run `Open-Controls.ps1`, `Open-CLI.ps1`, or `fishing.cmd --color tui` from the extracted application folder.

## Where it works

| Requirement | Support |
| --- | --- |
| Accounts | Any account that owns a rod, has it in the visible hotbar, and can use this game's private-server Join menu; configure the username for that account's presence checks |
| Operating system | Windows x64; not macOS, Linux, mobile, or Roblox console |
| Game | This game's Ouwland fishing minigame; not arbitrary Roblox games |
| Display | The calibrated 2560 × 1440 layout and normal game UI scale; other resolutions need recalibration |
| Position | Saved spawn at the fishing spot, with a usable camera after rejoin; the bot does not walk to the spot |
| Focus | Roblox must stay visible and foreground; switching apps pauses input |

Setup has been tested from a clean source checkout on Windows with Python 3.12. Portability removes hardcoded account and computer paths; it does not remove the screen-layout and in-game setup requirements.

## First setup

1. Install **Python 3.12, 64-bit** from [python.org](https://www.python.org/downloads/windows/). Include the Python launcher and Tcl/Tk when installing.
2. Download this repository with **Code → Download ZIP** and extract it to a permanent, writable folder, or clone it with Git.
3. Double-click **Setup.cmd**. It creates a local Python environment, installs `requirements.txt`, checks the required files, and adds three desktop shortcuts. No administrator privileges are needed.
4. Open **Fishing** from the desktop. In **Settings**, enter your Roblox **username**, set the rod's hotbar slot (1–9), and save. The username is optional; it enables the public presence check. It does not sign in or change the account open in Roblox.
5. Sign into the intended account in Roblox, open the game, and complete the fishing position setup below. Select **Continue** in Fishing.

An existing installation can be checked without reinstalling packages:

```powershell
.\Setup.ps1 -SkipInstall
```

If your PowerShell policy blocks scripts, use `Setup.cmd`. The launcher sets a policy only for that process; it does not change the machine's policy.

## Game setup

The account is configurable. Each account must own a fishing rod, have it in a visible hotbar slot, and have access to the private-server Join menu.

- Use **one Roblox client**, at **2560 × 1440**, with the game's normal UI scale. This is the currently calibrated layout. Other resolutions need new detection regions and menu calibration.
- Set the saved spawn at your fishing spot in Ouwland, facing the water. A rejoin must restore the same usable position and camera arrangement. The assistant does not navigate a character across the map or find a fishing spot.
- Keep the game visible and foreground. Opening another app releases input and waits; Continue returns focus to Roblox and recovery resumes. It cannot fish through a minimized window, lock screen, or sleeping PC. A second monitor is useful for viewing status.
- The rod is located in the visible hotbar and selected only when its selection ring is absent. If it cannot be recognized during a rejoin, the configured slot is used. Moving the rod to another visible slot is supported; an unequipped rod in the backpack must first be placed in the hotbar.
- Bait is optional. Equip it in-game if desired. There is no purchasing automation.

## Desktop shortcuts

| Shortcut | Action |
| --- | --- |
| Fishing | Opens the inventory window and controls |
| Fishing CLI | Opens the keyboard terminal app |
| Start Fishing | Continues the saved run, rejoins if needed, and equips the rod |

Opening or closing either view leaves the controller unchanged. **Pause** releases input and saves counters. **Continue** resumes the saved run. **Stop**, **F9**, **F12**, or **Escape** stops input. Automatic recovery never clears a manual stop; an explicit Continue does.

If you move the installation folder, run `Setup.cmd` again to refresh the shortcut paths.

## Terminal app

Launch **Fishing CLI**, or run:

```powershell
.\fishing.cmd --color tui
```

| Key | Action |
| --- | --- |
| Left / Right / Tab, or 1–4 | Switch Run, Items, Live log, Setup |
| Up / Down / Page Up / Page Down / Home / End | Select or scroll |
| Enter | Activate selection; inspect an item or edit a setting |
| `/` | Search items or live events |
| F in Live log | Toggle following new entries |
| G in Live log | Cycle All, Catches, Recovery, Warnings |
| C / P / S | Continue / Pause / Stop |
| Q or Ctrl+C | Close the view; fishing stays as it was |
| Enter / Ctrl+G while editing | Save / cancel |

Do not use Escape to cancel an edit: it is a global stop key while fishing. In Setup, **Motion** toggles animations. Use a terminal at least 65 columns × 22 rows; 100 × 32 or larger is more comfortable.

The Run tab shows current state, items, hooks, time, rejoins, game launch attempts, recent events, and a bait plan. Items can be opened directly into a filtered live log. Live log keeps the latest 4,000 events in memory; raw logs retain the complete history on disk.

Scriptable commands remain available:

```powershell
.\fishing.cmd status --json
.\fishing.cmd items --filter fish
.\fishing.cmd logs --follow
.\fishing.cmd logs --activity --follow
.\fishing.cmd plan --hours 8
.\fishing.cmd pause
.\fishing.cmd continue
.\fishing.cmd stop
.\fishing.cmd export
```

## Items and bait

The item journal records confirmed quantity/NEW reward banners, original OCR text, quantity, and time. A round without a reward is normal. Unread or partial names are retained instead of silently discarded. OCR can misread text; the original observation remains in the log.

Set **Bait left** in terminal Setup after buying/equipping bait. This updates the estimate without resetting hooks or items. Estimated remaining bait is starting stock minus hooks, bounded at zero. Estimated bait per hour is hooks divided by active fishing time; the planner rounds the projected total up. One bait is counted per hook/minigame, including empty rounds. Fishing continues when the estimate reaches zero. These are consumption estimates, not inventory readings.

## Recovery and focus

The supervisor handles visible disconnect dialogs and a stalled fishing loop. Recovery uses **M → Back to main menu → Play → Ouwland → held private Join**, then equips the rod. If necessary it opens `roblox://placeId=16205713724` or restarts the selected Roblox game process. Retry delays limit repeated restart attempts. Input is released on loss of focus, window changes, or stop requests.

When a username is configured, [Roblox's public user lookup](https://create.roblox.com/docs/cloud/reference/features/users) resolves it to an ID and the [presence API](https://create.roblox.com/docs/cloud/reference/domains/presence) is polled every 45 seconds. Persistent absence **and** no fishing activity can request recovery. An API error alone does not mean a disconnect. No Roblox password, cookie, or API key is used or stored.

Rejoin and relaunch are distinct counters. Rejoins count completed joins after the first one in the run; game launches count launch attempts. Known recovery paths are implemented, but a game update or an unfamiliar menu can require recalibration.

## Local files and privacy

| File or folder | Contents |
| --- | --- |
| `config.local.json` | Local username, numeric ID, rod slot, motion and data settings |
| `data/` | Default state directory: counters, presence, process IDs, STOP/PAUSE flags, raw events and diagnostic screenshots |
| `Item-log.csv`, `Item-totals.csv` | Exported item history and totals |
| `Logs/` | Per-run CSV exports |
| `config.example.json` | Portable defaults; no account attached |

All local settings, logs, screenshots, recordings, and the Python environment are ignored by Git. Diagnostics remain on your PC. Keep `data/` to retain your run when updating the code. Advanced installs can set `data_dir` in local configuration or `FISHING_DATA_DIR` in the environment; relative paths are resolved from the application folder.

## Troubleshooting

- **Waiting for Roblox:** select Continue, bring Roblox to the foreground, and keep it there.
- **No minigame:** check the rod, supported resolution/UI scale, spawn position, and camera. The game must be able to start fishing from a single click at the configured water position.
- **Rod is not selected:** put the rod in the visible hotbar and set the correct fallback slot. The automatic detector uses this game's rod artwork and selection ring.
- **Presence stays unknown:** check the username, rather than the display name. Fishing can run without presence configured.
- **A button seems unresponsive immediately after Pause:** the worker is releasing held inputs. Wait for Paused before Continue.
- **CSV cannot refresh:** close the CSV in Excel; collection and raw event logging continue.
- **Setup fails:** check Python 3.12 x64 and internet access, then run Setup.cmd again. `setup_check.py` reports missing imports/assets without starting the game.
- **Game layout changed:** stop the bot. The current screen coordinates and templates are in `fishing_assistant.py`, `recovery.py`, and `rod_detector.py`.

To remove the app, stop it first, close both views, delete its desktop shortcuts, and remove the extracted folder when you no longer need the saved logs. No Windows service or scheduled task is installed.

## Development

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe health_check.py
```

Tests use isolated temporary state and mocked controls; they do not drive Roblox. Live game validation is still needed after changing vision or input logic. Python 3.12 on Windows x64 is the tested runtime.

Game artwork in `assets/` is used as visual reference and UI thumbnails. This is an independent tool, not an official Roblox or game project.
