import json
import os
import sys
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
import urllib.request
import urllib.error

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
        text += f"  Info: {contest['link']}\n\n"
    
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


def send_email(subject, content, from_email, to_emails, sendgrid_api_key, reply_to=None):
    """Send email via SendGrid (supports both plain text and HTML)
    
    Args:
        content: Either a string (content) or dict with 'text' and 'html' keys
        to_emails: Can be a list of dicts with 'email' and 'type' keys, or a legacy string
        reply_to: Optional reply-to email address
    """
    if not SENDGRID_AVAILABLE:
        print("Error: sendgrid module not available. Install with: pip install sendgrid")
        return False
    
    try:
        # Parse email list - can be list of dicts or legacy comma-separated string
        if isinstance(to_emails, str):
            # Legacy format: comma-separated emails, assume HTML
            email_list = [
                {"email": email.strip(), "type": "html"}
                for email in to_emails.split(',')
            ]
        else:
            # Already a list of dicts
            email_list = to_emails
        
        sg = SendGridAPIClient(sendgrid_api_key)
        total_recipients = len(email_list)
        
        # Send to each recipient individually
        for recipient in email_list:
            recipient_email = recipient["email"]
            recipient_type = recipient.get("type", "html").lower()
            
            # Get the appropriate content based on recipient type
            if isinstance(content, dict):
                if recipient_type == "plain":
                    content_body = content.get('text', '')
                else:
                    content_body = content.get('html', '')
            else:
                content_body = content
            
            # Determine if HTML or plain text
            is_html = recipient_type == "html"
            
            message = Mail(
                from_email=Email(from_email),
                to_emails=To(recipient_email),
                subject=subject,
                plain_text_content=Content("text/plain", content_body) if not is_html else None,
                html_content=Content("text/html", content_body) if is_html else None
            )
            
            # Add reply-to if provided
            if reply_to:
                message.reply_to = Email(reply_to)
            
            response = sg.send(message)
            print(f"Email sent to {recipient_email} ({recipient_type}) - Status code: {response.status_code}")
        
        print(f"All emails sent! (total recipients: {total_recipients})")
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False


def lambda_handler(event, context):
    """AWS Lambda handler function
    
    Environment Variables:
        SENDGRID_API_KEY: SendGrid API key
        FROM_EMAIL: Sender email address
        EMAIL_LIST: JSON array of recipient objects with 'email' and 'type' keys
                    Example: '[{"email":"call1@winlink.org","type":"plain"},{"email":"call2@example.com","type":"html"}]'
                    Or use legacy TO_EMAIL if EMAIL_LIST not set
        TO_EMAIL: Legacy recipient email(s) - single or comma-separated list (used if EMAIL_LIST not set)
                  Example: "call1@winlink.org" or "call1@winlink.org, call2@example.com"
        REPLY_TO: Optional reply-to email address
        PLAIN_TEXT: Set to 'true' for plain text format (for legacy TO_EMAIL), default is HTML
        OUTPUT_FILE: Optional - write to file instead of sending email
    """
    
    # Get configuration from environment variables
    SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY')
    FROM_EMAIL = os.environ.get('FROM_EMAIL')
    REPLY_TO = os.environ.get('REPLY_TO')  # Optional: reply-to email address
    OUTPUT_FILE = os.environ.get('OUTPUT_FILE')  # Optional: write to file instead of sending email
    
    # Try to get EMAIL_LIST first (new format), fall back to TO_EMAIL (legacy format)
    EMAIL_LIST_JSON = os.environ.get('EMAIL_LIST')
    if EMAIL_LIST_JSON:
        try:
            TO_EMAIL = json.loads(EMAIL_LIST_JSON)
        except json.JSONDecodeError:
            print(f"Error parsing EMAIL_LIST JSON: {EMAIL_LIST_JSON}")
            return {
                'statusCode': 500,
                'body': json.dumps('Invalid EMAIL_LIST JSON format')
            }
    else:
        TO_EMAIL = os.environ.get('TO_EMAIL')  # Fall back to legacy comma-separated
        PLAIN_TEXT = os.environ.get('PLAIN_TEXT', 'false').lower() == 'true'
        # Convert legacy format to new format if PLAIN_TEXT is set
        if TO_EMAIL and PLAIN_TEXT:
            TO_EMAIL = [{"email": email.strip(), "type": "plain"} for email in TO_EMAIL.split(',')]
        elif TO_EMAIL:
            TO_EMAIL = [{"email": email.strip(), "type": "html"} for email in TO_EMAIL.split(',')]
    
    # Fetch data
    print("Fetching solar data...")
    solar_data = fetch_solar_data()
    
    print("Fetching contest data...")
    all_contests = fetch_contest_data()
    contests = filter_contests_for_next_week(all_contests, days=7)
    
    # Format email
    today = datetime.utcnow().strftime("%B %d, %Y")
    subject = f"Ham Radio Daily Digest - {today}"
    
    # Generate both text and HTML versions
    text_body = f"""HAM RADIO DAILY DIGEST
{today}

{format_solar_text(solar_data)}

{format_contests_text(contests)}

Data sources:
- Solar: https://www.hamqsl.com/solar.html
- Contests: https://www.contestcalendar.com
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
            
            {format_contests_html(contests)}
            
            <hr style="margin: 30px 0;">
            
            <p style="font-size: 12px; color: #666;">
                Data sources: 
                <a href="https://www.hamqsl.com/solar.html">HAMQSL.com</a> | 
                <a href="https://www.contestcalendar.com">WA7BNM Contest Calendar</a>
            </p>
        </body>
    </html>
    """
    
    # If OUTPUT_FILE is set, write to file instead of sending email
    if OUTPUT_FILE:
        print(f"Writing output to file: {OUTPUT_FILE}")
        try:
            with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                f.write(html_body)
            print(f"✅ HTML written to {OUTPUT_FILE}")
            return {
                'statusCode': 200,
                'body': json.dumps(f'HTML written to {OUTPUT_FILE}')
            }
        except Exception as e:
            print(f"Error writing file: {e}")
            return {
                'statusCode': 500,
                'body': json.dumps(f'Failed to write file: {str(e)}')
            }
    
    # Otherwise, send email
    if not all([SENDGRID_API_KEY, FROM_EMAIL, TO_EMAIL]):
        return {
            'statusCode': 500,
            'body': json.dumps('Missing required environment variables for email sending')
        }
    
    # Create content object that has both versions
    content_obj = {
        'text': text_body,
        'html': html_body
    }
    
    print(f"Sending emails...")
    success = send_email(subject, content_obj, FROM_EMAIL, TO_EMAIL, SENDGRID_API_KEY, reply_to=REPLY_TO)
    
    if success:
        return {
            'statusCode': 200,
            'body': json.dumps('Email sent successfully!')
        }
    else:
        return {
            'statusCode': 500,
            'body': json.dumps('Failed to send email')
        }


# For local testing
if __name__ == "__main__":
    # Set test environment variables
    # For file output (testing without SendGrid):
    # os.environ['OUTPUT_FILE'] = 'ham_radio_digest_output.html'
    
    # Run the handler
    result = lambda_handler({}, {})
    print(result)
