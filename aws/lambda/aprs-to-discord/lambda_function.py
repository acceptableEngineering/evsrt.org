"""aprs-to-discord -- maintain a single Discord "status board" message
showing APRS activity for a user-managed watch list of callsigns.

Runs on a schedule (EventBridge, e.g. every 10 minutes). Each run:
  1. reads the watch list from DynamoDB (managed by the companion
     aprs-watch-commands Lambda's /watch and /unwatch slash commands),
  2. queries aprs.fi for those callsigns,
  3. edits ONE pinned Discord message in place to reflect current status,
     rather than posting a new message each cycle (which made the channel
     an endless feed of stale info).

The board's message id is stored in SSM Parameter Store so the message
persists across invocations. On first run (or if the message was deleted)
the board is created fresh and its id saved.

Editing uses the webhook itself -- a webhook can edit its own messages via
PATCH /webhooks/{id}/{token}/messages/{message_id} -- so no bot token is
needed here. (The bot token is only used once, out of band, to register
the slash commands; see the README.)

Env vars (set on the Lambda):
    discord_webhook    Discord webhook URL                 (REQUIRED)
    aprs_fi_api_key    aprs.fi API key                     (REQUIRED)
    lookback_seconds   "active" window, seconds            (optional, default 600)
    watch_table        DynamoDB watch-list table name      (optional, default "evsrt-aprs-watch")
    board_param        SSM param holding the board msg id  (optional, default "/evsrt/aprs/board_message_id")
"""

import json
import os
import time

import boto3
import requests

APRS_API = "https://api.aprs.fi/api/get"
USER_AGENT = "evsrt-aprs-watch/2.0 (+https://evsrt.org)"
APRS_MAX_TARGETS = 20  # aprs.fi caps each query at 20 targets

WATCH_TABLE = os.environ.get("watch_table", "evsrt-aprs-watch")
BOARD_PARAM = os.environ.get("board_param", "/evsrt/aprs/board_message_id")

_ddb = boto3.resource("dynamodb")
_ssm = boto3.client("ssm")


# --- watch list (DynamoDB) -------------------------------------------------

def _load_watchlist():
    """Distinct enrolled callsign tokens from the watch table. Each item is
    a (callsign, user_id) pair, so multiple users may watch the same call;
    we return the unique set of callsign tokens (as users typed them)."""
    table = _ddb.Table(WATCH_TABLE)
    seen, out = set(), []
    resp = table.scan(ProjectionExpression="callsign")
    items = resp.get("Items", [])
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ProjectionExpression="callsign",
                          ExclusiveStartKey=resp["LastEvaluatedKey"])
        items += resp.get("Items", [])
    for it in items:
        cs = (it.get("callsign") or "").strip().upper()
        if cs and cs not in seen:
            seen.add(cs)
            out.append(cs)
    out.sort()
    return out


def _expand_callsign(token):
    """A trailing '*' (e.g. 'WZ1EEE*') means the base call on any SSID:
    the bare base plus -1..-15. aprs.fi has no wildcard matching, so we
    expand here before querying."""
    if token.endswith("*"):
        base = token[:-1].rstrip("-")
        if not base:
            return []
        return [base] + [f"{base}-{i}" for i in range(1, 16)]
    return [token]


# --- aprs.fi ---------------------------------------------------------------

def _chunks(items, n):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def _query_aprs(callsigns, api_key):
    """Return {uppercased name -> aprs.fi loc entry} for the given calls."""
    by_name = {}
    for batch in _chunks(callsigns, APRS_MAX_TARGETS):
        params = {"name": ",".join(batch), "what": "loc",
                  "apikey": api_key, "format": "json"}
        resp = requests.get(APRS_API, params=params,
                            headers={"User-Agent": USER_AGENT}, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if data.get("result") != "ok":
            print("aprs.fi non-ok:", data.get("description") or data)
            continue
        for e in data.get("entries", []):
            n = (e.get("name") or "").upper()
            if n:
                by_name[n] = e
    return by_name


def _via(entry):
    """'Via' summary from the path q-construct: RF -> igate, DMR -> gateway,
    or Internet. None if undeterminable."""
    path = entry.get("path") or ""
    dstcall = (entry.get("dstcall") or "").upper()
    tokens = [t for t in path.split(",") if t]
    q = next((t for t in tokens if t.lower().startswith("qa")), None)
    igate = None
    if q is not None:
        idx = tokens.index(q)
        igate = tokens[idx + 1] if idx + 1 < len(tokens) else None
    if dstcall.startswith("APBM") or any(t.upper().rstrip("*") == "DMR" for t in tokens):
        return f"DMR → {igate}" if igate else "DMR"
    if q is None:
        return None
    ql = q.lower()
    if ql in ("qar", "qao", "qau"):
        return f"RF → {igate}" if igate else "RF"
    if ql in ("qac", "qas", "qax"):
        return "Internet"
    return None


def _best_entry(token, by_name):
    """For an enrolled token, find the most-recently-heard aprs.fi entry.
    For a wildcard token this scans all its SSID expansions and returns the
    freshest; returns (entry, last_epoch) or (None, None)."""
    best, best_last = None, None
    for cand in _expand_callsign(token):
        e = by_name.get(cand.upper())
        if not e:
            continue
        try:
            last = int(e.get("lasttime", 0))
        except (TypeError, ValueError):
            continue
        if best_last is None or last > best_last:
            best, best_last = e, last
    return best, best_last


# --- board rendering -------------------------------------------------------

def _rel(now, last):
    secs = max(0, now - last)
    if secs < 90:
        return "just now"
    mins = secs // 60
    if mins < 60:
        return f"{mins} min ago"
    hrs = mins // 60
    if hrs < 24:
        return f"{hrs}h ago"
    return f"{hrs // 24}d ago"


def _board_line(token, by_name, now, lookback):
    entry, last = _best_entry(token, by_name)
    if entry is None or last is None:
        return f"⚫ **{token}** — no APRS data"  # black circle
    heard = entry.get("name", token)
    parts = []
    via = _via(entry)
    if via:
        parts.append(via)
    parts.append(f"[map](https://aprs.fi/?call={heard})")
    detail = " · ".join(parts)
    if now - last <= lookback:
        dot = "\U0001F7E2"  # green
        label = token if heard.upper() == token.upper() else f"{token} ({heard})"
        return f"{dot} **{label}** — {_rel(now, last)} · {detail}"
    dot = "⚪"  # white circle (idle)
    return f"{dot} **{token}** — last heard {_rel(now, last)} · {detail}"


def _build_embed(watchlist, by_name, now, lookback):
    if not watchlist:
        desc = "_No callsigns are being watched._\nUse `/watch <callsign>` to add one."
    else:
        lines = [_board_line(t, by_name, now, lookback) for t in watchlist]
        desc = "\n".join(lines)[:4000]
    active = sum(
        1 for t in watchlist
        if (lambda e_l: e_l[1] is not None and now - e_l[1] <= lookback)(_best_entry(t, by_name))
    )
    return {
        "title": "\U0001F4E1 APRS Watch — Status Board",
        "description": desc,
        "color": 0x2ECC71 if active else 0x95A5A6,
        "footer": {"text": f"{active} active · {len(watchlist)} watched · updated"},
        # Discord renders this as a localized "Updated <time>" in the footer.
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
    }


# --- board message persistence (create / edit) -----------------------------

def _get_board_id():
    try:
        return _ssm.get_parameter(Name=BOARD_PARAM)["Parameter"]["Value"]
    except _ssm.exceptions.ParameterNotFound:
        return None


def _save_board_id(message_id):
    _ssm.put_parameter(Name=BOARD_PARAM, Value=message_id, Type="String", Overwrite=True)


def _create_board(webhook, embed):
    resp = requests.post(f"{webhook}?wait=true",
                         json={"embeds": [embed], "username": "APRS Watch \U0001F4E1"},
                         timeout=20)
    resp.raise_for_status()
    mid = resp.json()["id"]
    _save_board_id(mid)
    print(f"created board message {mid}")
    return mid


def _publish_board(webhook, embed):
    """Edit the existing board message in place; (re)create it if missing."""
    mid = _get_board_id()
    if mid:
        resp = requests.patch(f"{webhook}/messages/{mid}",
                              json={"embeds": [embed]}, timeout=20)
        if resp.status_code == 404:
            print(f"board message {mid} gone; recreating")
            _create_board(webhook, embed)
        else:
            resp.raise_for_status()
    else:
        _create_board(webhook, embed)


def lambda_handler(event, context):
    webhook = os.environ.get("discord_webhook")
    api_key = os.environ.get("aprs_fi_api_key")
    lookback = int(os.environ.get("lookback_seconds", "600"))
    if not webhook or not api_key:
        msg = "discord_webhook and aprs_fi_api_key are required"
        print(msg)
        return {"statusCode": 500, "body": msg}

    watchlist = _load_watchlist()
    # Expand wildcards for the aprs.fi query; the board still shows the
    # original enrolled tokens.
    query_calls = []
    seen = set()
    for t in watchlist:
        for c in _expand_callsign(t):
            cu = c.upper()
            if cu not in seen:
                seen.add(cu)
                query_calls.append(c)

    by_name = _query_aprs(query_calls, api_key) if query_calls else {}
    now = int(time.time())
    embed = _build_embed(watchlist, by_name, now, lookback)
    _publish_board(webhook, embed)
    return {"statusCode": 200,
            "body": json.dumps({"watched": len(watchlist),
                                 "queried": len(query_calls)})}
