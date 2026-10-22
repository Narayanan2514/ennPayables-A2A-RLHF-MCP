from msal import ConfidentialClientApplication
from dotenv import load_dotenv
from pathlib import Path
import os, requests

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

TENANT_ID = os.getenv("TENANT_ID")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
TARGET_USER_EMAIL = os.getenv("TARGET_USER_EMAIL")

def get_graph_token():
    authority = f"https://login.microsoftonline.com/{TENANT_ID}"
    app = ConfidentialClientApplication(
        client_id=CLIENT_ID,
        client_credential=CLIENT_SECRET,
        authority=authority
    )
    token_response = app.acquire_token_for_client(
        scopes=["https://graph.microsoft.com/.default"]
    )
    return token_response.get("access_token")

def get_access_token():
    """Fetch an access token from Microsoft Graph API using client credentials."""
 
    url = f'https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token'
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
    }
    data = {
        'grant_type': 'client_credentials',
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'scope': 'https://graph.microsoft.com/.default',
    }
    response = requests.post(url, headers=headers, data=data)
   
    if response.status_code == 200:
        return response.json()['access_token']
    else:
        return None
