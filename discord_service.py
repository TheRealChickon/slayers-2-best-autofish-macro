"""Background Discord reporting owned by the full-fishing supervisor."""

import threading
import time

from discord_hourly import SECRET_FILE, atomic_json, send_due


class DiscordReporter:
    def __init__(self, run):
        self.run = run
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="fishing-discord-report", daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=2)

    def poll_once(self):
        now = time.time()
        if not (self.run / SECRET_FILE).is_file():
            self._status({"state": "unconfigured", "updated_at": now})
            return 60
        try:
            result = send_due(self.run, now)
        except Exception as error:
            # The network and reporting data must never stop fishing.
            self._status({"state": "retrying", "updated_at": now, "error": str(error)})
            return max(5,min(300,getattr(error,'retry_after',60)))
        self._status({"state": "sent" if result["sent"] else "waiting",
                      "updated_at": now, "next_due_at": result["next_due_at"],
                      **({"last_sent_at": result["at"]} if result["sent"] else {})})
        return max(5, min(60, result["next_due_at"] - time.time()))

    def _status(self, value):
        try:
            atomic_json(self.run / "discord-reporter-status.json", value)
        except OSError:
            pass

    def _run(self):
        while not self.stop_event.is_set():
            self.stop_event.wait(self.poll_once())
