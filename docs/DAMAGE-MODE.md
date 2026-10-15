# Damage-mode live checks

Run `autofish damage` with Roblox foreground, the saved statue spawn set, and Gauntlet in slot 1. `autofish tui` opens the dashboard; `autofish status` prints a snapshot.

The configured rotation is five M1s, ready C, ready Z, then a 25 ms X tap and a 2 s B hold only when B is ready. V, N, K and L are unused. Cooling skill borders prevent casting. The farmer waits through HUD-hidden ultimate animations.

Annihilator requires 10,000,000 total damage. The reader accepts the requirement plus the remaining `left` value in the title detail. Startup establishes a baseline; periodic title checks occur between complete strings.

Every five-click check is recorded in `events-damage-*.jsonl`. Five confirmed hits are healthy. A deficient string must repeat before a title check; reset is withheld if title damage increased or the readings are uncertain. Focus interruptions and combo-counter restarts do not count as verified stalls.

F8 pauses/resumes, and F9/F12 stop while Roblox is foreground. CLI Pause/Continue preserves counters. Leave Roblox foreground to continue input.

The September 28 live test verified title reading, M1 combo growth, C/Z casts and the X+B ultimate animation. The reset dialog is covered by unit tests; a real stall is required before the farmer attempts it.
