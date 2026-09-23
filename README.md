# Fishing

A Windows fishing assistant for the Project Slayers 2 / Ouwland fishing minigame. Includes a game-inspired inventory window, a keyboard terminal app, item history, live events, bait estimates, and reconnect recovery.

## Launch it

**First time:** extract the repository, install Python 3.12 x64, and double-click **Setup.cmd**. Then open **Fishing** on the desktop, set your Roblox username and rod slot in Settings, prepare the game as described below, and click **Continue**.

Setup installs the **`autofish`** command for your Windows account. Open a new terminal anywhere and run:

```powershell
autofish start
```

Choose the game, then **Minigame only**, **Fish here**, or **Full farmer**, with arrows and Enter. The dashboard opens after starting. Only Project Slayers 2 / Ouwland is supported currently; future supported games can appear in the same picker.

The CLI opens with a full-terminal rod cast over water and reels the float back across the scene when you press **Q**. **Setup → Motion → Reduced** skips both animations.
Ore pickups have their own short mineral-glint animation in the dashboard; it does not interrupt fishing or alter the item log.

Already set up? Double-click **Install-CLI.cmd** once to add the command without reinstalling dependencies. No administrator access is needed. If a terminal was open during installation, close and reopen it to pick up the updated PATH.

```powershell
autofish                  # Dashboard; does not start fishing
autofish games            # Supported games and IDs
autofish start --game project-slayers-2 --mode assist --no-ui
autofish status
autofish pause
autofish continue
autofish stop
autofish logs --activity --follow
```

The command points to this application folder and preserves its settings and saved run. Keep the folder in place; if you move it, rerun Install-CLI.cmd from the new location. To remove only the global command, run `Install-CLI.cmd -Uninstall`; the app and fishing data remain. `Setup.ps1 -NoCLI` skips command installation.

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
| Display | Automatic scaling for a 16:9 Roblox client area, with normal game UI scale. 1920 × 1080 and 2560 × 1440 tested live; see resolution notes below |
| Position | Full farmer uses a saved spawn; Fish here stays wherever you put it. No travel across the map |
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

- Use **one Roblox client**, with a **16:9 client area** and the game's normal UI scale. Fullscreen at **1920 × 1080** or **2560 × 1440** is the simplest setup. The bot measures the client area, scales screenshots for recognition, and maps clicks back to your window automatically.
- Set the saved spawn at your fishing spot in Ouwland, facing the water. A rejoin must restore the same general spot. Optional fishing references can correct small differences; the assistant does not navigate across the map or find a fishing spot.
- Keep the game visible and foreground. Opening another app releases input and waits; Continue returns focus to Roblox and recovery resumes. It cannot fish through a minimized window, lock screen, or sleeping PC. A second monitor is useful for viewing status.
- The rod is located in the visible hotbar and selected only when its selection ring is absent. If it cannot be recognized during a rejoin, the configured slot is used. Moving the rod to another visible slot is supported; an unequipped rod in the backpack must first be placed in the hotbar.
- In CLI **Setup → Cast point**, enter an X, Y target in the 2560 × 1440 reference view for Full farmer. The default is `1650, 800`. **Capture pointer** gives you four seconds to place the mouse over the Roblox game world, then saves its position without clicking or changing focus. This target scales with the Roblox window. Fish here continues to use the pointer position you choose in-game; Minigame only never casts.
- Bait is optional. Equip it in-game if desired. There is no purchasing automation.

## Resolution notes

No manual calibration is required for the supported 16:9 layout. Window borders and title bars are excluded from the measurements, and another monitor or window origin is supported. Moving or resizing Roblox releases input and causes the supervisor to reacquire the client area.

The same coordinate mapping is tested with 720p and 4K image fixtures, but those sizes have not had a full live fishing run. Very small windows can make text unreadable. An ultrawide, 4:3, or differently scaled game UI may rearrange controls; use a 16:9 window in that case. The bot reports an unsupported shape instead of clicking guessed locations. This is resolution adaptation, not automatic navigation to a fishing spot.

## Desktop shortcuts

| Shortcut | Action |
| --- | --- |
| Fishing | Opens the inventory window and controls |
| Fishing CLI | Opens the keyboard terminal app |
| Start Fishing | Continues the saved run, rejoins if needed, and equips the rod |

Opening or closing either view leaves the controller unchanged. **Pause** releases input and saves counters. **Continue** resumes the saved run. **Stop** stops input. In Minigame only and Fish here, **F9/F12 stop only while Roblox is foreground**; Escape never stops these modes. Full farmer retains its global F9/F12/Escape stop keys. Automatic recovery never clears a manual stop; an explicit Continue does. The CLI shows the stop or waiting reason, including the exact stop key for manual modes.

**F8 pauses/resumes all three modes while Roblox is foreground.** Full farmer keeps the same worker and counters, releases held input, and rereads the current minigame or pickup on resume. Holding F8 counts once. Switching apps or moving the pointer outside Roblox pauses Full farmer automatically; returning resumes unless F8 was used to pause manually. Neither kind of pause triggers a rejoin. The dashboard shows `Paused — F8 to resume`; an explicit Continue command also releases Full farmer's F8 pause. Health checks and presence recovery leave manual pauses alone.

If you move the installation folder, run `Setup.cmd` again to refresh the shortcut paths.

## Fishing modes

| Mode | You control | Assistant handles |
| --- | --- | --- |
| **Full farmer** (`full`) | Saved spawn and initial setup | Rod, casts, minigame, collection, inventory checks, local repairs and reconnects |
| **Minigame only** (`assist`) | Spot, rod, casts and pickups | Minigame mouse hold/release |
| **Fish here** (`spot`) | Spot, camera, mouse and rod; F8 starts | Click, reel, collect, repeat |

### Fish here

Choose **Settings → Mode → Fish here**, save and Continue. Or run:

```powershell
.\fishing.cmd spot
```

Bring Roblox forward, equip your rod, position your character, camera and mouse, then press **F8**. Fish here only clicks, reels, holds T for a recognized Collect prompt, and repeats. Bait is optional. Empty rounds continue normally. Confirmed reward banners are added to the item journal.

**Losing Roblox focus pauses input.** Return with the pointer inside its window to continue automatically. It rechecks any current minigame or pickup before casting again. Three unsuccessful cast or pickup attempts wait for you to check the spot and press F8 again.

**F8 toggles pause/resume while in Roblox**, including during a minigame or pickup. A held F8 counts once. A manual F8 pause stays paused when switching away and back. The controller launches idle until your first F8 press.

This mode never moves the mouse or character, adjusts the camera, changes shift lock, switches focus, equips items, opens inventory, or rejoins. Its only injected inputs are the left mouse button and T. It clicks wherever your mouse currently is, including the center when you use shift lock. A disconnect/menu waits for you to fix it.

Casting requires three consecutive checks of the selected rod plus a fresh check immediately before the click. Keep your pointer clear of the hotbar and other HUD controls. Temporary loss of the rod icon does not permit an early recast. After a round, the pickup scan covers a wider area at full resolution and requires six seconds of consistently empty observations before skipping an unconfirmed reward. While waiting for a bite, only the fast minigame detector runs.

After a confirmed collection, the assistant waits briefly for the rod and rechecks the scene, then casts even if the same reward popup is still fading. A fresh Collect prompt, menu, changed rod or different reward blocks the click. Pickup scans include OCR time in their interval; extra visual rod checks avoid waiting for three full text scans. The status reports pickup evidence and scan time for diagnosis.

Move or reposition while paused, then return to continue. Restarting the controller or Roblox requires F8 again. No pointer coordinate is saved or restored. F9/F12 in Roblox and the app's Pause/Stop remain available.

The detector combines color and target-outline checks so transparent green/yellow bars remain recognizable over red scenery. It still requires the fishing UI and white marker; obscured or ambiguous markers release input instead of guessing. A bounded set of missed-marker crops is retained locally for diagnosis.

The detector follows the target's paired side borders, keeping green scenery such as lily pads from becoming a false target. Dim tinted markers also use local contrast. Control-bar height is measured each frame, including larger bars. These cases have offline regression coverage.

Common and rare rods are recognized automatically in different hotbar positions, including their equipped and unequipped appearances. Selection uses the circular outline's contrast, so a scene tint or night lighting does not depend on a white-color threshold. Full farmer keeps an already selected rod; when neither is selected it prefers a confidently recognized rare rod. Fish here still waits for you to equip it. Additional rod references can be added to `assets/rods.json` with their image, selected state, center anchor and priority; unfamiliar icons are not guessed.

All modes use the same adaptive reeling controller and aim for 60 checks per second. It estimates marker speed, brakes before overshoot, learns upward/downward response, and rejects impossible one-frame marker jumps. Focus return discards old velocity. Offline tests include captured target motion replayed with several simulated rod response rates; these results are not a guaranteed live catch rate.

### Minigame only

For semi-automatic fishing, select **Settings → Mode → Minigame only**, save, and Continue. In the CLI, select **Run → Minigame only** and press Enter. Pause first when switching from a running mode.

Or start it directly:

```powershell
.\fishing.cmd assist
```

You choose the spot, position the camera, equip the rod, cast, and collect with T. The assistant only holds/releases the left mouse button while it recognizes the fishing minigame. It does not move the mouse or character, cast, equip, open inventory, collect, purchase, rejoin, or relaunch Roblox. It releases input when the UI disappears or focus is lost, and waits for Roblox to be foreground again. Q closes the CLI view; P/S pause/stop from the CLI. F9/F12 stop while Roblox is foreground; Escape and keys in other apps do not stop this mode.

**F8 pauses/resumes Minigame only as well as Fish here.** Minigame only starts enabled; focus loss pauses it automatically, and focus return resumes it unless you paused with F8. On return it waits for your Alt/Tab/Windows keys to be released, reacquires current marker positions, and resends a mouse-button release inside the recognized minigame before reeling. It never presses those navigation keys or changes focus. Manual F8 pause remains separate from automatic focus pause.

Detected minigames add to the hook count. Manual pickups are not recorded in the item journal in this mode. Waiting for your next cast is normal and does not trigger recovery. Use `fishing.cmd continue --mode full` after pausing to return to the full farmer.

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

The **Run** tab has direct **Minigame only**, **Fish here**, and **Full farmer** choices: select with ↑/↓ and press Enter to start. Pause the current mode before switching to another. **C** continues the saved mode. The command equivalents are `fishing.cmd assist`, `fishing.cmd spot`, and `fishing.cmd continue --mode full`.

Use Ctrl+G to cancel an edit; Escape remains a global stop key in Full farmer. In Setup, **Motion** toggles animations. Use a terminal at least 65 columns × 22 rows; 100 × 32 or larger is more comfortable.

The Run tab shows current state, items, hooks, time, rejoins, game launch attempts, recent events, and a bait plan. Items can be opened directly into a filtered live log. Live log keeps the latest 4,000 events in memory; raw logs retain the complete history on disk.

Recovery actions are cyan, retries and warnings amber, failures red, and catches green. The Run tab's recent events use the same colors as Live log. Rapid screen/OCR observations stay in the raw logs rather than filling the live feed; individual menu actions and Join attempts remain visible.

Fresh **Golden Fish, Clown Fish, and Zebra Fish** catches get a brief swimming fish and sparkle effect above the content. It clears after 4.8 seconds without moving the log or blocking controls. Opening a saved run does not replay its catches. **Motion → Reduced** uses a still banner. These are the app's highlighted catches, not a claim about official rarity tiers.

<details><summary>A little terminal secret</summary>

Type **blub** in the terminal dashboard, outside a text field, with less than two seconds between letters. A catfish visits for a few seconds. It is decorative and adds nothing to the item journal.

</details>

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

## Future bot integration

A local, versioned JSON interface is ready for another program to call:

```powershell
.\fishing.cmd api status
.\fishing.cmd api events --limit 20
.\fishing.cmd api pause --request-id example-123
```

It supports status, items, recent events, pause, resume, and stop. See [INTEGRATION.md](INTEGRATION.md) for the response contract and a subprocess example. This release does not connect to Discord or run a network listener; a remotely hosted bot will need an authenticated bridge to this Windows PC later.

## Items and bait

The item journal records confirmed quantity/NEW reward banners, original OCR text, quantity, and time. A round without a reward is normal. Unread or partial names are retained instead of silently discarded. OCR can misread text; the original observation remains in the log.

**Identify unknown drops** is enabled by default in Settings. On the first use, the bot attempts a baseline inventory scan. After that, inventory opens only for unresolved catches, between fishing rounds, with **at least ten minutes between attempts**. There are no timer-only scans, and empty rounds without a Collect prompt do not request a scan or create an item entry. Each attempt has a **20-second scanning budget**, followed by closing the menu; a native OCR call already in progress may finish first. Unreadable scans back off for 20, 40, then at most 60 minutes. Fishing continues during the wait. Cached thumbnails make later scans faster and supply artwork to the window.

The comparison subtracts known catches and corrects an unreadable journal entry only when one unexplained increase matches its quantity. A visible Collect prompt with a missed banner can also be recovered this way. Several unknown catches during the wait are kept as originally observed rather than assigning a combined inventory increase to the wrong catch; that scan establishes a fresh baseline. CSV exports include the evidence source.

Reconnects reuse a recent, complete checkpoint for the same account and supervisor without opening inventory again. An interrupted round, a new supervisor, an account change, or a stale checkpoint invalidates its item comparison but retains the scan cooldown. Fishing resumes immediately, and the next eligible unresolved catch can establish a fresh baseline. This prevents unlogged loot from an interrupted round being attributed to a later catch. Turning identification off in Settings disables these checks entirely.

Leave the in-game inventory search empty; the scanner does not send typing or movement shortcuts to clear it. The scanner currently requires the complete inventory to fit the visible 10-column grid (at most 100 occupied slots). Unreadable counts, ambiguous changes, or incomplete scans preserve the unknown label and log the reason. It closes the menu before fishing resumes. It cannot reliably repair older unknown entries without a before-catch baseline. Inventory use or trade changes during a comparison can also prevent identification.

Set **Bait left** in terminal Setup after buying/equipping bait. This updates the estimate without resetting hooks or items. Estimated remaining bait is starting stock minus hooks, bounded at zero. Estimated bait per hour is hooks divided by active fishing time; the planner rounds the projected total up. One bait is counted per hook/minigame, including empty rounds. Fishing continues when the estimate reaches zero. These are consumption estimates, not inventory readings.

## Recovery and focus

Pickup recognition covers a wider area and requires repeated Collect evidence before holding T. A quantity/NEW label must be next to an item name to count as a reward. Empty rounds continue without blind T holds. Wall Climb, vendor prompts, and conflicting prompts release T and request recovery.

Known pickup, missed-cast, tracking, window and landmark faults first get one eligible local repair per two minutes. Persistent faults escalate to the menu rejoin, then client relaunch if recovery fails. A lost-focus pause waits for Roblox. Local repairs preserve the run and do not count as a server rejoin. Unknown failures retain a diagnostic report and use the existing rejoin path.

### Saved fishing reference

This is optional and separate from resolution scaling. At a working fishing spot, pause the farmer, finish any open minigame, then use **Settings → Save fishing view** or **CLI Setup → Save fishing reference**. Setup brings Roblox forward and makes small camera probes. Enable **Correct small position drift** / **Position correction** to include short movement probes. Stop/F9/F12/Escape cancels setup. Setup does not resume the farmer.

```powershell
.\fishing.cmd reference save --position
.\fishing.cmd reference status
.\fishing.cmd reference disable
```

The default reference uses two crate surfaces, with the building across the water as optional extra evidence. Both crate surfaces must match; distant scenery can be excluded when fog or shadows obscure it. For a different arrangement, `reference save --boxes '[[x,y,w,h],...]'` accepts at least two boxes in a **1280 × 720** reference image: put two separate textured surfaces near the character first, then optional distant static scenery. Avoid the avatar, HUD, water, moving wheels and foliage. Reference images and calibration belong to the configured account and place and stay in local data. Without a matching profile, normal recovery remains available.

After recovery, a readable compass restores the saved heading using repeated observations and camera-only steps of at most 60 mouse pixels. This coarse pass is limited to 35 seconds and 1,100 total pixels; it never moves the character. The assistant then checks the crate reference and corrects the camera before position. Position corrections require the separate movement calibration. Each fine step is checked against the scene, with a separate 25-second budget, at most 160 camera pixels and 0.12 seconds of movement input per attempt. It tolerates small residual error because game movement is not pixel-exact. A correction that makes the measured view worse is reversed only while landmarks remain visible. Obscured scenery, excessive drift, a bad calibration or a new stop prevents further movement. If the initial view cannot be matched, fine alignment is skipped and the normal saved-spawn farmer continues; pickup and missed-cast safeguards still apply. Losing the reference after corrective input requests recovery, and repeated correction failure stops for adjustment. This handles nearby drift; it cannot prove a 3D position or recover arbitrary falls. Recapture or disable an unsuitable reference while paused.

A lightweight drift check runs between rounds at most once every three minutes. It does not open inventory or interrupt minigame tracking. Changing camera zoom or mouse sensitivity can require saving a new reference.

### Recent pace and diagnostics

The window and CLI show recent hooks/minute and items/minute over up to 15 minutes of sampled wall time, including recovery. `status --json` also includes phase seconds for bites, minigames, collection, inventory, recovery and focus waits. Rates marked saved are stale. Existing lifetime totals and the active-time bait planner remain available.

`fishing.cmd diagnostics` shows the last eight failure reports. Each includes a reason code, decision details and up to four local context frames; the diagnostic ring uses at most 32 JPEGs. Raw event logs retain the full history. Diagnostics do not add frame capture to the minigame tracking loop.

The supervisor handles visible disconnect dialogs and a stalled fishing loop. Vendor purchase dialogs are cancelled before recovery. Recovery uses **M → Back to main menu → Play → Ouwland → held private Join**, then equips the rod. If necessary it opens `roblox://placeId=16205713724` or restarts the selected Roblox game process. Retry delays limit repeated restart attempts. Input is released on loss of focus, window changes, or stop requests.

If casts stop starting minigames after three separate rejoins within 90 minutes, Full farmer stops with an unsafe-position message instead of endlessly cycling through menus. Move the saved spawn farther from the water edge, then explicitly start or continue again. Health checks flag the pattern after two such recoveries.

For a saved spawn right on a ledge, `spawn_backstep_seconds` in `config.local.json` can move the character a small distance backward after a confirmed private-server Join. It defaults to `0` for other accounts and is capped at `0.35`; it never runs on a focus return or rod-only repair. Check that your chosen cast point still lands in water after enabling it.

Menu actions wait for repeated observations of a stable target. Each action has its own retry delay, so a completed menu transition does not inherit a previous button's wait. The private Join button is checked again after the cursor settles; holding ends when its panel changes, with a 4.5-second limit. A short quiet period after Join lets the game transition before another attempt; repeated rejected joins back off. Recovery still requires three continuous seconds of the loaded world before equipping the rod and starting fishing.

Cast and rod clicks allow a brief cursor settle before pressing, with stop and focus checks throughout. The first cast after loading or selecting the rod uses a longer settle to let Roblox update its hover target after the menu; subsequent casts retain their normal timing. The minigame tracking loop is unchanged.
When a reward is confirmed, the next cast uses a shorter cooldown and skips repeated cursor-settling movements if the pointer is still at the known cast point. Menus, rod changes, focus pauses, pointer movement and uncertain pickups keep the longer checks.

On the primary monitor, mouse moves use primary-screen absolute coordinates; targets on other monitors use virtual-desktop coordinates. The actual cursor position is checked before clicking. This avoids the primary-screen hit-test mismatch observed on the tested two-monitor desktop.

When a username is configured, [Roblox's public user lookup](https://create.roblox.com/docs/cloud/reference/features/users) resolves it to an ID and the [presence API](https://create.roblox.com/docs/cloud/reference/domains/presence) is polled every 45 seconds. Persistent absence **and** no fishing activity can request recovery. An API error alone does not mean a disconnect. No Roblox password, cookie, or API key is used or stored.

Rejoin and relaunch are distinct counters. Rejoins count completed returns from a Join/reconnect/launch attempt after the initial game-ready state; repeated Join holds count once, and rod-only maintenance resumes do not add rejoins. Counts are rebuilt from saved events, including older runs. Game launches count launch attempts. Known recovery paths are implemented, but a game update or an unfamiliar menu can require recalibration.

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

## Branches and rollback

`master` is the stable release and GitHub default. `dev` holds validated candidates; `dev-rolling` integrates feature branches. New changes start on `feature/<name>` and merge into `dev-rolling` with a merge commit. See [CONTRIBUTING.md](CONTRIBUTING.md) for promotion and rollback commands. The pre-update release is tagged `stable-before-inventory-resolution`. Switching code versions keeps ignored run data and account settings. Always pause before switching.

## Development

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe health_check.py
```

The suite covers real 1080p inventory crops, input guards, duplicate prevention, inventory reconciliation and throttling, restart checkpoints, scan-budget cleanup, recovery-log counting and colors, menu and Join transitions, held-input cleanup, multi-monitor input, catch-effect deduplication, reduced motion, responsive controls and the JSON integration boundary. Additional checks cover minigame-only activation/release, spatial pickup evidence, local-repair limits, bounded diagnostic storage, landmark matching, correction limits and recent pace calculations. A prior live 1080p run confirmed four catches, including one recovered from inventory differences. The new minigame-only mode was checked with two manual casts; camera and small lateral corrections were also exercised live.

Tests use isolated temporary state and mocked controls; they do not drive Roblox. Live game validation is still needed after changing vision or input logic. Python 3.12 on Windows x64 is the tested runtime.

Game artwork in `assets/` is used as visual reference and UI thumbnails. This is an independent tool, not an official Roblox or game project.
