import json
import requests
import os

def lambda_handler(event, context):
    # Debugging: Log the raw event for troubleshooting
    print("Raw Event Received:", json.dumps(event, indent=4))

    # Extract data from HamAlert payload
    payload = event if isinstance(event, dict) else json.loads(event)
    payload = json.loads(payload['body'])

    full_callsign = payload.get("fullCallsign", "N/A")
    callsign = payload.get("callsign", "N/A")
    frequency = payload.get("frequency", "N/A")
    band = payload.get("band", "N/A")
    mode = payload.get("mode", "N/A")
    mode_detail = payload.get("modeDetail", "N/A")
    spotter = payload.get("spotter", "N/A")
    source = payload.get("source", "N/A")
    comment = payload.get("comment", "N/A")

    # Determine which webhook URL to use
    webhook_url = os.environ.get('webhook_spots')

    # Format Discord message
    discord_message = {
        "content": f"📡 **New {source.upper()} Spot Alert!**\n\n"
                   f"📌 **Callsign:** {full_callsign}\n"
                   f"🔊 **Frequency:** {frequency} MHz ({band})\n"
                   f"🎛️ **Mode:** {mode.upper()} ({mode_detail.upper()})\n"
                   f"👤 **Spotter:** {spotter}\n"
                   f"💬 **Comment:** {comment}\n",
        "username": "HamBOT 🐷"
    }

    # Sending the message to Discord
    try:
        response = requests.post(webhook_url, json=discord_message)
        response.raise_for_status()
        print("Notification sent to Discord successfully.")
        return {
            "statusCode": 200,
            "body": json.dumps({"message": "Notification sent to Discord successfully."})
        }
    except requests.RequestException as e:
        print(f"Error sending notification to Discord: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
