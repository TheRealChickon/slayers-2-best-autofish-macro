# Fishing

A Windows assistant for Project Slayers 2 fishing and stationary statue damage practice. It includes a game-inspired inventory window, a keyboard terminal app, item history, live events, bait estimates, and fishing reconnect recovery.

## Launch it

**First time:** extract the repository, install Python 3.12 x64, and double-click **Setup.cmd**. Then open **Fishing** on the desktop, set your Roblox username and rod slot in Settings, prepare the game as described below, and click **Continue**.

Setup installs the **`autofish`** command for your Windows account. Open a new terminal anywhere and run:

```powershell
autofish start
```

Choose the game, then **Minigame only**, **Fish here**, **Full farmer**, or **Statue damage**, with arrows and Enter. The dashboard opens after starting. Only Project Slayers 2 / Ouwland is supported currently; future supported games can appear in the same picker.

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
autofish continue --mode full --until 22:00  # Stop at 22:00 local time today
autofish damage        # Measured statue damage with configured rotation
autofish stop
autofish logs --activity --follow
autofish wiki             # Open your local item wiki, if captured
autofish wiki --site      # Open your configured private ChatGPT Site
autofish build            # Best known owned M1 gear and measured mastery anchor
autofish build --save-mastery 200
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
- **Camera** in Setup can keep your current zoom (default) or zoom into first person automatically when Full farmer starts. First person may slowly pitch toward a nearby railing; a missed cast then triggers a rejoin to restore the view. Keep the third-person view for a spot where first person does not consistently reach water. **Heading** is an optional compass direction for a saved spawn, restored after a rejoin when no fishing reference is saved. Set it while facing a working cast. A saved fishing reference takes precedence over the heading.
- **Fishing titles** defaults to keeping your loadout. **Auto best** checks the visible Fishing titles once when Full farmer starts, reads completed requirements, and equips the three strongest known fishing titles. It leaves an unreadable or unfamiliar loadout alone. This game's observed order is Legendary Fisherman, Salvager, Leviathan Hunter, Deep Water Angler, then Angler; luck takes priority for rare drops. It does not scan titles every round.
- Bait is optional. Equip it in-game if desired. Full farmer reads the equipped bait once at startup and estimates how many hooks remain. The CLI warns on a nighttime start when the observed stock is under about 30 minutes at the recent pace. Fishing continues after bait runs out. There is no purchasing automation.

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

**F8 pauses/resumes all four modes while Roblox is foreground.** Full farmer keeps the same worker and counters, releases held input, and rereads the current minigame or pickup on resume. Holding F8 counts once. Switching apps or moving the pointer outside Roblox pauses Full farmer automatically; returning resumes unless F8 was used to pause manually. Neither kind of pause triggers a rejoin. The dashboard shows `Paused — F8 to resume`; an explicit Continue command also releases Full farmer's F8 pause. Health checks and presence recovery leave manual pauses alone.

If you move the installation folder, run `Setup.cmd` again to refresh the shortcut paths.

## Fishing modes

| Mode | You control | Assistant handles |
| --- | --- | --- |
| **Full farmer** (`full`) | Saved spawn and initial setup | Rod, casts, minigame, collection, inventory checks, local repairs and reconnects |
| **Minigame only** (`assist`) | Spot, rod, casts and pickups | Minigame mouse hold/release |
| **Fish here** (`spot`) | Spot, camera, mouse and rod; F8 starts | Click, reel, collect, repeat |
| **Statue damage** (`damage`) | Saved spawn inside statue and gauntlet in hotbar slot 1 | Five M1s, configured moves, title-progress checks and bounded respawn attempts |

### Statue damage

This mode is for the stationary statue setup. It has passed offline tests but needs a fresh live check before unattended use. Start it only after stopping another mode:

```powershell
autofish damage
```

The default rotation is five M1 clicks, then Shock Wave (`C`) and follow-up (`Z`) only when their icons are ready. When `B` is visibly ready and its configured cooldown has elapsed, the worker taps `X` for 0.025 seconds, releases it, waits 0.5 seconds for the skill to transform, then holds `B` for 2 seconds. It skips cooling skills and repeats the five-click string. `X` is never used alone; `V`, `N`, `K`, and `L` are unused by this rotation.

Damage status and the terminal dashboard show DPH, remaining damage, sample age, and estimated local finish time. DPH uses elapsed time between verified title readings over roughly the last ten minutes, including animation and menu time. A new worker needs two readings before showing a rate. Stale readings and paused runs suppress the finish estimate. `--timing m1_interval=0.30` requests faster discrete clicks while preserving the five-hit check; reduce timing only if registered hits and measured damage remain healthy.

Use `autofish damage --measure-skills` to briefly interrupt normal farming and measure isolated damage for a complete five-M1 string and each enabled skill. The worker waits for prior damage to settle, checks readiness, uses one attack, and compares stable title totals before and after. X and B are measured together because X prepares the ultimate. The CLI and dashboard show these saved per-use samples and their times; they are not live attribution or guaranteed damage for every cast. Remeasure after changing equipment, buffs, targets, or bindings. Sampling never resets the character, rejects changing baselines or zero-damage casts, and resumes normal farming after a successful measurement. DPH recollects normal-farming samples afterward, excluding calibration time. Stop, F8, and focus checks remain active.

```powershell
autofish damage --show-config
autofish damage --key shock_wave=Q --key followup=E --key ultimate_prep=R --key ultimate=T --timing post_m1_wait=0.8 --timing ultimate_hold_seconds=2.5 --title Annihilator --target 10000000 --configure-only
autofish damage
```

Use `--moves shock_wave,followup,ultimate` to choose moves (`--moves none` runs M1 only); X and B are always one coupled ultimate move. Use `--name shock_wave=NAME`, `--name followup=NAME`, and `--name ultimate=NAME` to change labels. Other timing fields shown by `--show-config` can be set with `--timing FIELD=SECONDS`. `--configure-only` saves settings without starting input. The title category defaults to Combat and can be changed with `--category`. The exact title detail must display either a readable `current / target` pair or a matching total-damage requirement and remaining `left` count; an unreadable or changed detail pauses attacks for inspection.

At startup, the worker reads the configured title without separate attack trials. It reopens the title every three minutes by default to update verified damage gain, pace and remaining time. Annihilator currently requires 10,000,000 total damage. Damage estimates use the visible title counter, not assumed damage per click.

The worker waits for Roblox to be foreground with your pointer inside it. It checks the action bar before touching slot 1 and watches combo growth. A five-hit combo gain is healthy and never triggers a reset. If two consecutive five-M1 strings have stable but insufficient combo reads, it checks the in-game title; any title increase cancels the reset. Only a still-unchanged title allows a bounded Respawn attempt after verifying Roblox's confirmation dialog. Unreadable combo or title evidence withholds reset and, if needed, pauses for inspection. A menu, missing hotbar, lost focus, F8 pause, Stop, or an uncertain reset blocks attacks. F9/F12 stop while Roblox is foreground. It does not rejoin servers, move your character, or switch to fishing after the title completes.

F8 and CLI Pause/Continue keep the damage counters. CLI Stop ends that sample; the next start begins a fresh sample. The worker does not take over Roblox focus when another app is in front.

`autofish status` and the terminal Run page show combo, M1 counts, measured first/fifth hits, title progress, resets and an ETA derived from verified title progress. Each five-click health result is recorded in the damage event log. A five-hit gain clears suspicion; an interrupted string, counter restart, or unreadable result cannot confirm a stall. Two deficient strings, or two entirely absent combo readings, trigger a title check, and recovery requires that title progress also failed to increase.

### Sanemi boss trials

Boss mode is experimental. It has its own worker, health ledger, screenshots and
event log; opening the CLI or selecting **Sanemi trial** starts observation only.
It never starts the statue controller. Use an already verified `/set` beside
Sanemi (displayed as Saneri in game), with gauntlets in slot 1.

```powershell
autofish boss status
autofish boss observe --seconds 30
autofish boss configure --spawn-verified --strategy b_m1_c_reset --max-cycles 10
autofish boss trial --seconds 120
autofish boss farm --seconds 600
autofish boss loot --seconds 60
autofish stop
```

`b_m1_c_reset` aims normal B when ready, watches for the combat HUD after its
cutscene, follows with four M1s and ready C, then deliberately resets to the
saved spawn. `m1_reset` and `m1_c_reset` isolate the shorter alternatives;
`ultimate_reset` tests the separate 25 ms X tap, 500 ms wait and held B attack.
`k_m1_reset` is an isolated double-K timing trial followed by four M1s.
`block_k_m1_c_reset` checks for the visible shield after the first M1; only that
shield can trigger ready L, then two K taps when ready, followed by M1 and C.
These K/L alternatives remain experimental: displacement can spoil the follow-up.
V/N are never sent. Targeted Z is not enabled in the farm until its aim and
damage are validated. Readiness uses the visible cooldown border and skill art.

Recognition requires the boss header, a unique world name, and matching hair
appearance. It rechecks range and player health, limits searching and movement,
and verifies `/set` in chat before updating a displaced spawn. Missing vision
does not count as a kill or authorize a blind reset. The visible respawn timer
controls waiting. Confirmed zero HP or a consistent countdown records defeat.
During the countdown it opens uniquely recognized nearby chests and claims
named item prompts. Loot search is bounded and returns the camera afterward;
only visible item-and-quantity reward toasts are added to the loot totals.
Ground pickup circles and compact blue-white ore glow guide short, repeatedly
observed approaches. They never authorize a pickup by themselves: a named item,
Claim/Open action and nearby T prompt must agree twice. Small reward popups get
a focused OCR pass, including Coin Pouch quantities. Confirmed collection renews
the surrounding search; farm mode returns to the verified spawn after walking
for loot. Pink ground effects are excluded from the glow-only approach. An
unopened chest can also guide approach through its orange frame and green lid;
only a readable named Open/Claim prompt permits interaction. Armour drops use
the same prompt and reward-confirmation rules.

Respawn completion is detected from a death transition followed by three stable
full-health HUD frames. Camera return uses the observed post-combo compass,
including a contrast fallback for bright sunlight. Acquisition adjusts camera
gain from observed movement and rechecks the name, appearance and range before
attacking. Missing or ambiguous observations still stop the bounded run.

Status shows first-attack-to-confirmed-defeat time with the starting HP, measured
respawn duration, observed boss HP loss, elapsed-session DPH, per-combo/skill samples,
resets, spawn updates and confirmed loot. HP readings can include residual damage or damage from
another player; these are not statue title measurements or confirmed gold income.
Loot timing is separate: defeat to the first confirmed pouch reward. The combined
kill-and-pouch time is shown only when that reward is seen; it does not claim that
every other drop has been collected. Missing pouch evidence remains unverified.
Unattended loot collection and repeated respawn cycles require live validation.
F8/F9/F12 stop, and losing Roblox focus releases all owned input. Farm sessions
are bounded by both `--seconds` (up to 12 hours) and `--max-cycles`.

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

The **Run** tab has direct **Minigame only**, **Fish here**, **Full farmer**, and **Statue damage** choices: select with ↑/↓ and press Enter to start. Pause the current mode before switching to another. **C** continues the saved mode. The command equivalents are `fishing.cmd assist`, `fishing.cmd spot`, `fishing.cmd continue --mode full`, and `fishing.cmd damage`.

Use Ctrl+G to cancel an edit; Escape remains a global stop key in Full farmer. In Setup, **Motion** toggles animations. Use a terminal at least 65 columns × 22 rows; 100 × 32 or larger is more comfortable.

The field-terminal view has Run, Catches, Radio (live log), Rig (setup), and Damage pages. Run keeps the current state, pace, last catch, bait estimate and four mode choices together. Detailed recovery history is in Radio, where Catches can also open a filtered catch history. The live log keeps the latest 4,000 events in memory; raw logs retain the complete history on disk.

## Personal item wiki

`autofish wiki` builds and opens a local, searchable field ledger from saved inventory and archive captures. `autofish wiki --no-open` only rebuilds the files. The resulting `site/index.html` has Field (damage build and current character), Satchel (owned items), Archive (unowned reference items), and Bosses (when a reviewed `boss-analysis.json` is present beside the captures). The Field page includes the captured HUD, measured M1 build and recommended owned Stats pieces. `site/context.md` is the plain-text version to attach to an AI conversation; `site/items.json` provides the same snapshot as structured data. Open an item detail image to check its captured in-game text. If this account has a private hosted Site URL saved locally, `autofish wiki --site` opens it; rebuilding the local wiki does not automatically update that hosted snapshot.

`autofish build` shows a local damage profile beside the captured owned item cards. The profile records a measured M1 anchor, the five best known Stats-slot pieces, a separate weapon, and live swap tests. `autofish build --save-mastery N` stores your current Gauntlet mastery in the ignored run-data directory; `--mastery N` previews without saving, and `--json` exports the report for another tool. The fifth terminal page shows the same build; press **M** there to update mastery. The 0.025 base-M1-per-mastery estimate is inferred from four measured levels with unchanged gear, and predictions are suppressed if a recommended piece is missing from the captured inventory. Gear swaps or class effects need a fresh in-game measurement.

The wiki keeps live inventory stats and archive base stats separate, especially when an owned item has a `+N` refinement. Owned entries take priority, so an item also present in the archive does not appear twice in the main listings. Captures and generated pages are local account data and stay out of Git. The wiki is a snapshot, not a live inventory sync: rebuild it after changing equipment, refining items or collecting new gear. Item names and quantities come from UI OCR and may need checking against their attached screenshots.

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
When a reward is confirmed, the next cast uses a shorter cooldown and skips repeated cursor-settling movements if the pointer is still at the known cast point. Collection checks a focused reward toast twice while T is held, then falls back to the wider prompt scan if needed. Menus, rod changes, focus pauses, pointer movement and uncertain pickups keep the longer checks.

On the primary monitor, mouse moves use primary-screen absolute coordinates; targets on other monitors use virtual-desktop coordinates. The actual cursor position is checked before clicking. This avoids the primary-screen hit-test mismatch observed on the tested two-monitor desktop.

When a username is configured, [Roblox's public user lookup](https://create.roblox.com/docs/cloud/reference/features/users) resolves it to an ID and the [presence API](https://create.roblox.com/docs/cloud/reference/domains/presence) is polled every 45 seconds. Persistent absence **and** no fishing activity can request recovery. An API error alone does not mean a disconnect. No Roblox password, cookie, or API key is used or stored.

Rejoin and relaunch are distinct counters. Rejoins count completed returns from a Join/reconnect/launch attempt after the initial game-ready state; repeated Join holds count once, and rod-only maintenance resumes do not add rejoins. Counts are rebuilt from saved events, including older runs. Game launches count launch attempts. Known recovery paths are implemented, but a game update or an unfamiliar menu can require recalibration.

## Local files and privacy

### Optional Discord hourly report

`discord_hourly.py` reads the saved fishing events and posts one color-coded Discord embed per hour. It reports new confirmed item names and quantities, casts and items per minute, projected Ore per day from the confirmed Ore quantity in that window, minigame completions, empty rounds, pickup retries, and completed rejoins. It attaches the latest screenshot already saved by the bot's normal inventory scan and labels its capture time; reporting never opens Roblox or scans inventory. A clear Lost Set reward receives a Mythical highlight in that hour's report. Unreadable names are counted separately instead of being guessed.

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
