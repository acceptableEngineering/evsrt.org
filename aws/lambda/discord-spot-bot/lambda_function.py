import json
import requests
import os

def lambda_handler(event, context):
    # Extract data from HamAlert payload
    payload = event
    full_callsign = payload.get("fullCallsign", "N/A")
    callsign = payload.get("callsign", "N/A")
    frequency = payload.get("frequency", "N/A")
    band = payload.get("band", "N/A")
    mode = payload.get("mode", "N/A")
    mode_detail = payload.get("modeDetail", "N/A")
    spotter = payload.get("spotter", "N/A")
    source = payload.get("source", "N/A")
    comment = payload.get("comment", "")

    if source == "sotawatch":
        webhook_url = os.environ.get('webhook_sota')
    elif source == "pota":
        webhook_url = os.environ.get('webhook_pota')
    else: # Don't send if not SOTA or POTA
        return False

    # Format Discord message
    discord_message = {
        "content": f"📡 New HamAlert Spot!\n\n"
                   f"📌 **Callsign:** {full_callsign} ({callsign})\n"
                   f"🔊 **Frequency:** {frequency} MHz ({band})\n"
                   f"🎛️ **Mode:** {mode} ({mode_detail})\n"
                   f"👤 **Spotter:** {spotter}\n"
                   f"🔗 **Source:** {source}\n"
                   f"💬 **Comment:** {comment}\n"
    }

    # Sending the message to Discord
    try:
        response = requests.post(webhook_url, json=discord_message)
        response.raise_for_status()
        return {
            "statusCode": 200,
            "body": json.dumps({"message": "Notification sent to Discord successfully."})
        }
    except requests.RequestException as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
