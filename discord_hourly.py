"""Read-only hourly fishing digest for a private Discord webhook.

The webhook is stored with Windows DPAPI in the local run directory. This
module never imports the game controller or sends input to Roblox.
"""

import argparse
import collections
import datetime as dt
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import psutil
from pathlib import Path

from app_config import data_directory
from item_names import item_name
from reward_evidence import reward_quantity


WINDOW_SECONDS = 3600
LOST_SET = {"lost mask", "lost lantern", "lost cape", "lost outfit", "lost shotgun"}
STATE_FILE = "discord-hourly-state.json"
SECRET_FILE = "discord-webhook.dpapi"
REWARD_LABEL = re.compile(r"\bx\s*\d+\b|\bnew\b", re.I)
QUANTITY = re.compile(r"\bx\s*(\d+)\b", re.I)


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=path.stem + "-", suffix=".tmp", delete=False) as stream:
        json.dump(value, stream, indent=2)
        temporary = Path(stream.name)
    try:
        # Windows readers (including PowerShell's Get-Content) can briefly
        # deny replacement. A status view must never terminate reporting or
        # the watchdog that writes this file.
        for attempt in range(40):
            try:os.replace(temporary,path);break
            except PermissionError:
                if attempt==39:raise
                time.sleep(.025 if attempt<10 else .05)
    finally:
        temporary.unlink(missing_ok=True)


def valid_webhook(value):
    parsed = urllib.parse.urlparse(value.strip())
    return (parsed.scheme == "https" and parsed.hostname in ("discord.com", "discordapp.com")
            and bool(re.fullmatch(r"/api/webhooks/\d+/[^/]+", parsed.path)))


def configure_secret(run, value):
    if not valid_webhook(value):
        raise ValueError("Expected a Discord webhook URL")
    if os.name != "nt":
        raise RuntimeError("Local webhook storage requires Windows DPAPI")
    import win32crypt
    encrypted = win32crypt.CryptProtectData(value.strip().encode("utf-8"),
                                            "Fishing Discord webhook", None, None, None, 0)
    run.mkdir(parents=True, exist_ok=True)
    (run / SECRET_FILE).write_bytes(encrypted)


def load_secret(run):
    if os.name != "nt":
        raise RuntimeError("Local webhook storage requires Windows DPAPI")
    import win32crypt
    value = win32crypt.CryptUnprotectData((run / SECRET_FILE).read_bytes(),
                                          None, None, None, 0)[1].decode("utf-8")
    if not valid_webhook(value):
        raise ValueError("Stored Discord webhook is invalid")
    return value


def event_rows(run, start, end):
    """Include complete JSONL lines only; ignore an active writer's partial tail."""
    for path in sorted(run.glob("events-*.jsonl")):
        if path.stat().st_mtime < start - 86400:
            continue
        try:
            with path.open("r", encoding="utf-8", errors="replace") as stream:
                for line in stream:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if start <= row.get("at", 0) < end:
                        yield path.name, row
        except OSError:
            continue


def reward_name(raw, prompt=""):
    name = item_name(raw, prompt)
    if name.endswith("(partial)"):
        for lost in LOST_SET:
            if re.search(r"\b" + re.escape(lost) + r"\b", raw, re.I):
                return lost.title()
    return name


def recovery_rows(run, end):
    path = run / "recovery.jsonl"
    try:
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("at", 0) < end:
                    yield row
    except OSError:
        return


def summarize(run, start, end, now=None):
    now = time.time() if now is None else now
    from run_log import current
    log_run=current(run)
    start=max(start,log_run.get('started',start))
    events = list(event_rows(run, start, end))
    kinds = collections.Counter(row.get("event") for _, row in events)
    prompts = {};seen_banners=set()
    rewards = {}
    corrections = {}
    pickup_retries = 0
    failed = 0
    for path, row in events:
        kind = row.get("event")
        cycle = (path, row.get("cycle"))
        if kind == "pickup_hold":
            prompts[cycle] = row.get("text", "")
            pickup_retries += row.get("attempt", 1) > 1
        elif kind == "minigame_ended" and row.get("percent") not in (None, 100):
            failed += 1
        elif kind == "reward_observed":
            raw = row.get("text", "")
            banner=(path,row.get('cycle'),re.sub(r'[^a-z0-9]','',raw.casefold()))
            if row.get('cycle') is not None and banner in seen_banners:continue
            seen_banners.add(banner)
            quantity=reward_quantity(raw)
            if quantity is not None:
                key = row.get("reward_id") or f"{path}:{row.get('cycle')}:{row['at']}"
                rewards[key] = {"at": row["at"], "name": reward_name(raw, prompts.get(cycle, "")),
                                "quantity": quantity, "raw": raw}
        elif kind == "inventory_resolved" and row.get("reward_id"):
            corrections[row["reward_id"]] = row.get("item", "")
        elif kind == "inventory_recovered" and row.get("reward_id"):
            rewards.setdefault(row["reward_id"], {"at": row["at"], "name": row.get("item", "Unidentified item"),
                                                       "quantity": row.get("quantity", 1), "raw": row.get("raw", "")})
    for key, corrected in corrections.items():
        if key in rewards and corrected:
            rewards[key]["name"] = corrected

    items = collections.Counter()
    unknown = 0
    mythical = []
    for reward in rewards.values():
        name = reward["name"]
        if name == "Unidentified item" or name.endswith("(partial)"):
            unknown += 1
        else:
            items[name] += reward["quantity"]
        if name.lower() in LOST_SET or re.search(r"\bmythic(?:al)?\b", reward["raw"], re.I):
            mythical.append(reward)

    decisions = 0
    rejoins = 0
    launches = 0
    first_ready = False
    join_pending = False
    for row in recovery_rows(run, end):
        kind = row.get("event")
        at = row.get("at", 0)
        if kind in ("hold_private_join", "launching_game", "disconnect_observed"):
            join_pending = True
        elif kind == "equipped_rod":
            if first_ready and join_pending and at >= start:
                rejoins += 1
            first_ready = True
            join_pending = False
        elif kind == "supervisor_stopped":
            join_pending = False
        if at >= start:
            decisions += kind == "recovery_decision"
            launches += kind == "launching_game"

    supervisor = read_json(run / "supervisor.json")
    worker = read_json(run / "status.json")
    totals = read_json(run / "totals.json")
    if log_run:
        all_events=list(event_rows(run,log_run['started'],end))
        totals={'casts':sum(r.get('event')=='cast' for _,r in all_events),
                'rewards':len({(p,r['cycle']) if r.get('cycle') is not None else r.get('reward_id') or (p,r.get('at'))
                               for p,r in all_events if r.get('event')=='inventory_recovered'
                               or r.get('event')=='reward_observed' and reward_quantity(r.get('text','')) is not None}),
                'failed':sum(r.get('event')=='minigame_ended' and r.get('percent') not in (None,100) for _,r in all_events)}
    stopped = (run / "STOP").exists()
    paused = (run / "PAUSE").exists() or (run / "F8_PAUSE").exists() or bool(supervisor.get("manual_paused"))
    focus_paused = supervisor.get("stage") == "paused_focus" or worker.get("stage") == "paused_focus"
    active = (bool(supervisor.get("running")) and now - supervisor.get("updated", 0) < 45
              and psutil.pid_exists(supervisor.get('pid',-1)))
    elapsed = max(1, end - start)
    return {
        "start": start, "end": end, "seconds": elapsed, "casts": kinds["cast"],
        "minigames": kinds["minigame"],
        "completed": sum(row.get("event") == "minigame_ended" and row.get("percent") == 100 for _, row in events),
        "failed": failed, "empty": kinds["empty_round"], "rewards": len(rewards),
        "items": items, "unknown": unknown, "mythical": mythical,
        "ores": items.get("Ore", 0), "ores_per_day": items.get("Ore", 0) * 86400 / elapsed,
        "pickup_holds": kinds["pickup_hold"], "pickup_retries": pickup_retries,
        "unconfirmed_pickups": kinds["pickup_attempted"],
        "recovery_decisions": decisions, "rejoins": rejoins, "launches": launches,
        "worker_starts": kinds["started"], "totals": totals,
        "running": active, "stopped": stopped, "paused": paused, "focus_paused": focus_paused,
        "supervisor_stage": supervisor.get("stage", "unknown"),
        "worker_stage": worker.get("stage", "unknown"),
        "last_reward": worker.get("last_reward", ""),
        "run_id":log_run.get('id'),
        "health_state":'WAITING FOR GAME FRAMES' if active and supervisor.get('stage')=='capture_wait' else
                       'RECOVERING' if active and supervisor.get('stage') in ('recovering','restarting','retry_wait') else
                       'FISHING' if active and supervisor.get('stage')=='fishing' else 'WAITING' if active else 'OFFLINE',
    }


def compact_items(items, limit=950):
    if not items:
        return "No named items confirmed in this window."
    lines = []
    used = 0
    for name, quantity in items.most_common():
        line = f"**{name}** ×{quantity}"
        if used + len(line) + 1 > limit:
            lines.append(f"…and {len(items) - len(lines)} more types")
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)


def inventory_snapshot(run):
    """Reuse the scanner's saved frame; never open the game inventory here."""
    path = run / "inventory-latest.jpg"
    try:
        before = path.stat()
        data = path.read_bytes()
        after = path.stat()
    except OSError:
        return None
    if (before.st_mtime_ns != after.st_mtime_ns or before.st_size != after.st_size
            or len(data) > 8_000_000 or not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9")):
        return None
    return data, after.st_mtime


def embed(summary, inventory_at=None):
    s = summary
    minutes = s["seconds"] / 60
    status = "STOPPED" if s["stopped"] else ("PAUSED" if s["paused"] else
              ("FOCUS PAUSE" if s["focus_paused"] else s.get('health_state',"FISHING" if s["running"] else "OFFLINE")))
    title = "✦ Mythical catch!" if s["mythical"] else "Fishing · hourly report"
    color = 0xAD74E8 if s["mythical"] else (0xE7A954 if status != "FISHING" or s["failed"] else 0x55C5AE)
    item_text = compact_items(s["items"])
    if s["unknown"]:
        item_text += f"\n{ s['unknown'] } unreadable reward name(s) kept out of item totals"
    fields = [
        {"name": "NEW ITEMS", "value": item_text, "inline": False},
        {"name": "PACE", "value": (f"**{s['casts'] / minutes:.1f}** casts/min  ·  "
                                   f"**{s['rewards'] / minutes:.1f}** collected/min\n"
                                   f"{s['casts']} casts · {s['rewards']} confirmed rewards\n"
                                   f"**{s['ores_per_day']:,.0f} ores/day** projected · {s['ores']} Ore confirmed\n"
                                   f"Wall-clock pace, including pauses"), "inline": True},
        {"name": "MINIGAMES", "value": (f"{s['minigames']} started · {s['completed']} completed\n"
                                       f"{s['failed']} failed · {s['empty']} empty rounds"), "inline": True},
        {"name": "PICKUP", "value": (f"{s['pickup_holds']} holds · {s['pickup_retries']} retries\n"
                                    f"{s['unconfirmed_pickups']} without immediate banner"), "inline": True},
        {"name": "RECOVERY", "value": (f"{s['recovery_decisions']} decisions · {s['rejoins']} completed rejoins\n"
                                      f"{s['launches']} game relaunches · {s['worker_starts']} worker starts"), "inline": True},
        {"name": "RUN TOTAL", "value": (f"{s['totals'].get('casts', 0):,} casts · "
                                       f"{s['totals'].get('rewards', 0):,} rewards · "
                                       f"{s['totals'].get('failed', 0):,} failed rounds"), "inline": False},
    ]
    if inventory_at is not None:
        freshness = "new scan" if inventory_at >= s["start"] else "saved scan"
        fields.append({"name": "INVENTORY", "value": f"{freshness} · captured <t:{int(inventory_at)}:f>", "inline": False})
    else:
        fields.append({"name": "INVENTORY", "value": "No inventory scan for this run; event logs are attached.", "inline": False})
    if s["mythical"]:
        names = collections.Counter(row["name"] for row in s["mythical"])
        fields.insert(0, {"name": "✦ MYTHICAL", "value": compact_items(names), "inline": False})
    visual = {"title": title, "color": color,
                        "description": (f"**{status}**  ·  <t:{int(s['start'])}:t> → <t:{int(s['end'])}:t>\n"
                                        f"Current phase: {s['supervisor_stage']} / {s['worker_stage']}"),
                        "fields": fields,
                        "footer": {"text": "Run "+str(s.get('run_id') or 'legacy')+" · confirmed rewards · log attached"},
                        "timestamp": dt.datetime.fromtimestamp(s["end"], dt.timezone.utc).isoformat()}
    if inventory_at is not None:
        visual["image"] = {"url": "attachment://inventory.jpg"}
    return {"username": "Autofish", "allowed_mentions": {"parse": []}, "embeds": [visual]}


class WebhookError(RuntimeError):
    def __init__(self,message,retry_after=60):
        super().__init__(message);self.retry_after=retry_after


def request_webhook(url, payload=None, attachment=None, attachments=None):
    if payload is None:
        request = urllib.request.Request(url, headers={"User-Agent": "Autofish/1.0"}, method="GET")
    else:
        separator = "&" if "?" in url else "?"
        files=list(attachments or [])
        if attachment is not None:files.insert(0,('inventory.jpg','image/jpeg',attachment))
        if not files:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            content_type = "application/json"
        else:
            boundary = "autofish-" + uuid.uuid4().hex
            payload={**payload,'attachments':[{'id':i,'filename':name} for i,(name,_,_) in enumerate(files)]}
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            data = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n"
                    "Content-Type: application/json\r\n\r\n").encode() + encoded + b"\r\n"
            for i,(name,mime,contents) in enumerate(files):
                if not re.fullmatch(r'[a-zA-Z0-9_.-]+',name):raise ValueError('Unsafe attachment filename')
                data += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"files[{i}]\"; "
                         f"filename=\"{name}\"\r\nContent-Type: {mime}\r\n\r\n").encode()
                data += contents+b'\r\n'
            data += f"--{boundary}--\r\n".encode()
            content_type = f"multipart/form-data; boundary={boundary}"
        request = urllib.request.Request(url + separator + "wait=true", data=data,
                                         headers={"Content-Type": content_type, "User-Agent": "Autofish/1.0"},
                                         method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if payload is None:
                return response.status, None
            if response.status==204:return 204,None
            return response.status, json.load(response).get("id")
    except urllib.error.HTTPError as error:
        retry_after=60
        if error.code==429:
            try:retry_after=max(1,float(json.loads(error.read()).get('retry_after',60)))
            except (ValueError,TypeError):pass
        raise WebhookError(f"Discord returned HTTP {error.code}",retry_after) from None
    except urllib.error.URLError:
        raise RuntimeError("Discord connection failed") from None


def send_due(run, now=None):
    """Send one due digest using the saved checkpoint, without touching Roblox."""
    now = time.time() if now is None else now
    state_path = run / STATE_FILE
    state = read_json(state_path)
    from run_log import current, log_attachment
    log_run=current(run)
    if log_run and state.get('run_id')!=log_run['id']:
        state={**state,'run_id':log_run['id'],'last_end_at':log_run['started']}
        atomic_json(state_path,state)
    if not state:
        state = {"created_at": now, "last_end_at": now, "reports_sent": 0}
        atomic_json(state_path, state)
    start = state["last_end_at"]
    if now - start < WINDOW_SECONDS:
        return {"sent": False, "reason": "not_due", "next_due_at": start + WINDOW_SECONDS}
    summary = summarize(run, start, now, now)
    inventory = inventory_snapshot(run)
    if inventory and log_run and inventory[1]<log_run['started']:inventory=None
    payload = embed(summary, inventory[1] if inventory else None)
    code, message_id = request_webhook(load_secret(run), payload, inventory[0] if inventory else None,
                                       attachments=[log_attachment(run,summary['start'],now)])
    if code not in (200, 204):
        raise RuntimeError(f"Unexpected Discord response: HTTP {code}")
    state.update(last_end_at=now, reports_sent=state.get("reports_sent", 0) + 1,
                 last_message_id=message_id)
    atomic_json(state_path, state)
    return {"sent": True, "at": now, "next_due_at": now + WINDOW_SECONDS,
            "rewards": summary["rewards"], "inventory_at": inventory[1] if inventory else None,
            "mythical": [r["name"] for r in summary["mythical"]], "stopped": summary["stopped"]}


def send_run_end(run):
    from run_log import current,log_attachment
    selected=current(run)
    if not selected or not (run/SECRET_FILE).exists():return
    end=selected.get('ended') or time.time()
    summary=summarize(run,selected['started'],end,end)
    payload=embed(summary)
    payload['embeds'][0]['title']='Fishing · run finished'
    payload['embeds'][0]['description']+='\n'+selected.get('reason','Run ended')
    code,message_id=request_webhook(load_secret(run),payload,attachments=[log_attachment(run,selected['started'],end)])
    atomic_json(run/'discord-final-report.json',{'sent':True,'at':time.time(),'run_id':selected['id'],'message_id':message_id,'http':code})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    for option in ("configure", "verify", "init", "preview", "send", "send-now"):
        actions.add_argument("--" + option, action="store_true")
    args = parser.parse_args(argv)
    run = data_directory()
    state_path = run / STATE_FILE
    if args.configure:
        configure_secret(run, sys.stdin.read().strip())
        print("Discord webhook encrypted for this Windows user.")
        return
    if args.verify:
        code, _ = request_webhook(load_secret(run))
        print(f"Discord webhook reachable (HTTP {code}); no message sent.")
        return
    state = read_json(state_path)
    if args.init:
        if not state:
            now = time.time()
            atomic_json(state_path, {"created_at": now, "last_end_at": now, "reports_sent": 0})
        print("Hourly report checkpoint ready.")
        return
    if not state and args.send:
        print(json.dumps(send_due(run)))
        return
    if not state:
        raise RuntimeError("Run --init before preview or send")
    now = time.time()
    start = state["last_end_at"]
    if args.send:
        print(json.dumps(send_due(run, now)))
        return
    if args.send_now and not state.get("reports_sent"):
        start = min(start, now - WINDOW_SECONDS)
    summary = summarize(run, start, now, now)
    inventory = inventory_snapshot(run)
    from run_log import current
    log_run=current(run)
    if inventory and log_run and inventory[1]<log_run['started']:inventory=None
    payload = embed(summary, inventory[1] if inventory else None)
    if args.preview:
        print(json.dumps({"summary": {**summary, "items": dict(summary["items"])}, "payload": payload},
                         indent=2, ensure_ascii=True))
        return
    from run_log import log_attachment,current
    code, message_id = request_webhook(load_secret(run), payload, inventory[0] if inventory else None,
                                       attachments=[log_attachment(run,summary['start'],now)])
    if code not in (200, 204):
        raise RuntimeError(f"Unexpected Discord response: HTTP {code}")
    state.update(last_end_at=now, reports_sent=state.get("reports_sent", 0) + 1,
                 last_message_id=message_id)
    log_run=current(run)
    if log_run:state['run_id']=log_run['id']
    atomic_json(state_path, state)
    print(json.dumps({"sent": True, "at": now, "rewards": summary["rewards"],
                      "inventory_at": inventory[1] if inventory else None,
                      "mythical": [r["name"] for r in summary["mythical"]], "stopped": summary["stopped"]}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Hourly Discord report failed: {error}", file=sys.stderr)
        raise SystemExit(1)
