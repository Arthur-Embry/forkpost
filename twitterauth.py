import requests
from requests_oauthlib import OAuth1
import webbrowser
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Your API credentials
API_KEY = os.getenv('TWITTER_API_KEY')
API_SECRET = os.getenv('TWITTER_API_SECRET')

# URLs for OAuth 1.0a flow
REQUEST_TOKEN_URL = 'https://api.x.com/oauth/request_token'
AUTHORIZE_URL = 'https://api.x.com/oauth/authorize'
ACCESS_TOKEN_URL = 'https://api.x.com/oauth/access_token'

def get_permanent_token():
    # Initialize OAuth1 session
    oauth = OAuth1(API_KEY, client_secret=API_SECRET)
    
    # Step 1: Get request token
    r = requests.post(REQUEST_TOKEN_URL, auth=oauth)
    if r.status_code != 200:
        raise Exception(f"Failed to get request token: {r.text}")
    
    # Parse response
    credentials = dict(x.split('=') for x in r.text.split('&'))
    request_token = credentials.get('oauth_token')
    request_token_secret = credentials.get('oauth_token_secret')
    
    # Step 2: Direct user to authorization page
    auth_url = f"{AUTHORIZE_URL}?oauth_token={request_token}"
    print(f"\nPlease visit this URL to authorize the application: {auth_url}")
    webbrowser.open(auth_url)
    
    # Step 3: Get the verifier from callback URL
    callback_url = input("\nPaste the full callback URL here: ")
    
    # Parse the verifier from the callback URL
    from urllib.parse import urlparse, parse_qs
    parsed_url = urlparse(callback_url)
    params = parse_qs(parsed_url.query)
    verifier = params['oauth_verifier'][0]
    
    # Step 4: Get access token
    oauth = OAuth1(API_KEY,
                  client_secret=API_SECRET,
                  resource_owner_key=request_token,
                  resource_owner_secret=request_token_secret,
                  verifier=verifier)
    
    r = requests.post(ACCESS_TOKEN_URL, auth=oauth)
    if r.status_code != 200:
        raise Exception(f"Failed to get access token: {r.text}")
    
    credentials = dict(x.split('=') for x in r.text.split('&'))
    
    print("\nSave these tokens - you'll need them for future API calls:")
    print(f"Access Token: {credentials.get('oauth_token')}")
    print(f"Access Token Secret: {credentials.get('oauth_token_secret')}")
    
    return credentials

if __name__ == "__main__":
    print("Starting OAuth flow...")
    try:
        get_permanent_token()
    except Exception as e:
        print(f"Error: {str(e)}")