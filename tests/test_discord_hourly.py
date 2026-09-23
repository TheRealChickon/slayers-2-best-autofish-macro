"""The digest must reflect confirmed catches without touching the game."""

import json
import os
import tempfile
import unittest
import io
from pathlib import Path
from unittest.mock import patch

import discord_hourly as report
from discord_service import DiscordReporter


class DiscordHourlyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)

    def rows(self, name, *rows):
        (self.run / name).write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def test_named_items_retries_and_rejoins(self):
        self.rows("events-one.jsonl",
                  {"at": 10, "event": "cast"},
                  {"at": 11, "event": "minigame"},
                  {"at": 15, "event": "minigame_ended", "percent": 100},
                  {"at": 16, "event": "pickup_hold", "cycle": 1, "attempt": 1, "text": "Lost Mask Collect"},
                  {"at": 17, "event": "pickup_hold", "cycle": 1, "attempt": 2, "text": "Lost Mask Collect"},
                  {"at": 18, "event": "reward_observed", "cycle": 1, "text": "Lost Mask X1", "reward_id": "a"},
                  {"at": 19, "event": "reward_observed", "cycle": 1, "text": "Lost Mask X1", "reward_id": "a"},
                  {"at": 20, "event": "reward_observed", "cycle": 2, "text": "Coral X2", "reward_id": "b"},
                  {"at": 21, "event": "inventory_resolved", "reward_id": "b", "item": "Sea Horse"},
                  {"at": 22, "event": "empty_round"})
        self.rows("recovery.jsonl",
                  {"at": 1, "event": "hold_private_join"},
                  {"at": 2, "event": "equipped_rod"},
                  {"at": 23, "event": "recovery_decision"},
                  {"at": 24, "event": "hold_private_join"},
                  {"at": 25, "event": "hold_private_join"},
                  {"at": 26, "event": "equipped_rod"},
                  {"at": 27, "event": "equipped_rod"})
        result = report.summarize(self.run, 9, 30, now=30)
        self.assertEqual(result["casts"], 1)
        self.assertEqual(result["rewards"], 2)
        self.assertEqual(result["items"], {"Lost Mask": 1, "Sea Horse": 2})
        self.assertEqual(result["pickup_retries"], 1)
        self.assertEqual(result["recovery_decisions"], 1)
        self.assertEqual(result["rejoins"], 1)
        self.assertEqual(len(result["mythical"]), 1)
        self.assertEqual(report.embed(result)["embeds"][0]["title"], "✦ Mythical catch!")

    def test_prompt_is_not_a_collected_item(self):
        self.rows("events-one.jsonl",
                  {"at": 10, "event": "pickup_hold", "cycle": 1, "attempt": 1, "text": "Lost Mask Collect"},
                  {"at": 11, "event": "empty_round"})
        result = report.summarize(self.run, 9, 20, now=20)
        self.assertEqual(result["rewards"], 0)
        self.assertEqual(result["mythical"], [])

    def test_ore_projection_counts_only_confirmed_ore_quantity(self):
        self.rows("events-one.jsonl",
                  {"at": 10, "event": "reward_observed", "cycle": 1, "text": "Ore X3", "reward_id": "ore"},
                  {"at": 20, "event": "reward_observed", "cycle": 2, "text": "Coral X2", "reward_id": "coral"},
                  {"at": 30, "event": "pickup_hold", "cycle": 3, "text": "Ore Collect"})
        result = report.summarize(self.run, 0, 3600, now=3600)
        self.assertEqual(result["ores"], 3)
        self.assertEqual(result["ores_per_day"], 72)
        pace = next(field["value"] for field in report.embed(result)["embeds"][0]["fields"]
                    if field["name"] == "PACE")
        self.assertIn("72 ores/day", pace)
        self.assertIn("3 Ore confirmed", pace)

    def test_send_waits_one_hour_and_uses_checkpoint(self):
        with patch.object(report, "data_directory", return_value=self.run), patch.object(report.time, "time", return_value=100):
            report.main(["--init"])
        with patch.object(report, "data_directory", return_value=self.run), \
             patch.object(report.time, "time", return_value=1000), \
             patch.object(report, "request_webhook") as request:
            report.main(["--send"])
            request.assert_not_called()
        with patch.object(report, "data_directory", return_value=self.run), \
             patch.object(report.time, "time", return_value=3701), \
             patch.object(report, "load_secret", return_value="redacted"), \
             patch.object(report, "request_webhook", return_value=(200, "message-one")) as request:
            report.main(["--send"])
            request.assert_called_once()
        state = report.read_json(self.run / report.STATE_FILE)
        self.assertEqual(state["last_end_at"], 3701)
        self.assertEqual(state["reports_sent"], 1)

    def test_supervisor_reporter_uses_due_checkpoint_without_game_input(self):
        (self.run / report.SECRET_FILE).write_bytes(b"encrypted")
        (self.run / report.STATE_FILE).write_text(json.dumps({"last_end_at": 100, "reports_sent": 1}))
        reporter = DiscordReporter(self.run)
        with patch("discord_service.time.time", return_value=500), \
             patch("discord_service.send_due", return_value={"sent": False, "next_due_at": 3700}) as send:
            self.assertEqual(reporter.poll_once(), 60)
            send.assert_called_once_with(self.run, 500)
        with patch("discord_service.time.time", return_value=3701), \
             patch("discord_service.send_due", return_value={"sent": True, "at": 3701,
                                                               "next_due_at": 7301}) as send:
            self.assertEqual(reporter.poll_once(), 60)
            send.assert_called_once_with(self.run, 3701)
        self.assertEqual(report.read_json(self.run / "discord-reporter-status.json")["state"], "sent")

    def test_supervisor_reporter_retries_network_failure_without_stopping(self):
        (self.run / report.SECRET_FILE).write_bytes(b"encrypted")
        reporter = DiscordReporter(self.run)
        with patch("discord_service.send_due", side_effect=RuntimeError("Discord connection failed")):
            self.assertEqual(reporter.poll_once(), 300)
        self.assertEqual(report.read_json(self.run / "discord-reporter-status.json")["state"], "retrying")

    def test_only_discord_webhook_hosts_accepted(self):
        self.assertTrue(report.valid_webhook("https://discord.com/api/webhooks/123/secret"))
        self.assertFalse(report.valid_webhook("https://discord.com.evil.test/api/webhooks/123/secret"))
        self.assertFalse(report.valid_webhook("http://discord.com/api/webhooks/123/secret"))

    def test_cached_inventory_attaches_without_opening_game(self):
        (self.run / "inventory-latest.jpg").write_bytes(b"\xff\xd8test-image\xff\xd9")
        image, captured = report.inventory_snapshot(self.run)
        summary = report.summarize(self.run, 10, 20, now=20)
        payload = report.embed(summary, captured)
        self.assertEqual(payload["embeds"][0]["image"]["url"], "attachment://inventory.jpg")

        class Response(io.BytesIO):
            status = 200
            def __enter__(self): return self
            def __exit__(self, *_): self.close()

        with patch.object(report.urllib.request, "urlopen", return_value=Response(b'{"id":"posted"}')) as send:
            status, message_id = report.request_webhook("https://discord.com/api/webhooks/123/redacted", payload, image)
        self.assertEqual((status, message_id), (200, "posted"))
        request = send.call_args.args[0]
        self.assertIn("multipart/form-data", request.headers["Content-type"])
        self.assertIn(b'name="files[0]"', request.data)
        self.assertIn(image, request.data)

    def test_immediate_first_report_covers_prior_hour_and_moves_checkpoint(self):
        (self.run / report.STATE_FILE).write_text(json.dumps({"last_end_at": 1000, "reports_sent": 0}))
        with patch.object(report, "data_directory", return_value=self.run), \
             patch.object(report.time, "time", return_value=1100), \
             patch.object(report, "load_secret", return_value="redacted"), \
             patch.object(report, "request_webhook", return_value=(200, "message-now")) as send:
            report.main(["--send-now"])
            self.assertIn("<t:-2500:t>", send.call_args.args[1]["embeds"][0]["description"])
        self.assertEqual(report.read_json(self.run / report.STATE_FILE)["last_end_at"], 1100)

    @unittest.skipUnless(os.name == "nt", "DPAPI is Windows-only")
    def test_secret_is_encrypted_for_local_user(self):
        hook = "https://discord.com/api/webhooks/123/secret"
        report.configure_secret(self.run, hook)
        self.assertNotIn(hook.encode(), (self.run / report.SECRET_FILE).read_bytes())
        self.assertEqual(report.load_secret(self.run), hook)


if __name__ == "__main__":
    unittest.main()
