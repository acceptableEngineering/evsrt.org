"""aprs-to-discord -- poll aprs.fi for APRS activity from a watch list of
callsigns and post any recent hits to a Discord channel via webhook.

Callsigns are read from `callsigns.txt` (one per line, '#' comments and
blank lines ignored), bundled alongside this file in the deploy zip.

Intended to run on a schedule (EventBridge, e.g. every 10 minutes). Each
run queries aprs.fi for the watch list and posts the callsigns heard
within the last LOOKBACK_SECONDS.

Env vars (set on the Lambda):
    discord_webhook    Discord webhook URL              (REQUIRED)
    aprs_fi_api_key    aprs.fi API key                  (REQUIRED)
    lookback_seconds   "heard within" window, seconds   (optional, default 600)

NOTE on duplicates: this is stateless -- it reports anything heard in the
lookback window, so a station that keeps beaconing will be reported on
each run while it stays active. If you'd rather only announce when a
callsign *becomes* active (and not repeat while it stays up), that needs a
small state store (DynamoDB/S3) to remember what was reported last run --
straightforward to add as a follow-up.
"""

import json
import os
import time
from pathlib import Path

import requests

APRS_API = "https://api.aprs.fi/api/get"
# aprs.fi asks for a descriptive User-Agent and caps each query at 20 targets.
USER_AGENT = "evsrt-aprs-to-discord/1.0 (+https://evsrt.org)"
APRS_MAX_TARGETS = 20


def _load_callsigns():
    """Watch list from callsigns.txt -- one per line, '#' comments ignored."""
    path = Path(__file__).parent / "callsigns.txt"
    if not path.exists():
        print("callsigns.txt not found next to lambda_function.py")
        return []
    seen, out = set(), []
    for line in path.read_text(encoding="utf-8").splitlines():
        cs = line.strip().upper()
        if not cs or cs.startswith("#"):
            continue
        if cs not in seen:
            seen.add(cs)
            out.append(cs)
    return out


def _chunks(items, n):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def _query_aprs(callsigns, api_key):
    """Return aprs.fi location entries for the watch list."""
    entries = []
    for batch in _chunks(callsigns, APRS_MAX_TARGETS):
        params = {
            "name": ",".join(batch),
            "what": "loc",
            "apikey": api_key,
            "format": "json",
        }
        resp = requests.get(
            APRS_API, params=params,
            headers={"User-Agent": USER_AGENT}, timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("result") != "ok":
            print("aprs.fi returned non-ok:", data.get("description") or data)
            continue
        entries.extend(data.get("entries", []))
    return entries


def _format_message(active, now):
    lines = ["\U0001F4E1 **APRS activity**"]
    for entry, last in sorted(active, key=lambda x: x[1], reverse=True):
        name = entry.get("name", "?")
        mins = max(0, now - last) // 60
        when = "just now" if mins == 0 else f"{mins} min ago"
        line = f"• **{name}** — heard {when}"
        lat, lng = entry.get("lat"), entry.get("lng")
        if lat and lng:
            line += f" at {lat}, {lng}  <https://aprs.fi/?call={name}>"
        comment = (entry.get("comment") or "").strip()
        if comment:
            line += f" — _{comment}_"
        lines.append(line)
    # Discord hard-caps a message at 2000 chars.
    return "\n".join(lines)[:1900]


def lambda_handler(event, context):
    discord_webhook = os.environ.get("discord_webhook")
    api_key = os.environ.get("aprs_fi_api_key")
    lookback = int(os.environ.get("lookback_seconds", "600"))

    if not api_key:
        print("aprs_fi_api_key not configured")
        return {"statusCode": 500, "body": "aprs_fi_api_key not configured"}
    if not discord_webhook:
        print("discord_webhook not configured")
        return {"statusCode": 500, "body": "discord_webhook not configured"}

    callsigns = _load_callsigns()
    if not callsigns:
        return {"statusCode": 200, "body": "no callsigns to check"}

    entries = _query_aprs(callsigns, api_key)
    now = int(time.time())
    active = []
    for entry in entries:
        try:
            last = int(entry.get("lasttime", 0))
        except (TypeError, ValueError):
            continue
        if last and now - last <= lookback:
            active.append((entry, last))

    if not active:
        print(f"no activity in last {lookback}s among {len(callsigns)} callsign(s)")
        return {"statusCode": 200, "body": "no recent activity"}

    message = {"content": _format_message(active, now), "username": "APRS \U0001F4E1"}
    resp = requests.post(discord_webhook, json=message, timeout=20)
    resp.raise_for_status()
    print(f"posted {len(active)} active callsign(s) to Discord")
    return {"statusCode": 200, "body": json.dumps({"active": len(active)})}
