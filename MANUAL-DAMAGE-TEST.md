# Supervised damage-mode test

The controller remains stopped after the offline update. Use this only while watching the game; the new rotation and title OCR have not been verified in Roblox. Only Shock Wave has previously been tested.

1. In PowerShell, open the feature checkout and read the installed interpreter from the deployed folder. This tests feature source without replacing the stable Fishing folder:

   ```powershell
   Set-Location 'C:\Users\xsami\Documents\Codex\2026-09-21\ch\work\fishing-damage-farmer-src'
   $fishingPython = (Get-Content 'C:\Users\xsami\Documents\Codex\2026-09-21\ch\outputs\Fishing\runtime.local.json' -Raw | ConvertFrom-Json).python
   $env:FISHING_DATA_DIR = 'C:\Users\xsami\Documents\Codex\2026-09-21\ch\work\fishing'
   & $fishingPython .\fishing_cli.py damage --show-config
   ```

   Check the four physical keys, move names, waits, Annihilator title and 5,000,000 target. To change one, run `& $fishingPython .\fishing_cli.py damage --key followup=Q --timing followup_seconds=1.5 --configure-only`. This saves settings without starting.
2. In Roblox, stand at the intended statue with Gauntlet in slot 1. Open **Titles → Combat → Annihilator** and confirm the detail shows a readable `current / 5,000,000` damage figure. Close the menu. Keep Roblox foreground and the pointer inside it.
3. Explicitly start with `& $fishingPython .\fishing_cli.py damage`, then watch the calibration. It measures one, four, and five M1 clicks in separate trials, Shock Wave, the follow-up, then the X+B pair only after the B icon appears ready. If title reading or damage sampling is uncertain, it pauses. Press F8 to pause/resume and F9 or F12 in Roblox to stop.
4. Run `& $fishingPython .\fishing_cli.py status` from a separate console. Compare `title_progress`, first/fifth M1, each move's damage, and ETA against the visible Annihilator title. Check that X is tapped briefly only immediately before held B, that B is skipped when its icon is on cooldown, and that V is never used in the default rotation. Observe at least one periodic title recheck (three minutes by default).
5. Stop with `& $fishingPython .\fishing_cli.py stop`. Keep the resulting local counters, inventory data and wiki. If any key, hold length, title OCR, or reset behavior differs from the game, keep the controller stopped and report the exact status/error and screenshot for adjustment before an unattended run.

The source rollback point is `backup/statue-damage-before-universal`; the stable deployed Fishing checkout and its local run data have not been changed by this feature source update. No title completion switches into fishing mode.
