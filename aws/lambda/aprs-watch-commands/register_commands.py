#!/usr/bin/env python3
"""One-time (re-run on change) registration of the APRS watch slash
commands with Discord. Run locally, NOT in Lambda.

Usage:
    DISCORD_APP_ID=...  DISCORD_BOT_TOKEN=...  [DISCORD_GUILD_ID=...] \
        python3 register_commands.py

If DISCORD_GUILD_ID is set, commands register to that guild and appear
instantly (best for setup/testing). Without it, they register globally and
can take up to ~1 hour to propagate. This does a bulk overwrite, so the
three commands below become exactly the command set.

Stdlib only -- no pip install needed.
"""
import json
import os
import sys
import urllib.request
import urllib.error

APP_ID = os.environ.get("DISCORD_APP_ID")
BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
GUILD_ID = os.environ.get("DISCORD_GUILD_ID")

COMMANDS = [
    {
        "name": "watch",
        "type": 1,  # CHAT_INPUT
        "description": "Watch a callsign on the APRS status board",
        "options": [{
            "name": "callsign", "type": 3,  # STRING
            "description": "Callsign, with optional SSID or trailing * (e.g. K3MGM-9, WZ1EEE*)",
            "required": True,
        }],
    },
    {
        "name": "unwatch",
        "type": 1,
        "description": "Remove your watch on a callsign",
        "options": [{
            "name": "callsign", "type": 3,
            "description": "Callsign you previously added",
            "required": True,
        }],
    },
    {
        "name": "watchlist",
        "type": 1,
        "description": "List the callsigns currently being watched",
    },
]


def main():
    if not APP_ID or not BOT_TOKEN:
        sys.exit("Set DISCORD_APP_ID and DISCORD_BOT_TOKEN")
    if GUILD_ID:
        url = f"https://discord.com/api/v10/applications/{APP_ID}/guilds/{GUILD_ID}/commands"
        scope = f"guild {GUILD_ID}"
    else:
        url = f"https://discord.com/api/v10/applications/{APP_ID}/commands"
        scope = "global"
    req = urllib.request.Request(
        url, data=json.dumps(COMMANDS).encode(), method="PUT",
        headers={"Authorization": f"Bot {BOT_TOKEN}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            names = [c["name"] for c in json.loads(r.read())]
        print(f"registered {scope} commands: {names}")
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code}: {e.read().decode()[:500]}")


if __name__ == "__main__":
    main()
