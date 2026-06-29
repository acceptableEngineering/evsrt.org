"""aprs-watch-commands -- Discord slash-command handler for the APRS watch
list, served over HTTP from a Lambda Function URL (Discord's "Interactions
Endpoint URL"). No always-on gateway connection: Discord HTTP-POSTs each
interaction here, we verify it and reply inline.

Commands:
    /watch <callsign>      enroll a callsign (any user)
    /unwatch <callsign>    remove YOUR enrollment of a callsign
    /watchlist             list watched callsigns (yours flagged)

The watch list lives in DynamoDB as (callsign, user_id) pairs, so several
users can watch the same call and each only manages their own entries --
only the user who /watch'd an entry can /unwatch it. The companion
aprs-to-discord Lambda reads this table to maintain the status board.

Security: Discord signs every request (Ed25519). We verify the
X-Signature-Ed25519 / X-Signature-Timestamp headers against the
application public key; unverified requests get 401. This is mandatory --
Discord won't even accept the endpoint URL unless it answers the PING
handshake with a valid signature check.

Env vars:
    discord_public_key   Discord application public key (hex)  (REQUIRED)
    watch_table          DynamoDB table name      (optional, default "evsrt-aprs-watch")
    max_callsigns        cap on distinct watched calls (optional, default 50)
"""

import json
import os
import re
import time

import boto3
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

WATCH_TABLE = os.environ.get("watch_table", "evsrt-aprs-watch")
MAX_CALLSIGNS = int(os.environ.get("max_callsigns", "50"))
PUBLIC_KEY = os.environ.get("discord_public_key", "")

_ddb = boto3.resource("dynamodb")

# Interaction + response type constants (Discord API).
PING, APPLICATION_COMMAND = 1, 2
PONG, CHANNEL_MESSAGE = 1, 4
EPHEMERAL = 64

# Amateur callsign with optional SSID and optional trailing '*' wildcard,
# e.g. K3MGM, K3MGM-9, WZ1EEE*. Deliberately permissive but bounded.
_CALLSIGN_RE = re.compile(r"^[A-Z0-9]{2,8}(-[A-Z0-9]{1,2})?\*?$")


def _reply(content, ephemeral=True):
    data = {"content": content}
    if ephemeral:
        data["flags"] = EPHEMERAL
    return _http(200, {"type": CHANNEL_MESSAGE, "data": data})


def _http(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


# --- signature verification ------------------------------------------------

def _verify(event):
    """True iff the request carries a valid Discord Ed25519 signature."""
    if not PUBLIC_KEY:
        print("discord_public_key not configured")
        return False
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    sig = headers.get("x-signature-ed25519")
    ts = headers.get("x-signature-timestamp")
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        import base64
        raw = base64.b64decode(raw).decode("utf-8")
    if not sig or not ts:
        return False
    try:
        VerifyKey(bytes.fromhex(PUBLIC_KEY)).verify(
            (ts + raw).encode(), bytes.fromhex(sig))
        return True
    except (BadSignatureError, ValueError):
        return False


# --- command handlers ------------------------------------------------------

def _option(interaction, name):
    for opt in (interaction.get("data") or {}).get("options", []):
        if opt.get("name") == name:
            return opt.get("value")
    return None


def _actor(interaction):
    """(user_id, display_name) from a guild or DM interaction."""
    user = (interaction.get("member") or {}).get("user") or interaction.get("user") or {}
    return user.get("id"), (user.get("global_name") or user.get("username") or "unknown")


def _normalize_callsign(raw):
    cs = (raw or "").strip().upper()
    return cs if _CALLSIGN_RE.match(cs) else None


def _distinct_callsigns(table):
    seen = set()
    resp = table.scan(ProjectionExpression="callsign")
    items = resp.get("Items", [])
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ProjectionExpression="callsign",
                          ExclusiveStartKey=resp["LastEvaluatedKey"])
        items += resp.get("Items", [])
    for it in items:
        seen.add(it.get("callsign"))
    return seen


def _cmd_watch(interaction, table):
    cs = _normalize_callsign(_option(interaction, "callsign"))
    if not cs:
        return _reply("That doesn't look like a valid callsign. Try e.g. `K3MGM-9` or `WZ1EEE*`")
    user_id, user_name = _actor(interaction)
    existing = _distinct_callsigns(table)
    if cs not in existing and len(existing) >= MAX_CALLSIGNS:
        return _reply(f"The watch list is full ({MAX_CALLSIGNS} callsigns). Remove one first with `/unwatch`")
    table.put_item(Item={
        "callsign": cs, "user_id": user_id,
        "user_name": user_name, "added_at": int(time.time()),
    })
    return _reply(f"✅ Now watching **{cs}** — it'll appear on the status board on the next update")


def _cmd_unwatch(interaction, table):
    cs = _normalize_callsign(_option(interaction, "callsign"))
    if not cs:
        return _reply("That doesn't look like a valid callsign")
    user_id, _ = _actor(interaction)
    try:
        table.delete_item(
            Key={"callsign": cs, "user_id": user_id},
            ConditionExpression="attribute_exists(user_id)",
        )
    except _ddb.meta.client.exceptions.ConditionalCheckFailedException:
        return _reply(f"You're not watching **{cs}** — only the person who added an entry can remove it")
    return _reply(f"\U0001F5D1️ Removed your watch on **{cs}**")


def _cmd_watchlist(interaction, table):
    user_id, _ = _actor(interaction)
    resp = table.scan(ProjectionExpression="callsign, user_id")
    items = resp.get("Items", [])
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ProjectionExpression="callsign, user_id",
                          ExclusiveStartKey=resp["LastEvaluatedKey"])
        items += resp.get("Items", [])
    mine, calls = set(), {}
    for it in items:
        cs = it.get("callsign")
        calls[cs] = calls.get(cs, 0) + 1
        if it.get("user_id") == user_id:
            mine.add(cs)
    if not calls:
        return _reply("No callsigns are being watched yet. Add one with `/watch <callsign>`")
    lines = []
    for cs in sorted(calls):
        tag = " *(yours)*" if cs in mine else ""
        watchers = f" — {calls[cs]} watchers" if calls[cs] > 1 else ""
        lines.append(f"• **{cs}**{tag}{watchers}")
    return _reply("**Watched callsigns:**\n" + "\n".join(lines)[:1900])


_COMMANDS = {"watch": _cmd_watch, "unwatch": _cmd_unwatch, "watchlist": _cmd_watchlist}


def lambda_handler(event, context):
    if not _verify(event):
        return _http(401, {"error": "invalid request signature"})

    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        import base64
        raw = base64.b64decode(raw).decode("utf-8")
    interaction = json.loads(raw)

    itype = interaction.get("type")
    if itype == PING:
        return _http(200, {"type": PONG})
    if itype == APPLICATION_COMMAND:
        name = (interaction.get("data") or {}).get("name")
        handler = _COMMANDS.get(name)
        if handler:
            try:
                return handler(interaction, _ddb.Table(WATCH_TABLE))
            except Exception as e:  # never leave the user hanging
                print(f"error handling /{name}: {e}")
                return _reply("Something went wrong handling that command. Try again in a moment")
        return _reply("Unknown command")
    return _http(400, {"error": "unhandled interaction type"})
