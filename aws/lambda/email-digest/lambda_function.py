import hmac
import json
import hashlib
import os
import sys
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
import urllib.request
import urllib.error
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut

# Debug: Print Python path and check for sendgrid
print(f"Python version: {sys.version}")
print(f"Python path: {sys.path}")
print(f"Current directory contents: {os.listdir('.')}")

# Try to import SendGrid - it's required for Lambda but optional for local file generation
try:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail, Email, To, Content
    SENDGRID_AVAILABLE = True
    print("✓ SendGrid imported successfully")
except ImportError as e:
    SENDGRID_AVAILABLE = False
    print(f"✗ SendGrid import failed: {e}")
    # Only warn if we're not just generating a file
    if not os.environ.get('OUTPUT_FILE'):
        print("Warning: sendgrid not installed. Install with: pip install sendgrid")


def fetch_solar_data():
    """Fetch and parse solar propagation data from hamqsl.com"""
    url = "https://www.hamqsl.com/solarrss.php"

    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            xml_data = response.read().decode('utf-8')

        root = ET.fromstring(xml_data)
        solar = root.find('.//solar/solardata')

        if solar is None:
            return None

        # Extract key solar data
        data = {
            'updated': solar.find('updated').text if solar.find('updated') is not None else 'N/A',
            'solarflux': solar.find('solarflux').text if solar.find('solarflux') is not None else 'N/A',
            'aindex': solar.find('aindex').text if solar.find('aindex') is not None else 'N/A',
            'kindex': solar.find('kindex').text if solar.find('kindex') is not None else 'N/A',
            'sunspots': solar.find('sunspots').text if solar.find('sunspots') is not None else 'N/A',
            'solarwind': solar.find('solarwind').text if solar.find('solarwind') is not None else 'N/A',
            'geomagfield': solar.find('geomagfield').text if solar.find('geomagfield') is not None else 'N/A',
            'signalnoise': solar.find('signalnoise').text if solar.find('signalnoise') is not None else 'N/A',
        }

        # Extract band conditions
        conditions = solar.find('calculatedconditions')
        data['band_conditions'] = []
        if conditions is not None:
            for band in conditions.findall('band'):
                data['band_conditions'].append({
                    'name': band.get('name'),
                    'time': band.get('time'),
                    'condition': band.text
                })

        return data
    except Exception as e:
        print(f"Error fetching solar data: {e}")
        return None


def fetch_contest_data():
    """Fetch and parse contest calendar from contestcalendar.com"""
    url = "https://www.contestcalendar.com/calendar.rss"

    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            xml_data = response.read().decode('utf-8')

        root = ET.fromstring(xml_data)

        contests = []
        for item in root.findall('.//item'):
            title = item.find('title')
            description = item.find('description')
            link = item.find('link')

            contests.append({
                'title': title.text if title is not None else 'Unknown',
                'time': description.text if description is not None else 'N/A',
                'link': link.text if link is not None else ''
            })

        return contests
    except Exception as e:
        print(f"Error fetching contest data: {e}")
        return []


def filter_contests_for_next_week(contests, days=7):
    """Filter contests to include the next N days (default 7)"""
    today = datetime.utcnow().date()
    end_date = today + timedelta(days=days)

    filtered = []

    for contest in contests:
        time_str = contest['time']
        # Parse dates from descriptions like "0000Z-0100Z, Dec 18"
        # Extract the date portion
        if ',' in time_str:
            date_part = time_str.split(',')[-1].strip()
            try:
                # Try to parse "Dec 18" or "Dec 18 to Dec 19" formats
                if ' to ' in date_part:
                    # Handle multi-day contests - use the start date
                    start_date_str = date_part.split(' to ')[0].strip()
                    contest_date = datetime.strptime(f"{start_date_str} {today.year}", "%b %d %Y").date()
                else:
                    contest_date = datetime.strptime(f"{date_part} {today.year}", "%b %d %Y").date()
                
                # Include if it's within the next N days
                if today <= contest_date < end_date:
                    filtered.append(contest)
            except ValueError:
                # If we can't parse the date, include it anyway to be safe
                filtered.append(contest)
        else:
            # If no clear date format, include it
            filtered.append(contest)

    return filtered


def zip_to_coords(zip_code):
    """Convert US ZIP code to latitude/longitude coordinates

    Args:
        zip_code: US ZIP code string
        
    Returns:
        Tuple of (lat, lon) or None if lookup fails
    """
    try:
        geocoder = Nominatim(user_agent="ham_radio_digest")
        location = geocoder.geocode(f"{zip_code}, USA", timeout=5)

        if location:
            print(f"✓ ZIP {zip_code} -> ({location.latitude}, {location.longitude})")
            return (location.latitude, location.longitude)
        else:
            print(f"✗ Could not geocode ZIP {zip_code}")
            return None
    except GeocoderTimedOut:
        print(f"✗ Geocoding timeout for ZIP {zip_code}")
        return None
    except Exception as e:
        print(f"✗ Error geocoding ZIP {zip_code}: {e}")
        return None


def fetch_weather_forecast(latitude, longitude):
    """Fetch 7-day weather forecast from Open-Meteo API (free, no auth required)

    Args:
        latitude: Location latitude
        longitude: Location longitude
        
    Returns:
        Dict with daily forecast data or None on failure
    """
    url = f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code&temperature_unit=fahrenheit&timezone=auto"

    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))

        if 'daily' not in data:
            print(f"No daily forecast data in response")
            return None

        daily = data['daily']
        forecast = {
            'timezone': data.get('timezone', 'Unknown'),
            'days': []
        }

        # Parse each day's forecast
        for i in range(min(7, len(daily['time']))):
            day_date = daily['time'][i]
            high_temp = daily['temperature_2m_max'][i]
            low_temp = daily['temperature_2m_min'][i]
            weather_code = daily['weather_code'][i]
            precipitation = daily.get('precipitation_sum', [0] * 7)[i]

            # Convert WMO weather codes to human-readable descriptions
            weather_desc = wmo_code_to_description(weather_code)

            forecast['days'].append({
                'date': day_date,
                'high': high_temp,
                'low': low_temp,
                'condition': weather_desc,
                'precipitation': precipitation
            })

        return forecast
    except Exception as e:
        print(f"Error fetching weather forecast: {e}")
        return None


def wmo_code_to_description(code):
    """Convert WMO weather code to human-readable description
    
    WMO Weather interpretation codes:
    0 = Clear sky
    1, 2 = Mostly clear
    3 = Overcast
    45, 48 = Foggy
    51-67 = Drizzle/Rain
    71-77 = Snow
    80-82 = Rain showers
    85-86 = Snow showers
    80-99 = Thunderstorm
    """
    if code == 0:
        return "Clear"
    elif code in [1, 2]:
        return "Mostly Clear"
    elif code == 3:
        return "Overcast"
    elif code in [45, 48]:
        return "Foggy"
    elif code in range(51, 68):  # Drizzle and rain
        return "Rain"
    elif code in range(71, 78):  # Snow
        return "Snow"
    elif code in [80, 81, 82]:  # Rain showers
        return "Showers"
    elif code in [85, 86]:  # Snow showers
        return "Snow Showers"
    elif code in range(80, 100):  # Thunderstorm
        return "Thunderstorm"
    else:
        return "Unknown"


def format_solar_text(solar_data):
    """Format solar data as plain text"""
    if not solar_data:
        return "Solar data unavailable\n"

    text = "=" * 60 + "\n"
    text += "SOLAR PROPAGATION CONDITIONS\n"
    text += "=" * 60 + "\n"
    text += f"Updated: {solar_data['updated'].replace(' GMT', ' UTC')}\n\n"

    text += f"Solar Flux:      {solar_data['solarflux']:>6}\n"
    text += f"Sunspots:        {solar_data['sunspots']:>6}\n"
    text += f"A-Index:         {solar_data['aindex']:>6}\n"
    text += f"K-Index:         {solar_data['kindex']:>6}\n"
    text += f"Solar Wind:      {solar_data['solarwind']:>6} km/s\n"
    text += f"Geomag Field:    {solar_data['geomagfield']}\n"
    text += f"Signal Noise:    {solar_data['signalnoise']}\n\n"

    text += "BAND CONDITIONS\n"
    text += "-" * 60 + "\n"
    text += f"{'Band':<15} {'Day':<10} {'Night':<10}\n"
    text += "-" * 60 + "\n"

    # Group conditions by band
    bands = {}
    for condition in solar_data['band_conditions']:
        band = condition['name']
        time = condition['time']
        status = condition['condition']

        if band not in bands:
            bands[band] = {}
        bands[band][time] = status

    for band, times in bands.items():
        day_status = times.get('day', 'N/A')
        night_status = times.get('night', 'N/A')
        text += f"{band:<15} {day_status:<10} {night_status:<10}\n"

    text += "\n"
    return text


def format_contests_text(contests):
    """Format contest data as plain text"""
    if not contests:
        return "No contests scheduled for the next 7 days\n"

    text = "=" * 60 + "\n"
    text += "CONTESTS - NEXT 7 DAYS\n"
    text += "=" * 60 + "\n\n"

    for contest in contests:
        text += f"{contest['title']}\n"
        text += f"  Time: {contest['time']}\n"

    return text


def format_weather_text(forecast, zip_code):
    """Format weather forecast as plain text"""
    if not forecast:
        return f"Weather data unavailable for ZIP {zip_code}\n"

    text = "=" * 60 + "\n"
    text += f"WEATHER FORECAST - {zip_code}\n"
    text += "=" * 60 + "\n"
    text += f"Timezone: {forecast['timezone']}\n\n"
    text += f"{'Date':<12} {'High':<8} {'Low':<8} {'Condition':<15}\n"
    text += "-" * 60 + "\n"

    for day in forecast['days']:
        date_str = datetime.strptime(day['date'], '%Y-%m-%d').strftime('%a %m/%d')
        high = f"{day['high']:.0f}°F"
        low = f"{day['low']:.0f}°F"
        condition = day['condition']
        text += f"{date_str:<12} {high:<8} {low:<8} {condition:<15}\n"

    text += "\n"
    return text


def format_solar_html(solar_data):
    """Format solar data as HTML"""
    if not solar_data:
        return "<p>Solar data unavailable</p>"

    html = f"""
    <h2>📡 Solar Propagation Conditions</h2>
    <p><strong>Updated:</strong> {solar_data['updated'].replace(' GMT', ' UTC')}</p>

    <table style="border-collapse: collapse; margin: 10px 0;">
        <tr>
            <td style="padding: 5px;"><strong>Solar Flux:</strong></td>
            <td style="padding: 5px;">{solar_data['solarflux']}</td>
            <td style="padding: 5px;"><strong>Sunspots:</strong></td>
            <td style="padding: 5px;">{solar_data['sunspots']}</td>
        </tr>
        <tr>
            <td style="padding: 5px;"><strong>A-Index:</strong></td>
            <td style="padding: 5px;">{solar_data['aindex']}</td>
            <td style="padding: 5px;"><strong>K-Index:</strong></td>
            <td style="padding: 5px;">{solar_data['kindex']}</td>
        </tr>
        <tr>
            <td style="padding: 5px;"><strong>Solar Wind:</strong></td>
            <td style="padding: 5px;">{solar_data['solarwind']} km/s</td>
            <td style="padding: 5px;"><strong>Geomag Field:</strong></td>
            <td style="padding: 5px;">{solar_data['geomagfield']}</td>
        </tr>
        <tr>
            <td style="padding: 5px;"><strong>Signal Noise:</strong></td>
            <td style="padding: 5px;" colspan="3">{solar_data['signalnoise']}</td>
        </tr>
    </table>

    <h3>Band Conditions</h3>
    <table style="border-collapse: collapse; width: 100%; margin: 10px 0;">
        <thead>
            <tr style="background-color: #f0f0f0;">
                <th style="padding: 8px; text-align: left; border: 1px solid #ddd;">Band</th>
                <th style="padding: 8px; text-align: left; border: 1px solid #ddd;">Day</th>
                <th style="padding: 8px; text-align: left; border: 1px solid #ddd;">Night</th>
            </tr>
        </thead>
        <tbody>
    """

    # Group conditions by band
    bands = {}
    for condition in solar_data['band_conditions']:
        band = condition['name']
        time = condition['time']
        status = condition['condition']
        
        if band not in bands:
            bands[band] = {}
        bands[band][time] = status

    for band, times in bands.items():
        day_status = times.get('day', 'N/A')
        night_status = times.get('night', 'N/A')

        # Color code the status
        day_color = {'Good': '#90EE90', 'Fair': '#FFD700', 'Poor': '#FFB6C1'}.get(day_status, '#FFFFFF')
        night_color = {'Good': '#90EE90', 'Fair': '#FFD700', 'Poor': '#FFB6C1'}.get(night_status, '#FFFFFF')

        html += f"""
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;">{band}</td>
                <td style="padding: 8px; border: 1px solid #ddd; background-color: {day_color};">{day_status}</td>
                <td style="padding: 8px; border: 1px solid #ddd; background-color: {night_color};">{night_status}</td>
            </tr>
        """

    html += """
        </tbody>
    </table>
    """

    return html


def format_contests_html(contests):
    """Format contest data as HTML"""
    if not contests:
        return "<p>No contests scheduled for the next 7 days</p>"

    html = """
    <h2>🏆 Contests - Next 7 Days</h2>
    <table style="border-collapse: collapse; width: 100%; margin: 10px 0;">
        <thead>
            <tr style="background-color: #f0f0f0;">
                <th style="padding: 8px; text-align: left; border: 1px solid #ddd;">Contest</th>
                <th style="padding: 8px; text-align: left; border: 1px solid #ddd;">Time (UTC)</th>
            </tr>
        </thead>
        <tbody>
    """

    for contest in contests:
        html += f"""
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;">
                    <a href="{contest['link']}">{contest['title']}</a>
                </td>
                <td style="padding: 8px; border: 1px solid #ddd;">{contest['time']}</td>
            </tr>
        """

    html += """
        </tbody>
    </table>
    """

    return html


def format_weather_html(forecast, zip_code):
    """Format weather forecast as HTML"""
    if not forecast:
        return f"<p>Weather data unavailable for ZIP {zip_code}</p>"

    html = f"""
    <h2>🌤️ 7-Day Weather Forecast</h2>
    <p><strong>Location:</strong> ZIP {zip_code} ({forecast['timezone']})</p>

    <table style="border-collapse: collapse; width: 100%; margin: 10px 0;">
        <thead>
            <tr style="background-color: #f0f0f0;">
                <th style="padding: 8px; text-align: left; border: 1px solid #ddd;">Date</th>
                <th style="padding: 8px; text-align: center; border: 1px solid #ddd;">High</th>
                <th style="padding: 8px; text-align: center; border: 1px solid #ddd;">Low</th>
                <th style="padding: 8px; text-align: left; border: 1px solid #ddd;">Condition</th>
            </tr>
        </thead>
        <tbody>
    """

    for day in forecast['days']:
        date_obj = datetime.strptime(day['date'], '%Y-%m-%d')
        date_str = date_obj.strftime('%a, %b %d')
        high = f"{day['high']:.0f}°F"
        low = f"{day['low']:.0f}°F"
        condition = day['condition']

        # Color code conditions
        condition_color = {
            'Clear': '#87CEEB',
            'Mostly Clear': '#B0E0E6',
            'Overcast': '#D3D3D3',
            'Rain': '#4169E1',
            'Showers': '#6495ED',
            'Snow': '#F0F8FF',
            'Thunderstorm': '#191970'
        }.get(condition, '#FFFFFF')

        html += f"""
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;">{date_str}</td>
                <td style="padding: 8px; text-align: center; border: 1px solid #ddd; font-weight: bold;">{high}</td>
                <td style="padding: 8px; text-align: center; border: 1px solid #ddd;">{low}</td>
                <td style="padding: 8px; border: 1px solid #ddd; background-color: {condition_color}; color: {'white' if condition == 'Thunderstorm' else 'black'};">{condition}</td>
            </tr>
        """

    html += """
        </tbody>
    </table>
    """

    return html


def fetch_sendgrid_list(api_key, list_id):
    """Fetch all contacts from a SendGrid list"""
    try:
        url = f"https://api.sendgrid.com/v3/marketing/contacts?list_ids={list_id}"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        req = urllib.request.Request(url, headers=headers, method='GET')
        with urllib.request.urlopen(req, timeout=10) as response:
            response_dict = json.loads(response.read().decode('utf-8'))
        
        contacts = response_dict.get('result', [])
        list = []

        for contact in contacts:
            if list_id in contact.get('list_ids', []):
                list.append({
                    'email': contact.get('email'),
                    'postal_code': contact.get('postal_code')
                })
        return list
    except Exception as e:
        print(f"✗ Error fetching list {list_id}: {e}")
        import traceback
        traceback.print_exc()
        return []


def extract_zip_from_contact(contact, zip_field_name='zip_code'):
    """Extract ZIP code from contact custom fields
    
    Args:
        contact: Contact dict from SendGrid
        zip_field_name: Name of the custom field containing ZIP code
        
    Returns:
        ZIP code string or None
    """
    custom_fields = contact.get('custom_fields', {})
    return custom_fields.get(zip_field_name)


def generate_verification_token(email, list_id, secret_key):
    """Generate a verification token for unsubscribe URL

    Args:
        email: subscriber email
        list_id: SendGrid list ID
        secret_key: secret key for HMAC

    Returns:
        Truncated HMAC hash
    """
    message = f"{email}:{list_id}".encode('utf-8')
    token = hmac.new(
        secret_key.encode('utf-8'),
        message,
        hashlib.sha256
    ).hexdigest()

    # Truncate to first 12 characters for URL brevity
    return token[:12]


def lambda_handler(event, context):
    """AWS Lambda handler function
    
    Environment Variables:
        SENDGRID_API_KEY: SendGrid API key
        FROM_EMAIL: Sender email address
        SENDGRID_HTML_LIST_ID: SendGrid list ID for HTML subscribers
        SENDGRID_PLAIN_LIST_ID: SendGrid list ID for plain text subscribers
        REPLY_TO: Optional reply-to email address
    """

    SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY')
    FROM_EMAIL = os.environ.get('FROM_EMAIL')
    REPLY_TO = os.environ.get('REPLY_TO')
    
    HTML_LIST_ID = os.environ.get('SENDGRID_HTML_LIST_ID')
    PLAIN_LIST_ID = os.environ.get('SENDGRID_PLAIN_LIST_ID')

    if not all([SENDGRID_API_KEY, FROM_EMAIL, HTML_LIST_ID, PLAIN_LIST_ID]):
        return {
            'statusCode': 500,
            'body': json.dumps('Missing required environment variables')
        }

    # Initialize SendGrid client
    sg = SendGridAPIClient(SENDGRID_API_KEY)

    # Fetch global data
    print("Fetching solar data...")
    solar_data = fetch_solar_data()

    print("Fetching contest data...")
    all_contests = fetch_contest_data()
    contests = filter_contests_for_next_week(all_contests, days=7)

    # Fetch lists from SendGrid
    print("Fetching SendGrid lists...")
    html_contacts = fetch_sendgrid_list(SENDGRID_API_KEY, HTML_LIST_ID)
    plain_contacts = fetch_sendgrid_list(SENDGRID_API_KEY, PLAIN_LIST_ID)

    if not html_contacts and not plain_contacts:
        return {
            'statusCode': 500,
            'body': json.dumps('No contacts found in SendGrid lists')
        }

    # Combine all contacts with their type
    all_recipients = [
        {**contact, 'type': 'html'} for contact in html_contacts
    ] + [
        {**contact, 'type': 'plain'} for contact in plain_contacts
    ]

    # Fetch weather data for each unique ZIP
    print("Fetching weather forecasts...")
    weather_by_zip = {}
    for recipient in all_recipients:
        zip_code = recipient.get('postal_code')
        
        if zip_code and zip_code not in weather_by_zip:
            coords = zip_to_coords(zip_code)
            if coords:
                forecast = fetch_weather_forecast(coords[0], coords[1])
                weather_by_zip[zip_code] = forecast
            else:
                weather_by_zip[zip_code] = None

    # Send personalized emails
    today = datetime.utcnow().strftime("%B %d, %Y")
    subject = f"Ham Radio Daily Digest - {today}"

    print(f"Sending emails to {len(all_recipients)} recipients...")

    for recipient in all_recipients:
        recipient_email = recipient.get('email')
        recipient_type = recipient.get('type', 'html').lower()
        zip_code = recipient.get('postal_code')
        unsub_url = f"https://" + os.environ.get('UNSUBSCRIBE_BASE_URL') + f"?email={recipient_email}&list={HTML_LIST_ID if recipient_type == 'html' else PLAIN_LIST_ID}&token={generate_verification_token(recipient_email, HTML_LIST_ID if recipient_type == 'html' else PLAIN_LIST_ID, os.environ.get('UNSUBSCRIBE_SECRET'))}"

        if not recipient_email:
            print(f"✗ Skipping recipient with no email address")
            continue

        if not zip_code:
            print(f"✗ Skipping {recipient_email} - no ZIP code found")
            continue

        # Generate personalized content
        text_body = f"""HAM RADIO DAILY DIGEST
{today}

{format_solar_text(solar_data)}

{format_weather_text(weather_by_zip.get(zip_code), zip_code)}

{format_contests_text(contests)}

Data sources:
- Solar: https://www.hamqsl.com/solar.html
- Contests: https://www.contestcalendar.com
- Weather: https://open-meteo.com

Unsubscribe here: {unsub_url}
"""

        html_body = f"""
        <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    h2 {{ color: #2c5aa0; border-bottom: 2px solid #2c5aa0; padding-bottom: 5px; }}
                    h3 {{ color: #4a7ba7; }}
                    table {{ margin: 15px 0; }}
                </style>
            </head>
            <body>
                <h1>📻 Ham Radio Daily Digest</h1>
                <p><em>{today}</em></p>

                {format_solar_html(solar_data)}

                <hr style="margin: 30px 0;">

                {format_weather_html(weather_by_zip.get(zip_code), zip_code)}

                <hr style="margin: 30px 0;">

                {format_contests_html(contests)}

                <hr style="margin: 30px 0;">

                <p style="font-size: 12px; color: #666; text-align: center;">
                    Data sources: 
                    <a href="https://www.hamqsl.com/solar.html">HAMQSL.com</a> | 
                    <a href="https://www.contestcalendar.com">WA7BNM Contest Calendar</a> |
                    <a href="https://open-meteo.com">Open-Meteo</a>
                </p>

                <hr style="margin: 30px 0;">

                <p style="font-size: 12px; color: #666; text-align: center;">
                    This email was sent to {recipient_email} because you subscribed to the Ham Radio Daily Digest. <a href="{unsub_url}">Unsubscribe</a>?
                    <br /><br />
                    Landmark 717<br />
                    8149 Santa Monica Blvd. #122,<br />
                    Los Angeles CA 90046<br />
                </p>
            </body>
        </html>
        """

        unsubscribe_group = os.environ.get('UNSUBSCRIBE_GROUP_ID_HTML')

        if recipient_type == 'plain':
            unsubscribe_group = os.environ.get('UNSUBSCRIBE_GROUP_ID_PLAIN')

        try:
            message = Mail(
                from_email=Email(FROM_EMAIL, "Ham Daily Digest"),
                to_emails=To(recipient_email),
                subject=subject,
                plain_text_content=Content("text/plain", text_body) if recipient_type == 'plain' else None,
                html_content=Content("text/html", html_body) if recipient_type == 'html' else None
            )

            if REPLY_TO:
                message.reply_to = Email(REPLY_TO)

            response = sg.send(message)
            print(f"✓ Email sent to {recipient_email} ({recipient_type}, ZIP {zip_code}) - Status: {response.status_code}")

        except Exception as e:
            print(f"✗ Error sending email to {recipient_email}: {e}")

    return {
        'statusCode': 200,
        'body': json.dumps(f'Emails sent to {len(all_recipients)} recipients')
    }


# For local testing
if __name__ == "__main__":
    # Set test environment variables
    # os.environ['OUTPUT_FILE'] = 'ham_radio_digest_output.html'
    # os.environ['EMAIL_LIST'] = json.dumps([
    #     {"email": "markmutti@gmail.com", "type": "html", "zip": "91601"}
    # ])

    # Run the handler
    result = lambda_handler({}, {})
    print(result)
