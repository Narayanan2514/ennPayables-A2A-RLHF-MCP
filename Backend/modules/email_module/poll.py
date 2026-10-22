import requests
import time
import os
import traceback

from app.setttings.config import get_graph_token
from .service import process_email

TARGET_USER_EMAIL = os.getenv("TARGET_USER_EMAIL")
POLL_INTERVAL = 8

def fetch_unread_emails(access_token):
    url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/mailFolders/inbox/messages?$filter=isRead eq false"
    headers = {"Authorization": f"Bearer {access_token}"}

    r = requests.get(url, headers=headers)
    r.raise_for_status()
    return r.json().get("value", [])


def mark_email_as_read(access_token, message_id):
    url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/messages/{message_id}"
    headers = {"Authorization": f"Bearer {access_token}"}
    requests.patch(url, headers=headers, json={"isRead": True})


#-------------------------agent automation testing-----------------------
def get_unread_emails():
    token = get_graph_token()
    return fetch_unread_emails(token)

def mark_read(message_id):
    token = get_graph_token()
    mark_email_as_read(token, message_id)

#-------------------------------------------------------------------

def run():
    print("📨 Email poller started. Checking every 3 seconds...")
    while True:
        try:
            token = get_graph_token()
            emails = fetch_unread_emails(token)

            print(f"Found {len(emails)} unread emails")

            for mail in emails:
                try:
                    src_id = process_email(mail)
                    print("email processed ref---", src_id)
                    mark_email_as_read(token, mail["id"])
                    print(f"Processed email → src_id {src_id}")
                except Exception:
                    print("❌ Error while processing one email:")
                    traceback.print_exc()

        except Exception:
            print("❌ Polling error (outer loop):")
            traceback.print_exc()

        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    run()
