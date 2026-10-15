# Contributing

Thanks for helping! Bug reports, screenshots from unusual setups and small fixes are all welcome.

## Reporting a problem

Open an [issue](../../issues/new/choose) and include:

- what you expected and what happened,
- your screen resolution, Windows display scaling (100%, 125%, 150%) and whether Roblox is fullscreen or windowed,
- the last lines of `autofish logs --activity` (remove your Roblox username and anything personal first).

Never paste your Discord webhook URL, Roblox cookie or `config.local.json` into an issue.

## Making a change

1. Fork the repo and branch from `dev-rolling` (`feature/<short-name>`).
2. Set up a dev copy on Windows with Python 3.12: double-click `scripts\Setup.cmd`.
3. Run the tests before opening a pull request:

   ```powershell
   .\.venv\Scripts\python.exe -m unittest discover -s tests
   ```

4. Open the pull request against `dev-rolling`. Keep it focused on one thing and say how you tested it in the game, if it touches vision or input.

Tests use mocked input and saved screenshots; they never control Roblox. Anything that changes what the bot clicks or reads still needs a short live check.

## Branches

`feature/* → dev-rolling → dev → master`. `master` is the stable release that the download links point to. Releases are tagged `vX.Y` and come with a ready-to-install zip built by `scripts\Build-Share.ps1`.

To undo a merged feature, revert its merge commit on a new branch (`git revert -m 1 <merge-commit>`) and merge that normally. Please don't force-push shared branches.
