import json
import requests
from datetime import datetime
from zoneinfo import ZoneInfo  # Python 3.9+

DISCORD_WEBHOOKS = {
    "#evsrt": "https://discord.com/api/webhooks/1364335676442546360/g9JyXOfU4IIDoaUDo5Xwf8oMxmFzk42T5feQvdkaLfwYOvyN6LApKkkiUlhRWPY_-fQz",
    "#cw-club": "https://discord.com/api/webhooks/1369011481387208756/B7mM2zwxGP0Rrtoc4W3GX7n-Q_k1Jk0gdWArL1_ssMiEOwYwgNmdpljZ-a4KbmJ1GrSh"
}

SCHEDULES = [
    {
        "name": "EVSRT Reminder",
        "days_of_week": [6],
        "week_of_month": [1, 3],
        "hour": 12,
        "message": "@everyone 🚨 **EVSRT Tonight**\nWon't you join us at 9pm on 146.450 MHz?",
        "channel": "#evsrt",
    },
    {
        "name": "EVSRT Now",
        "days_of_week": [6],
        "week_of_month": [1, 3],
        "hour": 21,
        "message": "@everyone 🚨 **EVSRT Starting NOW!**\nBe there, and be square: 146.450 MHz, FM, no PL. Log-in Sheet here: https://bit.ly/4d6fDA8",
        "channel": "#evsrt",
    },
    {
        "name": "Daily CW Practice Check-In",
        "days_of_week": [0,1,2,3,4,5,6],
        "week_of_month": [1,2,3,4,5],
        "hour": 21,
        "message": "Did you get your 15 minutes of CW practice in today? (For those in the blood pact) ⭐",
        "channel": "#cw-club",
    },
]

def lambda_handler(event, context):
    now_utc = datetime.utcnow()
    now_pt = now_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("America/Los_Angeles"))

    for schedule in SCHEDULES:
        if should_trigger(schedule, now_pt):
            send_discord_message(schedule)

    return {
        'statusCode': 200,
        'body': json.dumps("Schedules checked.")
    }

def should_trigger(schedule, now):
    if now.weekday() not in schedule['days_of_week']:
        return False
    if now.hour != schedule['hour']:
        return False
    if 'week_of_month' in schedule:
        # Only count matching weekdays
        nth = get_weekday_occurrence_in_month(now)
        if nth not in schedule['week_of_month']:
            return False
    return True

def get_weekday_occurrence_in_month(dt):
    # Count how many times this weekday has occurred in the month so far
    count = 0
    for day in range(1, dt.day + 1):
        if datetime(dt.year, dt.month, day).weekday() == dt.weekday():
            count += 1
    return count

def send_discord_message(item_obj):
    webhook_url = DISCORD_WEBHOOKS[item_obj['channel']]
    payload = {
        "content": f"{item_obj['message']}",
        "username": "HamBOT 🐷"
    }
    requests.post(webhook_url, json=payload)
