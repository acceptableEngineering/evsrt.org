import json
import os
from sendgrid import SendGridAPIClient


def remove_from_sendgrid_list(api_key, list_id, id):
    """Remove contact from SendGrid list

    Args:
        api_key: SendGrid API key
        list_id: SendGrid list ID
        id: ID to remove
        
    Returns:
        True if successful, False otherwise
    """
    try:
        sg = SendGridAPIClient(api_key)

        # Delete contact from list using query_params
        response = sg.client.marketing.lists._(list_id).contacts.delete(
            query_params={"contact_ids": id}
        )

        print(f"✓ Removed {id} from list {list_id}")
        return True

    except Exception as e:
        print(f"✗ Error removing contact: {e}")
        import traceback
        traceback.print_exc()
        return False


def lambda_handler(event, context):
    """Handle unsubscribe requests

    Query parameters:
        id: subscriber ID
        list: SendGrid list ID

    Environment Variables:
        SENDGRID_API_KEY: SendGrid API key
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

        id = query_params.get('id', '').lower()
        list_id = query_params.get('list')

        if not all([id, list_id]):
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'text/html'},
                'body': '<h2>Invalid Request</h2><p>Missing required parameter(s)</p>'
            }

        # Get secrets from environment
        SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY')

        if not all([SENDGRID_API_KEY]):
            print("Error: Missing environment variables")
            return {
                'statusCode': 500,
                'headers': {'Content-Type': 'text/html'},
                'body': '<h2>Server Error</h2><p>Configuration error</p>'
            }

        # Remove from SendGrid list
        if not remove_from_sendgrid_list(SENDGRID_API_KEY, list_id, id):
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
                        <p>You have been removed from that mailing list. See ya! 👋</p>
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
