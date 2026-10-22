from datetime import datetime
import requests
from requests.auth import HTTPBasicAuth
from modules.email_module.service import send_automatic_duplicate_email
import urllib3
import json
from modules.email_module.db import *
from ERP.db import *

#----------------------------------------------EBS-----------------------------------------------------------#

import requests
from requests.auth import HTTPBasicAuth
import urllib3
import json
from datetime import datetime

def push_to_ebs_inv(src_id, is_reprocessed = False):

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    url = "http://ebs.ennveedemovcnpr.ennveedemovcn.oraclevcn.com:8000/webservices/rest/XXENVAP/create_invoices/"

    auth = HTTPBasicAuth("esb_user", "oracle321")

    headers = {
        "Content-Type": "application/json"
    }

    try:
        print("---------- EBS Step: Extracting data ----------")
        header_info, line_info = extract_inv_data_ebs(src_id)

        print("---------header ebs info---------",header_info)
        print("---------line ebs info---------",line_info)


        if not header_info or not line_info:
            insert_log(src_id, "Failed", "EBS", "Missing invoice data")
            return {"status": "error", "message": "Missing data"}

        payload = {
            "RESTHeader": {
                "Responsibility": "APPLICATION_DEVELOPER",
                "RespApplication": "FND",
                "SecurityGroup": "STANDARD",
                "NLSLanguage": "AMERICAN",
                "Language": "US",
                "Org_Id": ""
            },
            "InputParameters": {
                "P_INVOICE_HEADER": {
                    "P_INVOICE_HEADER_ITEM": {
                        "INVOICE_NUMBER": header_info.get("invoice_number"),
                        "SUPPLIER_NAME": header_info.get("supplier_name"),
                        # "SUPPLIER_NAME": "3M Health Care",

                        "SUPPLIER_SITE_NAME": header_info.get("supplier_site_name", ""),
                        "INVOICE_AMOUNT": str(header_info.get("invoice_amount", "")),
                        # "INVOICE_AMOUNT": "400",

                        # "INVOICE_DATE": header_info.get("invoice_date"),
                        "INVOICE_DATE" : header_info.get("invoice_date").isoformat() if header_info.get("invoice_date") else None,
                        "PO_NUMBER": header_info.get("customer_po_number"),
                        "CURRENCY_CODE": header_info.get("currency_code", "USD"),
                        # "PAYMENT_TERMS": header_info.get("payment_terms", "Immediate")
                        "PAYMENT_TERMS": "Immediate"

                    }
                },
                "P_INVOICE_LINES": {
                    "P_INVOICE_LINES_ITEM": [
                        {
                            "ITEM_NAME": line.get("item_name"),
                            "LINE_DESCRIPTION": line.get("item_desc", ""),
                            # "QTY": str(line.get("qty", 1)),
                            # "QTY": "1",
                            "QTY": str(line.get("ordered_quantity", 0)),
                            # "LINE_AMOUNT": str(line.get("gross_amount", 0))
                            # "LINE_AMOUNT": "400"
                            "LINE_AMOUNT":  line.get("total", 0),


                        }
                        for line in line_info
                    ]
                }
            }
        }

        print("EBS Payload:", json.dumps(payload, indent=2))

        response = requests.post(
            url,
            json=payload,
            headers=headers,
            auth=auth,
            verify=False
        )

        print("EBS Status:", response.status_code)
        print("EBS Response:", response.text)

        resp_json = response.json()
        print("-------------EBS response--------------", resp_json)
        output = resp_json.get("OutputParameters", {})

        status = output.get("X_STATUS")

        if status == "S":

            if not is_reprocessed:
                insert_log(
                    src_id,
                    "Successful",
                    "EBS",
                    "Invoice successfully posted in EBS"
                )
            else:

                insert_log(
                    src_id,
                    "Successful",
                    "EBS",
                    "Invoice successfully reprocessed and posted in EBS",
                    is_reviewed="1",
                    action_taken="Reprocessed"
                )
        elif status == "E":
            message = output.get("X_MESSAGE", "EBS posting failed")
            if "invoice number already exists" in message.lower():

                # 1. INSERT EBS DUPLICATE LOG FIRST
                insert_log(src_id, "Failed", "EBS", message)

                print(f"⚠️ Duplicate invoice detected for src_id {src_id}")

                # 2. SEND AUTOMATIC DUPLICATE EMAIL
                email_result = send_automatic_duplicate_email(src_id)

                if email_result.get("status") == "success":
                    print(f"✅ Duplicate email sent for src_id {src_id}")
                    insert_log(
                        src_id,
                        "Successful",
                        "EBS",
                        "Agent sent duplicate invoice email successfully",
                        is_reviewed="1",
                        action_taken="Email Sent",
                    )
                else:
                    print(
                        f"❌ Duplicate email failed for src_id {src_id}: "
                        f"{email_result.get('message')}"
                    )

                # 3. RETURN ORIGINAL EBS RESULT
                return {
                    "status": "error",
                    "message": message
                }
            else:
                insert_log(src_id, "Failed", "EBS", output.get("X_MESSAGE"))
                return {
                    "status": "error",
                    "message": output.get("X_MESSAGE", "EBS posting failed")
                }



        else:
            insert_log(src_id, "Failed", "EBS", output.get("X_MESSAGE"))
            return {
                "status": "error",
                "message": output.get("X_MESSAGE", "EBS posting failed")
            }

    except Exception as e:
        print("❌ EBS Exception:", str(e))
        insert_log(src_id, "Failed", "EBS", str(e))
        return {
            "status": "error",
            "message": "Unexpected error in EBS"
        }




def reporting_summary_ebs():

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    url = "http://ebs.ennveedemovcnpr.ennveedemovcn.oraclevcn.com:8000/webservices/rest/XXAPINVREPORT/get_ap_invoices/"

    auth = HTTPBasicAuth("esb_user", "oracle321")

    headers = {
        "Content-Type": "application/json"
    }

    payload = {
        "GET_AP_INVOICES_Input": {
            "RESTHeader": {
                "Responsibility": "APPLICATION_DEVELOPER",
                "RespApplication": "FND",
                "SecurityGroup": "STANDARD",
                "NLSLanguage": "AMERICAN",
                "Language": "US",
                "Org_Id": "204"
            },
            "InputParameters": {
                "P_SUPPLIER_NAME": "",
                "P_INVOICE_DATE_FROM": "2026-08-01T00:00:00",
                "P_INVOICE_DATE_TO": "2026-08-31T23:59:59",
                "P_PO_NUMBER": "",
                "P_INVOICE_NUMBER": ""
            }
        }
    }

    try:
        print("Calling EBS AP Invoice Reporting API...")
        print("Payload:", payload)

        response = requests.post(
            url,
            json=payload,
            headers=headers,
            auth=auth,
            verify=False
        )

        print("EBS Status:", response.status_code)
        print("EBS Response:", response.text)

        response.raise_for_status()

        return {
            "status": "success",
            "data": response.json()
        }

    except requests.exceptions.RequestException as e:
        print("❌ EBS Reporting API Error:", str(e))
        return {
            "status": "error",
            "message": str(e)
        }

    except Exception as e:
        print("❌ Unexpected Error:", str(e))
        return {
            "status": "error",
            "message": "Unexpected error while fetching reporting summary."
        }