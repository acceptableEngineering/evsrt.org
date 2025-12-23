import json
import os
import urllib.request
import urllib.error
import hmac
import hashlib


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


def verify_token(email, list_id, provided_token, secret_key):
    """Verify the unsubscribe token
    
    Args:
        email: subscriber email
        list_id: SendGrid list ID
        provided_token: token from URL
        secret_key: secret key for HMAC
        
    Returns:
        True if token is valid, False otherwise
    """
    expected_token = generate_verification_token(email, list_id, secret_key)
    return hmac.compare_digest(expected_token, provided_token)


def remove_from_sendgrid_list(api_key, list_id, email):
    """Remove contact from SendGrid list
    
    Args:
        api_key: SendGrid API key
        list_id: SendGrid list ID
        email: email to remove
        
    Returns:
        True if successful, False otherwise
    """
    try:
        url = f"https://api.sendgrid.com/v3/marketing/lists/{list_id}/contacts"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        # SendGrid API uses query params for contact removal
        request_url = f"{url}?contact_ids={email}"
        
        req = urllib.request.Request(
            request_url,
            headers=headers,
            method='DELETE'
        )
        
        with urllib.request.urlopen(req, timeout=10) as response:
            result = response.read().decode('utf-8')
        
        print(f"✓ Removed {email} from list {list_id}")
        return True
        
    except urllib.error.HTTPError as e:
        if e.code == 204:  # SendGrid returns 204 for successful delete
            print(f"✓ Removed {email} from list {list_id}")
            return True
        else:
            print(f"✗ HTTP Error {e.code}: {e.reason}")
            return False
    except Exception as e:
        print(f"✗ Error removing contact: {e}")
        return False


def lambda_handler(event, context):
    """Handle unsubscribe requests
    
    Query parameters:
        email: subscriber email (URL encoded)
        list: SendGrid list ID
        verify: HMAC verification token
    
    Environment Variables:
        SENDGRID_API_KEY: SendGrid API key
        UNSUBSCRIBE_SECRET: Secret key for HMAC verification
    """
    
    try:
        # Get parameters from query string
        query_params = event.get('queryStringParameters', {})
        
        if not query_params:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'text/html'},
                'body': '<h2>Invalid Request</h2><p>Missing parameters</p>'
            }
        
        email = query_params.get('email', '').lower()
        list_id = query_params.get('list')
        provided_token = query_params.get('verify')
        
        if not all([email, list_id, provided_token]):
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'text/html'},
                'body': '<h2>Invalid Request</h2><p>Missing email, list, or verify parameter</p>'
            }
        
        # Get secrets from environment
        SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY')
        UNSUBSCRIBE_SECRET = os.environ.get('UNSUBSCRIBE_SECRET')
        
        if not all([SENDGRID_API_KEY, UNSUBSCRIBE_SECRET]):
            print("Error: Missing environment variables")
            return {
                'statusCode': 500,
                'headers': {'Content-Type': 'text/html'},
                'body': '<h2>Server Error</h2><p>Configuration error</p>'
            }
        
        # Verify token
        if not verify_token(email, list_id, provided_token, UNSUBSCRIBE_SECRET):
            print(f"✗ Invalid token for {email}")
            return {
                'statusCode': 403,
                'headers': {'Content-Type': 'text/html'},
                'body': '<h2>Forbidden</h2><p>Invalid verification token</p>'
            }
        
        # Remove from SendGrid list
        if not remove_from_sendgrid_list(SENDGRID_API_KEY, list_id, email):
            return {
                'statusCode': 500,
                'headers': {'Content-Type': 'text/html'},
                'body': '<h2>Server Error</h2><p>Failed to process unsubscribe</p>'
            }
        
        # Success
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'text/html'},
            'body': '''
            <html>
                <head>
                    <style>
                        body {
                            font-family: Arial, sans-serif;
                            text-align: center;
                            padding: 40px;
                            background-color: #f5f5f5;
                        }
                        .container {
                            max-width: 600px;
                            margin: 0 auto;
                            background-color: white;
                            padding: 30px;
                            border-radius: 5px;
                            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                        }
                        h2 { color: #333; }
                        p { color: #666; line-height: 1.6; }
                    </style>
                </head>
                <body>
                    <div class="container">
                        <h2>Unsubscribed</h2>
                        <p>You have been removed from the Ham Radio Daily Digest mailing list.</p>
                        <p>We're sorry to see you go. If you change your mind, you can re-subscribe anytime.</p>
                    </div>
                </body>
            </html>
            '''
        }
        
    except Exception as e:
        print(f"Error processing unsubscribe: {e}")
        import traceback
        traceback.print_exc()
        
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'text/html'},
            'body': '<h2>Server Error</h2><p>An unexpected error occurred</p>'
        }

if __name__ == "__main__":
    result = lambda_handler({}, {})
    print(result)
