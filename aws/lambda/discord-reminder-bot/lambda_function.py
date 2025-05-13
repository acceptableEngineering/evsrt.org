import json
import os
import requests
from datetime import datetime
from zoneinfo import ZoneInfo  # Python 3.9+

def cw_random_string():
    strings = [
        "Hey silly-face, did you get your 15 minutes of CW practice in today?",
        "Hey lazy-ass, did you get your 15 minutes of CW practice in today?",
        "PRACTICE CW FOR 15 MINUTES, AT LEAST!",
        "Practice CW or die."
        "Did you get your 15 minutes of CW practice in today?",
        "Not decoding 20 WPM yet, eh? Did you practice today? Mmm-hmm...",
        "You can decrease the number of people you will disappoint with your CW by practicing more. Did you practice today?",
    ]

    now_utc = datetime.utcnow()
    now_pt = now_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("America/Los_Angeles"))

    return strings[now_pt.weekday()]

SCHEDULES = [
    {
        "name": "EVSRT Reminder",
        "days_of_week": [6],
        "week_of_month": [1, 3],
        "hour": 12,
        "message": "@everyone ⚠️ **EVSRT Tonight**\nWon't you join us at 9pm on 146.450 MHz?",
        "channel": "evsrt",
    },
    {
        "name": "EVSRT Now",
        "days_of_week": [6],
        "week_of_month": [1, 3],
        "hour": 21,
        "message": "@everyone 🚨 **EVSRT Starting NOW!**\nBe there, and be square: 146.450 MHz, FM, no PL. Log Sheet: https://bit.ly/4d6fDA8",
        "channel": "evsrt",
    },
    {
        "name": "Daily CW Practice Check-In",
        "days_of_week": [0,1,2,3,4,5,6],
        "week_of_month": [1,2,3,4,5],
        "hour": 21,
        "message": cw_random_string() + " (For those in the blood pact) ⭐",
        "channel": "cw_club",
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
    webhook_url = os.environ.get('webhook_' + item_obj['channel'])
    payload = {
        "content": f"{item_obj['message']}",
        "username": "HamBOT 🐷"
    }
    requests.post(webhook_url, json=payload)
