import os
import pymysql
import requests
from pathlib import Path
from msal import ConfidentialClientApplication
from dotenv import load_dotenv
from bs4 import BeautifulSoup

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

TENANT_ID = os.getenv("TENANT_ID")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
TARGET_USER_EMAIL = os.getenv("TARGET_USER_EMAIL")

# --- Shared attachment data root -- the ONE physical folder tree
# (to_process/processed/archival) Agent, RLHF_Tools and Backend all read
# through. SAME value as ENNVAULT_DATA_ROOT in Agent/.env and
# Agent/RLHF_Tools/.env (kept in sync by hand across the three .env files --
# see the comment next to it in Backend/.env). Every place that resolves
# source.folder_path/source.archive into a real filesystem path must join it
# onto DATA_ROOT this same way, rather than re-deriving its own base path.
DATA_ROOT = os.getenv("ENNVAULT_DATA_ROOT", "")
TO_PROCESS_DIR = os.path.join(DATA_ROOT, "to_process") if DATA_ROOT else ""
PROCESSED_DIR = os.path.join(DATA_ROOT, "processed") if DATA_ROOT else ""
ARCHIVAL_DIR = os.path.join(DATA_ROOT, "archival") if DATA_ROOT else ""

DB_HOST = "localhost"
DB_USER = "root"
DB_PASSWORD = "Ai@Envee!072024$"
DB_NAME = "ennvault"

def get_db_connection():
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True
    )

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
 