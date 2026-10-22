import re
import os
import base64
import datetime
import requests
from pathlib import Path
from dotenv import load_dotenv
from bs4 import BeautifulSoup
# from app.api.ennPayables.EBS.db import get_conversation_id_by_src_id, get_previous_src_id_by_customer_po, get_customer_po_number
from .db import *
from .sharepoint import get_graph_token, get_access_token
from .content import *
import os
from .db import extract_po_data_ebs
# from app.api.ennPayables.EBS.db import fetch_duplicate_email_recipient_db, get_source_attachments_db

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

TARGET_USER_EMAIL = os.getenv("TARGET_USER_EMAIL")
target_erp = os.getenv("TARGET_ERP")
print("Target ERP", target_erp)

def strip_html(html_content):
    soup = BeautifulSoup(html_content, "html.parser")

    # ✅ 1. Remove Outlook signature block
    signature_block = soup.find(id="Signature")
    if signature_block:
        signature_block.decompose()

    # ✅ 2. Remove disclaimer paragraphs
    for tag in soup.find_all(['p', 'div', 'span']):
        if tag.get_text(strip=True).lower().startswith("disclaimer"):
            tag.decompose()

    # ✅ 3. Get remaining clean text
    text = soup.get_text(separator="\n")
    text = text.replace('\r\n', '\n').replace('\xa0', ' ').strip()

    return text

def strip_signature(text):
    text = text.replace('\r\n', '\n').replace('\xa0', ' ').strip()
    pattern = r"(best regards[\s\S]*|regards[\s\S]*|thanks[\s\S]*|thank you[\s\S]*|sincerely[\s\S]*|--[\s\S]*|disclaimer[\s\S]*)"
    text = re.sub(pattern, '', text, flags=re.IGNORECASE).strip()

    return text

# -----------------------------
# Detect document type from subject
# -----------------------------
def detect_doc_type(subject):

    if not subject:
        return None

    subject = subject.lower()

    patterns = {
        "remittance": [
            r"remittance",
            r"payment",
            r"cash application",
            r"remittance advice",
            r"receipt"
        ],
        "purchase_order": [
            r"\bpo\b",
            r"purchase order",
            r"p\.o\."
        ],
        "invoice": [
            r"\binv\b",
            r"\binvoice\b",
            r"tax invoice"
        ],
        "bank": [  
            r"bank statement",
            r"bank advice",
            r"statement of account",
            r"bank file",
            r"deposit report",
            r"payment confirmation",
            r"utr",
            r"transaction report",
            r"bank reference"
        ]
    }

    for doc_type, pats in patterns.items():
        for p in pats:
            if re.search(p, subject):
                return doc_type

    return None


# -----------------------------
# Generate log comment dynamically
# -----------------------------

def generate_log_comment_collection(doc_type):

    comments = {
        "remittance": "Remittance email received and stored",
        "purchase_order": "Purchase Order email received and stored",
        "invoice": "Invoice email received and stored",
        "bank": "Bank Document email received and stored"  
    }

    return comments.get(doc_type, "Document email received and stored")


# -----------------------------
# Download attachments
# -----------------------------
def download_attachments(access_token, message_id, doc_type):

    url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/messages/{message_id}/attachments"
    headers = {"Authorization": f"Bearer {access_token}"}

    r = requests.get(url, headers=headers)

    if r.status_code != 200:
        return "", ""

    attachments = r.json().get("value", [])

    if not attachments:
        return "", ""

    doc_folder_map = {
        "invoice": "inv",
        "purchase_order": "po",
        "remittance": "remit",
        "bank": "bank"
    }

    subfolder = doc_folder_map.get(doc_type, "others")

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    # folder = os.path.join(
    #     "doc_transition",
    #     "to_process",
    #     subfolder,
    #     f"upload_{timestamp}"
    # )
    folder = os.path.join("data", "to_process", subfolder, f"upload_{timestamp}")

    os.makedirs(folder, exist_ok=True)

    names = []

    for att in attachments:

        if att.get("isInline"):
            continue

        content = att.get("contentBytes")
        name = att.get("name")

        path = os.path.join(folder, name)

        with open(path, "wb") as f:
            f.write(base64.b64decode(content))

        names.append(name)

    return ", ".join(names), folder


# -----------------------------
# Main Email Processor
# -----------------------------
def process_email(email_obj):
    print("Email_object to check from address")
    # print(email_obj)
    print("&"*200)
    from_email = email_obj["from"]["emailAddress"]["address"]
    # from_email = "krithika.appandaraj@ennvee.net"

    print("from_email",from_email)
    subject = email_obj.get("subject", "")
    body_html = email_obj["body"]["content"]
    message_id = email_obj["id"]
    convo_id = email_obj.get("conversationId", "")
    

    # Detect document type
    doc_type = detect_doc_type(subject)

    # Ignore irrelevant emails
    if not doc_type:
        return None

    # Clean body
    body = strip_signature(strip_html(body_html))

    # Get access token
    token = get_graph_token()

    # Download attachments
    atch_names, folder_path = download_attachments(token, message_id, doc_type)
    print("------email atch_names--------", atch_names, folder_path)
    # Insert into source table

    print("-------------target erp for source table-------------------", target_erp)
    src_id = insert_source(
        channel="email",
        target=target_erp,
        doc_type=doc_type,
        atch_nm=atch_names,
        archive=None,
        folder_path=folder_path
    )

    # Insert email record
    insert_email(
        src_id,
        from_email,
        subject,
        body, 
        convo_id,
        message_id

    )

    # Insert log
    comment = generate_log_comment_collection(doc_type)

    insert_log(
        src_id,
        "Successful",
        "Collection",
        comment
    )

    return src_id

# def send_duplicate_email_service(src_id, to, subject, body, attachment):
#     file_path = None

#     if attachment and attachment.lower() == "true":
#         file_path = get_attachment_path(src_id)
#     print ("-----file path----", file_path)
#     # send_dup_email_content(
#     #     from_email=TARGET_USER_EMAIL,
#     #     to=to,
#     #     subject=subject,
#     #     body=body,
#     #     attachment=file_path
#     # )

#     return 



def send_email(from_email, to_email, subject, body,detailed_report=False,html_body='',attachments=None,cc_emails=None):
    access_token = get_access_token()
    if access_token is None:
        return
    user_id = from_email

    #overwriting email for testing
    #to_email= 'krithika.appandaraj@ennvee.net'

    url = f"https://graph.microsoft.com/v1.0/users/{user_id}/sendMail"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
   
     # Create attachment objects
    attachment_objects = []
    if attachments:
        for filepath in attachments:
            if filepath is None:
                continue  # Skip None entries
 
            filename = os.path.basename(filepath)
            with open(filepath, "rb") as f:
                content_bytes = base64.b64encode(f.read()).decode('utf-8')
 
            attachment_objects.append({
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": filename,
                "contentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "contentBytes": content_bytes
            })
 
    # Prepare CC recipients if provided
    cc_recipients = []
    if cc_emails:
        if isinstance(cc_emails, str):  # if single email passed
            cc_emails = [cc_emails]
        for cc in cc_emails:
            cc_recipients.append({"emailAddress": {"address": cc}})
           
    if not detailed_report:  
        email_message = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": "HTML",
                    "content": body
                },
                "toRecipients": [
                    {
                        "emailAddress": {
                            "address": to_email
                        }
                    }
                ],
                 "ccRecipients": cc_recipients,
                "attachments": attachment_objects
            }
        }
    else:
        email_message = {
            "message": {
                "subject": subject,
                "body": {
                        "contentType": "HTML",  # Send HTML content
                    "content": f"{body}<br>{html_body}"
                },
                "toRecipients": [
                    {
                        "emailAddress": {
                            "address": to_email
                        }
                    }
                ],
                "ccRecipients": cc_recipients,
                "attachments": attachment_objects
            }
        }
 
    response = requests.post(url, json=email_message, headers=headers)
 
    if response.status_code == 202:
        print(f"Email sent to {to_email}")
    else:
        print(f"Failed to send email to {to_email}. Error: {response.status_code}, {response.text}")


print("---base dir-----", BASE_DIR)

# def send_duplicate_email_service(src_id, to, subject, body, attachment):
#     file_path = None

#     if attachment and attachment.lower() == "true":
#         relative_folder = get_attachment_path(src_id)

#         print("----path from db----", relative_folder)

#         if not relative_folder:
#             print(f"No archive path found for src_id={src_id}")
#         else:
#             folder_path = os.path.join(BASE_DIR, relative_folder)

#             print("----FULL FOLDER PATH----", folder_path)

#             if not os.path.isdir(folder_path):
#                 print(f"Folder does not exist: {folder_path}")
#             else:
#                 files = os.listdir(folder_path)

#                 if not files:
#                     print(f"No files in folder: {folder_path}")
#                 else:
#                     file_name = files[0]
#                     file_path = os.path.join(folder_path, file_name)

#     print("-----ABSOLUTE FILE PATH----", file_path)

#     send_email(
#         from_email=TARGET_USER_EMAIL,
#         to_email=to,
#         subject=subject,
#         body=body,
#         attachments=[file_path] if file_path else None 
#     )
#     return

from typing import List, Optional
from fastapi import UploadFile

def get_message_id_by_conversation_id(
    conversation_id,
    mailbox_email,
    access_token
):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }

    url = (
        f"https://graph.microsoft.com/v1.0/"
        f"users/{mailbox_email}/messages"
    )

    params = {
        "$filter": f"conversationId eq '{conversation_id}'",
        "$select": "id,subject,conversationId,receivedDateTime",
        "$top": "50"
    }

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=30
    )

    if response.status_code != 200:
        raise Exception(
            f"Failed to find email by conversationId: "
            f"{response.status_code} {response.text}"
        )

    messages = response.json().get("value", [])

    if not messages:
        raise ValueError(
            f"No Graph message found for conversationId: "
            f"{conversation_id}"
        )

    # Sort locally instead of using Graph $orderby
    messages.sort(
        key=lambda x: x.get("receivedDateTime", ""),
        reverse=True
    )

    return messages[0]["id"]


def download_email_as_eml(
    message_id,
    mailbox_email,
    access_token
):
    url = (
        f"https://graph.microsoft.com/v1.0/"
        f"users/{mailbox_email}/"
        f"messages/{message_id}/$value"
    )

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "message/rfc822"
    }

    response = requests.get(
        url,
        headers=headers
    )

    if response.status_code != 200:
        raise Exception(
            f"Failed to download EML: "
            f"{response.status_code} {response.text}"
        )

    return response.content


# def send_dup_email(
#     src_id: str,
#     email_to: str,
#     subject: str,
#     body: str,
#     attachments: Optional[List[UploadFile]] = None,
#     sender_email: str = None
# ):

#     print("-------------body for duplicate email--------------", body)
#     try:

#         customer_po_number = get_customer_po_number(src_id)

#         previous_src_id = get_previous_src_id_by_customer_po(
#             customer_po_number,
#             src_id
#         )

#         conversation_id = get_conversation_id_by_src_id(
#             previous_src_id
#         )

#         message_id = get_message_id_by_conversation_id(
#             conversation_id=conversation_id,
#             mailbox_email=TARGET_USER_EMAIL,
#             access_token=access_token
#         )

#         eml_content = download_email_as_eml(
#             message_id=message_id,
#             mailbox_email=TARGET_USER_EMAIL,
#             access_token=access_token
#         )
#         # -------------------------------------------------
#         # 1. GET ACCESS TOKEN
#         # -------------------------------------------------
#         access_token = get_access_token()

#         headers = {
#             "Authorization": f"Bearer {access_token}",
#             "Content-Type": "application/json"
#         }

#         # -------------------------------------------------
#         # 2. BUILD ATTACHMENTS (GRAPH FORMAT)
#         # -------------------------------------------------
#         graph_attachments = []

#         if attachments:
#             for file in attachments:
#                 content = file.file.read()

#                 graph_attachments.append({
#                     "@odata.type": "#microsoft.graph.fileAttachment",
#                     "name": file.filename,
#                     "contentBytes": base64.b64encode(content).decode("utf-8")
#                 })
#         # Attach previous email
#         graph_attachments.append({
#             "@odata.type": "#microsoft.graph.fileAttachment",
#             "name": f"{previous_src_id}.eml",
#             "contentType": "message/rfc822",
#             "contentBytes": base64.b64encode(
#                 eml_content
#             ).decode("utf-8")
#         })

#         # -------------------------------------------------
#         # 3. EMAIL PAYLOAD
#         # -------------------------------------------------
#         email_payload = {
#             "message": {
#                 "subject": subject,
#                 "body": {
#                     "contentType": "HTML",
#                     # "content": body
#                     "content": build_email_template(subject, body)

#                 },
#                 "toRecipients": [
#                     {
#                         "emailAddress": {
#                             "address": email_to
#                         }
#                     }
#                 ],

#                  "ccRecipients": [
#                     {
#                         "emailAddress": {
#                             "address": "balaji.srinivasan@ennvee.net"
#                         }
#                     }
#                 ],

#                 "attachments": graph_attachments if graph_attachments else []
#             },
#             "saveToSentItems": "true"
#         }

#         # -------------------------------------------------
#         # 4. SEND EMAIL (GRAPH API)
#         # -------------------------------------------------
#         sender = sender_email or "aiticketingsupport@ennvee.net"

#         url = f"https://graph.microsoft.com/v1.0/users/{sender}/sendMail"

#         response = requests.post(url, headers=headers, json=email_payload)

#         if response.status_code not in (200, 202):
#             return {
#                 "status": "error",
#                 "message": response.text
#             }

#         # -------------------------------------------------
#         # 5. SUCCESS RESPONSE
#         # -------------------------------------------------
#         return {
#             "status": "success",
#             "message": "Email sent successfully",
#             "to": email_to,
#             "subject": subject
#         }

#     except Exception as e:
#         return {
#             "status": "error",
#             "message": str(e)
#         }

# def send_dup_email(
#     src_id: str,
#     email_to: str,
#     subject: str,
#     body: str,
#     attachments: Optional[List[UploadFile]] = None,
#     sender_email: str = None
# ):
#     """
#     Send duplicate email using UploadFile attachments.
#     Also attaches the previous duplicate email as .eml.
#     """

#     print(
#         "------------- duplicate email --------------"
#     )
#     print("src_id:", src_id)
#     print("email_to:", email_to)

#     try:
#         # -------------------------------------------------
#         # 1. GET ACCESS TOKEN
#         # -------------------------------------------------
#         access_token = get_access_token()

#         if not access_token:
#             raise Exception(
#                 "Unable to get Microsoft Graph access token"
#             )

#         headers = {
#             "Authorization": f"Bearer {access_token}",
#             "Content-Type": "application/json"
#         }

#         # -------------------------------------------------
#         # 2. GET CURRENT CUSTOMER PO
#         # -------------------------------------------------
#         customer_po_number = get_customer_po_number(src_id)

#         print(
#             "Current customer PO:",
#             customer_po_number
#         )

#         # -------------------------------------------------
#         # 3. GET PREVIOUS SRC_ID
#         # -------------------------------------------------
#         previous_src_id = get_previous_src_id_by_customer_po(
#             customer_po_number,
#             src_id
#         )

#         print(
#             "Previous src_id:",
#             previous_src_id
#         )

#         # -------------------------------------------------
#         # 4. GET PREVIOUS EMAIL CONVERSATION ID
#         # -------------------------------------------------
#         conversation_id = get_conversation_id_by_src_id(
#             previous_src_id
#         )

#         print(
#             "Previous conversationId:",
#             conversation_id
#         )

#         # -------------------------------------------------
#         # 5. GET GRAPH MESSAGE ID
#         # -------------------------------------------------
#         message_id = get_message_id_by_conversation_id(
#             conversation_id=conversation_id,
#             mailbox_email=TARGET_USER_EMAIL,
#             access_token=access_token
#         )

#         # -------------------------------------------------
#         # 6. DOWNLOAD PREVIOUS EMAIL AS EML
#         # -------------------------------------------------
#         eml_content = download_email_as_eml(
#             message_id=message_id,
#             mailbox_email=TARGET_USER_EMAIL,
#             access_token=access_token
#         )

#         # -------------------------------------------------
#         # 7. BUILD ATTACHMENTS
#         # -------------------------------------------------
#         graph_attachments = []

#         # Current UploadFile attachments
#         if attachments:
#             for file in attachments:

#                 content = file.file.read()

#                 graph_attachments.append({
#                     "@odata.type": "#microsoft.graph.fileAttachment",
#                     "name": file.filename,
#                     "contentBytes": base64.b64encode(
#                         content
#                     ).decode("utf-8")
#                 })

#         # Previous email
#         graph_attachments.append({
#             "@odata.type": "#microsoft.graph.fileAttachment",
#             "name": f"{previous_src_id}.eml",
#             "contentType": "message/rfc822",
#             "contentBytes": base64.b64encode(
#                 eml_content
#             ).decode("utf-8")
#         })

#         # -------------------------------------------------
#         # 8. SEND EMAIL
#         # -------------------------------------------------
#         email_payload = {
#             "message": {
#                 "subject": subject,

#                 "body": {
#                     "contentType": "HTML",
#                     "content": build_email_template(
#                         subject,
#                         body
#                     )
#                 },

#                 "toRecipients": [
#                     {
#                         "emailAddress": {
#                             "address": email_to
#                         }
#                     }
#                 ],

#                 "ccRecipients": [
#                     {
#                         "emailAddress": {
#                             "address":
#                                 "balaji.srinivasan@ennvee.net"
#                         }
#                     }
#                 ],

#                 "attachments": graph_attachments
#             },

#             "saveToSentItems": True
#         }

#         sender = (
#             sender_email
#             or TARGET_USER_EMAIL
#         )

#         url = (
#             f"https://graph.microsoft.com/v1.0/"
#             f"users/{sender}/sendMail"
#         )

#         response = requests.post(
#             url,
#             headers=headers,
#             json=email_payload,
#             timeout=30
#         )

#         if response.status_code not in (200, 202):
#             return {
#                 "status": "error",
#                 "message": response.text
#             }

#         return {
#             "status": "success",
#             "message": "Email sent successfully",
#             "to": email_to,
#             "subject": subject,
#             "previous_src_id": previous_src_id,
#             "conversation_id": conversation_id,
#             "attachments": len(graph_attachments)
#         }

#     except Exception as e:

#         return {
#             "status": "error",
#             "message": str(e)
#         }

def send_dup_email(
    src_id: str,
    email_to: str,
    subject: str,
    body: str,
    attachments=None,
    sender_email=None
):

    try:
        access_token = get_access_token()

        if not access_token:
            raise Exception("Unable to get access token")

        previous_email = get_previous_email_eml(
            src_id,
            access_token
        )

        graph_attachments = []

        # Current invoice files
        if attachments:
            for file in attachments:

                content = file.file.read()

                graph_attachments.append({
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": file.filename,
                    "contentType": (
                        file.content_type
                        or "application/octet-stream"
                    ),
                    "contentBytes": base64.b64encode(
                        content
                    ).decode("utf-8")
                })

        # Previous email
        graph_attachments.append({
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": (
                f"{previous_email['previous_src_id']}.eml"
            ),
            "contentType": "message/rfc822",
            "contentBytes": base64.b64encode(
                previous_email["eml_content"]
            ).decode("utf-8")
        })

        sender = sender_email or TARGET_USER_EMAIL

        email_payload = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": "HTML",
                    "content": build_email_template(
                        subject,
                        body
                    )
                },
                "toRecipients": [
                    {
                        "emailAddress": {
                            "address": email_to
                        }
                    }
                ],
                "ccRecipients": [
                    {
                        "emailAddress": {
                            "address":
                                "balaji.srinivasan@ennvee.net"
                        }
                    }
                ],
                "attachments": graph_attachments
            },
            "saveToSentItems": True
        }

        url = (
            f"https://graph.microsoft.com/v1.0/"
            f"users/{sender}/sendMail"
        )

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        response = requests.post(
            url,
            headers=headers,
            json=email_payload,
            timeout=30
        )

        print("Graph status:", response.status_code)
        print("Graph response:", response.text)

        if response.status_code != 202:
            return {
                "status": "error",
                "message": response.text
            }

        return {
            "status": "success",
            "message": "Email sent successfully",
            "previous_src_id":
                previous_email["previous_src_id"],
            "conversation_id":
                previous_email["conversation_id"],
            "attachments":
                len(graph_attachments)
        }

    except Exception as e:
        import traceback
        traceback.print_exc()

        return {
            "status": "error",
            "message": str(e)
        }


def get_previous_email_eml(src_id, access_token):
    customer_po_number = get_customer_po_number(src_id)

    previous_src_id = get_previous_src_id_by_customer_po(
        customer_po_number,
        src_id
    )

    if not previous_src_id:
        raise ValueError(
            f"No previous invoice found for PO: {customer_po_number}"
        )

    conversation_id = get_conversation_id_by_src_id(
        previous_src_id
    )

    if not conversation_id:
        raise ValueError(
            f"No conversation ID found for src_id: {previous_src_id}"
        )

    message_id = get_message_id_by_conversation_id(
        conversation_id=conversation_id,
        mailbox_email=TARGET_USER_EMAIL,
        access_token=access_token
    )

    eml_content = download_email_as_eml(
        message_id=message_id,
        mailbox_email=TARGET_USER_EMAIL,
        access_token=access_token
    )

    return {
        "previous_src_id": previous_src_id,
        "conversation_id": conversation_id,
        "message_id": message_id,
        "eml_content": eml_content
    }


def send_automatic_duplicate_email(src_id: str):
    """
    Automatically send duplicate invoice email after EBS
    reports that the invoice number already exists.
    """

    try:
        # -------------------------------------------------
        # 1. GET RECIPIENT EMAIL
        # -------------------------------------------------
        email_to = fetch_duplicate_email_recipient_db(src_id)

        if not email_to:
            print(
                f"[send_automatic_duplicate_email] "
                f"No recipient email found for src_id: {src_id}"
            )

            return {
                "status": "error",
                "message": "No recipient email found"
            }

        # -------------------------------------------------
        # 2. GET INVOICE NUMBER
        # -------------------------------------------------
        header_info, line_info = extract_po_data_ebs(src_id)

        invoice_number = ""

        if header_info:
            invoice_number = header_info.get("invoice_number", "")

        # -------------------------------------------------
        # 3. SUBJECT
        # -------------------------------------------------
        subject = f"RE: Duplicate Invoice # {invoice_number or ''}"

        # -------------------------------------------------
        # 4. BODY
        # -------------------------------------------------
        body = """Hi,

We have identified a duplicate Invoice.

Please find the attached invoice for which duplicate entry has been detected.

Kindly review it.

Thanks & Regards
AI Agent"""

        # -------------------------------------------------
        # 5. GET ALL FILES FROM SOURCE FOLDER
        # -------------------------------------------------
        attachment_paths = get_source_attachments_db(src_id)

        # -------------------------------------------------
        # 6. SEND EMAIL
        # -------------------------------------------------
        send_result = send_dup_email_from_paths(
            src_id=src_id,
            email_to=email_to,
            subject=subject,
            body=body,
            attachment_paths=attachment_paths
        )

        return send_result

    except Exception as e:
        print(
            f"[send_automatic_duplicate_email] "
            f"Error for src_id {src_id}: {e}"
        )

        return {
            "status": "error",
            "message": str(e)
        }

# def send_dup_email_from_paths(
#     src_id: str,
#     email_to: str,
#     subject: str,
#     body: str,
#     attachment_paths=None,
#     sender_email: str = None
# ):
#     """
#     Send duplicate invoice email using files from the server filesystem.
#     """

#     print("------------- automatic duplicate email --------------")
#     print("src_id:", src_id)
#     print("email_to:", email_to)
#     # print("subject:", subject)
#     # print("body:", body)

#     try:
#         # -------------------------------------------------
#         # 1. GET ACCESS TOKEN
#         # -------------------------------------------------
#         access_token = get_access_token()

#         headers = {
#             "Authorization": f"Bearer {access_token}",
#             "Content-Type": "application/json"
#         }

#         # -------------------------------------------------
#         # 2. BUILD ATTACHMENTS
#         # -------------------------------------------------
#         graph_attachments = []

#         if attachment_paths:
#             for file_path in attachment_paths:

#                 if not os.path.isfile(file_path):
#                     print(
#                         f"Skipping missing attachment: {file_path}"
#                     )
#                     continue

#                 with open(file_path, "rb") as file:
#                     content = file.read()

#                 graph_attachments.append({
#                     "@odata.type": "#microsoft.graph.fileAttachment",
#                     "name": os.path.basename(file_path),
#                     "contentBytes": base64.b64encode(
#                         content
#                     ).decode("utf-8")
#                 })

#         # -------------------------------------------------
#         # 3. EMAIL PAYLOAD
#         # -------------------------------------------------
#         email_payload = {
#             "message": {
#                 "subject": subject,
#                 "body": {
#                     "contentType": "HTML",
#                     "content": build_email_template(
#                         subject,
#                         body
#                     )
#                 },
#                 "toRecipients": [
#                     {
#                         "emailAddress": {
#                             "address": email_to
#                         }
#                     }
#                 ],
#                 "attachments": graph_attachments
#             },
#             "saveToSentItems": True
#         }

#         # -------------------------------------------------
#         # 4. SENDER
#         # -------------------------------------------------
#         sender = (
#             sender_email
#             or os.getenv(
#                 "MS_SENDER_EMAIL",
#                 "aiticketingsupport@ennvee.net"
#             )
#         )

#         # -------------------------------------------------
#         # 5. SEND THROUGH GRAPH
#         # -------------------------------------------------
#         url = (
#             f"https://graph.microsoft.com/v1.0/"
#             f"users/{sender}/sendMail"
#         )

#         response = requests.post(
#             url,
#             headers=headers,
#             json=email_payload,
#             timeout=30
#         )

#         if response.status_code not in (200, 202):
#             print(
#                 "Microsoft Graph email error:",
#                 response.status_code,
#                 response.text
#             )

#             return {
#                 "status": "error",
#                 "message": response.text
#             }

#         # -------------------------------------------------
#         # 6. SUCCESS
#         # -------------------------------------------------
#         print(
#             f"Duplicate email sent successfully "
#             f"for src_id {src_id}"
#         )

#         return {
#             "status": "success",
#             "message": "Duplicate email sent successfully",
#             "to": email_to,
#             "subject": subject,
#             "attachments": len(graph_attachments)
#         }

#     except Exception as e:
#         print(
#             f"send_dup_email_from_paths error: {e}"
#         )

#         return {
#             "status": "error",
#             "message": str(e)
#         }

def send_dup_email_from_paths(
    src_id: str,
    email_to: str,
    subject: str,
    body: str,
    attachment_paths=None,
    sender_email: str = None
):
    """
    Send duplicate invoice email using files from the server filesystem.
    Also attaches the previous duplicate email as .eml.
    """

    print(
        "------------- automatic duplicate email --------------"
    )
    print("src_id:", src_id)
    print("email_to:", email_to)

    try:
        # -------------------------------------------------
        # 1. GET ACCESS TOKEN
        # -------------------------------------------------
        access_token = get_access_token()

        if not access_token:
            raise Exception(
                "Unable to get Microsoft Graph access token"
            )

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        # -------------------------------------------------
        # 2. GET CURRENT CUSTOMER PO
        # -------------------------------------------------
        customer_po_number = get_customer_po_number(src_id)

        print(
            "Current customer PO:",
            customer_po_number
        )

        # -------------------------------------------------
        # 3. GET PREVIOUS SRC_ID
        # -------------------------------------------------
        previous_src_id = get_previous_src_id_by_customer_po(
            customer_po_number,
            src_id
        )

        print(
            "Previous src_id:",
            previous_src_id
        )

        # -------------------------------------------------
        # 4. GET PREVIOUS EMAIL CONVERSATION ID
        # -------------------------------------------------
        conversation_id = get_conversation_id_by_src_id(
            previous_src_id
        )

        print(
            "Previous conversationId:",
            conversation_id
        )

        # -------------------------------------------------
        # 5. GET GRAPH MESSAGE ID
        # -------------------------------------------------
        message_id = get_message_id_by_conversation_id(
            conversation_id=conversation_id,
            mailbox_email=TARGET_USER_EMAIL,
            access_token=access_token
        )

        print(
            "Previous Graph message ID:",
            message_id
        )

        # -------------------------------------------------
        # 6. DOWNLOAD PREVIOUS EMAIL AS EML
        # -------------------------------------------------
        eml_content = download_email_as_eml(
            message_id=message_id,
            mailbox_email=TARGET_USER_EMAIL,
            access_token=access_token
        )

        print(
            "Previous EML downloaded:",
            len(eml_content),
            "bytes"
        )

        # -------------------------------------------------
        # 7. BUILD ATTACHMENTS
        # -------------------------------------------------
        graph_attachments = []

        # ---------------------------------------------
        # 7A. CURRENT INVOICE FILES
        # ---------------------------------------------
        if attachment_paths:

            for file_path in attachment_paths:

                if not file_path:
                    continue

                if not os.path.isfile(file_path):
                    print(
                        f"Skipping missing attachment: "
                        f"{file_path}"
                    )
                    continue

                with open(file_path, "rb") as file:
                    content = file.read()

                graph_attachments.append({
                    "@odata.type":
                        "#microsoft.graph.fileAttachment",
                    "name":
                        os.path.basename(file_path),
                    "contentBytes":
                        base64.b64encode(
                            content
                        ).decode("utf-8")
                })

        # ---------------------------------------------
        # 7B. PREVIOUS EMAIL EML
        # ---------------------------------------------
        graph_attachments.append({
            "@odata.type":
                "#microsoft.graph.fileAttachment",

            "name":
                f"{previous_src_id}.eml",

            "contentType":
                "message/rfc822",

            "contentBytes":
                base64.b64encode(
                    eml_content
                ).decode("utf-8")
        })

        # -------------------------------------------------
        # 8. EMAIL PAYLOAD
        # -------------------------------------------------
        email_payload = {
            "message": {
                "subject": subject,

                "body": {
                    "contentType": "HTML",
                    "content": build_email_template(
                        subject,
                        body
                    )
                },

                "toRecipients": [
                    {
                        "emailAddress": {
                            "address": email_to
                        }
                    }
                ],

                "ccRecipients": [
                    {
                        "emailAddress": {
                            "address":
                                "balaji.srinivasan@ennvee.net"
                        }
                    }
                ],

                "attachments": graph_attachments
            },

            "saveToSentItems": True
        }

        # -------------------------------------------------
        # 9. SENDER
        # -------------------------------------------------
        sender = (
            sender_email
            or TARGET_USER_EMAIL
        )

        # -------------------------------------------------
        # 10. SEND THROUGH GRAPH
        # -------------------------------------------------
        url = (
            f"https://graph.microsoft.com/v1.0/"
            f"users/{sender}/sendMail"
        )

        response = requests.post(
            url,
            headers=headers,
            json=email_payload,
            timeout=30
        )

        if response.status_code not in (200, 202):

            print(
                "Microsoft Graph email error:",
                response.status_code,
                response.text
            )

            return {
                "status": "error",
                "message": response.text
            }

        # -------------------------------------------------
        # 11. SUCCESS
        # -------------------------------------------------
        print(
            f"Duplicate email sent successfully "
            f"for src_id {src_id}"
        )

        return {
            "status": "success",
            "message":
                "Duplicate email sent successfully",
            "to": email_to,
            "cc":
                "balaji.srinivasan@ennvee.net",
            "subject": subject,
            "current_src_id": src_id,
            "customer_po_number":
                customer_po_number,
            "previous_src_id":
                previous_src_id,
            "conversation_id":
                conversation_id,
            "graph_message_id":
                message_id,
            "attachments":
                len(graph_attachments)
        }

    except Exception as e:

        print(
            f"send_dup_email_from_paths error: {e}"
        )

        return {
            "status": "error",
            "message": str(e)
        }
