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

    # Get webhook URLs from environment variables
    discord_webhook = os.environ.get('discord_webhook')
    mattermost_webhook = os.environ.get('mattermost_webhook')

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

    # Format Mattermost message (using Markdown formatting)
    mattermost_message = {
        "text": f"📡 **New {source.upper()} Spot Alert!**\n\n"
                f"📌 **Callsign:** {full_callsign}\n"
                f"🔊 **Frequency:** {frequency} MHz ({band})\n"
                f"🎛️ **Mode:** {mode.upper()} ({mode_detail.upper()})\n"
                f"👤 **Spotter:** {spotter}\n"
                f"💬 **Comment:** {comment}",
        "username": "HamBOT"
    }

    results = []
    
    # Send to Discord
    if discord_webhook:
        try:
            response = requests.post(discord_webhook, json=discord_message)
            response.raise_for_status()
            print("Notification sent to Discord successfully.")
            results.append("Discord: Success")
        except requests.RequestException as e:
            print(f"Error sending notification to Discord: {e}")
            results.append(f"Discord: Failed - {e}")
    else:
        print("Discord webhook URL not configured.")
        results.append("Discord: Not configured")

    # Send to Mattermost
    if mattermost_webhook:
        try:
            response = requests.post(mattermost_webhook, json=mattermost_message)
            response.raise_for_status()
            print("Notification sent to Mattermost successfully.")
            results.append("Mattermost: Success")
        except requests.RequestException as e:
            print(f"Error sending notification to Mattermost: {e}")
            results.append(f"Mattermost: Failed - {e}")
    else:
        print("Mattermost webhook URL not configured.")
        results.append("Mattermost: Not configured")

    # Return overall status
    return {
        "statusCode": 200,
        "body": json.dumps({"message": "Notifications processed.", "results": results})
    }
