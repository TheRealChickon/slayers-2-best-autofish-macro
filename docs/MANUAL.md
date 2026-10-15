# Autofish manual

The complete reference for every mode, setting and file. New here? Start with the
[README](../README.md) instead; it covers install and first run in a few steps.

A Windows assistant for Project Slayers 2 fishing. It includes a game-inspired inventory window, a keyboard terminal app, item history, live events, bait estimates, and fishing reconnect recovery.

## Launch it

**First time:** extract the repository, install Python 3.12 x64, and double-click **scripts\Setup.cmd**. Then open **Autofish** on the desktop, answer the gamepass question, set your rod slot and cast point in Settings, prepare the game as described below, and press **Start**.

Setup installs the **`autofish`** command for your Windows account. Open a new terminal anywhere and run:

```powershell
autofish start
```

Choose the game, then **Minigame only**, **Fish here**, or **Full farmer**, with arrows and Enter. The dashboard opens after starting. Only Project Slayers 2 / Ouwland is supported currently; future supported games can appear in the same picker.

Full farmer first checks the current world instead of forcing a startup rejoin. A visible fishing minigame goes straight to the worker without cancelling it; a stable loaded world starts fishing from the current position. A failed first catch continues from there. Saved heading, landmark alignment and title menus are skipped for that adopted position. Disconnects, menu-based joins and repeated inability to start fishing retain normal recovery; an actual rejoin restores the saved setup. Stop, F8, focus, capture and window guards still apply.

The CLI opens with a full-terminal rod cast over water and reels the float back across the scene when you press **Q**. **Setup → Motion → Reduced** skips both animations.
Ore pickups have their own short mineral-glint animation in the dashboard; it does not interrupt fishing or alter the item log.

Already set up? Double-click **scripts\Install-CLI.cmd** once to add the command without reinstalling dependencies. No administrator access is needed. If a terminal was open during installation, close and reopen it to pick up the updated PATH.

```powershell
autofish                  # Dashboard; does not start fishing
autofish games            # Supported games and IDs
autofish start --game project-slayers-2 --mode assist --no-ui
autofish status
autofish pause
autofish continue
autofish continue --mode full --until 22:00  # Stop at 22:00 local time today
autofish rejoin        # Reconnect the configured account without farming
autofish stop
autofish logs --activity --follow
autofish wiki             # Open your local item wiki, if captured
```

The command points to this application folder and preserves its settings and saved run. Keep the folder in place; if you move it, rerun scripts\Install-CLI.cmd from the new location. To remove only the global command, run `scripts\Install-CLI.cmd -Uninstall`; the app and fishing data remain. `scripts\Setup.ps1 -NoCLI` skips command installation.

**After setup:**

- **Autofish** on the desktop opens the app window (`src/app_window.py`): live status, Start/Continue, Pause and Stop, catches, log, Rod Lab and the main settings. It is served only to this PC on 127.0.0.1 and opens as an Edge app window. Closing it leaves the farmer running.
- **Fishing CLI** opens the terminal dashboard. Press **C** to continue, **P** to pause, **S** to stop, and **Q** to close only the dashboard.
- **Start Fishing** resumes the saved run directly.
- Without desktop shortcuts, run `scripts\Open-Autofish.ps1`, `scripts\Open-CLI.ps1`, or `scripts\fishing.cmd --color tui` from the extracted application folder.

## Where it works

Full farmer locates the return-to-menu confirmation from the adjacent green and
red buttons. It waits for a unique visible pair before clicking, including when
the inventory dialog places those buttons higher on screen.

| Requirement | Support |
| --- | --- |
| Accounts | Any account that owns a rod, has it in the visible hotbar, and can use this game's private-server Join menu; configure the username for that account's presence checks |
| Operating system | Windows x64; not macOS, Linux, mobile, or Roblox console |
| Game | This game's Ouwland fishing minigame; not arbitrary Roblox games |
| Display | Automatic scaling for a 16:9 Roblox client area, with normal game UI scale. 1920 × 1080 and 2560 × 1440 tested live; see resolution notes below |
| Position | Full farmer starts at the current position and uses the saved spawn when recovery requires a rejoin; Fish here stays wherever you put it. No travel across the map |
| Focus | Roblox must stay visible and foreground; switching apps pauses input |

Setup has been tested from a clean source checkout on Windows with Python 3.12. Portability removes hardcoded account and computer paths; it does not remove the screen-layout and in-game setup requirements.

## First setup

1. Install **Python 3.12, 64-bit** from [python.org](https://www.python.org/downloads/windows/). Include the Python launcher and Tcl/Tk when installing.
2. Download this repository with **Code → Download ZIP** and extract it to a permanent, writable folder, or clone it with Git.
3. Double-click **scripts\Setup.cmd**. It creates a local Python environment, installs `requirements.txt`, checks the required files, and adds three desktop shortcuts. No administrator privileges are needed.
4. Open **Autofish** from the desktop. In **Settings**, enter your Roblox **username** and set the rod's hotbar slot (1–9). The username is optional; it enables the public presence check. It does not sign in or change the account open in Roblox.
5. Sign into the intended account in Roblox, open the game, and complete the fishing position setup below. Press **Start** in Autofish.

An existing installation can be checked without reinstalling packages:

```powershell
.\scripts\Setup.ps1 -SkipInstall
```

If your PowerShell policy blocks scripts, use `scripts\Setup.cmd`. The launcher sets a policy only for that process; it does not change the machine's policy.

## Game setup

The account is configurable. Each account must own a fishing rod, have it in a visible hotbar slot, and have access to the private-server Join menu.

- Use **one Roblox client**, with a **16:9 client area** and the game's normal UI scale. Fullscreen at **1920 × 1080** or **2560 × 1440** is the simplest setup. The bot measures the client area, scales screenshots for recognition, and maps clicks back to your window automatically.
- Set the saved spawn at your fishing spot in Ouwland, facing the water. A rejoin must restore the same general spot. Optional fishing references can correct small differences; the assistant does not navigate across the map or find a fishing spot.
- Keep the game visible and foreground. Opening another app releases input and waits; Continue returns focus to Roblox and recovery resumes. It cannot fish through a minimized window, lock screen, or sleeping PC. A second monitor is useful for viewing status.
- The rod is located in the visible hotbar and selected only when its selection ring is absent. If it cannot be recognized during a rejoin, the configured slot is used. Moving the rod to another visible slot is supported; an unequipped rod in the backpack must first be placed in the hotbar.
- Rod recognition also checks the rod foreground when daylight scenery shows through the hotbar. Selection attempts are logged separately from verified equipment. With automatic rod detection enabled, recovery does not start fishing until selection is verified.
- An unreadable rod keeps the supervisor alive with released input and a visible retry countdown. Full farmer tries two local repairs, then rejoins the saved spawn, at most once per ten minutes while this fault persists. Farm here keeps checking locally and only reconnects after positive disconnect evidence. Manual Stop, Pause, F8 and focus guards still apply.
- In CLI **Setup → Cast point**, enter an X, Y target in the 2560 × 1440 reference view for Full farmer. The default is `1650, 800`. **Capture pointer** gives you four seconds to place the mouse over the Roblox game world, then saves its position without clicking or changing focus. This target scales with the Roblox window. Fish here continues to use the pointer position you choose in-game; Minigame only never casts.
- **Camera** in Setup can keep your current zoom (default) or zoom into first person automatically when Full farmer starts. First person may slowly pitch toward a nearby railing; a missed cast then triggers a rejoin to restore the view. Keep the third-person view for a spot where first person does not consistently reach water. **Heading** is an optional compass direction for a saved spawn, restored after a rejoin when no fishing reference is saved. Set it while facing a working cast. A saved fishing reference takes precedence over the heading.
- **Fishing titles** defaults to keeping your loadout. **Auto best** checks the visible Fishing titles once during normal world preparation after a needed join, reads completed requirements, and equips the three strongest known fishing titles. Adopting the current fishing position skips that menu work. It leaves an unreadable or unfamiliar loadout alone. This game's observed order is Legendary Fisherman, Salvager, Leviathan Hunter, Deep Water Angler, then Angler; luck takes priority for rare drops. It does not scan titles every round.
- Bait is optional. Equip it in-game if desired. Full farmer reads the equipped bait once at startup and estimates how many hooks remain. The CLI warns on a nighttime start when the observed stock is under about 30 minutes at the recent pace. Fishing continues after bait runs out. There is no purchasing automation.

## Resolution notes

No manual calibration is needed. The bot reads the Roblox client as a 16:9 picture
and scales it to a 2560 × 1440 reference; window borders and title bars are
excluded, and any monitor or window position works.

When the client is not 16:9 (more than 8% off, e.g. maximized on a 1366 × 768
laptop, a 16:10 or 4:3 monitor, or ultrawide), startup and recovery resize the
Roblox window to the largest 16:9 client that fits the monitor's work area and
centre it (`src/window_fit.py`). A maximized window is restored first. If Roblox is
fullscreen on a screen that is not 16:9, Full farmer presses F11 once (only with
Roblox in front) to leave fullscreen and then resizes; Minigame only asks you
to press F11 yourself. Clients from 960 × 540 up to 4K are accepted.
A screen too small for a 960 × 540 client, or a window Windows refuses to resize,
stops with a message naming the size and what to change.

The process is per-monitor DPI aware, so 125% and 150% Windows scaling and
mixed-scale multi-monitor setups use real pixels for the window, cursor and
capture. `tests/test_resolution_fixtures.py` re-renders real game frames at 16
client sizes (fullscreen, maximized and fitted windows) and checks the minigame
and rod detection against the reference.

## Desktop shortcuts

| Shortcut | Action |
| --- | --- |
| Fishing | Opens the inventory window and controls |
| Fishing CLI | Opens the keyboard terminal app |
| Start Fishing | Continues the saved run, rejoins if needed, and equips the rod |

Opening or closing either view leaves the controller unchanged. **Pause** releases input and saves counters. **Continue** resumes the saved run. **Stop** stops input. In Minigame only and Fish here, **F9/F12 stop only while Roblox is foreground**; Escape never stops these modes. Full farmer retains its global F9/F12/Escape stop keys. Automatic recovery never clears a manual stop; an explicit Continue does. The CLI shows the stop or waiting reason, including the exact stop key for manual modes.

**F8 pauses/resumes all four modes while Roblox is foreground.** Full farmer keeps the same worker and counters, releases held input, and rereads the current minigame or pickup on resume. Holding F8 counts once. Switching apps or moving the pointer outside Roblox pauses Full farmer automatically; returning resumes unless F8 was used to pause manually. Neither kind of pause triggers a rejoin. The dashboard shows `Paused — F8 to resume`; an explicit Continue command also releases Full farmer's F8 pause. Health checks and presence recovery leave manual pauses alone.

If you move the installation folder, run `scripts\Setup.cmd` again to refresh the shortcut paths.

## Fishing modes

| Mode | You control | Assistant handles |
| --- | --- | --- |
| **Full farmer** (`full`) | Saved spawn and initial setup | Rod, casts, minigame, collection, inventory checks, local repairs and reconnects |
| **Minigame only** (`assist`) | Spot, rod, casts and pickups | Minigame mouse hold/release |
| **Fish here** (`spot`) | Spot, camera, mouse and rod; F8 starts | Click, reel, collect, repeat |
| **Auto rejoin** (`rejoin`) | The game after reconnection | Detect disconnects and return to Ouwland; no fishing, attacks or gear changes |

### Auto rejoin from the CLI

Set the Roblox username in Setup first, then run `autofish rejoin`. For the configured account, the guard checks Roblox's presence about every 45 seconds and reads the visible client. A disconnect dialog or Ouwland menu starts recovery through the game's private-server Join flow. If the Roblox window is gone for 45 seconds, it can reopen the configured place link after the desktop has been idle for 90 seconds. A failed presence API call alone does not count as a disconnect. A visible, loaded world prevents a presence-only rejoin.

This is a **standalone** CLI mode; the app allows only one controller at a time. Full farmer already has its own reconnect recovery. To switch from another running mode, use `autofish pause`, wait for it to stop, then `autofish rejoin`. The guard does not resume fishing or statue attacks after reconnecting. `autofish status`, `autofish watch`, and `autofish logs --activity --follow` show its state, attempts, successful rejoins, client launches, and retries. `autofish pause` retains those counters, `autofish continue` resumes, and `autofish stop` ends the guard. F8 pauses or resumes only with Roblox foreground; F9/F12 stop only with Roblox foreground. It never sends input to another foreground app.

### Fish here

Choose **Settings → Mode → Fish here**, save and Continue. Or run:

```powershell
.\scripts\fishing.cmd spot
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
.\scripts\fishing.cmd assist
```

You choose the spot, position the camera, equip the rod, cast, and collect with T. The assistant only holds/releases the left mouse button while it recognizes the fishing minigame. It does not move the mouse or character, cast, equip, open inventory, collect, purchase, rejoin, or relaunch Roblox. It releases input when the UI disappears or focus is lost, and waits for Roblox to be foreground again. Q closes the CLI view; P/S pause/stop from the CLI. F9/F12 stop while Roblox is foreground; Escape and keys in other apps do not stop this mode.

**F8 pauses/resumes Minigame only as well as Fish here.** Minigame only starts enabled; focus loss pauses it automatically, and focus return resumes it unless you paused with F8. On return it waits for your Alt/Tab/Windows keys to be released, reacquires current marker positions, and resends a mouse-button release inside the recognized minigame before reeling. It never presses those navigation keys or changes focus. Manual F8 pause remains separate from automatic focus pause.

Detected minigames add to the hook count. Manual pickups are not recorded in the item journal in this mode. Waiting for your next cast is normal and does not trigger recovery. Use `scripts\fishing.cmd continue --mode full` after pausing to return to the full farmer.

## Terminal app

Launch **Fishing CLI**, or run:

```powershell
.\scripts\fishing.cmd --color tui
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

The **Run** tab has direct **Minigame only**, **Fish here**, **Full farmer** choices: select with ↑/↓ and press Enter to start. Pause the current mode before switching to another. **C** continues the saved mode. The command equivalents are `scripts\fishing.cmd assist`, `scripts\fishing.cmd spot`, `scripts\fishing.cmd continue --mode full`.

Use Ctrl+G to cancel an edit; Escape remains a global stop key in Full farmer. In Setup, **Motion** toggles animations. Use a terminal at least 65 columns × 22 rows; 100 × 32 or larger is more comfortable.

The terminal view has Run, Items, Logs, Settings and Predictions pages. Run keeps the current state, pace, last catch, bait estimate and four mode choices together. Detailed recovery history is in Logs. The live log keeps the latest 4,000 events in memory; raw logs retain the complete history on disk.

## Personal item wiki

`autofish wiki` builds and opens a local, searchable field ledger from saved inventory and archive captures. `autofish wiki --no-open` only rebuilds the files. The resulting `site/index.html` has Field (damage build and current character), Satchel (owned items), Archive (unowned reference items), and Bosses (when a reviewed `boss-analysis.json` is present beside the captures). The Field page includes the captured HUD, measured M1 build and recommended owned Stats pieces. `site/context.md` is the plain-text version to attach to an AI conversation; `site/items.json` provides the same snapshot as structured data. Open an item detail image to check its captured in-game text. If this account has a private hosted Site URL saved locally, `autofish wiki --site` opens it; rebuilding the local wiki does not automatically update that hosted snapshot.


The wiki keeps live inventory stats and archive base stats separate, especially when an owned item has a `+N` refinement. Owned entries take priority, so an item also present in the archive does not appear twice in the main listings. Captures and generated pages are local account data and stay out of Git. The wiki is a snapshot, not a live inventory sync: rebuild it after changing equipment, refining items or collecting new gear. Item names and quantities come from UI OCR and may need checking against their attached screenshots.

Recovery actions are cyan, retries and warnings amber, failures red, and catches green. The Run tab's recent events use the same colors as Live log. Rapid screen/OCR observations stay in the raw logs rather than filling the live feed; individual menu actions and Join attempts remain visible.

Fresh **Golden Fish, Clown Fish, and Zebra Fish** catches get a brief swimming fish and sparkle effect above the content. It clears after 4.8 seconds without moving the log or blocking controls. Opening a saved run does not replay its catches. **Motion → Reduced** uses a still banner. These are the app's highlighted catches, not a claim about official rarity tiers.

<details><summary>A little terminal secret</summary>

Type **blub** in the terminal dashboard, outside a text field, with less than two seconds between letters. A catfish visits for a few seconds. It is decorative and adds nothing to the item journal.

</details>

Scriptable commands remain available:

```powershell
.\scripts\fishing.cmd status --json
.\scripts\fishing.cmd items --filter fish
.\scripts\fishing.cmd logs --follow
.\scripts\fishing.cmd logs --activity --follow
.\scripts\fishing.cmd plan --hours 8
.\scripts\fishing.cmd pause
.\scripts\fishing.cmd continue
.\scripts\fishing.cmd stop
.\scripts\fishing.cmd export
```

## Future bot integration

A local, versioned JSON interface is ready for another program to call:

```powershell
.\scripts\fishing.cmd api status
.\scripts\fishing.cmd api events --limit 20
.\scripts\fishing.cmd api pause --request-id example-123
```

It supports status, items, recent events, pause, resume, and stop. See [INTEGRATION.md](INTEGRATION.md) for the response contract and a subprocess example. This release does not connect to Discord or run a network listener; a remotely hosted bot will need an authenticated bridge to this Windows PC later.

## Items and bait

### Record a bait route

The recorder teaches a future restocking route; it does not replay, buy, teleport,
reset, or resume the farmer. It records only physical inputs while your selected
Roblox Player window is foreground, game video, and native-resolution PNG
checkpoints. Raw mouse device deltas are included for camera turns and shift lock,
alongside normalized cursor positions for menus. Recordings stay in the configured
local data folder and are excluded from Git.

1. Use **Pause** in Autofish and wait for the controller to stop. F8 alone leaves
   the supervisor alive, so use the app/CLI Pause before recording. Existing run
   counters, spawn, configuration and manual stop flags are retained.
2. Open **Settings → Record bait route**, double-click `scripts\Record-Bait-Route.cmd`,
   or run `autofish route record`. Opening the recorder does not record anything.
3. At your fishing spot, bring the intended Roblox window forward and press
   **F7** with other keys/buttons released. That window is selected for this take,
   even when multiple Player windows exist.
4. Demonstrate the shrine teleport, walk to the bait seller, and purchase.
   Press **F6** while standing still at the shrine menu, shrine arrival, important
   turns, seller, shop, and visible bait count after buying. Leave each view on
   screen briefly. Checkpoints are numbered; video supplies their context.
5. Perform your normal reset to your existing saved fishing spawn. Wait for the
   character to return and the fishing view to settle, then press **F6**, followed
   by **F10** to finish and save. The reset menu's Escape/R/Enter inputs are recorded.

**F7** also pauses/resumes; **F8** pauses. Changing apps, minimizing, moving or
resizing Roblox, or losing capture pauses recording. Return to the same game and
press F7 to resume; other app input and pixels are discarded. **F9/F12**, closing
the recorder, Fishing Pause/Stop, an input capture failure, low disk space, or the
20-minute recording limit save a partial demonstration. Pause/Stop during startup
cancels the recorder. Continue and automatic farmer startup are blocked while the
recorder is open; close it before explicitly continuing your saved run.

Use **Open recordings** or `autofish route folder` to open `bait-routes/` in the
data folder. Each unique take contains `route.json`, `video.mp4`, `events.jsonl`,
`frames.jsonl`, and `checkpoints/*.png`. Input `t` excludes pauses; `wall_t` includes
them. The frame index maps video time to actual observation time, so capture rate
variation is visible. `autofish route status` shows the recorder's liveness and
latest saved take. An unclosed/crashed take remains marked incomplete/running;
its video may need repair. Keep all files together for the later route analysis.

### Bait restock in CLI Settings

Open `autofish`, choose **Settings → Bait restock**, then use **Run bait restock**,
**Check bait route**, **Stop bait restock** or **BaitBot status**. **Fish Head reserve**
defaults to **2,500** and **Refill buffer** to **500**; edit either with Enter.
The existing **Buy bait** shop controls remain available in their own group.

The restock entry launches the separate route bot with this autofish account,
settings and controller data. That process owns reset, Hidden Mist shrine travel,
scenery navigation, Nori purchases, inventory verification and reset return.
It refuses an incomplete route before game input and another active controller
prevents it starting. The current route still requires drop, seller endpoint and
return-camera calibration. This Settings entry does not enable automatic refills
or certify a complete live trip. `Check bait route` is read-only.

The same controls are available without the dashboard:

```powershell
autofish baitbot check
autofish baitbot run                 # Uses the saved reserve and buffer
autofish baitbot run --reserve 2500 --buffer 500
autofish baitbot status
autofish baitbot stop
```

`baitbot.local.json` connects this installation to the standalone bot's Python,
script, dependency folder and route folder; it stays local and outside Git.
Bot progress is saved beside that route and command output in the normal data
folder's `baitbot-stdout.log` and `baitbot-stderr.log`. Reopen only the CLI view
after a Settings update; the farmer and its manual holds can keep their state.

The item journal records confirmed quantity/NEW reward banners, original OCR text, quantity, and time. A round without a reward is normal. Unread or partial names are retained instead of silently discarded. OCR can misread text; the original observation remains in the log.

**Identify unknown drops** is enabled by default in Settings. On the first use, the bot attempts a baseline inventory scan. After that, inventory opens only for unresolved catches, between fishing rounds, with **at least ten minutes between attempts**. There are no timer-only scans, and empty rounds without a Collect prompt do not request a scan or create an item entry. Each attempt has a **20-second scanning budget**, followed by closing the menu; a native OCR call already in progress may finish first. Unreadable scans back off for 20, 40, then at most 60 minutes. Fishing continues during the wait. Cached thumbnails make later scans faster and supply artwork to the window.

The comparison subtracts known catches and corrects an unreadable journal entry only when one unexplained increase matches its quantity. A visible Collect prompt with a missed banner can also be recovered this way. Several unknown catches during the wait are kept as originally observed rather than assigning a combined inventory increase to the wrong catch; that scan establishes a fresh baseline. CSV exports include the evidence source.

Reconnects reuse a recent, complete checkpoint for the same account and supervisor without opening inventory again. An interrupted round, a new supervisor, an account change, or a stale checkpoint invalidates its item comparison but retains the scan cooldown. Fishing resumes immediately, and the next eligible unresolved catch can establish a fresh baseline. This prevents unlogged loot from an interrupted round being attributed to a later catch. Turning identification off in Settings disables these checks entirely.

Leave the in-game inventory search empty; the scanner does not send typing or movement shortcuts to clear it. The scanner currently requires the complete inventory to fit the visible 10-column grid (at most 100 occupied slots). Unreadable counts, ambiguous changes, or incomplete scans preserve the unknown label and log the reason. It closes the menu before fishing resumes. It cannot reliably repair older unknown entries without a before-catch baseline. Inventory use or trade changes during a comparison can also prevent identification.

Once a count above 100 proves automatic comparison unsupported, the same farmer/account/place run retains that capacity limit across worker reloads and stops reopening the inventory between catches. Pending unknown evidence remains bounded and retains its original labels; no quantity or identity is invented. A successful explicit comparison clears the block. A different farmer run or account does not reuse it.

Set **Bait left** in terminal Setup after buying/equipping bait. This updates the estimate without resetting hooks or items. Estimated remaining bait is starting stock minus hooks, bounded at zero. Estimated bait per hour is hooks divided by active fishing time; the planner rounds the projected total up. One bait is counted per hook/minigame, including empty rounds. Fishing continues when the estimate reaches zero. These are consumption estimates, not inventory readings.

## Recovery and focus

Pickup recognition covers a wider area and requires repeated Collect evidence before holding T. A quantity/NEW label must be next to an item name to count as a reward. Empty rounds continue without blind T holds. Wall Climb, vendor prompts, and conflicting prompts release T and request recovery.

Known pickup, missed-cast, tracking, window and landmark faults first get one eligible local repair per two minutes. Persistent faults escalate to the menu rejoin, then client relaunch if recovery fails. A lost-focus pause waits for Roblox. Local repairs preserve the run and do not count as a server rejoin. Unknown failures retain a diagnostic report and use the existing rejoin path.

### Saved fishing reference

This is optional and separate from resolution scaling. At a working fishing spot, pause the farmer, finish any open minigame, then use **Settings → Save fishing view** or **CLI Setup → Save fishing reference**. Setup brings Roblox forward and makes small camera probes. Enable **Correct small position drift** / **Position correction** to include short movement probes. Stop/F9/F12/Escape cancels setup. Setup does not resume the farmer.

```powershell
.\scripts\fishing.cmd reference save --position
.\scripts\fishing.cmd reference status
.\scripts\fishing.cmd reference disable
```

The default reference uses two crate surfaces, with the building across the water as optional extra evidence. Both crate surfaces must match; distant scenery can be excluded when fog or shadows obscure it. For a different arrangement, `reference save --boxes '[[x,y,w,h],...]'` accepts at least two boxes in a **1280 × 720** reference image: put two separate textured surfaces near the character first, then optional distant static scenery. Avoid the avatar, HUD, water, moving wheels and foliage. Reference images and calibration belong to the configured account and place and stay in local data. Without a matching profile, normal recovery remains available.

After recovery, a readable compass restores the saved heading using repeated observations and camera-only steps of at most 60 mouse pixels. This coarse pass is limited to 35 seconds and 1,100 total pixels; it never moves the character. The assistant then checks the crate reference and corrects the camera before position. Position corrections require the separate movement calibration. Each fine step is checked against the scene, with a separate 25-second budget, at most 160 camera pixels and 0.12 seconds of movement input per attempt. It tolerates small residual error because game movement is not pixel-exact. A correction that makes the measured view worse is reversed only while landmarks remain visible. Obscured scenery, excessive drift, a bad calibration or a new stop prevents further movement. If the initial view cannot be matched, fine alignment is skipped and the normal saved-spawn farmer continues; pickup and missed-cast safeguards still apply. Losing the reference after corrective input requests recovery, and repeated correction failure stops for adjustment. This handles nearby drift; it cannot prove a 3D position or recover arbitrary falls. Recapture or disable an unsuitable reference while paused.

A lightweight drift check runs between rounds at most once every three minutes. It does not open inventory or interrupt minigame tracking. Changing camera zoom or mouse sensitivity can require saving a new reference.

### Recent pace and diagnostics

The window and CLI show recent hooks/minute and items/minute over up to 15 minutes of sampled wall time, including recovery. `status --json` also includes phase seconds for bites, minigames, collection, inventory, recovery and focus waits. Rates marked saved are stale. Existing lifetime totals and the active-time bait planner remain available.

`scripts\fishing.cmd diagnostics` shows the last eight failure reports. Each includes a reason code, decision details and up to four local context frames; the diagnostic ring uses at most 32 JPEGs. Raw event logs retain the full history. Diagnostics do not add frame capture to the minigame tracking loop.

The supervisor handles visible disconnect dialogs and a stalled fishing loop. Vendor purchase dialogs are cancelled before recovery. Recovery uses **M → Back to main menu → Play → Ouwland → held private Join**, then equips the rod. If necessary it opens `roblox://placeId=16205713724` or restarts the selected Roblox game process. Retry delays limit repeated restart attempts. Input is released on loss of focus, window changes, or stop requests.

If casts stop starting minigames after three separate rejoins within 90 minutes, Full farmer stops with an unsafe-position message instead of endlessly cycling through menus. Move the saved spawn farther from the water edge, then explicitly start or continue again. Health checks flag the pattern after two such recoveries.

For a saved spawn right on a ledge, `spawn_backstep_seconds` in `config.local.json` can move the character a small distance backward after a confirmed private-server Join. It defaults to `0` for other accounts and is capped at `0.35`; it never runs on a focus return or rod-only repair. Check that your chosen cast point still lands in water after enabling it.

Menu actions wait for repeated observations of a stable target. Each action has its own retry delay, so a completed menu transition does not inherit a previous button's wait. The private Join button is checked again after the cursor settles; holding ends when its panel changes, with a 4.5-second limit. A short quiet period after Join lets the game transition before another attempt; repeated rejected joins back off. Recovery still requires three continuous seconds of the loaded world before equipping the rod and starting fishing.

Cast and rod clicks allow a brief cursor settle before pressing, with stop and focus checks throughout. The first cast after loading or selecting the rod uses a longer settle to let Roblox update its hover target after the menu; subsequent casts retain their normal timing. The minigame tracking loop is unchanged.
When an item banner confirms collection, T releases immediately and the next cast has no fixed cooldown. It skips repeated cursor-settling movements if the pointer is still at the known cast point. A fresh full-scene scan of the exact confirmed receipt can clear the next cast without repeating the generic empty-scene dwell and OCR confirmation. Collect and other interactions take priority over the receipt. Collection checks a focused reward toast twice while T is held, then falls back to the wider prompt scan if needed. Periodic rod checks verify fresh icon and selection-ring pixels at the last known selected slot; missing or changed evidence falls back to the full hotbar search with the same confidence floors. Menus and focus pauses discard that slot. Menus, rod changes, focus pauses, pointer movement and uncertain pickups keep the longer checks. The receipt is discarded after a pause, inventory menu, new minigame or cast; it cannot authorize a later cycle. The recast_pressed event records confirmation to mouse-down latency separately from completion of the cast press.

Confirmed recasts finish eligible inventory/reference work before the fresh scene check. Known unsupported inventory comparisons are deferred without opening the menu. The full-scene OCR also checks the original disconnect region with its existing confidence and orientation checks; eligible inventory menus still receive the separate GUI check before input. A fast marker check after OCR gives a newly appeared minigame priority over casting. The guarded cast press is 0.16 seconds.

The collection frame is captured immediately. Its fault-evidence JPEG encoding and two JPEG file writes run on one bounded background writer with one owned frame, so image processing does not delay recasting. Later screenshots, fault reports and shutdown wait for it so evidence and archive/latest ordering are preserved. Input, reward logs, counters and inventory state stay synchronous. Controlled replay latency and saved-frame processing measurements are not live game timing guarantees.

After a confirmed receipt fades, a fresh full-scene scan with repeated stable empty evidence can also clear the recast without the generic 0.35-second dwell. A single empty observation, ambiguous evidence, other interactions and receipts discarded by a pause still require the existing checks.

Stable Collect plus a confident nearby T starts immediately. Occluded T uses repeated label evidence with a bounded 0.12–0.3 second settling check. A changed T position or newly visible T can trigger one early retry after two settled observations plus 0.12 seconds; item-name/title OCR changes do not reset a valid hold. Occluded-key evidence keeps a 0.25-second movement grace. The maximum first hold is 3.75 seconds, later holds 3.5 seconds, retaining a margin beyond observed successful holds. Reward checks run promptly and a confirmed reward releases T immediately. The cast press retains its original 160 ms duration, with focus/pause checks during the press and no capture/OCR extending it. Manual pause and non-fishing interaction guards remain immediate.

On the primary monitor, mouse moves use primary-screen absolute coordinates; targets on other monitors use virtual-desktop coordinates. The actual cursor position is checked before clicking. This avoids the primary-screen hit-test mismatch observed on the tested two-monitor desktop.

When a username is configured, [Roblox's public user lookup](https://create.roblox.com/docs/cloud/reference/features/users) resolves it to an ID and the [presence API](https://create.roblox.com/docs/cloud/reference/domains/presence) is polled every 45 seconds. Persistent absence **and** no fishing activity can request recovery. An API error alone does not mean a disconnect. No Roblox password, cookie, or API key is used or stored.

Rejoin and relaunch are distinct counters. Rejoins count completed returns from a Join/reconnect/launch attempt after the initial game-ready state; repeated Join holds count once, and rod-only maintenance resumes do not add rejoins. Counts are rebuilt from saved events, including older runs. Game launches count launch attempts. Known recovery paths are implemented, but a game update or an unfamiliar menu can require recalibration.

## Local files and privacy

### Optional Discord hourly report

`src/discord_hourly.py` reads the saved fishing events and posts one color-coded Discord embed per hour. It reports new confirmed item names and quantities, casts and items per minute, projected Ore per day from the confirmed Ore quantity in that window, minigame completions, empty rounds, pickup retries, and completed rejoins. It attaches the latest screenshot already saved by the bot's normal inventory scan and labels its capture time; reporting never opens Roblox or scans inventory. A clear Lost Set reward receives a Mythical highlight in that hour's report. Unreadable names are counted separately instead of being guessed.

Configure a private webhook locally. The full farmer initializes its first hourly window automatically if needed:

```powershell
autofish webhook set
autofish webhook verify
```

The CLI's **Setup** page also lets you set, verify, or remove the webhook without showing its value. While the full farmer is running, its supervisor sends each due report itself; no Codex automation or external scheduler is needed. Reporting runs in a background thread and a network failure cannot stop fishing. `discord-reporter-status.json` records whether the reporter is waiting, sent, or retrying. `--send-now` posts immediately and moves the checkpoint; the first immediate report includes the preceding hour. A successful send advances the checkpoint, so later reports cover only new activity. `--preview` renders the next embed locally without sending or advancing the checkpoint. The webhook is encrypted for the current Windows user in the selected local data directory as `discord-webhook.dpapi`; it is never written to Git or the item logs. Keep that file and `discord-hourly-state.json` together when moving a run. A different Windows account must configure its own webhook.

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
- **Setup fails:** check Python 3.12 x64 and internet access, then run scripts\Setup.cmd again. `src/setup_check.py` reports missing imports/assets without starting the game.
- **Game layout changed:** stop the bot. The current screen coordinates and templates are in `src/fishing_assistant.py`, `src/recovery.py`, and `src/rod_detector.py`.

To remove the app, stop it first, close the app window and the terminal dashboard, delete its desktop shortcuts, and remove the extracted folder when you no longer need the saved logs. No Windows service or scheduled task is installed.

## Branches and rollback

`master` is the stable release and GitHub default. `dev` holds validated candidates; `dev-rolling` integrates feature branches. New changes start on `feature/<name>` and merge into `dev-rolling` with a merge commit. See [CONTRIBUTING.md](../CONTRIBUTING.md) for promotion and rollback commands. The pre-update release is tagged `stable-before-inventory-resolution`. Switching code versions keeps ignored run data and account settings. Always pause before switching.

## Development

Overnight reliability update: native 2560×1440 and normal widescreen window borders
are supported. Reconnect waits for a stable client rectangle. Twelve seconds of
unchanged minigame markers triggers a typed recovery with a current screenshot;
moving rounds retain a separate 120-second upper bound. Pickup checks use a small
crop first and a wide fallback. A clear adjacent T and Collect can start pickup
immediately; uncertain prompts still require repeated evidence.

The Catches page shows only the current session by default. Press **T** there to
show lifetime catches; press **T** again to return. Reopening the terminal starts
with session catches. The toggle changes only Catches; Run counters and Logs keep
their existing views. `autofish items` shows this session; `autofish items --total`
shows lifetime catches. No old records are deleted.

The Logs view shows only the current run. Press **R** on that page to
cycle through saved runs. `autofish runs` lists IDs; `autofish logs --activity -f`
follows this run and `autofish logs --activity --run ID --all` reads a whole saved
run. Ending a run saves `runs/ID/run.json`, `events.jsonl` and `events.log` in the
configured data directory. Pause/continue and worker recovery preserve the run;
a new start after Stop creates a new log run. Lifetime counters stay separate.

Hourly Discord reports use the current run and attach its interval's JSONL log.
Stopping sends a final report with that run's log (gzip for large logs). The
reporter handles empty HTTP 204 responses and rate-limit retry timing; reporting
failures never stop game input. The webhook remains encrypted locally.

An optional `src/overnight_watch.py` runs without a window, checks saved state every
three seconds and sends authorized errors to an existing Codex chat through the
desktop app's MCP tools. Its local `monitor.local.json` supplies Node/MCP paths,
chat ID and expiry; it does not contain a webhook URL. It never controls Roblox,
clears STOP/PAUSE or starts a controller. Monitor status and delivery results are
saved separately. Codex's 30-minute heartbeat is configured in the app.

Overnight is **on by default** when the setting has not been saved. Settings →
Overnight and `autofish overnight on/off` still control the persistent setting;
an explicitly saved Off stays off. Physical input yields temporarily; it does
not disable the setting. Opening the terminal does not start fishing.
Only the verified Roblox Player receives input. Focus takeover requires the
configured grace (5–300 seconds), physical inactivity, and no recent competing
injected input. The observer keeps event timestamps only; bot input is tagged
and never counted as physical activity. `autofish overnight off` disarms both
automatic restart and future idle activation. Stop disarms them too; explicit
Pause/F8 stays paused until Continue. Keyboard Stop applies to physical keys
inside Roblox, so other automated applications cannot silently stop the bot.

Auto-enable after idle also defaults to **On**, with a **10-minute** delay. It can
enable Overnight after physical inactivity with Player open and autofocus on.
`--auto-idle off` disables it; a saved Off stays off. `--idle-minutes 10` sets the
delay. This has no clock/night condition.
An intent guard performs bounded restarts for unexpected exits, with at most
three restarts in 90 minutes; manual stops, challenges and exhausted local repair
require the user. Turning the tag off prevents every automatic restart.

Farm here uses the full cast/reel/collect worker in the current server/location
and does not rejoin or restore a different saved scene at startup. Window/focus,
capture, pickup and minigame faults are repaired locally with bounded attempts.
Only positive disconnect/client-loss evidence permits rejoining. Full farmer
retains its separate spawn/rejoin startup. Fish here remains the F8-controlled
pointer mode for compatibility.

Capture sessions close and replace failed GDI contexts. Blank white/black game
frames are unavailable visual evidence, never a successful minigame or a
disconnect. Capture waits release input and retry locally; the bot does not
turn monitors on. The process requests system wakefulness without a display
power request. A stale Windows protocol association falls back to an existing
Player executable without modifying the registry or credentials.
Persistent white frames can refresh the Player's presentation surface with a pair of F11 toggles
after ten seconds of failed captures, only with Overnight enabled, Player already
foreground, physical inactivity and no manual hold. This releases all fishing
input and replaces the capture source; it never rejoins or changes monitor power.
Refreshes are limited to two in 90 minutes, at least 60 seconds apart.
An unsupported temporary Player window is maximized locally before stable-client
validation; a resize/focus fault never launches another client in Farm here.
Rod startup now verifies the selected hotbar icon before casting, corrects a
confirmed accidental slot toggle once, and bounds unreadable-rod retries locally.
Inventory filters are located by their visible labels; the search placeholder
uses a crop that includes its full text at 1440p with normal window borders.
The watcher also alerts for failed minigames and empty pickup rounds.
Empty pickup decisions now retain bounded screenshots and OCR rows, and each T
retry is logged. A confirmed 100% minigame permits up to ten seconds for a late
loot prompt before an empty decision; a visible prompt still starts pickup as
soon as its evidence is sufficient. This wait never authorizes a blind T hold.
An OCR miss during an already-verified pickup no longer aborts its held T early.
Reward confirmation, focus/manual guards and other interaction evidence still
release it immediately, with the existing four-second maximum for each attempt.
If the first held Collect target moves more than 180 reference pixels and then
settles across two fresh Collect scans, one early retry avoids waiting for the
full timeout after an ineffective airborne press. Stationary, moving, stale or
competing interactions cannot trigger this retry; the existing three-attempt cap
and input guards still apply.

The read-only **Predictions** page (5) shows unique catches by item, worker-active
time separately from elapsed time, items/hour, sample warnings and a configurable
forecast duration (H or Enter). Reopen only the terminal view to see the new tab;
the farmer can keep running. Arrow/Page keys scroll the complete table and value
summary. `autofish predictions --hours 8` prints it; `--json` exports its calculation
and `--run ID` selects a saved run. Prices for OuwFish/OuwFwesh/Coral (33 Wen) and
Clown Fish/Golden Fish (66 Wen) are user-provided. Other prices remain unknown;
historical Crustadon/Krathulon 110 Wen is never treated as a current price.
Known-price NPC estimates and confirmed sale proceeds are separate. Forecasts
require 20 catches and ten active minutes; incomplete activity records withhold
them. Active time includes casting, pickup and inventory work, excludes recorded
focus/manual pauses and recovery gaps, and never counts overlapping workers twice.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe src\health_check.py
```

The suite covers real 1080p inventory crops, input guards, duplicate prevention, inventory reconciliation and throttling, restart checkpoints, scan-budget cleanup, recovery-log counting and colors, menu and Join transitions, held-input cleanup, multi-monitor input, catch-effect deduplication, reduced motion, responsive controls and the JSON integration boundary. Additional checks cover minigame-only activation/release, spatial pickup evidence, local-repair limits, bounded diagnostic storage, landmark matching, correction limits and recent pace calculations. A prior live 1080p run confirmed four catches, including one recovered from inventory differences. The new minigame-only mode was checked with two manual casts; camera and small lateral corrections were also exercised live.

Tests use isolated temporary state and mocked controls; they do not drive Roblox. Live game validation is still needed after changing vision or input logic. Python 3.12 on Windows x64 is the tested runtime.

Game artwork in `assets/` is used as visual reference and UI thumbnails. This is an independent tool, not an official Roblox or game project.
