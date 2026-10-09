# Read-only fishing telemetry

`fishing_readonly.FishingReader` is a transport-independent adapter with three
bounded operations. It never imports the fishing input/controller modules,
captures the screen, changes focus, sends input, writes files, or starts a
listener. A status read verifies process creation identity and heartbeat age;
saved `running: true` alone is insufficient.

| Proposed MCP tool | Arguments | Result |
| --- | --- | --- |
| `fishing_status` | none | Worker, supervisor, watcher and guard identity/freshness; current run and manual flags |
| `fishing_recent_events` | `limit` 1–200, `seconds` 30–3600 | Whitelisted events within the current run and requested recent window |
| `fishing_metrics` | `seconds` 30–3600 | Sample event counts, OCR scan latency and prompt-to-hold median/p95 |

The host configures a single allowed data directory at startup. Do not expose
`data-dir`, arbitrary paths, commands, environment settings or control actions
as tool parameters. Register wrappers around one `FishingReader` instance in
the existing server, using that server's existing authentication and audience.
There are no start, continue, stop, reload, screenshot or inventory tools.

Status JSON is capped at 64 KiB per file. Event reads inspect at most four
ordinary worker logs and 128 KiB per log. Partial/truncated coverage is explicit;
these samples are not complete run totals or active-farming rates. Invalid
JSON, partial lines, unsafe session filenames and paths outside the configured
root fail closed. Responses exclude configuration, webhook URLs, account data,
raw error messages, arbitrary OCR rows and attachments. Windows reads share
delete access so the farmer can replace status files atomically.

Local operator checks:

```powershell
python -B fishing_readonly.py status --data-dir <existing-data-directory>
python -B fishing_readonly.py events --data-dir <existing-data-directory> --limit 20 --seconds 300
python -B fishing_readonly.py metrics --data-dir <existing-data-directory> --seconds 900
```

## Existing AnythingMCP hosting boundary

Local deployment records identify the existing AnythingMCP Docker/Caddy host. The finance service uses that host and its existing proxy;
it is a separate app, not a fishing data transport. No verified existing path
from this Windows farmer to the hosted Linux server was found during this
change. The installed AnythingMCP-backed tools expose finance operations only.

The adapter is tested locally. Remote MCP registration is deliberately not
activated yet: the server must first receive a sanitized snapshot through an
approved existing transport or have an already authorized read-only data mount.
For a Linux host consuming snapshots, preserve the Windows producer's observed
time, PID creation check and freshness result; do not test Windows PIDs against
the Linux host's processes. A stale snapshot must remain visibly stale.

Reuse existing hosting and authentication after that transport is verified.
This change creates no credentials, scheduled exporter, persistent remote
access, listening ports, proxy routes or security rules. Remote end-to-end
availability remains unverified.

## Candidate validation and deployment

The geometry change keeps world positions relative to the measured physical
client area, while marker/Exit crops use fractional UI anchors and a uniform
scale. It removes the aspect-ratio rejection, not the visual evidence gates.
Small unreadable clients still wait safely. Custom game UI scales or relocated
controls can require further fixtures; no coordinate mapping alone guarantees
recognition on every game layout.

Resize/move events release owned input, wait for a 150 ms stable client, replace
the mapping and invalidate cached prompt/hover/tracking state in the same
worker. Every new press also checks the client rectangle, protecting against
changes during OCR. Hardware activity yields for 45 seconds, competing injected
input observes the configured grace, and explicit Stop/Pause/F8 remain manual
holds. Own tagged input does not count as hardware activity.

Pickup search retains only a recent confirmed crop center (45 seconds), always
falls back to the wide scan and obtains new evidence before holding T. A cached
location is never cached authorization. The cached crop uses a 384-pixel
detector pass only when a new explicit strong Collect cue is present; otherwise
it falls back to the original detector. Existing bounded three-attempt retry,
moving-target settle checks and late-loot wait remain in force.

Develop and validate on `feature/*`; integrate with a merge commit into
`dev-rolling`. The running checkout, runtime files, counters and process are
not switched by tests or GitHub pushes. A live reload requires coordination with
the repair task that owns the active farmer, followed by observation of actual
catches. Cross-task messaging was previously rejected, so that coordination
must be completed through an authorized route before deployment.
